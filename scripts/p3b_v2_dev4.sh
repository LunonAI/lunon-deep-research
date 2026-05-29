#!/bin/bash
# P3b-v2 bundle dev4 — concurrent-safe runner.
#
# Validates the p3b-v2 bundle (G2/G12 xref excision, G11-A list-all de-scaffold,
# G3 tier-ranking commitment gate, G5 axis-label pin, G7 CJK de-spacing, G8
# mermaid recalibration) on the 4-archetype dev4 set (id 8/14/37/91).
#
# Two design goals from the operator:
#   1. RUN MULTIPLE AT ONCE WITHOUT MESSING UP. Every output path is keyed by
#      $RUN_TAG, so N concurrent invocations (different tags) never collide on
#      the generation jsonl, the staged harness raw_data file, the RACE output
#      dir, or the logs. The only shared resource left is the API itself —
#      handled by (2).
#   2. NO SILENT SPECIALIST DROPS UNDER CONCURRENCY. Exports
#      DR_SPECIALIST_TIMEOUT_S (PR #61) so that when several articles' (or
#      several runs') specialists hit the shared API at once, a slow-but-fine
#      pass is NOT killed at the old 240s cap and silently dropped — which
#      confounded the 2026-05-28 run (14 drops). Default 600s.
#
# One generation, BOTH judges: after generating once, it grades with the
# gpt-5.5 internal gate AND (if GEMINI_RACE_MODEL is set) the leaderboard-
# comparable gemini judge, against distinct output dirs. Re-using one
# generation for both judges is the cheap, correct "run multiple at once".
#
# Usage:
#   scripts/p3b_v2_dev4.sh                       # default tag, gpt-5.5 only
#   RUN_TAG=lunon-p3b-v2-a scripts/p3b_v2_dev4.sh &   # one of N concurrent runs
#   GEMINI_RACE_MODEL=gemini/gemini-2.5-pro scripts/p3b_v2_dev4.sh   # both judges
#
# Env overrides:
#   RUN_TAG   (default: lunon-p3b-v2-<UTC-stamp>)   IDS      (default: 8,14,37,91)
#   WORKERS   (default: 4)                          PY       (default: repo .venv)
#   DRB_REPO  (default: ~/dev/deep_research_bench)  RACE_MODEL (gpt-5.5 internal gate)
#   GEMINI_RACE_MODEL (unset → skip the gemini eval; set to your leaderboard judge id)
#   DR_SPECIALIST_TIMEOUT_S (default: 600)
#
# Cost: ~$80-120 (4 tasks). Wall-clock: ~45-90 min gen + ~15-25 min per eval.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LUNON_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$LUNON_REPO"

DRB_REPO="${DRB_REPO:-$HOME/dev/deep_research_bench}"
if [ ! -d "$DRB_REPO" ]; then
    echo "[p3b-v2-dev4] ERROR: DRB_REPO not found: $DRB_REPO (export DRB_REPO=... to override)" >&2
    exit 1
fi
export DRB_REPO
export DRB_PHASE="${DRB_PHASE:-P3}"
# PR #61: keep specialists from being dropped under concurrent API load.
export DR_SPECIALIST_TIMEOUT_S="${DR_SPECIALIST_TIMEOUT_S:-600}"

IDS="${IDS:-8,14,37,91}"
WORKERS="${WORKERS:-4}"
# A collision-proof default tag: the UTC stamp is only second-precision, so two
# invocations in the same second would share a tag and clobber each other's
# outputs — appending $$ (the shell PID) makes the default unique per process.
# Operator can override RUN_TAG to launch named parallel variants.
RUN_TAG="${RUN_TAG:-lunon-p3b-v2-$(date -u +%Y%m%dT%H%M%SZ)-$$}"

PY="${PY:-$LUNON_REPO/.venv/bin/python}"
if [ ! -x "$PY" ]; then
    echo "[p3b-v2-dev4] ERROR: python not executable: $PY (export PY=... to override)" >&2
    exit 1
fi

# Keys: source .env upfront so a missing key fails BEFORE the costly gen step.
if [ ! -f "$LUNON_REPO/.env" ]; then
    echo "[p3b-v2-dev4] ERROR: $LUNON_REPO/.env not found (need ANTHROPIC_API_KEY + OPENAI_API_KEY)." >&2
    exit 1
