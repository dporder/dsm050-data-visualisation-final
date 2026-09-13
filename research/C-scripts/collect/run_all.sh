#!/bin/bash
# Orchestrator for the Session 2 collection run.
#
# Stages that touch different services run at the same time. Stages that share a
# rate-limit bucket do not. GitHub search (stages 1 and 2) is one bucket, GitHub
# core (stage 3) another, and stages 4 and 5 touch app hosts and web.archive.org
# and so are free to run alongside. Every stage is resumable, so re-running this
# script only does what is missing.
set -u
cd /Users/testdan/Projects/masters_degree_2026/data_visualisation_course/final
PY=.venv/bin/python
OUT=${OUT:-/tmp/collect}
mkdir -p "$OUT"

wait_for () { while pgrep -f "$1" >/dev/null; do sleep 10; done; }

echo "== waiting for stage 1 (search bucket) =="
wait_for "stage1_lovable.py"

echo "== stage 2: contrast strata (search + code + core) =="
$PY research/C-scripts/collect/stage2_strata.py > "$OUT/stage2.out" 2>&1 &
S2=$!

echo "== stage 4 pass 1: liveness on the Lovable spine (app hosts) =="
$PY research/C-scripts/collect/stage4_liveness.py > "$OUT/stage4a.out" 2>&1 &
S4=$!

echo "== stage 5 pass 2: per-host Wayback lookups (web.archive.org) =="
wait_for "stage5_wayback.py"
$PY research/C-scripts/collect/stage5_wayback.py > "$OUT/stage5b.out" 2>&1 &
S5=$!

wait $S2
echo "== stage 2 done; stage 3: owner metadata (core bucket) =="
$PY research/C-scripts/collect/stage3_owners.py > "$OUT/stage3.out" 2>&1 &
S3=$!

wait $S4
echo "== stage 4 pass 2: liveness including the contrast strata =="
$PY research/C-scripts/collect/stage4_liveness.py > "$OUT/stage4b.out" 2>&1 &
S4=$!

wait $S3 $S4 $S5
echo "== stage 5 pass 3: pick up contrast-stratum hosts =="
$PY research/C-scripts/collect/stage5_wayback.py > "$OUT/stage5c.out" 2>&1

echo "== stage 6: assemble the corpus =="
$PY research/C-scripts/collect/stage6_assemble.py > "$OUT/stage6.out" 2>&1
echo "== ALL STAGES DONE =="
tail -5 "$OUT/stage6.out"
