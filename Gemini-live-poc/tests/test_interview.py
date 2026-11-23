import pytest
from pydantic import ValidationError

from api.interview_engine.instruction_generator import generate_interviewer_instructions
from api.interview_engine.interview_manager import InterviewSession
from api.interview_engine.models import InterviewConfig
from api.interview_engine.question_generator import build_question_direction


def make_config(**overrides: object) -> InterviewConfig:
    data: dict[str, object] = {
        "candidate_name": "Alex",
        "job_role": "Data Analyst",
        "experience_level": "Mid-level",
        "interview_type": "Mixed",
        "duration_minutes": 30,
        "topics": ["SQL", "Communication"],
        "job_description": "Own reporting and stakeholder analysis.",
    }
    data.update(overrides)
    return InterviewConfig.model_validate(data)


def test_config_validates_and_normalizes_topics() -> None:
    config = make_config(topics=[" SQL ", "sql", "", "Dashboards"])
    assert config.topics == ["SQL", "Dashboards"]


@pytest.mark.parametrize("duration", [10, 20, 75])
def test_config_rejects_invalid_duration(duration: int) -> None:
    with pytest.raises(ValidationError):
        make_config(duration_minutes=duration)


def test_instructions_adapt_to_role_experience_and_description() -> None:
    junior = generate_interviewer_instructions(make_config(experience_level="Junior"))
    senior = generate_interviewer_instructions(make_config(experience_level="Senior", job_role="Project Manager"))
    assert "Data Analyst" in junior and "practical ownership" in junior
    assert "Project Manager" in senior and "strategy" in senior
    assert "Own reporting" in junior


def test_interviewer_instructions_require_english_only() -> None:
    instructions = generate_interviewer_instructions(make_config())
    assert "entire interview in English only" in instructions
    assert "Do not switch languages" in instructions
    assert "first interview question" in instructions
    assert "introduce themselves" in instructions
    assert "Do not ask a technical" in instructions
    assert "strictly an interviewer" in instructions
    assert "Never provide answers" in instructions
    assert "unrelated conversation" in instructions


def test_question_direction_avoids_previous_questions() -> None:
    guidance = build_question_direction(make_config(), ["Describe a dashboard you built."])
    assert "exactly one next interview question" in guidance
    assert "Describe a dashboard you built." in guidance


def test_session_tracks_transcript_and_completion() -> None:
    session = InterviewSession(config=make_config())
    session.add_transcript_entry("interviewer", "How do you validate a report?")
    session.add_transcript_entry("candidate", "I reconcile totals with source data.")
    assert len(session.transcript) == 2
    assert session.asked_questions == ["How do you validate a report?"]
    assert session.remaining_seconds <= 1800
    session.finish()
    assert session.completed


@pytest.mark.parametrize(("duration", "actual_seconds"), [(15, 15 * 60), (30, 30 * 60), (45, 45 * 60), (60, 60 * 60)])
def test_actual_interview_duration_uses_full_configured_duration(duration: int, actual_seconds: int) -> None:
    session = InterviewSession(config=make_config(duration_minutes=duration))
    created_at = session.started_at
    assert session.actual_duration_seconds == actual_seconds
    assert not session.started_event.is_set()
    session.start()
    assert session.started_event.is_set()
    assert session.started_at >= created_at
