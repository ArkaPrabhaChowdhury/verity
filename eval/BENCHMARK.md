# Verity Enterprise Benchmark

The reproducible seed set currently contains 50 public HotpotQA dev-distractor questions sampled with seed `42` and recorded in `datasets/hotpotqa_dev_100.manifest.json`. This covers multi-hop research. The enterprise expansion target is 100 questions with 20 each for multi-hop, current events, technical/official documentation, conflicting or inaccessible sources, and low-evidence/abstention cases.

Run the dataset and evaluation from `eval/`:

```powershell
python download_hotpot.py --size 50 --seed 42
python run_agent_eval.py --variant no_replan --dataset datasets/hotpotqa_dev_100.jsonl --output results/no_replan.jsonl
python run_agent_eval.py --variant critic_replan --dataset datasets/hotpotqa_dev_100.jsonl --output results/critic_replan.jsonl
python score.py
```

The evaluator preserves failed and abstained runs, scores citation validity and numeric-claim coverage, and reports average/P50/P95 latency, estimated cost, trust, contradiction detection, independent domains, failure rate, and abstention rate. `results/benchmark_report.md` is now a measured pilot: one completed Verity no-re-plan run was recorded at 137.97s and $0.00075, while the five baseline calls were blocked by Groq HTTP 403. These numbers are reproducible evidence, not representative benchmark proof. Complete all 50 questions and both Verity variants before claiming benchmark-level accuracy or citation integrity.
