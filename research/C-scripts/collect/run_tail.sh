#!/bin/bash
# Stages 2 to 6, chained by rate-limit bucket rather than by stage number.
#
#   GitHub search  : stage 1, stage 1b, stage 2   (30/min, one process at a time)
#   GitHub core    : stage 2 fills, stage 3       (5,000/hour)
#   app hosts      : stage 4                      (1 s per host, parallel across hosts)
#   web.archive.org: stage 5                      (1 s, single thread)
#
# Stages in different buckets run at the same time. Stages in the same bucket do
# not, because two processes pacing themselves at the documented limit would
# together exceed it and trip GitHub's secondary rate limiter.
#
# Every stage is resumable, so re-running this script only does what is missing.
set -u
cd /Users/testdan/Projects/masters_degree_2026/data_visualisation_course/final
PY=.venv/bin/python
OUT=${OUT:-/tmp/collect}
mkdir -p "$OUT"
wait_for () { while pgrep -f "$1" >/dev/null; do sleep 10; done; }

echo "[$(date -u +%H:%M:%S)] waiting for stage 1 pass 1"
wait_for "stage1_lovable.py"

echo "[$(date -u +%H:%M:%S)] stage 2: contrast strata"
$PY research/C-scripts/collect/stage2_strata.py > "$OUT/stage2.out" 2>&1

echo "[$(date -u +%H:%M:%S)] stage 1b (two more day-windows a month) + stage 3 (owners)"
LOVABLE_DAYS=10,24,3,17 $PY research/C-scripts/collect/stage1_lovable.py > "$OUT/stage1b.out" 2>&1 &
S1B=$!
$PY research/C-scripts/collect/stage3_owners.py > "$OUT/stage3.out" 2>&1 &
S3=$!

wait $S1B
echo "[$(date -u +%H:%M:%S)] stage 4 (liveness) + stage 5 (wayback per host)"
$PY research/C-scripts/collect/stage4_liveness.py > "$OUT/stage4.out" 2>&1 &
S4=$!
$PY research/C-scripts/collect/stage5_wayback.py > "$OUT/stage5b.out" 2>&1 &
S5=$!

wait $S3 $S4 $S5
echo "[$(date -u +%H:%M:%S)] stage 6: assemble"
$PY research/C-scripts/collect/stage6_assemble.py > "$OUT/stage6.out" 2>&1
echo "[$(date -u +%H:%M:%S)] ALL STAGES DONE"
tail -4 "$OUT/stage6.out"
