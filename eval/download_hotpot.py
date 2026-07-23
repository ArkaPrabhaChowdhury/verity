#!/usr/bin/env python3
"""Download HotpotQA dev-distractor and create a deterministic JSONL subset."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import urllib.request
from pathlib import Path

SOURCE_URLS = [
    "https://curtis.ml.cmu.edu/datasets/hotpot/hotpot_dev_distractor_v1.json",
    "https://huggingface.co/datasets/namlh2004/hotpotqa/resolve/main/hotpot_dev_distractor_v1.json?download=true",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", type=int, default=100, choices=range(1, 101))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path("datasets/hotpotqa_dev_100.jsonl"))
    args = parser.parse_args()

    raw_path = args.output.parent / "hotpot_dev_distractor_v1.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    downloaded_from = "existing local file"
    if not raw_path.exists():
        last_error = None
        for source_url in SOURCE_URLS:
            try:
                print(f"Downloading {source_url}")
                request = urllib.request.Request(source_url, headers={"User-Agent": "VerityEval/1.0"})
                with urllib.request.urlopen(request, timeout=120) as response, raw_path.open("wb") as output:
                    output.write(response.read())
                downloaded_from = source_url
                break
            except Exception as error:
                last_error = error
                raw_path.unlink(missing_ok=True)
        if not raw_path.exists():
            raise SystemExit(f"Could not download HotpotQA from configured sources: {last_error}")

    raw_bytes = raw_path.read_bytes()
    records = json.loads(raw_bytes)
    rng = random.Random(args.seed)
    indices = sorted(rng.sample(range(len(records)), args.size))
    with args.output.open("w", encoding="utf-8") as handle:
        for index in indices:
            item = records[index]
            handle.write(json.dumps({
                "id": item["_id"],
                "question": item["question"],
                "answer": item["answer"],
                "type": item.get("type"),
                "level": item.get("level"),
            }, ensure_ascii=False) + "\n")

    manifest = {
        "source_url": downloaded_from,
        "source_candidates": SOURCE_URLS,
        "source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "seed": args.seed,
        "size": args.size,
        "output": str(args.output),
        "selected_ids_sha256": hashlib.sha256("\n".join(records[i]["_id"] for i in indices).encode()).hexdigest(),
    }
    args.output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
