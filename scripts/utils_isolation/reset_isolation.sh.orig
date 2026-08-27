#!/usr/bin/env bash
# Undo isolate_cpus.sh
set -euo pipefail
if [[ $EUID -ne 0 ]]; then
  echo "Run as root (sudo)." >&2
  exit 1
fi
cset shield --reset
echo "[isolate] shield removed."
