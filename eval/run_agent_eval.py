#!/usr/bin/env python3
"""Run Verity through its public API with or without critic-triggered re-planning."""

from __future__ import annotations

import argparse
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin

from common import append_jsonl, completed_ids, iter_pending, load_jsonl, request_json

DIRECT_ANSWER = re.compile(r"\*\*Direct answer:\*\*\s*(.+)", re.IGNORECASE)
CITATION = re.compile(r"\[(\d+)\]")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("datasets/hotpotqa_dev_100.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend", default="http://localhost:8080")
    parser.add_argument("--variant", choices=("no_replan", "critic_replan"), required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--run-timeout", type=float, default=240)
    parser.add_argument("--api-token", default=os.getenv("VERITY_API_TOKEN"), help="Optional bearer token for authenticated deployments")
    args = parser.parse_args()

    headers = {"Authorization": f"Bearer {args.api_token}"} if args.api_token else None

    done = completed_ids(args.output)
    for item in iter_pending(load_jsonl(args.dataset), done, args.limit):
        started = time.perf_counter()
        create = request_json(urljoin(args.backend, "/api/runs"), method="POST", headers=headers, body={
            "question": item["question"],
            "replan_enabled": args.variant == "critic_replan",
        })
        run_id = create["run_id"]
        deadline = time.monotonic() + args.run_timeout
        run = None
        while time.monotonic() < deadline:
            run = request_json(urljoin(args.backend, f"/api/runs/{run_id}"), headers=headers)
            if run["status"] in ("completed", "failed", "dead_letter"):
                break
            time.sleep(args.poll_seconds)
        if run is None or run["status"] not in ("completed", "failed", "dead_letter"):
            error = "evaluation polling timeout"
            run = run or {}
        else:
            error = run.get("error")
        report = run.get("report", "")
        match = DIRECT_ANSWER.search(report)
        prediction = match.group(1).strip() if match else first_prose_line(report)
        findings = run.get("findings") or []
        source_count = len({source["url"] for finding in findings for source in (finding.get("sources") or []) if source["url"] in report})
        critiques = run.get("critiques") or []
        metadata = run.get("metadata") or {}
        trust = run.get("trust") or {}
        citation_metrics = citation_health(report, findings)
        prediction_lower = prediction.lower()
        append_jsonl(args.output, {
            **item,
            "variant": args.variant,
            "run_id": run_id,
            "prediction": prediction,
            "latency_seconds": metadata.get("total_latency_ms", (time.perf_counter() - started) * 1000) / 1000,
            "estimated_cost_usd": metadata.get("estimated_cost_usd", 0),
            "total_tokens": metadata.get("total_tokens", 0),
            "source_count": source_count,
            "critic_detected_contradiction": any(critic.get("contradictions") for critic in critiques),
            "replan_occurred": metadata.get("replan_occurred", False),
            "trust_status": trust.get("status"),
            "trust_score": trust.get("score"),
            "independent_domains": trust.get("independent_domains"),
            "abstained": any(marker in prediction_lower for marker in ("insufficient evidence", "cannot determine", "unable to determine", "inconclusive")),
            **citation_metrics,
            "error": error,
        })
        print(f"{item['id']} {args.variant} {run.get('status')} {time.perf_counter() - started:.2f}s")


def first_prose_line(report: str) -> str:
    for line in report.splitlines():
        value = line.strip().lstrip("#").strip()
        if value and not value.lower().startswith("references"):
            return value
    return ""


def citation_health(report: str, findings: list[dict]) -> dict[str, float | int]:
    sources = {source["url"] for finding in findings for source in (finding.get("sources") or [])}
    references = {url for url in sources if url in report}
    citation_numbers = [int(value) for value in CITATION.findall(report)]
    valid = [number for number in citation_numbers if 1 <= number <= len(references)]
    factual_lines = [line for line in report.splitlines() if re.search(r"\d|%|\$", line) and not line.lstrip().startswith("[")]
    cited_factual_lines = [line for line in factual_lines if CITATION.search(line)]
    return {
        "citation_count": len(citation_numbers),
        "citation_validity_pct": 100 * len(valid) / len(citation_numbers) if citation_numbers else 0,
        "numeric_claim_citation_pct": 100 * len(cited_factual_lines) / len(factual_lines) if factual_lines else 100,
    }


if __name__ == "__main__":
    main()
