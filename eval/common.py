from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def completed_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {item["id"] for item in load_jsonl(path)}


def request_json(url: str, *, method: str = "GET", body: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: float = 60) -> dict[str, Any]:
    payload = json.dumps(body).encode() if body is not None else None
    final_headers = {"Accept": "application/json", **(headers or {})}
    if payload is not None:
        final_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=payload, method=method, headers=final_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {error.code} from {url}: {detail}") from error


def iter_pending(dataset: Iterable[dict[str, Any]], done: set[str], limit: int | None) -> Iterable[dict[str, Any]]:
    emitted = 0
    for item in dataset:
        if item["id"] in done:
            continue
        if limit is not None and emitted >= limit:
            return
        emitted += 1
        yield item


def sleep_backoff(attempt: int) -> None:
    time.sleep(min(30, 2 ** attempt))

