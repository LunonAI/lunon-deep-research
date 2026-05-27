#!/bin/bash
# P3-Bundle dev4 wiring verification.
#
# Generates 4 articles against the post-W#.b main (#44/#45/#46/#47 merged),
# stages them under the DRB harness raw_data dir, and grades them with the
# GPT-5.5 RACE judge. Purpose: empirically verify that the four wiring PRs
# produce the intended structures end-to-end (architect → writer → post-pass).
#
# Selection: 8 (ZH ML/materials predict-ish), 14 (ZH q14 deep-dive predict —
# strongest W7.b + W6.b anchor), 37 (ZH jazz piano broad), 91 (EN Saint Seiya
# compare-contest — W7.b anchor). Coverage: predict + compare + broad +
# ZH/EN mix. W6.b stakeholder fires confidently only on id=14; if it doesn't
# fire on any of the 4, follow up with a targeted plural-audience prompt.
#
# Pass criteria (all 6 must hold to declare bundle empirically green):
#   1. W3.b active — orchestrate telemetry shows non-zero xref_repair phase
#      invocation count for every article.
#   2. W5.b firing — articles contain a limitations chapter with all 5
#      sub-sections; _validate_limitations_chapter returns ok=True.
#   3. W6.b firing — ≥1 article contains stakeholder sub-sections;
#      _validate_stakeholder_overlap returns max_pair_overlap < 0.20.
#   4. W7.b firing — id=14 and id=91 articles contain a tier-ranking
#      scoring table with 2-decimal precision AND a sensitivity sub-section.
#   5. No regression on Lunon strengths: footnote def coverage ≥99%, 0 bare
#      URLs, opening-template rate stays at 0%, mermaid blocks valid.
#   6. Composite: ΔO ≥ +0.020 over pre-bundle baseline on the dev4 set.
#
# Cost: ~$80 (4 tasks × ~$20 ea., no CAPEL overhead).
# Wall-clock: ~45-75 min at workers=4 (generation) + ~15-25 min (RACE eval).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LUNON_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
# Honor an explicit DRB_REPO if exported; otherwise default to the Mac
# clone path. The portable harness_bridge.py (post commit 5c60a22) reads
# the same env var, so generation and grading agree on the path.
DRB_REPO="${DRB_REPO:-$HOME/dev/deep_research_bench}"
export DRB_REPO

cd "$LUNON_REPO"

# Phase tag for cost/ledger attribution.
export DRB_PHASE=P3

RUN_TAG="lunon-p3b-2026-05-27-dev4-wiring"
OUT_JSONL="p3b_artifacts/dev4_wiring.jsonl"
LOG="p3b_artifacts/dev4_wiring.log"
SELECTION_JSON="p3b_artifacts/dev4_wiring_selection.json"

mkdir -p p3b_artifacts

# Record selection metadata for the analyzer.
cat > "$SELECTION_JSON" <<EOF
{"selection": "P3-bundle dev4 wiring verification",
 "all": [8, 14, 37, 91],
 "en": [91],
 "zh": [8, 14, 37],
 "archetype_anchors": {"predict": 14, "compare_contest": 91, "broad": 37, "predict_ish": 8},
 "wiring_anchors": {
   "w3b_xref_repair": "all 4 (fires on every article)",
   "w5b_limitations": "all 4 (every article has limitations chapter)",
   "w6b_stakeholder": "14 (q14 deep-dive — 7 stakeholders in Qianfan); fallback if no fire",
   "w7b_tier_ranking": "14 + 91 (predict + compare-contest archetypes)"
 },
 "rationale": "Empirical verification of #44/#45/#46/#47 wiring against main. Single graded dev4 before any caching PR or full-100 W13."}
EOF

echo "[dev4-wiring] launching at $(date -Iseconds)" | tee "$LOG"
echo "[dev4-wiring] LUNON_REPO=$LUNON_REPO" | tee -a "$LOG"
echo "[dev4-wiring] DRB_REPO=$DRB_REPO" | tee -a "$LOG"
echo "[dev4-wiring] DRB_PHASE=$DRB_PHASE" | tee -a "$LOG"
echo "[dev4-wiring] ids=8,14,37,91 workers=4" | tee -a "$LOG"

# Generation. Lunon clients auto-load .env via deep_research._env.get(),
# so no shell export needed for ANTHROPIC_API_KEY here.
python3 -m deep_research.adapter \
  --query-file "$DRB_REPO/data/prompt_data/query.jsonl" \
  --out "$OUT_JSONL" \
  --ids 8,14,37,91 \
  --workers 4 \
  2>&1 | tee -a "$LOG"

echo "[dev4-wiring] adapter done at $(date -Iseconds)" | tee -a "$LOG"

# Stage for harness scoring under the run-tag dir name.
HARNESS_RAW="$DRB_REPO/data/test_data/raw_data/${RUN_TAG}.jsonl"
cp "$OUT_JSONL" "$HARNESS_RAW"
echo "[dev4-wiring] staged → $HARNESS_RAW" | tee -a "$LOG"

# Hand off to DRB RACE eval (GPT-5.5 judge). DRB uses raw os.environ.get()
# with NO dotenv loader, so the OpenAI key must be in the process env. Source
# Lunon's .env with auto-export so the python3 child below inherits it.
EVAL_LOG="p3b_artifacts/dev4_wiring_eval.log"
set -a
# shellcheck disable=SC1091
source "$LUNON_REPO/.env"
set +a

cd "$DRB_REPO"
echo "[dev4-wiring] starting RACE eval at $(date -Iseconds)" | tee "$LUNON_REPO/$EVAL_LOG"
python -u deepresearch_bench_race.py "$RUN_TAG" \
  --raw_data_dir data/test_data/raw_data \
  --max_workers 4 \
  --query_file data/prompt_data/query.jsonl \
  --output_dir "results/race/${RUN_TAG}" \
  2>&1 | tee -a "$LUNON_REPO/$EVAL_LOG"
echo "[dev4-wiring] RACE eval done at $(date -Iseconds)" | tee -a "$LUNON_REPO/$EVAL_LOG"

cd "$LUNON_REPO"
echo "[dev4-wiring] complete. inspect drift telemetry + scores:"
echo "  cat p3b_artifacts/dev4_wiring.log | grep xref_repair"
echo "  cat $DRB_REPO/results/race/${RUN_TAG}/*.json"
