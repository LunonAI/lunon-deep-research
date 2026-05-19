<p align="center">
  <img src="assets/lunon-announcement.gif" alt="Lunon" width="680">
</p>

# lunon-deep-research

*Lunon's public submission, results, and reproducibility record for DeepResearch Bench.*

![DRB I rank](https://img.shields.io/badge/DRB_I_rank-TBD-0A2236?style=flat-square)
![DRB II rank](https://img.shields.io/badge/DRB_II_rank-TBD-0A2236?style=flat-square)
![RACE](https://img.shields.io/badge/RACE-TBD-2563EB?style=flat-square)
![FACT](https://img.shields.io/badge/FACT-TBD-2563EB?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-0A2236?style=flat-square)
![Status](https://img.shields.io/badge/status-active-2563EB?style=flat-square)

[Results](#results) · [Reproducibility](#reproducibility) · [Methodology](#methodology) · [About Lunon](#about-lunon)

---

## About

[Lunon](https://lunon.ai) is an AI-native consulting firm that produces institutional-grade research and analysis for private equity firms and global enterprises. We submit to DeepResearch Bench because the public leaderboard measures, on a shared and contested set of tasks, the same capability our clients pay for: accurate, well-sourced, deeply synthesized research. This repository is the results and reproducibility record for that submission.

---

## Results

DeepResearch Bench (DRB) I, evaluated with RACE and FACT.

| Metric          | Score | Rank |
| --------------- | ----- | ---- |
| RACE (overall)  | TBD   | TBD  |
| FACT            | TBD   | TBD  |

DeepResearch Bench (DRB) II, evaluated with the upstream rubric.

| Metric                 | Score | Rank |
| ---------------------- | ----- | ---- |
| Rubric score (overall) | TBD   | TBD  |

Scores reflect the most recent independent re-scoring by the DeepResearch Bench team. Last updated: TBD.

---

## What was benchmarked

Every result in this repository was produced by the production Lunon Investigation phase running against the unmodified DeepResearch Bench query sets: the 100 DRB I queries and the 132 DRB II tasks. The exact platform build is pinned in `VERSION` as `lunon-platform@<sha>`.

> No benchmark-specific code path, prompt, or scaffold was used. The same Investigation pipeline that runs paid client engagements is what produced these outputs.

The research pipeline is built on the Claude Agent SDK, and final reports are composed in the production report editor (Tiptap). Neither was modified for the benchmark. The DRB queries entered the pipeline through the same interface a consultant uses to brief an engagement.

---

## Reproducibility

The production platform is private, so end-to-end reproduction of the pipeline is not possible from this repository alone. Independent verification is instead done the way the leaderboard intends: by submitting the produced outputs to the DeepResearch Bench team for re-scoring.

1. Fetch the pinned platform build. Read `VERSION` for the exact `lunon-platform@<sha>` tag used for this run. This is the single source of truth for what produced the outputs.
2. Run against the unmodified DRB query sets. Use the published query files as-is, with no rewrites or filtering. DRB I and DRB II query sets and tooling are maintained upstream at [agentresearchlab.com](https://agentresearchlab.com) and [github.com/Ayanami0730/deep_research_bench](https://github.com/Ayanami0730/deep_research_bench).
3. Submit outputs to the DeepResearch Bench team for re-scoring. The contents of `report_logs/` are the JSONL submission artifact (`{id, prompt, article}` per line). Send them to the maintainers for independent scoring. Contact: `<ustc-drb-contact@placeholder>`.

---

## Production constraints

These outputs were generated under live production conditions, not an unconstrained benchmark configuration. We disclose the constraints so the scores are read correctly.

- Engagement-time budget. Runs were bounded by the same wall-clock and compute budget a real client engagement receives. The pipeline was not given extended time for the benchmark.
- Output token cap. Each report was generated under the standard production output ceiling. Reports were not lengthened to chase rubric coverage.
- Citation requirements. Every nontrivial claim carries a resolvable source citation, enforced by the production pipeline rather than added for the benchmark.
- Model configuration. Frontier general-purpose models in the standard production configuration. No benchmark-specific model selection, fine-tuning, decoding changes, or query-specific tuning.

Proprietary prompts and any internal scoring or rubric details are deliberately excluded.

---

## Repository structure

```
lunon-deep-research/
├── eval_results/         # RACE and FACT scores (DRB I), rubric scores (DRB II)
├── report_logs/          # Model outputs as JSONL: {id, prompt, article}
│   ├── drb_i/             # 100 DRB I query outputs
│   └── drb_ii/            # 132 DRB II task outputs
├── assets/                # Brand and product visuals
│   └── lunon-announcement.gif  # Hero banner (Lunon logo reveal)
├── VERSION                # Pinned lunon-platform commit SHA / version tag
├── CITATION.cff           # Machine-readable citation metadata
├── LICENSE                # MIT (placeholder)
└── README.md              # This file
```

---

## Methodology

Lunon runs DeepResearch Bench because it is an external, adversarial check on the capability our clients depend on. We optimize for factual accuracy first, then citation density, then synthesis depth. The work that moves our DRB score, stronger source triangulation, tighter citation discipline, and deeper multi-hop synthesis, is the same work that improves client deliverables. That alignment is the reason we maintain this benchmark as a standing part of evaluation rather than a one-time exercise.

---

## About Lunon

Lunon is an AI-native consulting firm. We deliver commercial due diligence, market assessments, strategic options, value creation, technology assessments, and sell-side vendor due diligence for private equity firms and global enterprises. Lunon is backed by General Catalyst and SV Angel. More at [lunon.ai](https://lunon.ai), and we are hiring: `<careers-url-placeholder>`.

---

## Citation

```bibtex
@misc{lunon2026deepresearch,
  title        = {Lunon on DeepResearch Bench},
  author       = {Lunon},
  year         = {2026},
  howpublished = {\url{https://github.com/LunonAI/lunon-deep-research}},
  note         = {Public submission and reproducibility record}
}
```

---

## Acknowledgments

DeepResearch Bench is built and maintained by the USTC team. We thank Du Mingxuan and Li Ruizhe for the benchmark and the independent re-scoring process, the DRB maintainers for keeping the leaderboard rigorous and public, and the broader open evaluation community whose work makes claims like these checkable.

---

## License

Released under the MIT License. See `LICENSE`. License is a placeholder pending final selection (MIT or Apache-2.0).
