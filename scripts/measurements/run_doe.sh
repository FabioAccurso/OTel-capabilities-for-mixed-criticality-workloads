#!/usr/bin/env bash
# Orchestrates the full DoE: rebuilds rt-app with the right OTel macros for
# each "cell", generates the JSON workload, and repeats the run REPS times.
#
# Usage: ./run_doe.sh <block1|block2|block3|all>
#
# Resolved from this script's own location (scripts/measurements/ -> project root), so a
# clone anywhere works without editing. Each is still overridable from the environment.
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RTAPP_SRC_DIR="${RTAPP_SRC_DIR:-$PROJECT_ROOT/rt-app/src}"
BIN_CACHE="${BIN_CACHE:-$PROJECT_ROOT/bin}"
DOE_ROOT="${DOE_ROOT:-$PROJECT_ROOT/2-DoE}"

# ns per loop, hardcoded into every generated config so that rt-app skips its own
# calibration (6-20 s per run, and a different value each time -> "run": 2000 would
# mean a different amount of work in every cell of the DoE).
# Valid only with the CPU frequency pinned. Re-measure with
#   scripts/utils_freq/tune_calib.sh
# after changing machine or pinned ratio, and re-pin after every reboot with
#   pkexec /usr/bin/python3 scripts/utils_freq/cpu_freq.py pin
CALIB_NS="${CALIB_NS:-139}"

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GEN="$HERE/gen_config.py"
TEST="$HERE/test.sh"
DATA_TABLE="$DOE_ROOT/data_table.csv"
INDEX_FILE="$DOE_ROOT/index.txt"

