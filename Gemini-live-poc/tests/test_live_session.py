from types import SimpleNamespace

import pytest

from api.interview_engine.models import InterviewConfig
from api.live_session import (
    GeminiLiveSession,
    LiveEvent,
    LiveSessionError,
    build_opening_prompt,
)


def make_config() -> InterviewConfig:
    return InterviewConfig(candidate_name="Sam", job_role="Analyst", experience_level="Junior")


def test_opening_prompt_requests_candidate_introduction_before_follow_up() -> None:
    prompt = build_opening_prompt(make_config())
    assert "Hello, Sam" in prompt
    assert "FIRST interview question" in prompt
    assert "introduce yourself" in prompt
    assert "Stop and listen" in prompt
    assert "After the candidate answers" in prompt


@pytest.mark.asyncio
async def test_send_audio_requires_open_session() -> None:
    session = GeminiLiveSession(make_config())
    with pytest.raises(LiveSessionError, match="not open"):
        await session.send_audio(b"\x00\x00")


@pytest.mark.asyncio
async def test_receive_events_preserves_audio_transcript_and_turn_markers() -> None:
    class FakeSession:
        async def receive(self):
            yield SimpleNamespace(
                server_content=SimpleNamespace(
                    input_transcription=SimpleNamespace(text="Candidate answer"),
                    output_transcription=SimpleNamespace(text="Next question"),
                    model_turn=SimpleNamespace(
                        parts=[SimpleNamespace(inline_data=SimpleNamespace(data=b"\x01\x02"))]
                    ),
                    turn_complete=True,
                    interrupted=False,
                )
            )

    live = GeminiLiveSession(make_config())
    live._session = FakeSession()
    events = live.receive_events()

    assert await anext(events) == LiveEvent(audio=b"\x01\x02")
    assert await anext(events) == LiveEvent(
        input_transcript="Candidate answer",
        output_transcript="Next question",
        turn_complete=True,
    )
    await events.aclose()


@pytest.mark.asyncio
async def test_receive_events_restarts_sdk_iterator_for_next_turn() -> None:
    class FakeSession:
        def __init__(self):
            self.turn = 0

        async def receive(self):
            self.turn += 1
            yield SimpleNamespace(
                server_content=SimpleNamespace(
                    output_transcription=SimpleNamespace(text=f"Turn {self.turn}"),
                    turn_complete=True,
                )
            )

    fake = FakeSession()
    live = GeminiLiveSession(make_config())
    live._session = fake
    events = live.receive_events()

    assert await anext(events) == LiveEvent(output_transcript="Turn 1", turn_complete=True)
    assert await anext(events) == LiveEvent(output_transcript="Turn 2", turn_complete=True)
    assert fake.turn == 2
    await events.aclose()


@pytest.mark.asyncio
async def test_interruption_discards_canceled_audio_but_keeps_candidate_transcript() -> None:
    class FakeSession:
        async def receive(self):
            yield SimpleNamespace(
                server_content=SimpleNamespace(
                    interrupted=True,
                    input_transcription=SimpleNamespace(text="Let me finish my answer."),
                    model_turn=SimpleNamespace(
                        parts=[SimpleNamespace(inline_data=SimpleNamespace(data=b"stale audio"))]
                    ),
                    turn_complete=False,
                )
            )

    live = GeminiLiveSession(make_config())
    live._session = FakeSession()
    events = live.receive_events()

    assert await anext(events) == LiveEvent(interrupted=True)
    assert await anext(events) == LiveEvent(input_transcript="Let me finish my answer.")
    await events.aclose()


@pytest.mark.asyncio
async def test_audio_chunk_rejects_odd_pcm_byte_count() -> None:
    live = GeminiLiveSession(make_config())
    live._session = object()
    with pytest.raises(ValueError, match="even number"):
        await live.send_audio(b"\x00")
