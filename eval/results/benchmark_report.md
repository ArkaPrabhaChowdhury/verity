# Verity HotpotQA Benchmark

| Metric | Baseline | Verity (no re-plan) | Verity (critic re-plan) |
|---|---:|---:|---:|
| Completed runs | 0 | 0 | 0 |
| Accuracy (exact / partial) | NOT RUN / NOT RUN | NOT RUN / NOT RUN | NOT RUN / NOT RUN |
| Token F1 | NOT RUN | NOT RUN | NOT RUN |
| Avg wall-clock latency | NOT RUN | NOT RUN | NOT RUN |
| Avg estimated cost/query | NOT RUN | NOT RUN | NOT RUN |
| Avg sources cited | NOT RUN | NOT RUN | NOT RUN |
| Critic detected contradiction | — | NOT RUN | NOT RUN |
| Avg deterministic trust score | — | NOT RUN | NOT RUN |
| Citation index validity | — | NOT RUN | NOT RUN |
| Numeric claims with citations | — | NOT RUN | NOT RUN |
| Avg independent domains | — | NOT RUN | NOT RUN |
| Abstention accuracy | — | NOT RUN | NOT RUN |

## Method

A deterministic subset of the official HotpotQA dev-distractor set is sampled with seed 42. Exact match and token F1 follow normalized SQuAD-style answer scoring; partial match is true when token F1 is at least 0.50 or the normalized gold answer is contained in the extracted direct answer. Failed runs remain in raw outputs and are excluded from averages, while the completed-run row exposes the denominator.

## Trade-off analysis

No benchmark claims are made yet. Configure free-tier provider keys and run the documented commands; `score.py` will replace every `NOT RUN` cell from raw JSONL outputs.
