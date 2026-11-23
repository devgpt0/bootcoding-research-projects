"""Question planning helpers; actual questions are generated from live context."""

from api.interview_engine.models import InterviewConfig


def build_question_direction(config: InterviewConfig, asked_questions: list[str]) -> str:
    """Return guidance for the next model turn rather than a hardcoded question."""
    prior = "\n".join(f"- {question}" for question in asked_questions[-12:]) or "- None yet"
    topics = ", ".join(config.topics) if config.topics else "choose role-relevant competencies from the job description"
    return (
        f"Ask exactly one next interview question for a {config.experience_level.value} {config.job_role} "
        f"candidate. Prioritize: {topics}. Use the job description and conversation context. "
        "Do not repeat or merely rephrase a prior question. Respond naturally to the latest answer first, "
        "then ask the next question.\nPreviously asked questions:\n" + prior
    )
