#!/usr/bin/env python3
"""Run the no-search, one-call Groq control condition."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from common import append_jsonl, completed_ids, iter_pending, load_jsonl, request_json, sleep_backoff

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("datasets/hotpotqa_dev_100.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("results/baseline.jsonl"))
    parser.add_argument("--model", default=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"))
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise SystemExit("GROQ_API_KEY is required; never commit it.")

    done = completed_ids(args.output)
    for item in iter_pending(load_jsonl(args.dataset), done, args.limit):
        started = time.perf_counter()
        response = None
        error = None
        for attempt in range(2):
            try:
                response = request_json(GROQ_URL, method="POST", headers={"Authorization": f"Bearer {api_key}"}, body={
                    "model": args.model,
                    "temperature": 0,
                    "max_tokens": 160,
                    "messages": [
                        {"role": "system", "content": "Answer the question from parametric knowledge only. Return only the shortest complete answer; no explanation and no citations."},
                        {"role": "user", "content": item["question"]},
                    ],
                })
                break
            except Exception as reason:  # preserve failures in the reproducible output
                error = str(reason)
                if attempt == 0:
                    sleep_backoff(attempt)
        latency = time.perf_counter() - started
        usage = (response or {}).get("usage", {})
        prediction = ((response or {}).get("choices") or [{}])[0].get("message", {}).get("content", "")
        cost = usage.get("prompt_tokens", 0) * 0.59 / 1_000_000 + usage.get("completion_tokens", 0) * 0.79 / 1_000_000
        append_jsonl(args.output, {
            **item,
            "variant": "baseline",
            "prediction": prediction.strip(),
            "latency_seconds": latency,
            "estimated_cost_usd": cost,
            "total_tokens": usage.get("total_tokens", 0),
            "source_count": 0,
            "critic_detected_contradiction": None,
            "error": error if response is None else None,
        })
        print(f"{item['id']} baseline {latency:.2f}s")


if __name__ == "__main__":
    main()
