"""Validated report and transcript artifact creation and persistence."""

from __future__ import annotations

import re
import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from api.evaluation.evaluator import (
    EvaluationResult,
    Recommendation,
    SkillAssessment,
    overall_score,
)
from api.interview_engine.interview_manager import TranscriptEntry
from api.interview_engine.models import ExperienceLevel, InterviewConfig, InterviewType

PROJECT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_NUMBERED_FILE = re.compile(r"^(?:transcript|report)(\d+)\.(?:txt|json)$")
_allocation_lock = threading.Lock()


@contextmanager
def _reserve_interview_number(output_root: Path):
    """Reserve a number across threads and processes until all files are written."""
    transcripts = output_root / "transcripts"
    reports = output_root / "reports"
    transcripts.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    with _allocation_lock:
        used = []
        for directory in (transcripts, reports):
            for path in directory.iterdir():
                match = _NUMBERED_FILE.match(path.name)
                if match:
                    used.append(int(match.group(1)))
                if path.name.startswith(".interview-number-"):
                    try:
                        used.append(int(path.name.rsplit("-", 1)[1]))
                    except ValueError:
                        pass
        number = max(used, default=0) + 1
        while True:
            marker = reports / f".interview-number-{number}"
            try:
                descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(descriptor)
                break
            except FileExistsError:
                number += 1
    try:
        yield number
    finally:
        marker.unlink(missing_ok=True)


class InterviewReport(BaseModel):
    """Complete, JSON-serializable interview evaluation report."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    interview_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    candidate_name: str
    job_role: str
    experience_level: ExperienceLevel
    interview_type: InterviewType
    duration_minutes: int
    topics: list[str]
    job_description: str
    started_at: datetime
    completed_at: datetime
    overall_score: int = Field(ge=0, le=100)
    skill_scores: list[SkillAssessment]
    strengths: list[str]
    weaknesses: list[str]
    improvement_suggestions: list[str]
    final_assessment: str
    recommendation: Recommendation


class TranscriptArtifact(BaseModel):
    """Persisted transcript envelope with timestamps and speaker labels."""

    model_config = ConfigDict(extra="forbid")

    interview_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    candidate_name: str
    job_role: str
    entries: list[TranscriptEntry]


def build_report(
    config: InterviewConfig,
    interview_id: str,
    started_at: datetime,
    completed_at: datetime,
    evaluation: EvaluationResult,
) -> InterviewReport:
    """Combine validated setup and evaluation into a validated report."""
    recommendation = evaluation.recommendation
    if not any(skill.score is not None for skill in evaluation.skills):
        recommendation = Recommendation.INSUFFICIENT
    return InterviewReport(
        interview_id=interview_id,
        candidate_name=config.candidate_name,
        job_role=config.job_role,
        experience_level=config.experience_level,
        interview_type=config.interview_type,
        duration_minutes=config.duration_minutes,
        topics=config.topics,
        job_description=config.job_description,
        started_at=started_at,
        completed_at=completed_at,
        overall_score=overall_score(evaluation),
        skill_scores=evaluation.skills,
        strengths=evaluation.strengths,
        weaknesses=evaluation.weaknesses,
        improvement_suggestions=evaluation.improvement_suggestions,
        final_assessment=evaluation.final_assessment,
        recommendation=recommendation,
    )


def _write_atomically(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
            temporary.write(content)
        # Exclusive creation protects existing artifacts even in an unexpected collision.
        with open(temp_name, "rb") as source, open(path, "xb") as target:
            target.write(source.read())
    finally:
        Path(temp_name).unlink(missing_ok=True)
    return path


def save_report(report: InterviewReport, output_root: Path = PROJECT_OUTPUT_DIR) -> Path:
    """Validate and save a report using the next sequential report number."""
    validated = InterviewReport.model_validate(report.model_dump())
    if not _SAFE_ID.fullmatch(validated.interview_id):
        raise ValueError("interview_id contains unsafe path characters")
    with _reserve_interview_number(output_root) as number:
        target = output_root / "reports" / f"report{number}.json"
        return _write_atomically(target, validated.model_dump_json(indent=2))


def save_transcript(
    interview_id: str,
    config: InterviewConfig,
    entries: list[TranscriptEntry],
    output_root: Path = PROJECT_OUTPUT_DIR,
) -> tuple[Path, Path]:
    """Save timestamped JSON and readable TXT transcript files."""
    if not _SAFE_ID.fullmatch(interview_id):
        raise ValueError("interview_id contains unsafe path characters")
    artifact = TranscriptArtifact(
        interview_id=interview_id,
        candidate_name=config.candidate_name,
        job_role=config.job_role,
        entries=entries,
    )
    lines = [f"Interview: {interview_id}", f"Candidate: {config.candidate_name}", f"Role: {config.job_role}", ""]
    lines.extend(
        f"[{entry.timestamp.astimezone(timezone.utc).isoformat()}] {entry.speaker.title()}: {entry.text}"
        for entry in entries
    )
    return _save_transcript_with_number(artifact, "\n".join(lines) + "\n", output_root)


def _save_transcript_with_number(artifact: TranscriptArtifact, text: str, output_root: Path, number: int | None = None):
    if number is None:
        with _reserve_interview_number(output_root) as allocated:
            return _save_transcript_with_number(artifact, text, output_root, allocated)
    base = output_root / "transcripts" / f"transcript{number}"
    json_path = _write_atomically(base.with_suffix(".json"), artifact.model_dump_json(indent=2))
    text_path = _write_atomically(base.with_suffix(".txt"), text)
    return json_path, text_path


def save_interview_artifacts(
    report: InterviewReport,
    transcript: list[TranscriptEntry],
    output_root: Path = PROJECT_OUTPUT_DIR,
) -> dict[str, Path]:
    """Save the report and both transcript formats under the configured output root."""
    config = InterviewConfig(
            candidate_name=report.candidate_name,
            job_role=report.job_role,
            experience_level=report.experience_level,
            interview_type=report.interview_type,
            duration_minutes=report.duration_minutes,
            topics=report.topics,
            job_description=report.job_description,
        )
    artifact = TranscriptArtifact(
        interview_id=report.interview_id,
        candidate_name=report.candidate_name,
        job_role=report.job_role,
        entries=transcript,
    )
    lines = [f"Interview: {report.interview_id}", f"Candidate: {config.candidate_name}", f"Role: {config.job_role}", ""]
    lines.extend(f"[{entry.timestamp.astimezone(timezone.utc).isoformat()}] {entry.speaker.title()}: {entry.text}" for entry in transcript)
    validated = InterviewReport.model_validate(report.model_dump())
    with _reserve_interview_number(output_root) as number:
        transcript_json, transcript_txt = _save_transcript_with_number(artifact, "\n".join(lines) + "\n", output_root, number)
        report_path = _write_atomically(output_root / "reports" / f"report{number}.json", validated.model_dump_json(indent=2))
    return {"report": report_path, "transcript_json": transcript_json, "transcript_txt": transcript_txt}
