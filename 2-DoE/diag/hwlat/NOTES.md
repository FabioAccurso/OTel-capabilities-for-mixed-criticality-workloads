# hwlatdetect — ricerca di latenze di origine hardware/firmware

Eseguito il 2026-08-28 a sistema fermo, shield rimosso, dopo la campagna `diag`.
`rt-tests` 2.5-1 installato per l'occasione. Kernel: `CONFIG_HWLAT_TRACER=y`,
tracer `hwlat` presente in `available_tracers`.

## Cosa misura

Il tracer `hwlat` disabilita gli interrupt e legge l'orologio in un loop stretto:
se fra due letture consecutive il tempo **salta**, quel salto e' tempo in cui la
CPU non stava eseguendo istruzioni pur non essendo stata preemptata dal kernel.
E' la firma di un SMI (System Management Interrupt) o di un altro evento di
firmware, invisibile al sistema operativo.

## Risultati

| run | CPU | duty | durata | campionato | latenze > 10 us |
|---|---|---|---|---|---|
| 1 | 2 | 50 % (width 500 ms / window 1 s) | 5 min | ~150 s | **0** |
| 2 | 2, 6 | 95 % (width 950 ms / window 1 s) | 5 min | ~285 s | **0** |

**435 s di campionamento effettivo, zero latenze hardware sopra i 10 us.**
`Max Latency: Below threshold` in entrambi i run, file di report vuoti.

## Due avvertenze sulla lettura di questo risultato

**1. La riga "SMIs during run: 0" non e' una misura.** `hwlatdetect` la ricava da
`rdmsr 0x34` (`MSR_SMI_COUNT`), che e' un registro **Intel**: su questo Ryzen 7
3700U non esiste. Infatti stampa `rdmsr: CPU 0 cannot read MSR 0x00000034` e poi
riporta 0. Il conteggio SMI su questa piattaforma **non e' disponibile**; l'unico
dato valido e' la misura diretta dei salti temporali, che e' indipendente dal
contatore.

**2. `hwlatdetect` e' lo strumento giusto per il deadline miss isolato, non per
il regime a 3.5x.** La distinzione e' concettuale e va tenuta presente:

- il **deadline miss** del blocco 2 (una singola iterazione a 11 093 us contro
  1953) e' un *buco*: la CPU sparisce per ~9 ms. E' esattamente cio' che
  `hwlatdetect` sa vedere;
- il **regime a 3.5x** non e' un buco: la CPU continua a eseguire, solo piu'
  lentamente, per run interi. Un rallentamento sostenuto — per frequenza ridotta,
  contesa SMT o pressione sulla memoria — **non produce salti temporali** e
  quindi e' invisibile a questo tracer *per costruzione*.

Il risultato negativo va quindi letto cosi': **nessuna evidenza di SMI** su 435 s,
il che indebolisce l'ipotesi firmware per il miss isolato **senza escluderla** —
il miss ha un tasso di ~1 ogni 50 minuti di esecuzione, e sono stati campionati
7 minuti. Sul regime a 3.5x questo test non dice nulla, ne' a favore ne' contro.

## Dove resta la diagnosi

| fenomeno | strumento | stato |
|---|---|---|
| regime a ~3.5x | `aperf_mhz` (gia' in `run_doe.sh`) | armato, aspetta il prossimo evento |
| deadline miss isolato | `hwlatdetect` | 0 su 435 s, ipotesi SMI indebolita |

Se al prossimo run anomalo `aperf_mhz` riportasse ~2296 invece di ~626, l'ipotesi
frequenza sarebbe falsificata e resterebbero contesa SMT sul sibling cpu3 o
pressione sulla memoria, da misurare con i contatori IPC di `perf stat`.
