import pytest

from verity.models import (
    Contradiction,
    CriticOutput,
    Finding,
    SourceEvidence,
    SubQuestion,
)
from verity.orchestrator import (
    Executor,
    UsageRecorder,
    assess_trust,
    classify_evidence_path,
    classify_source,
    enforce_critic_decision,
    validate_report,
)


def source(url: str, quality_score: int = 65) -> SourceEvidence:
    return SourceEvidence(
        title=url,
        url=url,
        domain=url.split("/")[2],
        summary="Supported evidence.",
        excerpt="Evidence excerpt.",
        source_type="web",
        quality_score=quality_score,
    )


def test_trust_is_inconclusive_without_successful_evidence() -> None:
    trust = assess_trust(
        [
            Finding(
                sub_question_id="q1",
                question="Question",
                status="partial",
                sources=[source("https://one.example/a")],
                round=0,
            )
        ],
        [],
    )
    assert trust.status == "inconclusive"
    assert trust.score <= 30


def test_trust_verifies_independent_successful_evidence() -> None:
    trust = assess_trust(
        [
            Finding(
                sub_question_id="q1",
                question="Question",
                status="success",
                sources=[
                    source("https://one.example/a", 90),
                    source("https://two.example/b", 90),
                ],
                round=0,
            )
        ],
        [],
    )
    assert trust.status == "verified"
    assert trust.score == 100


def test_discarded_search_noise_does_not_downgrade_supported_path() -> None:
    status, error = classify_evidence_path(
        [
            source("https://one.example/a"),
            source("https://two.example/b"),
        ],
        result_count=4,
        direct_failures=1,
        rejected=1,
    )
    assert status == "success"
    assert error == ""


def test_same_domain_sources_remain_partial() -> None:
    status, error = classify_evidence_path(
        [
            source("https://one.example/a"),
            source("https://one.example/b"),
        ],
        result_count=4,
        direct_failures=0,
        rejected=2,
    )
    assert status == "partial"
    assert "1 independent domains" in error


async def test_executor_persists_subquestion_exception_as_failed_finding() -> None:
    class FailingSearch:
        async def search(self, query: str, max_results: int):
            raise RuntimeError("search unavailable")

    executor = Executor(
        llm=None,
        search=FailingSearch(),
        extractor=None,
        concurrency=1,
        search_cost_per_query=0,
    )
    finding = await executor._execute_one(
        SubQuestion(
            id="q1",
            question="Question",
            search_query="query",
            rationale="Test failure persistence",
            round=0,
        ),
        UsageRecorder(),
    )

    assert finding.status == "failed"
    assert finding.error == "search unavailable"


def test_official_documentation_receives_primary_source_weight() -> None:
    assert classify_source("fastapi.tiangolo.com") == ("documentation", 95)


def test_mixed_replan_evidence_is_qualified_instead_of_collapsed() -> None:
    findings = [
        Finding(
            sub_question_id=f"success-{index}",
            question="Question",
            status="success",
            sources=[
                source(f"https://primary{index}.example/a", 75),
                source(f"https://secondary{index}.example/b", 75),
            ],
            round=0,
        )
        for index in range(4)
    ]
    findings.extend(
        Finding(
            sub_question_id=f"partial-{index}",
            question="Question",
            status="partial",
            sources=[source(f"https://partial{index}.example/a", 65)],
            round=0,
        )
        for index in range(4)
    )
    findings.append(
        Finding(
            sub_question_id="failed",
            question="Question",
            status="failed",
            round=1,
        )
    )
    critique = CriticOutput(
        coverage_assessment=[],
        decision="PROCEED",
        forced_proceed=True,
    )

    trust = assess_trust(findings, [critique])

    assert trust.status == "qualified"
    assert 55 <= trust.score <= 70
    assert "re-plan limit" in " ".join(trust.reasons)


def test_contradiction_qualifies_trust() -> None:
    finding = Finding(
        sub_question_id="q1",
        question="Question",
        status="success",
        sources=[source("https://one.example/a"), source("https://two.example/b")],
        round=0,
    )
    critique = CriticOutput(
        coverage_assessment=[],
        contradictions=[
            Contradiction(
                claim="Conflicting claim",
                source_urls=["https://one.example/a", "https://two.example/b"],
                explanation="Sources disagree.",
            )
        ],
        decision="PROCEED",
    )
    assert assess_trust([finding], [critique]).status == "qualified"


def test_deterministic_gate_overrides_overconfident_critic() -> None:
    critique = CriticOutput(
        coverage_assessment=[
            {
                "sub_question_id": "q1",
                "assessment": "thin",
                "reason": "Only one source",
            }
        ],
        decision="PROCEED",
    )
    finding = Finding(
        sub_question_id="q1",
        question="Question",
        status="partial",
        sources=[source("https://one.example/a")],
        round=0,
    )
    enforce_critic_decision(critique, [finding])
    assert critique.decision == "RE_PLAN"


def test_report_rejects_unknown_urls() -> None:
    report = (
        "**Direct answer:** Supported [1]\n\n"
        "## References\n1. https://unknown.example\n\n"
        "## Gaps & Caveats\nNone."
    )
    with pytest.raises(ValueError, match="unknown URL"):
        validate_report(report, {"https://known.example"})