fi
set -a
# shellcheck disable=SC1091
source "$LUNON_REPO/.env"
set +a
for var in OPENAI_API_KEY ANTHROPIC_API_KEY; do
    if [ -z "${!var:-}" ]; then
        echo "[p3b-v2-dev4] ERROR: $var empty after sourcing .env." >&2
        exit 1
    fi
done

# All paths keyed by RUN_TAG → concurrent-safe.
OUT_JSONL="p3b_artifacts/${RUN_TAG}.jsonl"
GEN_LOG="p3b_artifacts/${RUN_TAG}.gen.log"
mkdir -p p3b_artifacts

echo "[p3b-v2-dev4] tag=$RUN_TAG ids=$IDS workers=$WORKERS timeout=${DR_SPECIALIST_TIMEOUT_S}s" | tee "$GEN_LOG"
echo "[p3b-v2-dev4] commit=$(git rev-parse --short HEAD) branch=$(git branch --show-current)" | tee -a "$GEN_LOG"
echo "[p3b-v2-dev4] gen start $(date -Iseconds)" | tee -a "$GEN_LOG"

"$PY" -m deep_research.adapter \
  --query-file "$DRB_REPO/data/prompt_data/query.jsonl" \
  --out "$OUT_JSONL" \
  --ids "$IDS" \
  --workers "$WORKERS" \
  2>&1 | tee -a "$GEN_LOG"

echo "[p3b-v2-dev4] gen done $(date -Iseconds)" | tee -a "$GEN_LOG"

# Stage once under the run tag; both judges read this same file (read-only).
HARNESS_RAW="$DRB_REPO/data/test_data/raw_data/${RUN_TAG}.jsonl"
cp "$OUT_JSONL" "$HARNESS_RAW"
echo "[p3b-v2-dev4] staged → $HARNESS_RAW" | tee -a "$GEN_LOG"

# --- eval helper: grade with a given RACE_MODEL into a tag-suffixed dir ------
_run_eval() {
    local suffix="$1" model="$2"
    local tag="${RUN_TAG}${suffix}"
    local eval_log="$LUNON_REPO/p3b_artifacts/${tag}.eval.log"
    # The harness reads raw_data_dir/<tag>.jsonl; symlink/copy the staged file
    # to the suffixed tag so the gemini eval finds its input too.
    if [ "$suffix" != "" ]; then
        cp "$HARNESS_RAW" "$DRB_REPO/data/test_data/raw_data/${tag}.jsonl"
    fi
    echo "[p3b-v2-dev4] eval[$model] start $(date -Iseconds) → results/race/${tag}" | tee "$eval_log"
    ( cd "$DRB_REPO" && RACE_MODEL="$model" "$PY" -u deepresearch_bench_race.py "$tag" \
        --raw_data_dir data/test_data/raw_data \
        --max_workers "$WORKERS" \
        --query_file data/prompt_data/query.jsonl \
        --output_dir "results/race/${tag}" ) 2>&1 | tee -a "$eval_log"
    echo "[p3b-v2-dev4] eval[$model] done $(date -Iseconds)" | tee -a "$eval_log"
}

# Internal gate (gpt-5.5) — always.
_run_eval "" "${RACE_MODEL:-openai/gpt-5.5}"
# Leaderboard-comparable gemini judge — only if the operator set the model id.
if [ -n "${GEMINI_RACE_MODEL:-}" ]; then
    _run_eval "-gemini" "$GEMINI_RACE_MODEL"
else
    echo "[p3b-v2-dev4] GEMINI_RACE_MODEL unset → skipped the leaderboard (gemini) eval." | tee -a "$GEN_LOG"
fi

# Greptile PR #68 round-2: brace expansion `{,-gemini}` is suppressed inside
# double quotes, so spell both result paths out explicitly.
echo "[p3b-v2-dev4] ALL DONE $(date -Iseconds). Scores: results/race/${RUN_TAG}/race_result.txt" \
    "(gemini: results/race/${RUN_TAG}-gemini/race_result.txt if run)" | tee -a "$GEN_LOG"
