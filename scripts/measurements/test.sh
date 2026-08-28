#!/usr/bin/env bash
# Run ONE rt-app experiment and collect its output into a run directory.
# Mirrors the workflow described in the project README ("test.sh $DIR").
#
# Usage: test.sh <run_dir> <rt-app-binary> <config.json>
set -euo pipefail

DIR="$1"
BIN="$2"
CFG="$3"

mkdir -p "$DIR"

# Rewrite logdir/log_basename inside the config so rt-app writes its
# per-thread logs directly into $DIR (keeps every run self-contained).
python3 - "$CFG" "$DIR" << 'PYEOF'
import json, sys
cfg_path, outdir = sys.argv[1], sys.argv[2]
with open(cfg_path) as f:
    data = json.load(f)
data.setdefault("global", {})["logdir"] = outdir
data["global"]["log_basename"] = "rtapp"
with open(f"{outdir}/config.json", "w") as f:
    json.dump(data, f, indent=2)
PYEOF

echo "[test] $BIN  $DIR/config.json"

# Run inside the CPU shield if cset is available and a shield is active;
# fall back to a plain run otherwise (still useful for smoke-testing).
if command -v cset >/dev/null 2>&1 && cset shield >/dev/null 2>&1; then
    sudo cset shield --exec -- "$BIN" "$DIR/config.json" \
        > "$DIR/stdout.log" 2> "$DIR/stderr.log"
else
    "$BIN" "$DIR/config.json" > "$DIR/stdout.log" 2> "$DIR/stderr.log"
fi

# Compress the LO_noise logs. With up to 8 background threads they dominate a
# run's footprint (~1.2 MB each, ~8:1 compression), while HI_task-0.log is left
# in clear so find_hi_log() in analyze_doe.py keeps matching "*HI*log".
# Decided before launching block 2; see CLAUDE.md, Task 4.
shopt -s nullglob
lo_logs=("$DIR"/*LO_noise*.log)
shopt -u nullglob
if (( ${#lo_logs[@]} > 0 )); then
    gzip -f "${lo_logs[@]}"
    echo "[test] gzipped ${#lo_logs[@]} LO_noise log(s)"
fi

echo "[test] done -> $DIR"
