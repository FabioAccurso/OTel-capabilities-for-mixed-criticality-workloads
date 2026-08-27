#!/usr/bin/env bash
# Find the ns-per-loop value to hardcode in the DoE configs, by closed loop on
# what rt-app actually executes instead of trusting its own calibration.
#
# Why not use rt-app's calibration: calibrate_cpu_cycles_1() (rt-app.cpp:451)
# grows an exponential moving average from 0 and stops when the last sample is
# within 2% of it, so it needs >= 6 iterations to converge by construction --
# each preceded by a 1 s clock_nanosleep. It therefore costs 6-20 s per run and
# still returns a noisy value.
#
# How this works instead: rt-app turns a run phase into
#     load_count = run_us * 1000 / p_load          (rt-app.cpp:580)
# loops of waste_cpu_cycles(). So if we run with a KNOWN p_load and observe the
# resulting phase duration in the log, the true cost per loop is simply
#     p_load_true = p_load_used * run_measured / run_configured
# One run gives the answer; the script then verifies it with a second run,
# which should land on run_measured ~= run_configured.
#
# Usage: [RT=1] ./tune_calib.sh [cpu] [seconds] [rt-app binary]
set -euo pipefail
export LC_ALL=C

CPU="${1:-2}"
DUR="${2:-10}"
BIN="${3:-$(dirname "$0")/../../rt-app/src/rt-app}"
RUN_US=2000
SEED=100          # arbitrary starting p_load; the maths does not depend on it
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if [[ "${RT:-0}" == "1" ]]; then
    PREFIX=(chrt -f 90 taskset -c "$CPU")
else
    PREFIX=(taskset -c "$CPU")
fi

probe() {   # $1 = p_load to configure -> prints the median measured run [us]
    local pload="$1" dir="$TMP/p$1"
    mkdir -p "$dir"
    cat > "$dir/cfg.json" <<JSON
{
  "tasks": { "probe": { "policy": "SCHED_OTHER", "cpus": [${CPU}],
                        "loop": -1, "run": ${RUN_US}, "sleep": 8000 } },
  "global": { "duration": ${DUR}, "default_policy": "SCHED_OTHER",
              "calibration": ${pload}, "logdir": "${dir}", "log_basename": "probe" }
}
JSON
    "${PREFIX[@]}" "$BIN" "$dir/cfg.json" > "$dir/out" 2> "$dir/err"
    # column 3 is the measured run duration in us; drop the '#' header
    gawk '!/^#/ && NF>3 {v[n++]=$3} END {asort(v); print v[int((n+1)/2)]}' "$dir"/probe-probe-0.log
}

echo "binary   : $BIN"
echo "cpu      : $CPU   prefix: ${PREFIX[*]}   duration: ${DUR}s   run: ${RUN_US}us"
echo

m1=$(probe "$SEED")
true_pload=$(gawk -v s="$SEED" -v m="$m1" -v r="$RUN_US" 'BEGIN{printf "%d", (s*m/r)+0.5}')
echo "step 1: p_load=${SEED} -> median run = ${m1} us   (configured ${RUN_US})"
echo "        => true cost per loop = ${SEED} * ${m1} / ${RUN_US} = ${true_pload} ns"
echo

m2=$(probe "$true_pload")
err=$(gawk -v m="$m2" -v r="$RUN_US" 'BEGIN{printf "%+.1f", 100.0*(m-r)/r}')
echo "step 2: p_load=${true_pload} -> median run = ${m2} us   (error ${err}%)"
echo
echo "Use this in the DoE configs:   --calib ${true_pload}"
