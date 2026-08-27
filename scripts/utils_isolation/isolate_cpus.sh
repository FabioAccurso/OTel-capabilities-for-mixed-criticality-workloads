#!/usr/bin/env bash
# Shield a set of CPUs from the rest of the system for RT experiments.
# Works WITHOUT rebooting (uses cset shield / cgroups). For best results
# also add to the GRUB kernel cmdline and reboot once:
#   isolcpus=<ISO_CPUS> nohz_full=<ISO_CPUS> rcu_nocbs=<ISO_CPUS>
# then re-run this script to additionally shield/move IRQs at runtime.
#
# Usage: sudo ./isolate_cpus.sh [cpu_list]   (default: 2,3)
#        cpu_list accetta sia "2,3" sia "2-3" sia "0-2,5"
#
# Task 0.4: corretti 3 difetti della versione originale (vedi 0-explore/0.4/NOTES.md)
#   1. usava `nproc`, che e' affinity-aware: DOPO `cset shield` la shell e' gia' confinata
#      nel cpuset "system", quindi nproc tornava 6 invece di 8 e l'elenco delle CPU non
#      isolate veniva calcolato sbagliato (0,1,4,5 invece di 0,1,4,5,6,7);
#   2. `grep -vFf` senza -x fa match di SOTTOSTRINGA: isolando la CPU 1 su una macchina
#      con >=10 CPU avrebbe escluso anche 10..19;
#   3. con la sintassi a intervallo ("2-3", valida per cset) nessun pattern faceva match e
#      le CPU isolate restavano nell'elenco -> gli IRQ NON venivano spostati, in silenzio.
# Aggiunto inoltre il backup delle affinita' IRQ, che reset_isolation.sh ora ripristina.
set -euo pipefail
ISO_CPUS="${1:-2,3}"
STATE_DIR=/var/tmp/rtapp-isolation
IRQ_BAK="${STATE_DIR}/irq_affinity.bak"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root (sudo)." >&2
  exit 1
fi

if ! command -v cset >/dev/null 2>&1; then
  echo "cpuset-tools not found. Install with: sudo apt install cpuset" >&2
  exit 1
fi

# "0-2,5" -> righe "0","1","2","5"
expand_cpus() {
  local part a b i
  for part in ${1//,/ }; do
    if [[ $part == *-* ]]; then
      a=${part%%-*}; b=${part##*-}
      for ((i = a; i <= b; i++)); do echo "$i"; done
    else
      echo "$part"
    fi
  done
}

# nproc --all, non nproc: il conteggio non deve dipendere dall'affinita' del chiamante
ALL_CPUS=$(nproc --all)
NON_ISO=$(seq 0 $((ALL_CPUS - 1)) | grep -vxFf <(expand_cpus "$ISO_CPUS") | paste -sd, -)

if [[ -z "$NON_ISO" ]]; then
  echo "ERRORE: '${ISO_CPUS}' isolerebbe tutte le ${ALL_CPUS} CPU, non resta nulla per il sistema." >&2
  exit 1
fi
while read -r c; do
  if (( c < 0 || c >= ALL_CPUS )); then
    echo "ERRORE: CPU ${c} fuori range (0-$((ALL_CPUS - 1)))." >&2
    exit 1
  fi
done < <(expand_cpus "$ISO_CPUS")

echo "[isolate] CPU isolate: ${ISO_CPUS}   CPU di sistema: ${NON_ISO}   (totali: ${ALL_CPUS})"

# Backup delle affinita' IRQ, una sola volta: se lo script viene rilanciato a shield
# gia' attivo non deve salvare lo stato gia' modificato.
mkdir -p "$STATE_DIR"
if [[ ! -f "$IRQ_BAK" ]]; then
  for f in /proc/irq/*/smp_affinity_list; do
    printf '%s\t%s\n' "$f" "$(cat "$f")"
  done > "$IRQ_BAK"
  echo "[isolate] affinita' IRQ originali salvate in ${IRQ_BAK}"
fi

echo "[isolate] shielding CPUs ${ISO_CPUS} (system + kthreads moved off)..."
cset shield --cpu="${ISO_CPUS}" --kthread=on

echo "[isolate] moving all IRQ affinities off the isolated CPUs..."
ok=0; ko=0
for f in /proc/irq/*/smp_affinity_list; do
  if echo "${NON_ISO}" > "$f" 2>/dev/null; then ok=$((ok + 1)); else ko=$((ko + 1)); fi
done
echo "[isolate]   IRQ riassegnati: ${ok}   rifiutati dal kernel: ${ko}"
if (( ko > 0 )); then
  echo "[isolate]   (i rifiuti sono IRQ 'managed' per-CPU, tipicamente code NVMe: il kernel"
  echo "[isolate]    non ne consente la migrazione. Si spostano solo con isolcpus= al boot.)"
fi

# --- verifica ---------------------------------------------------------------
echo "[isolate] verifica:"
# NB: niente pipeline che possa uscire !=0 dentro $( ), altrimenti pipefail + set -e
# abortiscono lo script proprio mentre verifica (successo del test = grep senza match).
mapfile -t iso_arr < <(expand_cpus "$ISO_CPUS")
residuo=0
for f in /proc/irq/*/smp_affinity_list; do
  mapfile -t cur_arr < <(expand_cpus "$(cat "$f")")
  for c in "${cur_arr[@]}"; do
    for i in "${iso_arr[@]}"; do
      if [[ "$c" == "$i" ]]; then residuo=$((residuo + 1)); break 2; fi
    done
  done
done
echo "[isolate]   IRQ che toccano ancora ${ISO_CPUS}: ${residuo}"
echo "[isolate]   (i kthread per-CPU come migration/N, ksoftirqd/N, ktimers/N NON sono"
echo "[isolate]    spostabili: e' un limite di cset, non un errore)"

echo "[isolate] done. Launch experiments INSIDE the shield with:"
echo "  sudo cset shield --exec -- <command...>"
echo "To undo everything: sudo ./reset_isolation.sh"
