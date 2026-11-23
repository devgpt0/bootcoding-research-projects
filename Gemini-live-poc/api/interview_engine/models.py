"""Validated interview setup models shared by the API and interview engine."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExperienceLevel(StrEnum):
    FRESHER = "Fresher"
    JUNIOR = "Junior"
    MID_LEVEL = "Mid-level"
    SENIOR = "Senior"


class InterviewType(StrEnum):
    TECHNICAL = "Technical"
    HR = "HR"
    BEHAVIORAL = "Behavioral"
    MANAGERIAL = "Managerial"
    MIXED = "Mixed"


class InterviewConfig(BaseModel):
    """Candidate-selected context for one interview."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    candidate_name: str = Field(min_length=1, max_length=120)
    job_role: str = Field(min_length=2, max_length=160)
    experience_level: ExperienceLevel
    interview_type: InterviewType = InterviewType.MIXED
    duration_minutes: int = Field(default=30, ge=15, le=60, multiple_of=15)
    topics: list[str] = Field(default_factory=list, max_length=20)
    job_description: str = Field(default="", max_length=10_000)

    @field_validator("topics")
    @classmethod
    def normalize_topics(cls, topics: list[str]) -> list[str]:
        cleaned = [topic.strip() for topic in topics if topic.strip()]
        if any(len(topic) > 100 for topic in cleaned):
            raise ValueError("Each topic must be 100 characters or fewer")
        # Deduplicate case-insensitively while retaining user-provided order.
        return list({topic.casefold(): topic for topic in reversed(cleaned)}.values())[::-1]
