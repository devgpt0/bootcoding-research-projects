
import asyncio

from fastapi.testclient import TestClient

from api import interview as interview_routes
from api.evaluation.evaluator import (
    EvaluationResult,
    EvidenceStatus,
    Recommendation,
    SkillAssessment,
)
from api.interview_engine.interview_manager import TranscriptEntry
from api.main import app
from api.live_session import LiveEvent


class FakeLiveSession:
    def __init__(self, config):
        self.received_audio = asyncio.Event()
        self.audio_finished = asyncio.Event()
        self.started = asyncio.Event()

    async def open(self):
        pass

    async def start_interview(self):
        self.started.set()

    async def send_audio(self, chunk: bytes):
        assert chunk == b"\x00\x00"
        self.received_audio.set()

    async def finish_audio(self):
        self.audio_finished.set()

    async def receive_events(self):
        await self.started.wait()
        yield LiveEvent(
            audio=b"\x03\x04",
            output_transcript="Hello, Sam. Welcome to your Analyst interview. Please introduce yourself.",
            turn_complete=True,
        )

        await self.received_audio.wait()

        yield LiveEvent(
            audio=b"\x01\x02",
            input_transcript="A sample answer",
            output_transcript="Tell me about your analysis experience.",
            turn_complete=True,
        )

        await self.audio_finished.wait()

        yield LiveEvent(turn_complete=True)
        await asyncio.Event().wait()

    async def close(self):
        pass


async def fake_evaluate_transcript(config, transcript):
    assert any(
        entry.speaker == "candidate"
        for entry in transcript
    )

    return EvaluationResult(
        skills=[
            SkillAssessment(
                skill="Communication",
                score=85,
                weight=2,
                evidence_status=EvidenceStatus.ASSESSED,
                rationale="The candidate provided a clear answer.",
            )
        ],
        strengths=["Clear explanation"],
        weaknesses=[],
        improvement_suggestions=["Provide more examples"],
        final_assessment="Good interview performance.",
        recommendation=Recommendation.RECOMMEND,
    )


def test_websocket_relays_audio_and_completes_evaluation(monkeypatch):
    monkeypatch.setattr(
        interview_routes,
        "GeminiLiveSession",
        FakeLiveSession,
    )

    monkeypatch.setattr(
        interview_routes,
        "evaluate_transcript",
        fake_evaluate_transcript,
    )

    monkeypatch.setattr(
        interview_routes,
        "save_interview_artifacts",
        lambda report, transcript: {
            "report": "fake_report.json",
            "transcript_json": "fake_transcript.json",
            "transcript_txt": "fake_transcript.txt",
        },
    )

    client = TestClient(app)

    with client.websocket_connect("/ws/interview") as websocket:
        websocket.send_json({
            "type": "start",
            "config": {
                "candidate_name": "Sam",
                "job_role": "Analyst",
                "experience_level": "Junior",
            },
        })

        assert websocket.receive_json()["type"] == "connected"
        assert websocket.receive_bytes() == b"\x03\x04"
        assert websocket.receive_json() == {
            "type": "transcript",
            "speaker": "interviewer",
            "text": "Hello, Sam. Welcome to your Analyst interview. Please introduce yourself.",
        }
        assert websocket.receive_json() == {"type": "turn_complete"}
        assert websocket.receive_json() == {
            "type": "transcript_final",
            "speaker": "interviewer",
        }
        started = websocket.receive_json()
        assert started["type"] == "interview_started"
        assert started["remaining_seconds"] <= 30 * 60
        assert started["deadline"] > 0

        websocket.send_bytes(b"\x00\x00")

        assert websocket.receive_bytes() == b"\x01\x02"

        assert websocket.receive_json() == {
            "type": "transcript",
            "speaker": "candidate",
            "text": "A sample answer",
        }

        assert websocket.receive_json() == {
            "type": "transcript",
            "speaker": "interviewer",
            "text": "Tell me about your analysis experience.",
        }

        assert websocket.receive_json() == {"type": "turn_complete"}
        assert websocket.receive_json() == {
            "type": "transcript_final",
            "speaker": "candidate",
        }
        assert websocket.receive_json() == {
            "type": "transcript_final",
            "speaker": "interviewer",
        }

        websocket.send_json({"type": "end"})

        # The model finishes its response to the candidate before the interview ends.
        assert websocket.receive_json() == {"type": "turn_complete"}

        assert websocket.receive_json() == {
            "type": "interview_ended",
        }

        result = websocket.receive_json()

        assert result["type"] == "evaluation_complete"
        assert result["report"]["candidate_name"] == "Sam"
        assert result["report"]["job_role"] == "Analyst"
        assert result["report"]["overall_score"] == 85
        assert result["report"]["recommendation"] == "Recommend"
        assert result["artifacts"]["report"] == "fake_report.json"
