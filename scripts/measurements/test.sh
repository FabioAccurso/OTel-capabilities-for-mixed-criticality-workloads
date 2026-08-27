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

echo "[test] done -> $DIR"
