import pytest

from verity.models import (
    Contradiction,
    CriticOutput,
    Finding,
    SourceEvidence,
)
from verity.orchestrator import (
    assess_trust,
    enforce_critic_decision,
    validate_report,
)


def source(url: str) -> SourceEvidence:
    return SourceEvidence(
        title=url,
        url=url,
        domain=url.split("/")[2],
        summary="Supported evidence.",
        excerpt="Evidence excerpt.",
        source_type="web",
        quality_score=65,
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
                    source("https://one.example/a"),
                    source("https://two.example/b"),
                ],
                round=0,
            )
        ],
        [],
    )
    assert trust.status == "verified"
    assert trust.score == 100


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

