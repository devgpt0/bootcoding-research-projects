
"""HTTP and WebSocket routes for interview setup and live sessions."""

import asyncio
import json
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from api.evaluation.evaluator import EvaluationError, evaluate_transcript
from api.evaluation.report_generator import (
    build_report,
    save_interview_artifacts,
    save_transcript,
)
from api.interview_engine.instruction_generator import generate_interviewer_instructions
from api.interview_engine.interview_manager import InterviewSession
from api.interview_engine.models import InterviewConfig
from api.live_session import GeminiLiveSession, LiveSessionError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/interviews", tags=["interviews"])
live_router = APIRouter(tags=["live interview"])

FINAL_TURN_TIMEOUT_SECONDS = 20
_seen_client_interviews: set[str] = set()
_client_interview_lock = asyncio.Lock()


async def _wait_for_interview_deadline(seconds: float) -> None:
    await asyncio.sleep(seconds)


@router.post("/instructions")
async def preview_instructions(config: InterviewConfig) -> dict[str, str]:
    """Validate setup and return the generated instruction text for inspection."""
    return {"instructions": generate_interviewer_instructions(config)}


@live_router.websocket("/ws/interview")
async def live_interview(websocket: WebSocket) -> None:
    """Bridge browser PCM/control messages and Gemini Live events."""
    await websocket.accept()

    live: GeminiLiveSession | None = None
    session_state: InterviewSession | None = None
    browser_task: asyncio.Task | None = None
    receiver_task: asyncio.Task | None = None
    timer_task: asyncio.Task | None = None

    send_lock = asyncio.Lock()
    final_turn_complete = asyncio.Event()
    greeting_complete = asyncio.Event()
    transcript_buffers = {"candidate": "", "interviewer": ""}
    normal_end = False
    artifacts_saved = False
    termination_lock = asyncio.Lock()
    automatic_end = False

    async def send_json(payload: dict) -> None:
        async with send_lock:
            await websocket.send_json(payload)

    async def send_audio(payload: bytes) -> None:
        async with send_lock:
            await websocket.send_bytes(payload)

    async def finalize_transcript(speaker: str, *, announce: bool = True) -> None:
        text = transcript_buffers[speaker].strip()
        if not text:
            return
        transcript_buffers[speaker] = ""
        session_state.add_transcript_entry(speaker, text)
        if announce:
            await send_json({"type": "transcript_final", "speaker": speaker})

    async def finalize_all_transcripts(*, announce: bool = True) -> None:
        await finalize_transcript("candidate", announce=announce)
        await finalize_transcript("interviewer", announce=announce)

    async def save_transcript_only() -> None:
        """Preserve any captured transcript even if evaluation is unavailable."""
        nonlocal artifacts_saved

        if session_state is None or artifacts_saved:
            return

        try:
            paths = save_transcript(
                session_state.interview_id,
                session_state.config,
                session_state.transcript,
            )
            artifacts_saved = True
            logger.info(
                "Transcript saved for interview %s",
                session_state.interview_id,
            )
            await send_json({
                "type": "transcript_saved",
                "artifacts": {
                    "transcript_json": str(paths[0]),
                    "transcript_txt": str(paths[1]),
                },
            })
        except Exception:
            logger.exception("Could not save interview transcript")

    try:
        first = await websocket.receive_json()

        if first.get("type") != "start":
            await send_json({
                "type": "error",
                "message": "First message must be a start event.",
            })
            await websocket.close(code=1008)
            return

        try:
            config = InterviewConfig.model_validate(first.get("config", {}))
        except ValidationError as exc:
            await send_json({
                "type": "error",
                "message": "Invalid interview configuration.",
                "details": exc.errors(include_input=False),
            })
            await websocket.close(code=1008)
            return

        client_id = first.get("client_interview_id")
        if client_id is not None:
            if not isinstance(client_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", client_id):
                await send_json({"type": "error", "message": "Invalid interview session identifier."})
                await websocket.close(code=1008)
                return
            async with _client_interview_lock:
                if client_id in _seen_client_interviews:
                    await send_json({"type": "error", "message": "This interview has already started and cannot be restarted."})
                    await websocket.close(code=1008)
                    return
                _seen_client_interviews.add(client_id)

        session_state = InterviewSession(config=config)
        live = GeminiLiveSession(config)

        await live.open()

        await send_json({
            "type": "connected",
            "interview_id": session_state.interview_id,
            "candidate_name": config.candidate_name,
            "job_role": config.job_role,
            "duration_minutes": config.duration_minutes,
        })

        async def browser_to_gemini() -> bool:
            """Forward browser audio and return True for an intentional end."""
            while True:
                message = await websocket.receive()

                if message["type"] == "websocket.disconnect":
                    return False

                if message.get("bytes") is not None:
                    if not session_state.completed and session_state.started_event.is_set():
                        await live.send_audio(message["bytes"])
                    continue

                raw_text = message.get("text")
                if raw_text is None:
                    continue

                try:
                    control = json.loads(raw_text)
                except json.JSONDecodeError:
                    await send_json({
                        "type": "error",
                        "message": "Control messages must be valid JSON.",
                    })
                    continue

                if control.get("type") == "end":
                    async with termination_lock:
                        if session_state.completed:
                            return False
                        session_state.finish()
                    # Ignore any earlier turn completion, such as the greeting.
                    final_turn_complete.clear()

                    await live.finish_audio()
                    session_state.finish()
                    return True

                if control.get("type") == "ping":
                    await send_json({"type": "pong", "remaining_seconds": session_state.remaining_seconds})

        async def end_at_deadline() -> bool:
            nonlocal automatic_end
            await session_state.started_event.wait()
            conclusion_delay = max(0, session_state.actual_duration_seconds - 60)
            await _wait_for_interview_deadline(conclusion_delay)
            async with termination_lock:
                if session_state.completed:
                    return False
            final_turn_complete.clear()
            try:
                await live.send_text(
                    "The interview has one minute remaining. Begin concluding naturally now. "
                    "Do not start another lengthy question. If appropriate, briefly ask whether "
                    "the candidate has anything brief to add, then thank them and deliver a warm, "
                    "concise closing statement. Finish speaking within the remaining minute."
                )
                await send_json({"type": "conclusion_started", "remaining_seconds": 60})
            except LiveSessionError:
                logger.exception("Could not send the one-minute conclusion direction")

            await _wait_for_interview_deadline(60)
            async with termination_lock:
                if session_state.completed:
                    return False
                session_state.finish()
                automatic_end = True
            # Do not accept more candidate input after the deadline. Give the
            # already-requested closing turn a short chance to finish so its
            # audio and transcript can be captured before closing Gemini.
            try:
                await live.finish_audio()
            except LiveSessionError:
                pass
            await send_json({"type": "timer_expired", "remaining_seconds": 0})
            try:
                await asyncio.wait_for(final_turn_complete.wait(), timeout=FINAL_TURN_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                logger.warning("Closing turn timed out for interview %s", session_state.interview_id)
            await live.close()
            return True

        async def gemini_to_browser() -> None:
            """Forward Gemini audio, transcripts and turn-completion events."""
            async for event in live.receive_events():
                if event.audio:
                    await send_audio(event.audio)

                if event.input_transcript:
                    transcript_buffers["candidate"] += event.input_transcript
                    await send_json({
                        "type": "transcript",
                        "speaker": "candidate",
                        "text": event.input_transcript,
                    })

                if event.output_transcript:
                    transcript_buffers["interviewer"] += event.output_transcript
                    await send_json({
                        "type": "transcript",
                        "speaker": "interviewer",
                        "text": event.output_transcript,
                    })

                if event.interrupted:
                    await finalize_transcript("interviewer")
                    await send_json({"type": "interrupted"})

                if event.turn_complete:
                    final_turn_complete.set()
                    await send_json({"type": "turn_complete"})
                    await finalize_all_transcripts()
                    if not greeting_complete.is_set():
                        greeting_complete.set()
                        session_state.start()
                        # This event tells the browser to open its microphone.
                        # Wait until Gemini has completed the spoken introduction.
                        await send_json({
                            "type": "interview_started",
                            "remaining_seconds": session_state.remaining_seconds,
                            "deadline": session_state.started_at.timestamp() + session_state.actual_duration_seconds,
                        })

        receiver_task = asyncio.create_task(
            gemini_to_browser(),
            name="gemini-to-browser",
        )
        await live.start_interview()
        browser_task = asyncio.create_task(
            browser_to_gemini(),
            name="browser-to-gemini",
        )
        timer_task = asyncio.create_task(end_at_deadline(), name="interview-deadline")

        # Monitor both directions. A failed Gemini reader must not leave the
        # browser task waiting indefinitely for another microphone frame.
        done, _pending = await asyncio.wait(
            {browser_task, receiver_task, timer_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if receiver_task in done:
            receive_error = receiver_task.exception()
            if receive_error is not None:
                raise receive_error
            if not browser_task.done() and not timer_task.done() and not automatic_end:
                raise LiveSessionError(
                    "Gemini Live closed the response stream unexpectedly."
                )

        normal_end = (browser_task.result() if browser_task.done() else False) or (timer_task.result() if timer_task.done() else False)

        if normal_end:
            # Allow Gemini time to finish its final response and transcript.
            if not automatic_end:
                try:
                    await asyncio.wait_for(
                        final_turn_complete.wait(),
                        timeout=FINAL_TURN_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    logger.warning("Gemini final turn timed out for interview %s", session_state.interview_id)

            await finalize_all_transcripts()

            await send_json({"type": "interview_ended"})

        # Stop receiving only after the final-turn wait has completed.
        if receiver_task is not None and not receiver_task.done():
            receiver_task.cancel()

        if receiver_task is not None:
            results = await asyncio.gather(
                receiver_task,
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, Exception) and not isinstance(
                    result,
                    asyncio.CancelledError,
                ):
                    raise result

        if not normal_end:
            # A disconnected candidate does not receive an evaluation.
            # Preserve whatever transcript was captured.
            if session_state is not None:
                session_state.finish()
            await save_transcript_only()
            return

        # Evaluate only after the final Gemini turn has been processed.
        try:
            evaluation = await evaluate_transcript(
                session_state.config,
                session_state.transcript,
            )
        except EvaluationError as exc:
            logger.exception(
                "Evaluation failed for interview %s",
                session_state.interview_id,
            )
            await save_transcript_only()
            await send_json({
                "type": "evaluation_error",
                "message": str(exc),
            })
            return

        completed_at = datetime.now(timezone.utc)

        report = build_report(
            config=session_state.config,
            interview_id=session_state.interview_id,
            started_at=session_state.started_at,
            completed_at=completed_at,
            evaluation=evaluation,
        )

        paths = save_interview_artifacts(
            report,
            session_state.transcript,
        )
        artifacts_saved = True

        await send_json({
            "type": "evaluation_complete",
            "report": report.model_dump(mode="json"),
            "artifacts": {
                name: str(path)
                for name, path in paths.items()
            },
        })

    except WebSocketDisconnect:
        logger.info("Interview WebSocket disconnected")

    except LiveSessionError as exc:
        logger.error("Gemini Live session error: %s", exc)
        try:
            await send_json({
                "type": "error",
                "message": str(exc),
            })
        except Exception:
            pass

    except Exception:
        logger.exception("Unexpected interview error")
        try:
            await send_json({
                "type": "error",
                "message": "The interview connection ended unexpectedly.",
            })
        except Exception:
            pass

    finally:
        for task in (browser_task, receiver_task, timer_task):
            if task is not None and not task.done():
                task.cancel()

        pending_tasks = [
            task
            for task in (browser_task, receiver_task, timer_task)
            if task is not None
        ]

        if pending_tasks:
            await asyncio.gather(
                *pending_tasks,
                return_exceptions=True,
            )

        if live is not None:
            await live.close()

        # Preserve any last partial transcript fragments on disconnect/error.
        if session_state is not None:
            await finalize_all_transcripts(announce=False)

        if session_state is not None and not session_state.completed:
            session_state.finish()

        if not artifacts_saved and session_state is not None:
            # Avoid losing captured data after unexpected errors/disconnects.
            try:
                paths = save_transcript(
                    session_state.interview_id,
                    session_state.config,
                    session_state.transcript,
                )
                logger.info(
                    "Saved transcript after incomplete interview: %s",
                    paths[0],
                )
            except Exception:
                logger.exception("Could not save incomplete interview transcript")

        try:
            await websocket.close()
        except Exception:
            pass
