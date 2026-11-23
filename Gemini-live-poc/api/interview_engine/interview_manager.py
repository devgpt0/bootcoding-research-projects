"""In-memory lifecycle and turn tracking for interview sessions."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4
import asyncio

from api.interview_engine.models import InterviewConfig


@dataclass
class TranscriptEntry:
    speaker: str
    text: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class InterviewSession:
    config: InterviewConfig
    interview_id: str = field(default_factory=lambda: str(uuid4()))
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    transcript: list[TranscriptEntry] = field(default_factory=list)
    asked_questions: list[str] = field(default_factory=list)
    completed: bool = False
    started_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    @property
    def actual_duration_seconds(self) -> int:
        return self.config.duration_minutes * 60

    def start(self) -> None:
        """Start the timed interview after Gemini finishes its opening turn."""
        if not self.started_event.is_set() and not self.completed:
            self.started_at = datetime.now(timezone.utc)
            self.started_event.set()

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, (datetime.now(timezone.utc) - self.started_at).total_seconds())

    @property
    def remaining_seconds(self) -> float:
        if not self.started_event.is_set():
            return float(self.actual_duration_seconds)
        return max(0.0, self.actual_duration_seconds - self.elapsed_seconds)

    def add_transcript_entry(self, speaker: str, text: str) -> TranscriptEntry:
        if speaker not in {"candidate", "interviewer"}:
            raise ValueError("speaker must be 'candidate' or 'interviewer'")
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("transcript text cannot be empty")
        entry = TranscriptEntry(speaker=speaker, text=cleaned)
        self.transcript.append(entry)
        if speaker == "interviewer":
            self.asked_questions.append(cleaned)
        return entry

    def finish(self) -> None:
        self.completed = True
