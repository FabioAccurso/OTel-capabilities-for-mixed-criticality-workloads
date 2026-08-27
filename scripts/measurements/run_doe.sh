#!/usr/bin/env bash
# Orchestrates the full DoE: rebuilds rt-app with the right OTel macros for
# each "cell", generates the JSON workload, and repeats the run REPS times.
#
# Usage: ./run_doe.sh <block1|block2|block3|all>
#
# EDIT THESE THREE PATHS FOR YOUR MACHINE before running:
RTAPP_SRC_DIR="${RTAPP_SRC_DIR:-$HOME/rtsia-project/project/rt-app/src}"
BIN_CACHE="${BIN_CACHE:-$HOME/rtsia-project/project/bin}"
DOE_ROOT="${DOE_ROOT:-$HOME/rtsia-project/project/2-DoE}"

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GEN="$HERE/gen_config.py"
TEST="$HERE/test.sh"
DATA_TABLE="$DOE_ROOT/data_table.csv"
INDEX_FILE="$DOE_ROOT/index.txt"

mkdir -p "$BIN_CACHE" "$DOE_ROOT"
[ -f "$DATA_TABLE" ] || echo "run_id,block,trace_level,processor_type,sampler_type,sampler_ratio,n_lo,rep,run_dir" > "$DATA_TABLE"
touch "$INDEX_FILE"
RUN_COUNTER=$(( $(wc -l < "$INDEX_FILE") + 1 ))

# --- build (or reuse cached) binary for a given macro combination ---------
build_bin() {
    local trace=$1 proc=$2 samp=$3 ratio=$4
    local tag="t${trace}_p${proc}_s${samp}_r${ratio}"
    local bin_path="$BIN_CACHE/rtapp_${tag}"
    if [ -x "$bin_path" ]; then
        echo "$bin_path"
        return
    fi
    echo "[build] $tag" >&2
    (
        cd "$RTAPP_SRC_DIR"
        make clean >/dev/null
        make CPPFLAGS="-DRTAPP_TRACE_LEVEL=${trace} -DRTAPP_PROCESSOR_TYPE=${proc} -DRTAPP_SAMPLER_TYPE=${samp} -DRTAPP_SAMPLER_RATIO=${ratio}" >/dev/null
    ) >&2
    cp "$RTAPP_SRC_DIR/rt-app" "$bin_path"
    echo "$bin_path"
}

# --- run one cell: build once, execute REPS repetitions --------------------
run_cell() {
    local block=$1 trace=$2 proc=$3 samp=$4 ratio=$5 n_lo=$6 reps=$7 duration=$8
    local bin; bin=$(build_bin "$trace" "$proc" "$samp" "$ratio")
    local cell_dir="$DOE_ROOT/$block/t${trace}_p${proc}_s${samp}_r${ratio}_n${n_lo}"
    mkdir -p "$cell_dir"
    local cfg="$cell_dir/config.json"
    python3 "$GEN" --n-lo "$n_lo" --duration "$duration" --out "$cfg"

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
# mixed workload (1 HI + 4 LO). Questo blocco richiede l'exporter ostream, per
# avere gli span contabili su stdout.log. NON serve piu' modificare main(): dal
# Task 3 basta la macro -DRTAPP_EXPORTER_TYPE=1 (0 = Zipkin, default).
# DA FARE nel Task 4: build_bin() non passa ancora quella macro — va aggiunto un
# quinto parametro 'exporter', incluso nel tag del binario in cache, e block2 deve
# invocare run_cell con exporter=1.
# 6 cells x 25 reps = 150 runs.
block2() {
    run_cell "block2" 2 0 2 0.0 4 25 20   # AlwaysOff  (sanity control)
    run_cell "block2" 2 0 0 0.0 4 25 20   # AlwaysOn   (sanity control)
    run_cell "block2" 2 0 1 0.1 4 25 20
    run_cell "block2" 2 0 1 0.3 4 25 20
    run_cell "block2" 2 0 1 0.5 4 25 20
    run_cell "block2" 2 0 1 0.7 4 25 20
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
