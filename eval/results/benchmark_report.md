# Verity HotpotQA Benchmark (measured pilot)

| Metric | Baseline | Verity (no re-plan) | Verity (critic re-plan) |
|---|---:|---:|---:|
| Completed runs | 0 | 1 | 0 |
| Accuracy (exact / partial) | NOT RUN / NOT RUN | 0.00% / 100.00% | NOT RUN / NOT RUN |
| Token F1 | NOT RUN | 13.33% | NOT RUN |
| Avg wall-clock latency | NOT RUN | 137.97s | NOT RUN |
| P50 / P95 latency | NOT RUN / NOT RUN | 137.97s / 137.97s | NOT RUN / NOT RUN |
| Avg estimated cost/query | NOT RUN | $0.00075 | NOT RUN |
| Avg sources cited | NOT RUN | 0.00 | NOT RUN |
| Critic detected contradiction | — | 0.00% | NOT RUN |
| Avg deterministic trust score | — | 70.00 | NOT RUN |
| Citation index validity | — | 0.00% | NOT RUN |
| Numeric claims with citations | — | 0.00% | NOT RUN |
| Avg independent domains | — | 9.00 | NOT RUN |
| Abstention accuracy | — | NOT RUN | NOT RUN |
| Failure rate / abstention rate | NOT RUN / NOT RUN | 0.00% / 0.00% | NOT RUN / NOT RUN |

## Method

A deterministic subset of the official HotpotQA dev-distractor set is sampled with seed 42. Exact match and token F1 follow normalized SQuAD-style answer scoring; partial match is true when token F1 is at least 0.50 or the normalized gold answer is contained in the extracted direct answer. Failed runs remain in raw outputs and are excluded from averages, while the completed-run row exposes the denominator. This report is a pilot result and must not be described as a representative benchmark until all planned variants complete across the 50-question set.

## Trade-off analysis

This is a measured pilot, not benchmark proof: only completed raw records are scored, and the table exposes the small denominator. The baseline sample recorded provider HTTP 403 failures, so its NOT RUN cells are an observed integration failure rather than a zero score. Run the full 50-question matrix before presenting accuracy or citation integrity as representative.
