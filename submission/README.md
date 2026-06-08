# Lunon Deep Research — DeepResearch Bench Submission

This directory contains **Lunon Deep Research**'s submission to [DeepResearch Bench](https://github.com/Ayanami0730/deep_research_bench) — the 100 generated research reports and their RACE evaluation scores — so the leaderboard entry can be independently inspected and reproduced. The engine that generated them lives in this repository's root (see the [top-level README](../README.md)).

Links: [🏆 Leaderboard](https://huggingface.co/spaces/muset-ai/DeepResearch-Bench-Leaderboard) · [Benchmark](https://github.com/Ayanami0730/deep_research_bench) · [Paper (arXiv:2506.11763)](https://arxiv.org/abs/2506.11763)

## Results

RACE evaluation on all 100 tasks under the **official GPT-5.5 evaluator** (the benchmark's current evaluator, which replaced Gemini-2.5-Pro on 11 May 2026):

| Dimension | Score |
|---|---:|
| Comprehensiveness | 54.10 |
| Insight / Depth | 55.29 |
| Instruction Following | 53.92 |
| Readability | 50.41 |
| **Overall** | **53.97** |

> **Scores are from our own run of the official DRB harness** (RACE evaluator `openai/gpt-5.5`, article cleaner `openai/gpt-5.4-mini`) on the unmodified 100-task query set, June 2026. The maintainers' GPT-5.5 leaderboard is still being populated; treat these as a verified pre-print until the official re-score is posted — that re-score is canonical. Scores are shown ×100; the files in `results/` use the harness-native 0–1 scale.

## Contents

```
submission/
├── data/test_data/raw_data/
│   └── lunon-deep-research.jsonl          # the submission: {id, prompt, article} × 100
├── reports/
│   └── 1.md … 100.md                      # per-task report (the `article` field, for browsing)
└── results/race/lunon-deep-research/
    ├── race_result.txt                    # aggregate: 4 dimensions + weighted overall
    └── raw_results.jsonl                  # per-task RACE scores (id, prompt, 4 dims, overall)
```

- **`data/test_data/raw_data/lunon-deep-research.jsonl`** — the canonical submission file, one JSON object per line in the benchmark's required format: `{"id": <int 1–100>, "prompt": <task>, "article": <report>}`. Citations are inline markdown links.
- **`reports/<id>.md`** — the same report text broken out per task for easy reading. `reports/<id>.md` is byte-for-byte the `article` field of task `<id>`.
- **`results/race/lunon-deep-research/`** — the RACE evaluation output (aggregate + per-task), exactly as written by the official harness.

The benchmark covers 100 PhD-level tasks across 22 fields, **50 Chinese + 50 English**; prompts and reports are kept in each task's native language.

## Reproducing

To regenerate the reports, run the Lunon engine (repo root) against the benchmark's unmodified query set (`data/prompt_data/query.jsonl` from the [benchmark repo](https://github.com/Ayanami0730/deep_research_bench)) — see the [top-level README](../README.md) for setup and run commands.

To re-score this submission against the public harness:

```bash
git clone https://github.com/Ayanami0730/deep_research_bench.git
cd deep_research_bench
cp /path/to/submission/data/test_data/raw_data/lunon-deep-research.jsonl data/test_data/raw_data/
# set TARGET_MODELS=("lunon-deep-research") in run_benchmark.sh, then:
bash run_benchmark.sh
```

**Note on citations and RACE:** the submission uses inline markdown-link citations (the format the FACT grounding metric expects). The RACE evaluator strips all citations before judging, so citation style does not affect the RACE scores reported above.

## Citation

If you use DeepResearch Bench, please cite:

```bibtex
@article{du2025deepresearch,
  author  = {Mingxuan Du and Benfeng Xu and Chiwei Zhu and Xiaorui Wang and Zhendong Mao},
  title   = {DeepResearch Bench: A Comprehensive Benchmark for Deep Research Agents},
  journal = {arXiv preprint},
  year    = {2025},
}
```

The contents of this directory are released under the repository's [MIT License](../LICENSE).
