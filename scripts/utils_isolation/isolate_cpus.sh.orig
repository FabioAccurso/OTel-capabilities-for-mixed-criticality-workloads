#!/usr/bin/env bash
# Shield a set of CPUs from the rest of the system for RT experiments.
# Works WITHOUT rebooting (uses cset shield / cgroups). For best results
# also add to the GRUB kernel cmdline and reboot once:
#   isolcpus=<ISO_CPUS> nohz_full=<ISO_CPUS> rcu_nocbs=<ISO_CPUS>
# then re-run this script to additionally shield/move IRQs at runtime.
#
# Usage: sudo ./isolate_cpus.sh [cpu_list]   (default: 2,3)
set -euo pipefail
ISO_CPUS="${1:-2,3}"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root (sudo)." >&2
  exit 1
fi

if ! command -v cset >/dev/null 2>&1; then
  echo "cpuset-tools not found. Install with: sudo apt install cpuset" >&2
  exit 1
fi

echo "[isolate] shielding CPUs ${ISO_CPUS} (system + kthreads moved off)..."
cset shield --cpu="${ISO_CPUS}" --kthread=on

echo "[isolate] moving all IRQ affinities off the isolated CPUs..."
ALL_CPUS=$(nproc)
NON_ISO=$(seq -s',' 0 $((ALL_CPUS-1)) | tr ',' '\n' | grep -vFf <(echo "${ISO_CPUS}" | tr ',' '\n') | paste -sd, -)
for f in /proc/irq/*/smp_affinity_list; do
  echo "${NON_ISO}" > "$f" 2>/dev/null || true
done

echo "[isolate] done. Launch experiments INSIDE the shield with:"
echo "  sudo cset shield --exec -- <command...>"
echo "To undo everything: sudo ./reset_isolation.sh"
