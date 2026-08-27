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

# "0-3,5" -> "0 1 2 3 5"
expand_list() {
  local part out=()
  IFS=',' read -ra _parts <<< "$1"
  for part in "${_parts[@]}"; do
    if [[ $part == *-* ]]; then out+=($(seq "${part%%-*}" "${part##*-}"));
    else out+=("$part"); fi
  done
  echo "${out[@]}"
}
ISO_EXP=$(expand_list "${ISO_CPUS}")

if [[ $EUID -ne 0 ]]; then
  echo "Run as root (sudo)." >&2
  exit 1
fi

if ! command -v cset >/dev/null 2>&1; then
  echo "cpuset-tools not found. Install with: sudo apt install cpuset" >&2
  exit 1
fi

# An isolated CPU whose SMT sibling is NOT isolated shares its physical core with
# whatever the OS schedules there. Measured on this machine (task 0.4): rt-app's
# waste_cpu_cycles() runs 35% faster when the sibling is busy, so the "run" phase
# silently executes a different amount of work. Isolate siblings too, or disable SMT.
for c in ${ISO_EXP}; do
  sibs=$(expand_list "$(cat /sys/devices/system/cpu/cpu${c}/topology/thread_siblings_list)")
  for sib in ${sibs}; do
    if [[ " ${ISO_EXP} " != *" ${sib} "* ]]; then
      echo "[isolate] WARNING: cpu${sib} is the SMT sibling of isolated cpu${c} but is NOT isolated." >&2
    fi
  done
done

echo "[isolate] shielding CPUs ${ISO_CPUS} (system + kthreads moved off)..."
cset shield --cpu="${ISO_CPUS}" --kthread=on

echo "[isolate] moving all IRQ affinities off the isolated CPUs..."
# NOT nproc: this shell has already been moved into the "system" cpuset by cset, so
# nproc returns the size of its affinity mask (6 here, not 8) and seq would enumerate
# CPU *indices* 0..5 instead of the real non-isolated CPU *ids*. Read the id list from
# sysfs, which is affinity-independent.
# Keep IRQs off the isolated CPUs *and* off their SMT siblings: an interrupt taken on
# the sibling steals the shared physical core from the RT task just the same.
IRQ_EXCL="${ISO_EXP}"
for c in ${ISO_EXP}; do
  IRQ_EXCL+=" $(expand_list "$(cat /sys/devices/system/cpu/cpu${c}/topology/thread_siblings_list)")"
done
NON_ISO=""
for c in $(expand_list "$(cat /sys/devices/system/cpu/present)"); do
  [[ " ${IRQ_EXCL} " == *" ${c} "* ]] || NON_ISO+="${NON_ISO:+,}${c}"
done
for f in /proc/irq/*/smp_affinity_list; do
  echo "${NON_ISO}" > "$f" 2>/dev/null || true
done

# The kernel silently clips these writes for managed IRQs when the cmdline carries
# isolcpus=managed_irq, so report what actually stuck instead of what we asked for.
echo "[isolate] IRQ affinity requested: ${NON_ISO} | actually set: $(cat /proc/irq/0/smp_affinity_list)"

echo "[isolate] done. Launch experiments INSIDE the shield with:"
echo "  sudo cset shield --exec -- <command...>"
echo "To undo everything: sudo ./reset_isolation.sh"
