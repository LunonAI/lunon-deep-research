#!/bin/bash
# W9 supervisor: stuck-task detection via ledger-event-growth monitor.
# If no new ledger event in 15 min while python is running, kill+relaunch.
# Resumable adapter picks up. Exits when p1_final reaches 95/100 OR after
# 6 hard-restart cycles (gives up).
set -u
cd /home/connor/dev/lunon-deep-research
LEDGER=cost_tracking/ledger.jsonl
OUT=p1_artifacts/p1_final.jsonl
LOG=/tmp/p1_final.out

launch() {
    DR_SECTION_WORKERS=8 DRB_PHASE=P1 PYTHONPATH=/home/connor/dev/lunon-deep-research \
        nohup /usr/bin/python3 -u -m deep_research.adapter \
        --out p1_artifacts/p1_final.jsonl --workers 20 \
        > "$LOG" 2>&1 &
    echo $!
}

is_alive() {
    pgrep -f "p1_final.jsonl --workers 20" >/dev/null 2>&1
}

restart_count=0
PID=$(launch)
echo "[supervisor] launched W9 pid $PID at $(date -u +%H:%M:%S)"
sleep 30  # initial warmup

while true; do
    n=$(wc -l < "$OUT" 2>/dev/null || echo 0)
    if [ "$n" -ge 95 ]; then
        echo "[supervisor] W9 at $n/100 — DONE $(date -u +%H:%M:%S)"
        break
    fi
    if [ "$restart_count" -ge 6 ]; then
        echo "[supervisor] 6 restarts exhausted — STOP. final=$n/100"
        break
    fi
    # check ledger growth over 15 min
    start_ledger=$(wc -l < "$LEDGER")
    start_ts=$(date -u +%H:%M:%S)
    sleep 900  # 15 min
    end_ledger=$(wc -l < "$LEDGER")
    end_ts=$(date -u +%H:%M:%S)
    n_now=$(wc -l < "$OUT" 2>/dev/null || echo 0)
    delta=$((end_ledger - start_ledger))
    if is_alive && [ "$delta" -lt 5 ]; then
        echo "[supervisor] STALL detected $start_ts→$end_ts ledger Δ=$delta tasks=$n_now/100 — kill+restart"
        pkill -9 -f "p1_final.jsonl --workers 4" 2>/dev/null
        sleep 5
        restart_count=$((restart_count + 1))
        PID=$(launch)
        echo "[supervisor] relaunch #$restart_count pid $PID at $(date -u +%H:%M:%S)"
        sleep 30
    elif ! is_alive; then
        # adapter exited (normally or crashed). Check completion.
        if [ "$n_now" -ge 95 ]; then break; fi
        echo "[supervisor] adapter exited without completing (n=$n_now); restarting"
        restart_count=$((restart_count + 1))
        PID=$(launch)
        echo "[supervisor] relaunch #$restart_count pid $PID at $(date -u +%H:%M:%S)"
        sleep 30
    else
        echo "[supervisor] healthy: ledger Δ=$delta in 15min, tasks=$n_now/100, restarts=$restart_count"
    fi
done
echo "[supervisor] EXIT final=$(wc -l < $OUT)/100 restarts=$restart_count"
