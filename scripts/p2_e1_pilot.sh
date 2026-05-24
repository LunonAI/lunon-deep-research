#!/bin/bash
# P2-Wave-2.5-E1 pilot — end-to-end 3-task A/B vs revert baseline.
#
# Flow:
#   1. Generate baseline articles from main (revert state, no E1 directive)
#      → p2_artifacts/e1_baseline.jsonl
#   2. Switch to p2/e1-with-ab-toolchain branch (has E1 rule)
#      → p2_artifacts/e1_experiment.jsonl
#   3. Compliance check (free): does E1's recap pattern actually fire?
#   4. Structural-sim (free): do metrics move toward the reference?
#   5. A/B judge: same-task pairwise comparison per dim
#
# Selection: [56, 91, 23] — 3 reference-folder gate-verify IDs:
#   - 56 (EN explain-mech): math-heavy, framework-recap structure
#     most natural here
#   - 91 (EN list-all): pop-culture taxonomy, recap tests cross-section
#     coherence
#   - 23 (ZH list-all/recommend): short-scope ZH, tests ZH recap templates
#
# Cost: ~$65 (3 × ~$8 baseline + 3 × ~$8 experiment + ~$15 A/B judge).
# Wall-clock: ~35-45 min total.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LUNON_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
DRB_REPO="${DRB_REPO:-/home/connor/dev/deep_research_bench}"
QUERY_FILE="$DRB_REPO/data/prompt_data/query.jsonl"

cd "$LUNON_REPO"

export DRB_PHASE=P1
# G stays on (it's hardcoded post-PR-11). E1 rule rides on top.
export DR_CAPEL_G=on
export DR_EVIDENCE_DEDUP=url+embedding

IDS="56,91,23"
LOG="p2_artifacts/e1_pilot.log"
BASELINE_JSONL="p2_artifacts/e1_baseline.jsonl"
EXPERIMENT_JSONL="p2_artifacts/e1_experiment.jsonl"
mkdir -p p2_artifacts

echo "[e1-pilot] launching at $(date -Iseconds)" | tee "$LOG"
echo "[e1-pilot] selection: $IDS  (3 reference-folder IDs)" | tee -a "$LOG"

# -- Step 1: baseline from main (revert state, no E1) ----------------------
echo "[e1-pilot] === STEP 1: baseline generation (main) ===" | tee -a "$LOG"
git checkout main
/usr/bin/python3 -m deep_research.adapter \
  --query-file "$QUERY_FILE" \
  --out "$BASELINE_JSONL" \
  --ids "$IDS" \
  --workers 3 \
  2>&1 | tee -a "$LOG"

# -- Step 2: experiment from E1 branch -------------------------------------
echo "[e1-pilot] === STEP 2: E1 generation (p2/e1-with-ab-toolchain) ===" | tee -a "$LOG"
git checkout p2/e1-with-ab-toolchain
/usr/bin/python3 -m deep_research.adapter \
  --query-file "$QUERY_FILE" \
  --out "$EXPERIMENT_JSONL" \
  --ids "$IDS" \
  --workers 3 \
  2>&1 | tee -a "$LOG"

# Stay on E1 branch for analysis steps (the scripts/ live here).

# -- Step 3: compliance check ($0) -----------------------------------------
echo "[e1-pilot] === STEP 3: compliance check ===" | tee -a "$LOG"
/usr/bin/python3 scripts/p2_e_compliance.py \
  --experiment e1_section_opening_recap \
  --jsonl "$EXPERIMENT_JSONL" \
  --out p2_artifacts/e1_compliance.json \
  2>&1 | tee -a "$LOG"

# -- Step 4: structural-similarity diff ($0) -------------------------------
echo "[e1-pilot] === STEP 4: structural-similarity (E1 vs the reference) ===" | tee -a "$LOG"
/usr/bin/python3 scripts/p2_structural_sim.py \
  --jsonl "$EXPERIMENT_JSONL" \
  --out p2_artifacts/e1_struct_sim.json \
  2>&1 | tee -a "$LOG"

# -- Step 5: within-task A/B judge -----------------------------------------
echo "[e1-pilot] === STEP 5: within-task A/B judge ===" | tee -a "$LOG"
# Source the harness's env for OpenAI key (judge runs through inner_scorer).
[ -f "$DRB_REPO/env.local.sh" ] && source "$DRB_REPO/env.local.sh"
/usr/bin/python3 scripts/p2_within_task_ab.py \
  --a "$BASELINE_JSONL" \
  --b "$EXPERIMENT_JSONL" \
  --query-file "$QUERY_FILE" \
  --out p2_artifacts/e1_ab.json \
  2>&1 | tee -a "$LOG"

echo "[e1-pilot] complete at $(date -Iseconds)" | tee -a "$LOG"
echo "[e1-pilot] artifacts:"
echo "  $BASELINE_JSONL"
echo "  $EXPERIMENT_JSONL"
echo "  p2_artifacts/e1_compliance.json"
echo "  p2_artifacts/e1_struct_sim.json"
echo "  p2_artifacts/e1_ab.json"
