#!/usr/bin/env bash
# Measure rt-app's calibration result (pLoad, ns per loop) several times and
# report how stable it is, plus how long the calibration itself takes.
#
# The number this prints is what goes into the "calibration" field of the DoE
# configs as an integer, so that rt-app skips calibration entirely and every
# run of the campaign does the same amount of work per loop.
#
# Usage: [RT=1] ./measure_ploop.sh [reps] [calib_cpu] [rt-app binary]
#
# RT=1 runs the probe pinned to calib_cpu at SCHED_FIFO 90 (needs root): that is
# how HI_task runs in the DoE, and it is the only way to get a stable reading on
# a machine that is not otherwise quiet -- calibration is plain SCHED_OTHER code
# in rt-app's main(), so anything else running preempts it and inflates the loop
# it is timing.
set -euo pipefail
export LC_ALL=C   # bc prints "9.18"; printf under it_IT would reject the dot

REPS="${1:-10}"
CALIB_CPU="${2:-2}"
BIN="${3:-$(dirname "$0")/../../rt-app/src/rt-app}"
RT="${RT:-0}"
if [[ "$RT" == "1" ]]; then
    PREFIX=(chrt -f 90 taskset -c "$CALIB_CPU")
    [[ $EUID -eq 0 ]] || echo "warning: RT=1 without root, chrt will fail" >&2
else
    PREFIX=(taskset -c "$CALIB_CPU")
fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cat > "$TMP/cfg.json" <<JSON
{
  "tasks": { "probe": { "policy": "SCHED_OTHER", "loop": -1, "run": 1000, "sleep": 9000 } },
  "global": {
    "duration": 1,
    "default_policy": "SCHED_OTHER",
    "calibration": "CPU${CALIB_CPU}",
    "logdir": "${TMP}",
    "log_basename": "probe"
  }
}
JSON

echo "binary : $BIN"
echo "calib  : CPU${CALIB_CPU}, ${REPS} repetitions, prefix: ${PREFIX[*]}"
echo
printf "%4s %12s %14s\n" "rep" "pLoad [ns]" "calib time [s]"
for i in $(seq 1 "$REPS"); do
    t0=$(date +%s.%N)
    "${PREFIX[@]}" "$BIN" "$TMP/cfg.json" > /dev/null 2> "$TMP/err.$i"
    t1=$(date +%s.%N)
    pload=$(grep -oP 'pLoad = \K[0-9]+' "$TMP/err.$i" || echo "?")
    # total wall time minus the 1 s of workload ~= calibration time
    printf "%4d %12s %14.2f\n" "$i" "$pload" "$(echo "$t1 - $t0 - 1" | bc)"
done | tee "$TMP/results.txt"

echo
gawk 'NR>0 && $2 ~ /^[0-9]+$/ {v[n++]=$2; s+=$2; if(min==""||$2<min)min=$2; if($2>max)max=$2}
     END {
       if (n==0) { print "no samples"; exit }
       asort(v);
       printf "pLoad: n=%d  min=%d  median=%d  max=%d  mean=%.1f  spread=%.1f%%\n",
              n, min, v[int((n+1)/2)], max, s/n, 100.0*(max-min)/min;
       printf "\nSuggested config field:  \"calibration\": %d\n", min;
       print   "(rt-app itself keeps the MINIMUM of its two calibration methods,";
       print   " i.e. the highest achievable compute capacity: see calibrate_cpu_cycles())";
     }' "$TMP/results.txt"
