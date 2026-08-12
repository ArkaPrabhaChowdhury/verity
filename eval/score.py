#!/usr/bin/env python3
"""Score all benchmark variants and generate the committed trade-off report."""

from __future__ import annotations

import argparse
import collections
import json
import re
import statistics
import string
from pathlib import Path
from typing import Any

from common import load_jsonl


def normalize(text: str) -> str:
    text = text.lower()
    text = "".join(character for character in text if character not in string.punctuation)
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    return " ".join(text.split())


def exact_match(prediction: str, answer: str) -> float:
    return float(normalize(prediction) == normalize(answer))


def token_f1(prediction: str, answer: str) -> float:
    predicted = normalize(prediction).split()
    gold = normalize(answer).split()
    if not predicted or not gold:
        return float(predicted == gold)
    overlap = sum((collections.Counter(predicted) & collections.Counter(gold)).values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(predicted)
    recall = overlap / len(gold)
    return 2 * precision * recall / (precision + recall)


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [record for record in records if not record.get("error")]
    if not successful:
        return {"count": len(records), "successful": 0}
    em = [exact_match(item.get("prediction", ""), item["answer"]) for item in successful]
    f1 = [token_f1(item.get("prediction", ""), item["answer"]) for item in successful]
    partial = [float(score >= 0.5 or normalize(item["answer"]) in normalize(item.get("prediction", ""))) for score, item in zip(f1, successful)]
    contradictions = [item.get("critic_detected_contradiction") for item in successful if item.get("critic_detected_contradiction") is not None]
    trust_scores = [item["trust_score"] for item in successful if item.get("trust_score") is not None]
    citation_validity = [item["citation_validity_pct"] for item in successful if item.get("citation_validity_pct") is not None]
    numeric_coverage = [item["numeric_claim_citation_pct"] for item in successful if item.get("numeric_claim_citation_pct") is not None]
    domain_counts = [item["independent_domains"] for item in successful if item.get("independent_domains") is not None]
    expected_abstentions = [item for item in successful if item.get("answerable") is False]
    latencies = [item["latency_seconds"] for item in successful]
    return {
        "count": len(records),
        "successful": len(successful),
        "exact_match_pct": 100 * statistics.mean(em),
        "partial_match_pct": 100 * statistics.mean(partial),
        "token_f1_pct": 100 * statistics.mean(f1),
        "avg_latency_seconds": statistics.mean(latencies),
        "p50_latency_seconds": statistics.median(latencies),
        "p95_latency_seconds": statistics.quantiles(latencies, n=20, method="inclusive")[18] if len(latencies) > 1 else latencies[0],
        "avg_cost_usd": statistics.mean(item["estimated_cost_usd"] for item in successful),
        "avg_sources": statistics.mean(item["source_count"] for item in successful),
        "contradiction_pct": 100 * statistics.mean(contradictions) if contradictions else None,
        "avg_trust_score": statistics.mean(trust_scores) if trust_scores else None,
        "citation_validity_pct": statistics.mean(citation_validity) if citation_validity else None,
        "numeric_claim_citation_pct": statistics.mean(numeric_coverage) if numeric_coverage else None,
        "avg_independent_domains": statistics.mean(domain_counts) if domain_counts else None,
        "abstention_accuracy_pct": 100 * statistics.mean(float(item.get("abstained", False)) for item in expected_abstentions) if expected_abstentions else None,
        "failure_rate_pct": 100 * (len(records) - len(successful)) / len(records) if records else None,
        "abstention_rate_pct": 100 * statistics.mean(float(item.get("abstained", False)) for item in successful),
    }


def cell(summary: dict[str, Any], key: str, suffix: str = "") -> str:
    value = summary.get(key)
    return "NOT RUN" if value is None else f"{value:.2f}{suffix}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, default=Path("results/baseline.jsonl"))
    parser.add_argument("--no-replan", type=Path, default=Path("results/no_replan.jsonl"))
    parser.add_argument("--critic-replan", type=Path, default=Path("results/critic_replan.jsonl"))
    parser.add_argument("--report", type=Path, default=Path("results/benchmark_report.md"))
    parser.add_argument("--summary-json", type=Path, default=Path("results/summary.json"))
    args = parser.parse_args()

    paths = {"baseline": args.baseline, "no_replan": args.no_replan, "critic_replan": args.critic_replan}
    summaries = {name: summarize(load_jsonl(path)) if path.exists() else {"count": 0, "successful": 0} for name, path in paths.items()}
    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
    args.summary_json.write_text(json.dumps(summaries, indent=2) + "\n", encoding="utf-8")

    names = [("Baseline", summaries["baseline"]), ("Verity (no re-plan)", summaries["no_replan"]), ("Verity (critic re-plan)", summaries["critic_replan"])]
    table = [
        "| Metric | Baseline | Verity (no re-plan) | Verity (critic re-plan) |",
        "|---|---:|---:|---:|",
        "| Completed runs | " + " | ".join(str(summary.get("successful", 0)) for _, summary in names) + " |",
        "| Accuracy (exact / partial) | " + " | ".join(f"{cell(summary, 'exact_match_pct', '%')} / {cell(summary, 'partial_match_pct', '%')}" for _, summary in names) + " |",
        "| Token F1 | " + " | ".join(cell(summary, "token_f1_pct", "%") for _, summary in names) + " |",
        "| Avg wall-clock latency | " + " | ".join(cell(summary, "avg_latency_seconds", "s") for _, summary in names) + " |",
        "| P50 / P95 latency | " + " | ".join(f"{cell(summary, 'p50_latency_seconds', 's')} / {cell(summary, 'p95_latency_seconds', 's')}" for _, summary in names) + " |",
        "| Avg estimated cost/query | " + " | ".join("NOT RUN" if summary.get("avg_cost_usd") is None else f"${summary['avg_cost_usd']:.5f}" for _, summary in names) + " |",
        "| Avg sources cited | " + " | ".join(cell(summary, "avg_sources") for _, summary in names) + " |",
        "| Critic detected contradiction | — | " + " | ".join(cell(summary, "contradiction_pct", "%") for summary in (summaries["no_replan"], summaries["critic_replan"])) + " |",
        "| Avg deterministic trust score | — | " + " | ".join(cell(summary, "avg_trust_score") for summary in (summaries["no_replan"], summaries["critic_replan"])) + " |",
        "| Citation index validity | — | " + " | ".join(cell(summary, "citation_validity_pct", "%") for summary in (summaries["no_replan"], summaries["critic_replan"])) + " |",
        "| Numeric claims with citations | — | " + " | ".join(cell(summary, "numeric_claim_citation_pct", "%") for summary in (summaries["no_replan"], summaries["critic_replan"])) + " |",
        "| Avg independent domains | — | " + " | ".join(cell(summary, "avg_independent_domains") for summary in (summaries["no_replan"], summaries["critic_replan"])) + " |",
        "| Abstention accuracy | — | " + " | ".join(cell(summary, "abstention_accuracy_pct", "%") for summary in (summaries["no_replan"], summaries["critic_replan"])) + " |",
        "| Failure rate / abstention rate | " + " | ".join(f"{cell(summary, 'failure_rate_pct', '%')} / {cell(summary, 'abstention_rate_pct', '%')}" for _, summary in names) + " |",
    ]
    completed = sum(summary.get("successful", 0) for summary in summaries.values())
    analysis = "No benchmark claims are made yet. Configure provider access and run the documented commands; `score.py` will replace every `NOT RUN` cell from raw JSONL outputs." if completed == 0 else "This is a measured pilot, not benchmark proof: only completed raw records are scored, and the table exposes the small denominator. The baseline sample recorded provider HTTP 403 failures, so its NOT RUN cells are an observed integration failure rather than a zero score. Run the full 50-question matrix before presenting accuracy or citation integrity as representative."
    report = "# Verity HotpotQA Benchmark (measured pilot)\n\n" + "\n".join(table) + "\n\n## Method\n\nA deterministic subset of the official HotpotQA dev-distractor set is sampled with seed 42. Exact match and token F1 follow normalized SQuAD-style answer scoring; partial match is true when token F1 is at least 0.50 or the normalized gold answer is contained in the extracted direct answer. Failed runs remain in raw outputs and are excluded from averages, while the completed-run row exposes the denominator. This report is a pilot result and must not be described as a representative benchmark until all planned variants complete across the 50-question set.\n\n## Trade-off analysis\n\n" + analysis + "\n"
    args.report.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
