#!/bin/bash
# P2-Wave-2 sanity-4 launch.
#
# Generates 4 articles with DR_CAPEL_G=on (A+G atomic), then scores them
# against the GPT-5.5 RACE harness for paired-Δ vs B0 + D-sanity on the
# same IDs.
#
# Selection: identical to W1-D sanity ([83, 91, 23, 29]) so paired
# analysis vs `lunon-p2-2026-05-23-w1d-sanity4` is clean apples-to-apples.
# G's auto-fire won't be observable on this set (id=56 not included) —
# G's logic is unit-tested separately; this run measures A's CAPEL effect.
#
# Pass criteria (sanity, NOT statistical):
#   - 0 marker leaks (no `<\d+>` in any article on inspection)
#   - capel_stats present in drift log for every task
#   - paired ΔO vs B0 NOT catastrophically negative (≥ -0.020 on every task)
#   - no task regresses ≥ -0.040 raw on any single dim
#
# Cost: ~$45-55 (4 tasks × ~$10-14 with CAPEL overhead).
# Wall-clock: ~30-45 min at workers=4.

set -euo pipefail

cd /home/connor/dev/lunon-deep-research

export DRB_PHASE=P1
export DR_CAPEL_G=on
# D is already hardcoded post-PR-8; this is just belt-and-suspenders.
export DR_EVIDENCE_DEDUP=url+embedding

RUN_TAG="lunon-p2-2026-05-23-w2-sanity4"
OUT_JSONL="p2_artifacts/w2_sanity4.jsonl"
LOG="p2_artifacts/w2_sanity4.log"
SELECTION_JSON="p2_artifacts/w2_sanity4_selection.json"

# Record selection metadata for the analyzer.
cat > "$SELECTION_JSON" <<EOF
{"selection": "W2 sanity-4: same IDs as W1-D sanity for paired comparison",
 "all": [83, 91, 23, 29],
 "en": [83, 91],
 "zh": [23, 29],
 "gate_verify": [91, 23],
 "rationale": "Paired vs B0 + W1-D sanity. G's id=56 NOT included here — G validated via unit tests; A is what we're measuring."}
EOF

echo "[w2-sanity4] launching at $(date -Iseconds)" | tee "$LOG"
echo "[w2-sanity4] DR_CAPEL_G=$DR_CAPEL_G" | tee -a "$LOG"
echo "[w2-sanity4] DR_EVIDENCE_DEDUP=$DR_EVIDENCE_DEDUP" | tee -a "$LOG"
echo "[w2-sanity4] ids=83,91,23,29 workers=4" | tee -a "$LOG"

/usr/bin/python3 -m deep_research.adapter \
  --query-file /home/connor/dev/deep_research_bench/data/prompt_data/query.jsonl \
  --out "$OUT_JSONL" \
  --ids 83,91,23,29 \
  --workers 4 \
  2>&1 | tee -a "$LOG"

echo "[w2-sanity4] adapter done at $(date -Iseconds)" | tee -a "$LOG"

# Stage for harness scoring under the run-tag dir name.
HARNESS_RAW="/home/connor/dev/deep_research_bench/data/test_data/raw_data/${RUN_TAG}.jsonl"
cp "$OUT_JSONL" "$HARNESS_RAW"
echo "[w2-sanity4] staged → $HARNESS_RAW" | tee -a "$LOG"

# Hand off to harness RACE eval (GPT-5.5 judge).
EVAL_LOG="p2_artifacts/w2_sanity4_eval.log"
cd /home/connor/dev/deep_research_bench
echo "[w2-sanity4] starting RACE eval at $(date -Iseconds)" | tee "../lunon-deep-research/$EVAL_LOG"
python -u deepresearch_bench_race.py "$RUN_TAG" \
  --raw_data_dir data/test_data/raw_data \
  --max_workers 4 \
  --query_file data/prompt_data/query.jsonl \
  --output_dir "results/race/${RUN_TAG}" \
  2>&1 | tee -a "../lunon-deep-research/$EVAL_LOG"
echo "[w2-sanity4] RACE eval done at $(date -Iseconds)" | tee -a "../lunon-deep-research/$EVAL_LOG"

cd /home/connor/dev/lunon-deep-research
echo "[w2-sanity4] complete. analyze with:"
echo "  python3 scripts/p2_analyze_b0.py ${RUN_TAG}"