# Refuse to run with the frequency unpinned: CALIB_NS was measured at a fixed
# frequency, so with turbo back on rt-app would silently execute ~30% less work
# per phase than the config asks for. Only checkable as root (no cpufreq sysfs on
# this kernel); skipped otherwise with a warning.
check_freq_pinned() {
    if [[ ! -r /dev/cpu/0/msr ]]; then
        echo "warning: cannot read /dev/cpu/0/msr, not verifying the frequency pin." >&2
        echo "         Make sure you ran: pkexec /usr/bin/python3 $HERE/../utils_freq/cpu_freq.py pin" >&2
        return 0
    fi
    local turbo_off
    turbo_off=$(python3 -c "
import struct
f=open('/dev/cpu/0/msr','rb'); f.seek(0x1A0)
print((struct.unpack('<Q', f.read(8))[0] >> 38) & 1)")
    if [[ "$turbo_off" != "1" ]]; then
        echo "ERROR: CPU frequency is NOT pinned (turbo still enabled), but CALIB_NS=$CALIB_NS" >&2
        echo "       was measured with it pinned. Run:" >&2
        echo "         pkexec /usr/bin/python3 $HERE/../utils_freq/cpu_freq.py pin" >&2
        exit 1
    fi
}
check_freq_pinned

mkdir -p "$BIN_CACHE" "$DOE_ROOT"
[ -f "$DATA_TABLE" ] || echo "run_id,block,trace_level,processor_type,sampler_type,sampler_ratio,n_lo,rep,run_dir" > "$DATA_TABLE"
touch "$INDEX_FILE"
RUN_COUNTER=$(( $(wc -l < "$INDEX_FILE") + 1 ))

# --- build (or reuse cached) binary for a given macro combination ---------
# exporter: 0 = Zipkin (spans go to the network, stdout stays empty), 1 = ostream
# (spans printed on stdout, which is how block 2 counts them). It is part of the cache
# tag: two binaries differing only by exporter are different binaries.
build_bin() {
    local trace=$1 proc=$2 samp=$3 ratio=$4 exporter=${5:-0}
    local tag="t${trace}_p${proc}_s${samp}_r${ratio}_e${exporter}"
    local bin_path="$BIN_CACHE/rtapp_${tag}"
    if [ -x "$bin_path" ]; then
        echo "$bin_path"
        return
    fi
    echo "[build] $tag" >&2
    (
        cd "$RTAPP_SRC_DIR"
        make clean >/dev/null
        make CPPFLAGS="-DRTAPP_TRACE_LEVEL=${trace} -DRTAPP_PROCESSOR_TYPE=${proc} -DRTAPP_SAMPLER_TYPE=${samp} -DRTAPP_SAMPLER_RATIO=${ratio} -DRTAPP_EXPORTER_TYPE=${exporter}" >/dev/null
    ) >&2
    cp "$RTAPP_SRC_DIR/rt-app" "$bin_path"
    echo "$bin_path"
}

# --- run one cell: build once, execute REPS repetitions --------------------
run_cell() {
    local block=$1 trace=$2 proc=$3 samp=$4 ratio=$5 n_lo=$6 reps=$7 duration=$8
    local exporter=${9:-0}
    local bin; bin=$(build_bin "$trace" "$proc" "$samp" "$ratio" "$exporter")
    local cell_dir="$DOE_ROOT/$block/t${trace}_p${proc}_s${samp}_r${ratio}_n${n_lo}"
    mkdir -p "$cell_dir"
    local cfg="$cell_dir/config.json"
    python3 "$GEN" --n-lo "$n_lo" --duration "$duration" --calib "$CALIB_NS" --out "$cfg"

    for rep in $(seq 1 "$reps"); do
        local run_dir="$cell_dir/run_$(printf '%02d' "$rep")"
        bash "$TEST" "$run_dir" "$bin" "$cfg"
        echo "$RUN_COUNTER,$block,$trace,$proc,$samp,$ratio,$n_lo,$rep,$run_dir" >> "$DATA_TABLE"
        echo "$RUN_COUNTER $run_dir" >> "$INDEX_FILE"
        RUN_COUNTER=$((RUN_COUNTER + 1))
    done
}

# ============================ BLOCK 1 =======================================
# Pure instrumentation overhead: HI-only, no background load, AlwaysOn
# sampler, Batch processor fixed. Factor: trace granularity level.
# 4 cells x 20 reps = 80 runs.
block1() {
    for trace in 0 1 2 3; do
        run_cell "block1" "$trace" 0 0 0.0 0 20 20
    done
}

# ============================ BLOCK 2 =======================================
# Sampling granularity: can OTel's ratio sampler actually protect HI spans
# when HI and LO share one trace? Fixed trace_level=2, processor=Batch,
# mixed workload (1 HI + 4 LO). The last argument selects the ostream exporter
# (RTAPP_EXPORTER_TYPE=1), so exported spans are printed on stdout and
# analyze_doe.py can count them -- no source edit needed any more.
#
# At trace_level=2 a sampled run exports a FIXED 8 spans regardless of duration
# (main, calibration, graceful-shutdown, one per thread, one phase and one
# thread_loop per thread); an unsampled run exports 0. The ratio sampler decides
# on the trace_id, which the whole execution shares, so the count per run is
# all-or-nothing and hi/lo_spans_exported is effectively a coin flip per run.
# That is the measurement: over 25 reps the sampled fraction estimates the ratio,
# and HI and LO are never sampled independently of each other.
# 6 cells x 25 reps = 150 runs.
block2() {
    run_cell "block2" 2 0 2 0.0 4 25 20 1   # AlwaysOff  (sanity control)
    run_cell "block2" 2 0 0 0.0 4 25 20 1   # AlwaysOn   (sanity control)
    run_cell "block2" 2 0 1 0.1 4 25 20 1
    run_cell "block2" 2 0 1 0.3 4 25 20 1
    run_cell "block2" 2 0 1 0.5 4 25 20 1
    run_cell "block2" 2 0 1 0.7 4 25 20 1
}

# ============================ BLOCK 3 =======================================
# Processor/exporter contention under growing noisy background load.
# trace_level in {0 (control), 3 (max span volume)}, processor in
# {Batch, Simple} (only meaningful when trace_level=3), sampler=AlwaysOn
# (worst case: every span goes through the processor), n_lo in {0,1,4,8}.
# (1 + 2) x 4 x 15 reps = 180 runs.
block3() {
    for n_lo in 0 1 4 8; do
        run_cell "block3" 0 0 0 0.0 "$n_lo" 15 20   # no instrumentation, control
        run_cell "block3" 3 0 0 0.0 "$n_lo" 15 20   # trace_level=3, Batch processor
        run_cell "block3" 3 1 0 0.0 "$n_lo" 15 20   # trace_level=3, Simple processor
    done
}

case "${1:-}" in
    block1) block1 ;;
    block2) block2 ;;
    block3) block3 ;;
    all) block1; block2; block3 ;;
    *) echo "Usage: $0 <block1|block2|block3|all>"; exit 1 ;;
esac

echo "[run_doe] finished '$1'. Results under: $DOE_ROOT"
