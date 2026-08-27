# Task 0.1 — rt-app senza tracing (baseline)

## Cosa è stato fatto
- Layout: scaffolding autotools spostato dalla radice del repo dentro `rt-app/`
  (`src/Makefile.am` cerca `libdl/` e `doc/workgen` come fratelli di `src/`).
- Build: `./autogen.sh && ./configure && make rt_app_LDADD="../libdl/libdl.a -lpthread"`
  L'override di `rt_app_LDADD` serve solo qui: `src/Makefile.am` linka sempre le
  `-lopentelemetry_*`, che a `RTAPP_TRACE_LEVEL=0` non servono e non esistono ancora
  (`otel-installdir/` va costruita nel Task 1).
- Binario: `rt-app/src/rt-app`, 0 simboli opentelemetry (`nm -C | grep -c opentelemetry` → 0),
  `ldd` senza libcurl/OTel → baseline pulita.
- Run: `cfg_single.json` (1 thread SCHED_OTHER, run 2 ms / sleep 8 ms, duration 5 s).

## Due fix necessari per compilare (estensioni minime, non riscritture)
1. `src/rt-app_types.h`: `#include "opentelemetry/trace/provider.h"` era **fuori** da
   qualsiasi guardia → a `RTAPP_TRACE_LEVEL=0` la build falliva. Ora è dentro
   `#if (RTAPP_TRACE_LEVEL > 0)`, coerente con il resto del file (il campo `span`
   della `thread_data_t` era già guardato allo stesso modo).
2. `libdl/dl_syscalls.h`: prototipi di `sched_setattr`/`sched_getattr` senza
   `extern "C"` → compilati come C++ producevano un simbolo mangled non risolto contro
   `libdl.a` (compilata come C). Aggiunta la guardia `#ifdef __cplusplus extern "C" {`.
   Serve perché questo fork è C++ mentre `libdl/` è rimasta C. `configure` rileva
   `sched_setattr: no` → `SET_DLSCHED` attivo → `libdl.a` viene linkata davvero.

## Formato del log nativo (`log_timing`, rt-app_utils.cpp:151)
Header scritto in `rt-app.cpp:1454`. Una riga per *phase loop*:

| col | significato | in questo run |
|---|---|---|
| `#idx` | indice del thread | sempre 0 |
| `perf` | lavoro svolto = `exec / p_load` (unità di loop di calibrazione), **fisso** per costruzione | 32 = 2000 µs / 62 ns |
| `run` | durata **misurata** dei soli eventi `run` (µs) | ~4150 µs medi (configurati 2000!) |
| `period` | durata **misurata** dell'intera iterazione, run+sleep (µs) | ~12250 µs medi (attesi 10000) |
| `start`/`end` | timestamp assoluti CLOCK_MONOTONIC (µs) | |
| `rel_st` | start relativo a `main_app_start` (µs) | |
| `slack` | margine sulla deadline, valorizzato **solo** dall'evento `timer` (rt-app.cpp:742) | 0 |
| `c_duration` | run *configurato* (µs) | 2000 |
| `c_period` | periodo *configurato*, solo con `timer` | 0 |
| `wu_lat` | wake-up latency, solo con `timer` | 0 |

407 loop in 5 s. `perf` costante e `run` variabile è la coppia chiave: rt-app tiene fisso
il **lavoro**, non il tempo → `run` misura quanto tempo è costato quel lavoro.

## Finding rilevante per il DoE
Configurato `run=2000 µs`, misurato ~4150 µs. I **primi due** loop danno 1970 e 2102 µs,
poi il valore raddoppia e si stabilizza a ~4460 µs. Causa: DVFS/turbo. i7-8565U, base
1.8 GHz / turbo ~4.1 GHz; `/proc/cpuinfo` mostra core a 4.1 GHz e core a 2.0 GHz nello
stesso istante. La calibrazione (`calibration: CPU0`, `pLoad = 62 ns`) avviene in un burst
breve a frequenza turbo, poi il carico sostenuto fa scendere il clock → lo stesso lavoro
costa ~2x.

Conseguenza per i task successivi: il **WCET empirico** (`max_duration_us`) è dominato
dalla frequenza, non dall'overhead OTel, se non si fissa il punto di lavoro della CPU.
Prima del DoE vero serve almeno: isolamento CPU (task 0.4) + calibrazione sulla stessa
CPU su cui gira il task, e idealmente frequenza bloccata. Altrimenti il rumore DVFS
(~100%) sommerge l'effetto che stiamo misurando.

## Verifica sperimentale della causa (diag/)
Secondo run (`diag/cfg_cpu2.json`: task pinnato su CPU2, `calibration: CPU2`) con
campionamento di `/proc/cpuinfo` MHz per CPU2 ogni 0.2 s (`diag/freq_cpu2.txt`):

```
3947 1800 1800 1800 1801 1800 ... (35 campioni su 40 a 1800 MHz)
```

Il primo campione (fase di calibrazione) è a ~3.9 GHz, tutto il resto del run è a
**1800 MHz = clock base**. Rapporto 4100/1800 = 2.28, contro un rapporto misurato
run/c_duration = 4383/2000 = 2.19. La causa è confermata quantitativamente: `p_load` è
calibrato in turbo, l'esecuzione avviene a frequenza base.

Pinnare il task e calibrare sulla stessa CPU **non** risolve (run medio 4383 µs, praticamente
identico al run non pinnato): il problema è temporale (turbo all'inizio, base dopo), non
spaziale.

Vincolo della macchina: il kernel RT è compilato con `# CONFIG_CPU_FREQ is not set`
(`/home/fabio/linux-6.12.79/.config`), quindi non esistono `/sys/.../cpufreq` né
`intel_pstate`: **da Linux non c'è alcun governor su cui agire**. Le frequenze sono decise
dal firmware/HWP. Opzioni: (a) disattivare il Turbo Boost dal BIOS, (b) ricompilare il
kernel RT con `CONFIG_CPU_FREQ` + `intel_pstate` e usare governor `performance` con
`no_turbo=1`, (c) mitigare nel disegno sperimentale (warm-up scartato, ordine dei run
randomizzato, confronti appaiati, molte repliche).
