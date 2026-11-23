"""Asynchronous adapter for Google's Gemini Live API.

Audio input is raw signed 16-bit little-endian PCM at 16 kHz mono. Live API
audio output is raw 16-bit PCM at 24 kHz mono. This module forwards bytes; it
does not resample or reinterpret browser audio.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator

from api.config import settings
from api.interview_engine.instruction_generator import generate_interviewer_instructions
from api.interview_engine.models import InterviewConfig

INPUT_MIME_TYPE = "audio/pcm;rate=16000"
OUTPUT_SAMPLE_RATE = 24_000


class LiveSessionError(RuntimeError):
    """Raised when Gemini Live is unavailable or session setup fails."""


@dataclass(frozen=True)
class LiveEvent:
    """Normalized event data consumed by the WebSocket/API layer."""

    audio: bytes | None = None
    input_transcript: str | None = None
    output_transcript: str | None = None
    turn_complete: bool = False
    interrupted: bool = False


def build_opening_prompt(config: InterviewConfig) -> str:
    """Require a spoken greeting and candidate introduction before role questions."""
    return (
        "You are acting only as an interviewer. Do not teach, answer questions, explain concepts, give hints, or discuss unrelated topics. "
        f"Start by speaking this greeting in English: 'Hello, {config.candidate_name}. "
        f"Welcome to your {config.job_role} interview. I’m your interviewer today.' "
        "Then ask this as your FIRST interview question: 'Could you please introduce yourself "
        "and briefly describe the experience most relevant to this role?' Stop and listen to the "
        "candidate's complete answer. Do not ask a technical or other role question yet. After the "
        "candidate answers, ask one relevant follow-up based specifically on what they said. "
        "Continue the interview naturally from there, in English only."
    )


class GeminiLiveSession:
    """Own one async Gemini Live connection and expose audio/event methods."""

    def __init__(self, config: InterviewConfig) -> None:
        self.config = config
        self._client = None
        self._context = None
        self._session = None
        self._closed = False

    async def open(self) -> None:
        if self._session is not None:
            return
        if not settings.gemini_api_key:
            raise LiveSessionError("GEMINI_API_KEY is not configured")
        if not settings.gemini_live_model:
            raise LiveSessionError("GEMINI_LIVE_MODEL is not configured")

        try:
            from google import genai

            self._client = genai.Client(
                api_key=settings.gemini_api_key,
                http_options={"api_version": "v1beta"},
            )
            live_config = {
                "response_modalities": ["AUDIO"],
                "system_instruction": generate_interviewer_instructions(self.config),
                "input_audio_transcription": {},
                "output_audio_transcription": {},
            }
            self._context = self._client.aio.live.connect(
                model=settings.gemini_live_model,
                config=live_config,
            )
            self._session = await self._context.__aenter__()
        except Exception as exc:
            await self.close()
            raise LiveSessionError(f"Could not establish Gemini Live session: {exc}") from exc

    async def send_audio(self, pcm_chunk: bytes) -> None:
        """Forward a non-empty 16 kHz mono PCM16 chunk to Gemini."""
        self._require_open()
        if not pcm_chunk:
            return
        if len(pcm_chunk) % 2:
            raise ValueError("PCM16 audio chunks must contain an even number of bytes")
        try:
            from google.genai import types

            await self._session.send_realtime_input(
                audio=types.Blob(data=pcm_chunk, mime_type=INPUT_MIME_TYPE)
            )
        except Exception as exc:
            raise LiveSessionError(f"Could not send audio to Gemini Live: {exc}") from exc

    async def finish_audio(self) -> None:
        """Signal that the client microphone stream has ended."""
        self._require_open()
        try:
            await self._session.send_realtime_input(audio_stream_end=True)
        except Exception as exc:
            raise LiveSessionError(f"Could not finish Gemini Live audio input: {exc}") from exc

    async def start_interview(self) -> None:
        """Ask Gemini to greet the candidate and request their introduction first."""
        self._require_open()
        try:
            await self._session.send_realtime_input(text=build_opening_prompt(self.config))
        except Exception as exc:
            raise LiveSessionError(f"Could not start the interview: {exc}") from exc

    async def send_text(self, text: str) -> None:
        """Send an interviewer direction through the active Gemini Live turn."""
        self._require_open()
        try:
            await self._session.send_realtime_input(text=text)
        except Exception as exc:
            raise LiveSessionError(f"Could not send an interviewer direction: {exc}") from exc

    async def receive_events(self) -> AsyncIterator[LiveEvent]:
        """Yield events across every completed model turn until the session closes.

        The Google SDK's ``session.receive()`` iterator ends after one complete
        model turn. Re-open it for the next turn so the socket keeps being read
        throughout the full duplex conversation.
        """
        self._require_open()
        try:
            while not self._closed:
                async for response in self._session.receive():
                    content = getattr(response, "server_content", None)
                    if content is None:
                        continue
                    input_transcription = getattr(content, "input_transcription", None)
                    output_transcription = getattr(content, "output_transcription", None)
                    model_turn = getattr(content, "model_turn", None)
                    interrupted = bool(getattr(content, "interrupted", False))
                    if interrupted:
                        # Notify the browser before other data from this
                        # response and discard audio from the canceled turn.
                        yield LiveEvent(interrupted=True)
                    if model_turn and not interrupted:
                        for part in model_turn.parts or []:
                            inline_data = getattr(part, "inline_data", None)
                            if inline_data and inline_data.data:
                                data = inline_data.data
                                yield LiveEvent(audio=data if isinstance(data, bytes) else bytes(data))
                    input_text = getattr(input_transcription, "text", None) if input_transcription else None
                    output_text = getattr(output_transcription, "text", None) if output_transcription else None
                    turn_complete = bool(getattr(content, "turn_complete", False))
                    if interrupted:
                        output_text = None
                    if input_text or output_text or turn_complete:
                        yield LiveEvent(
                            input_transcript=input_text or None,
                            output_transcript=output_text or None,
                            turn_complete=turn_complete,
                            interrupted=False,
                        )
        except Exception as exc:
            if not self._closed:
                raise LiveSessionError(f"Gemini Live receive failed: {exc}") from exc

    async def close(self) -> None:
        """Exit the SDK context once, releasing the underlying WebSocket."""
        if self._closed:
            return
        self._closed = True
        context, self._context = self._context, None
        self._session = None
        if context is not None:
            try:
                await context.__aexit__(None, None, None)
            except Exception:
                pass

    def _require_open(self) -> None:
        if self._closed or self._session is None:
            raise LiveSessionError("Gemini Live session is not open")

    async def __aenter__(self) -> "GeminiLiveSession":
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.close()
