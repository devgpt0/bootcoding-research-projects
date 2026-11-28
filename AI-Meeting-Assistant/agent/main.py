"""Entry point for the explicitly dispatched meeting transcription agent."""

import asyncio
from datetime import datetime
import logging
import os
from pathlib import Path
import re

from dotenv import load_dotenv
from livekit.agents import (
    AgentServer,
    Agent,
    AgentSession,
    JobContext,
    JobRequest,
    WorkerPermissions,
    cli,
    inference,
    llm,
    room_io,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")
os.environ.setdefault("LIVEKIT_AGENT_DEPLOYMENT", "local-dev")

logging.basicConfig(level=logging.INFO)
AI_AGENT_NAME = "ai-meeting-assistant"
logger = logging.getLogger(AI_AGENT_NAME)
TRANSCRIPTS_DIR = PROJECT_ROOT / "storage" / "transcripts"
SUMMARIES_DIR = PROJECT_ROOT / "storage" / "summaries"

server = AgentServer(
    host="127.0.0.1",
    port=8081,
    permissions=WorkerPermissions(
        can_publish=False,
        can_subscribe=True,
        can_publish_data=False,
        can_update_metadata=False,
    )
)


async def accept_agent_job(job_request: JobRequest) -> None:
    """Give the visible room participant a stable identity and display name."""
    await job_request.accept(
        name="AI Meeting Assistant",
        identity=AI_AGENT_NAME,
    )


async def create_meeting_summary(room_name: str, transcript_path: Path) -> Path:
    """Summarize a completed room transcript and save it alongside local data."""
    safe_room_name = re.sub(r"[^A-Za-z0-9._-]", "_", room_name).strip("._") or "meeting"
    summary_path = SUMMARIES_DIR / f"{safe_room_name}.txt"
    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    transcript_text = transcript_path.read_text(encoding="utf-8").strip()
    if not transcript_text:
        summary_path.write_text(
            "No transcript was captured for this meeting, so a summary could not be generated.\n",
            encoding="utf-8",
        )
        return summary_path

    context = llm.ChatContext()
    context.add_message(
        role="system",
        content=(
            "Write a concise, factual meeting summary based only on the transcript. "
            "Use sections for Overview, Key points, Decisions, Action items, and Open questions. "
            "If a section has no evidence in the transcript, write 'None noted'. Do not invent details."
        ),
    )
    context.add_message(role="user", content=transcript_text)
    stream = inference.LLM(
        model="google/gemma-4-31b-it",
        inference_class="low",
    ).chat(chat_ctx=context)
    summary_parts: list[str] = []
    try:
        async for chunk in stream:
            if chunk.delta and chunk.delta.content:
                summary_parts.append(chunk.delta.content)
    finally:
        await stream.aclose()

    summary = "".join(summary_parts).strip()
    if not summary:
        raise RuntimeError("LiveKit Inference returned an empty meeting summary")
    summary_path.write_text(summary + "\n", encoding="utf-8")
    return summary_path


@server.rtc_session(agent_name=AI_AGENT_NAME, on_request=accept_agent_job)
async def entrypoint(ctx: JobContext) -> None:
    """Transcribe room audio and append final segments to a room transcript."""
    logger.info("Starting transcription assistant in room %s", ctx.room.name)
    disconnected = asyncio.Event()

    @ctx.room.on("disconnected")
    def on_disconnected(*_: object) -> None:
        disconnected.set()

    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    safe_room_name = re.sub(r"[^A-Za-z0-9._-]", "_", ctx.room.name).strip("._")
    transcript_path = TRANSCRIPTS_DIR / f"{safe_room_name or 'meeting'}.txt"
    transcript_path.touch(exist_ok=True)

    session = AgentSession(
        stt=inference.STT(model="deepgram/nova-3-general"),
    )

    @session.on("user_input_transcribed")
    def on_transcript(transcript: object) -> None:
        if not getattr(transcript, "is_final", False):
            return
        text = str(getattr(transcript, "transcript", "")).strip()
        if not text:
            return
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with transcript_path.open("a", encoding="utf-8") as transcript_file:
            transcript_file.write(f"[{timestamp}] {text}\n")
        logger.info("Saved transcript segment for room %s", ctx.room.name)

    await session.start(
        agent=Agent(instructions="Transcribe the user's speech accurately."),
        room=ctx.room,
        room_options=room_io.RoomOptions(text_output=False),
    )
    await ctx.connect()
    try:
        await disconnected.wait()
        try:
            summary_path = await create_meeting_summary(ctx.room.name, transcript_path)
            logger.info("Saved meeting summary to %s", summary_path)
        except Exception:
            logger.exception("Could not create meeting summary for room %s", ctx.room.name)
    except asyncio.CancelledError:
        logger.info("Transcription assistant disconnecting from room %s", ctx.room.name)
        raise


if __name__ == "__main__":
    cli.run_app(server)
