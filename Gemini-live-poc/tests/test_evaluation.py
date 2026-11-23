from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from api.evaluation.evaluator import (
    EvaluationResult,
    EvidenceStatus,
    Recommendation,
    SkillAssessment,
    build_evaluation_prompt,
    overall_score,
)
from api.evaluation.report_generator import build_report, save_interview_artifacts
from api.interview_engine.interview_manager import TranscriptEntry
from api.interview_engine.models import InterviewConfig


def config() -> InterviewConfig:
    return InterviewConfig(
        candidate_name="Taylor",
        job_role="Data Analyst",
        experience_level="Mid-level",
        topics=["SQL", "Stakeholder communication"],
        job_description="Build reliable analytics for business teams.",
    )


def test_skill_cannot_claim_score_without_evidence() -> None:
    with pytest.raises(ValidationError):
        SkillAssessment(
            skill="SQL reasoning",
            score=80,
            evidence_status=EvidenceStatus.INSUFFICIENT,
            rationale="No relevant answer was captured.",
        )


def test_overall_score_is_weighted_and_ignores_insufficient_skills() -> None:
    result = EvaluationResult(
        skills=[
            SkillAssessment(skill="SQL", score=80, weight=3, evidence_status="assessed", rationale="Explained joins."),
            SkillAssessment(skill="Presentation", score=40, weight=1, evidence_status="assessed", rationale="Brief example."),
            SkillAssessment(skill="Governance", evidence_status="insufficiently_assessed", rationale="Not discussed."),
        ],
        final_assessment="Some evidence was available.",
        recommendation=Recommendation.CONSIDER,
    )
    assert overall_score(result) == 70


def test_evaluation_prompt_uses_role_context_and_evidence_safeguards() -> None:
    transcript = [TranscriptEntry(speaker="candidate", text="I used SQL to reconcile totals.")]
    prompt = build_evaluation_prompt(config(), transcript)
    assert "Data Analyst" in prompt
    assert "reliable analytics" in prompt
    assert "transcript as evidence" in prompt
    assert "insufficiently_assessed" in prompt


def test_response_schema_has_no_unsupported_additional_properties_fields() -> None:
    schema = EvaluationResult.model_json_schema()

    def contains_additional_properties(value) -> bool:
        if isinstance(value, dict):
            return "additionalProperties" in value or any(
                contains_additional_properties(child) for child in value.values()
            )
        if isinstance(value, list):
            return any(contains_additional_properties(child) for child in value)
        return False

    assert not contains_additional_properties(schema)


def test_build_and_save_validated_report_and_transcripts(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    transcript = [TranscriptEntry(speaker="candidate", text="I reconciled the source data.")]
    evaluation = EvaluationResult(
        skills=[SkillAssessment(
            skill="Data validation",
            score=84,
            weight=2,
            evidence_status="assessed",
            rationale="Described reconciling source data.",
        )],
        strengths=["Uses source reconciliation."],
        weaknesses=["Limited detail on edge cases."],
        improvement_suggestions=["Explain validation of missing values."],
        final_assessment="Relevant evidence for the role was demonstrated.",
        recommendation=Recommendation.RECOMMEND,
    )
    report = build_report(config(), "interview-test_123", now, now, evaluation)
    paths = save_interview_artifacts(report, transcript, tmp_path)

    assert report.overall_score == 84
    assert paths["report"].exists()
    assert paths["transcript_json"].exists()
    assert "Candidate: I reconciled the source data." in paths["transcript_txt"].read_text(encoding="utf-8")
    assert '"overall_score": 84' in paths["report"].read_text(encoding="utf-8")
    assert paths["report"].name == "report1.json"
    assert paths["transcript_json"].name == "transcript1.json"
    assert paths["transcript_txt"].name == "transcript1.txt"


def test_numbering_continues_and_never_overwrites_existing_artifacts(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    transcript = [TranscriptEntry(speaker="candidate", text="Existing evidence.")]
    evaluation = EvaluationResult(
        skills=[SkillAssessment(skill="Analysis", score=80, weight=1, evidence_status="assessed", rationale="Evidence.")],
        final_assessment="Good evidence.", recommendation=Recommendation.RECOMMEND,
    )
    report = build_report(config(), "interview-second", now, now, evaluation)
    first = save_interview_artifacts(report, transcript, tmp_path)
    original = first["report"].read_bytes()
    second = save_interview_artifacts(report, transcript, tmp_path)
    assert second["report"].name == "report2.json"
    assert second["transcript_json"].name == "transcript2.json"
    assert first["report"].read_bytes() == original


def test_concurrent_artifact_saves_get_unique_shared_numbers(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    transcript = [TranscriptEntry(speaker="candidate", text="Evidence.")]
    evaluation = EvaluationResult(
        skills=[SkillAssessment(skill="Analysis", score=80, weight=1, evidence_status="assessed", rationale="Evidence.")],
        final_assessment="Good evidence.", recommendation=Recommendation.RECOMMEND,
    )
    reports = [build_report(config(), f"interview-{n}", now, now, evaluation) for n in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda item: save_interview_artifacts(item, transcript, tmp_path), reports))
    report_nums = {path["report"].stem.removeprefix("report") for path in results}
    transcript_nums = {path["transcript_txt"].stem.removeprefix("transcript") for path in results}
    assert len(report_nums) == 8
    assert report_nums == transcript_nums
