#!/bin/bash
# P2-Wave-2.5 dev8 — combined-effect validation of the 5 merged D-PRs.
#
# Selection: 8 of the 10 Qianfan-folder IDs so we have a direct head-to-head
# against the #1 leaderboard articles + W9 paired comparison on every ID.
#   ids = [8, 14, 20, 23, 38, 56, 89, 91]
#   - 5 gate-verify: 8, 20, 23, 56, 91
#   - 3 bonus: 14 (math/quantum ZH), 38 (jewelry trends ZH), 89 (game design EN)
#   - 5 ZH + 3 EN (matches DRB's ~50/50 with slight ZH lean)
#
# Wave 2.5 features under test (all live on main):
#   D1 — length_target archetype × depth_tier matrix; confident-expert voice;
#        forbidden meta-commentary phrases
#   D2 — pre_fix_deep_numeric telemetry; architect TOC 8→14 sections
#   D3 — `[n]` footnotes encouraged; LaTeX math-preservation
#   D4 — priority indicators + ranked tables + action lists (conditional)
#   D0 — profiler ZH char-count fix (no engine impact)
#
# Pass criteria (per tiered-gate agreement):
#   ΔO ≥ +0.020 vs B0/W9            → clear pass → keep
#   ΔO ∈ (-0.020, +0.020)            → marginal  → escalate to dev10/full
#   ΔO ≤ -0.020 OR gate-verify ≥-0.040 regression → fail → diagnostic
#
# Cost: ~$150-250 (per-task output ~2× larger than W2-sanity-4 due to
# Wave-2.5 length governor). Wall-clock: ~45-90 min at workers=4.
#
# Pre-flight (checked 2026-05-23):
#   - WRITER_CALL_TOKEN_CAP=16000 + dynamic max_tokens scaling with target.
#   - refiner.py max_tokens=32000 (handles long articles end-to-end).
#   - anthropic_client.py up to 32000 with thinking-aware adjust.
#   - list-URL bug fixed (PR #10 merged); evidence_dedup fail-soft.
#   - All wave-2.5 conditional rules archetype/domain-gated with fallbacks.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LUNON_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
DRB_REPO="${DRB_REPO:-/home/connor/dev/deep_research_bench}"

cd "$LUNON_REPO"

export DRB_PHASE=P1
export DR_CAPEL_G=on
# D evidence-dedup hardcoded post-PR-8; explicit here as belt+suspenders.
export DR_EVIDENCE_DEDUP=url+embedding

RUN_TAG="lunon-p2-2026-05-23-w25-dev8"
OUT_JSONL="p2_artifacts/w25_dev8.jsonl"
LOG="p2_artifacts/w25_dev8.log"
SELECTION_JSON="p2_artifacts/w25_dev8_selection.json"

mkdir -p p2_artifacts

cat > "$SELECTION_JSON" <<EOF
{
  "selection": "W2.5 dev8: 8 of 10 Qianfan-folder IDs for paired comparison",
  "all": [8, 14, 20, 23, 38, 56, 89, 91],
  "en": [56, 89, 91],
  "zh": [8, 14, 20, 23, 38],
  "gate_verify": [8, 20, 23, 56, 91],
  "bonus_high_scoring": [14, 38, 89],
  "rationale": "Every Qianfan article we have ground-truth for; spans archetypes + domains; matches DRB ZH/EN balance."
}
EOF

echo "[w25-dev8] launching at $(date -Iseconds)" | tee "$LOG"
echo "[w25-dev8] DR_CAPEL_G=$DR_CAPEL_G" | tee -a "$LOG"
echo "[w25-dev8] DR_EVIDENCE_DEDUP=$DR_EVIDENCE_DEDUP" | tee -a "$LOG"
echo "[w25-dev8] ids=8,14,20,23,38,56,89,91 workers=4" | tee -a "$LOG"

/usr/bin/python3 -m deep_research.adapter \
  --query-file "$DRB_REPO/data/prompt_data/query.jsonl" \
  --out "$OUT_JSONL" \
  --ids 8,14,20,23,38,56,89,91 \
  --workers 4 \
  2>&1 | tee -a "$LOG"

echo "[w25-dev8] adapter done at $(date -Iseconds)" | tee -a "$LOG"

HARNESS_RAW="$DRB_REPO/data/test_data/raw_data/${RUN_TAG}.jsonl"
cp "$OUT_JSONL" "$HARNESS_RAW"
echo "[w25-dev8] staged → $HARNESS_RAW" | tee -a "$LOG"

EVAL_LOG="p2_artifacts/w25_dev8_eval.log"
cd "$DRB_REPO"
# shellcheck source=/dev/null
[ -f "env.local.sh" ] && source env.local.sh
echo "[w25-dev8] starting RACE eval at $(date -Iseconds)" | tee "$LUNON_REPO/$EVAL_LOG"
/usr/bin/python3 -u deepresearch_bench_race.py "$RUN_TAG" \
  --raw_data_dir data/test_data/raw_data \
  --max_workers 4 \
  --query_file data/prompt_data/query.jsonl \
  --output_dir "results/race/${RUN_TAG}" \
  2>&1 | tee -a "$LUNON_REPO/$EVAL_LOG"
echo "[w25-dev8] RACE eval done at $(date -Iseconds)" | tee -a "$LUNON_REPO/$EVAL_LOG"

cd "$LUNON_REPO"
echo "[w25-dev8] complete. analyze with:"
echo "  python3 scripts/p2_analyze_b0.py ${RUN_TAG}"
