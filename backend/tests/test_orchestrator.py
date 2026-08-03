import pytest

from verity.models import (
    Contradiction,
    CriticOutput,
    Document,
    Finding,
    SearchResult,
    SourceEvidence,
    SubQuestion,
)
from verity.orchestrator import (
    Executor,
    UsageRecorder,
    assess_trust,
    build_search_queries,
    classify_evidence_path,
    classify_source,
    enforce_critic_decision,
    is_relevant_document,
    select_source_candidates,
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


def test_search_queries_cover_primary_and_research_evidence() -> None:
    queries = build_search_queries("climate adaptation policy", 3)
    assert queries[0] == "climate adaptation policy"
    assert "official government guidance" in queries[1]
    assert "systematic review meta-analysis PubMed" in queries[2]


def test_research_and_validated_domains_are_prioritized() -> None:
    assert classify_source("pubmed.ncbi.nlm.nih.gov") == ("research", 90)
    assert classify_source("example.gov") == ("government", 95)


def test_source_candidates_prefer_trusted_domains() -> None:
    results = [
        SearchResult(title="Generic blog", url="https://blog.example/a"),
        SearchResult(title="Research paper", url="https://www.nature.com/articles/a"),
    ]
    assert [item.url for item in select_source_candidates(results)] == [
        "https://www.nature.com/articles/a"
    ]


def test_irrelevant_boilerplate_is_rejected() -> None:
    assert not is_relevant_document(
        Document(
            url="https://pmc.ncbi.nlm.nih.gov/articles/PMC7544061",
            title="Checking your browser",
            text="Please complete the CAPTCHA challenge to continue.",
        ),
        "urban tree planting reducing summer heat",
    )
    assert is_relevant_document(
        Document(
            url="https://journals.plos.org/plosone/article?id=1",
            title="Urban tree planting and summer heat",
            text="This study evaluates cooling from urban tree planting.",
        ),
        "urban tree planting reducing summer heat",
    )
    assert not is_relevant_document(
        Document(
            url="https://doi.org/10.1234/stroke",
            title="The impact of triglyceride index on ischemic stroke: a systematic review",
            text="This review examines stroke outcomes and metabolic risk factors.",
        ),
        "intermittent fasting for weight loss in adults",
    )
    assert not is_relevant_document(
        Document(
            url="https://journals.plos.org/plosone/article?id=2",
            title="Intermittent fasting in animal models: a systematic review",
            text="This review evaluates animal models.",
        ),
        "intermittent fasting for weight loss in adults",
    )
    assert not is_relevant_document(
        Document(
            url="https://doi.org/10.1234/exercise",
            title="Effects of high-intensity interval training on cardiometabolic health",
            text="A systematic review of exercise and body weight outcomes.",
        ),
        "intermittent fasting for weight loss in adults",
    )


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
