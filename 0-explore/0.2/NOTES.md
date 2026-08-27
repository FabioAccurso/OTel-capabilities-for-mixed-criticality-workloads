# Task 0.2 — rt-app con RTAPP_TRACE_LEVEL=1, SAMPLER=AlwaysOn, exporter Zipkin

## Come è stato costruito ed eseguito

```
cd rt-app/
make clean
make CPPFLAGS="-DRTAPP_TRACE_LEVEL=1 -DRTAPP_SAMPLER_TYPE=0"
cd 0-explore/0.2/
../../rt-app/src/rt-app cfg_single.json
```

Config identica a 0.1 (`cfg_single.json`: 1 thread SCHED_OTHER, run 2000 us /
sleep 8000 us, duration 5 s, calibration "CPU0").
Binari salvati in `bin/`: `rt-app_T0` (livello 0, task 0.1) e `rt-app_T1_S0` (questo).

## Cosa è cambiato nel binario

| | TRACE_LEVEL=0 | TRACE_LEVEL=1 |
|---|---|---|
| dimensione | 1 985 872 B | 5 310 264 B (+167 %) |
| stringhe OTel | assenti | `rt-app_zipkin`, `rt-app-tracer`, `http://localhost:9411/api/v2/spans` |

Le macro sono di compilazione: a livello 0 tutto il codice OTel è dietro
`#if (RTAPP_TRACE_LEVEL > 0)` e sparisce dal binario; a livello 1 vengono linkate
staticamente le librerie OTel + libcurl.

## Nessun collector in ascolto: OTel NON fallisce in silenzio

`ss -ltnp` → nessun listener su 9411. Endpoint di default hardcoded in
`otel-installdir/include/opentelemetry/exporters/zipkin/zipkin_exporter_options.h:22`
(`kZipkinEndpointDefault = "http://localhost:9411/api/v2/spans"`).

Su **stderr** compaiono 2 righe (una per tentativo di export):

```
[Error] File: .../exporters/zipkin/src/zipkin_exporter.cc:111 ZIPKIN EXPORTER] Zipkin Exporter: Connection failed
```

**Exit status 0**: rt-app non si accorge del fallimento, non ritenta, non bufferizza
su disco. Gli span sono persi. Per l'esperimento questo significa che *"il programma
gira senza errori" non è prova che la telemetria sia arrivata*: il conteggio degli span
va fatto lato collector (o con l'exporter ostream, task 0.3 / Task 3).

## Quando avvengono i tentativi di export (run con stderr timestampato)

`run2_stderr_ts.log`:

```
[ +0.017s] Calibrate ns per loop
[ +7.076s] pLoad = 27ns : calib_cpu 0
[ +7.089s] [0] Starting with SCHED_OTHER policy with priority 0
[+10.019s] ZIPKIN EXPORTER: Connection failed      <-- durante il run del thread RT
[+12.078s] ZIPKIN EXPORTER: Connection failed      <-- flush di shutdown
```

Ricostruzione: `InitTracerZipkin()` gira a t≈0 e il BatchSpanProcessor è configurato
con `schedule_delay_millis = 5000` (rt-app.cpp:154). Tick a ~5 s: coda vuota (nessuno
span ancora chiuso) → nessun export. Tick a ~10 s: in coda c'è lo span `calibration`
(chiuso a +7.07 s) → export → connessione rifiutata. A +12.08 s il thread finisce, si
chiudono span `thread0-0` e `main`, e il flush di shutdown fa il secondo tentativo.

A livello 1 gli span totali sono solo **3** (`main`, `calibration`, `thread0-0`):
uno per thread, non uno per loop. Nessun lavoro OTel dentro il loop periodico.

## Overhead sul thread periodico: n=1 non basta

**Attenzione — dati rivisti il 2026-08-27.** La tabella originale di questa sezione
confrontava il log di 0.1 con un run di 0.2 il cui log è stato **sovrascritto**: rt-app
scrive sempre su `rtapp-thread0-0.log` nella cwd, e un terzo run non registrato (mtime
23:28, contro le 22:21 di `run_stderr.log`) ha rimpiazzato il file. I numeri qui sotto
sono ricalcolati sui log **effettivamente presenti** nelle due cartelle.

Colonne del log in **microsecondi**.

| | 0.1 (TRACE 0) | 0.2 (TRACE 1) |
|---|---|---|
| pLoad del run (dalla colonna `perf`) | 18 ns | 18 ns |
| loop completati | 454 | 469 |
| run medio | 2887 us | 2572 us |
| run max | 4628 us | 4929 us |
| period p50 / p99 / max | 10749 / 12305 / 12695 us | 10561 / 11572 / 13014 us |

Entrambi i log hanno `perf = 111` costante su tutte le righe: `perf = exec / p_load`
(rt-app.cpp:563) con `exec = 2000` us → `p_load = 18` ns in **tutti e due** i run, quindi
per una volta il lavoro nominale richiesto è identico (111 111 iterazioni di
`waste_cpu_cycles` per fase). Nonostante questo il `run` medio differisce del 12 %
(2887 vs 2572 us, cioè 26.0 vs 23.1 ns reali per iterazione) e i massimi sono entrambi
~2x la media. Con n=1 e CPU non isolate il rumore di piattaforma domina qualunque
effetto del tracing: da questi due run **non si può concludere nulla sull'overhead**.
Conferma pratica del perché la traccia chiede 10-30 ripetizioni e perché servono il
task 0.4 (isolamento CPU) e `"calibration": <int>` fisso.

## pLoad: perché varia tra run (e perché NON dipende dal tracing)

`p_load` (`rt-app.cpp:2080`) è il costo in ns di **una** iterazione di
`waste_cpu_cycles()` (4 `ldexp` in doppia precisione, rt-app.cpp:428), misurato allo
startup. Serve solo come fattore di conversione in `loadwait()`:

```c
load_count = (exec * 1000) / p_load;   // rt-app.cpp:580
```

quindi **riscala il lavoro effettivo di ogni fase**: `run: 2000` us diventa 111 111
iterazioni con pLoad=18 e 74 074 con pLoad=27. Due run con pLoad diverso eseguono
workload diversi e non sono confrontabili.

Nelle prime stesure di queste note comparivano 18 ns (0.1) e 27 ns (0.2), e la
differenza era stata attribuita al caso. Verificato: è rumore di macchina, non effetto
del tracing.

**Misura**: 12 run alternati dei due binari cached, stessa config, macchina idle.

| binario | pLoad osservati |
|---|---|
| `bin/rt-app_T0` (TRACE 0) | 18, 20, 18, 18, 21, 18 |
| `bin/rt-app_T1_S0` (TRACE 1) | 18, 18, 20, 20, 18, 18 |

Distribuzioni indistinguibili. Con 8 busy-loop in background: pLoad = **58, 63, 58**;
tolto il carico, di nuovo 18, 18. La calibrazione risponde al carico di sistema di un
fattore 3x.

**Perché è così instabile**:

1. *Misura la CPU, non il binario.* Ryzen 7 3700U mobile, base 2.3 GHz / boost 4.0 GHz;
   il loop è puramente FP-bound, quindi il costo per iterazione è inversamente
   proporzionale alla frequenza istantanea. 1.5x di spread in frequenza = 1.5x in pLoad,
   che è esattamente 18 -> 27.
2. *L'euristica di convergenza esce troppo presto* (`calibrate_cpu_cycles_1`,
   rt-app.cpp:451-486):
   ```c
   avg_per_loop = (avg_per_loop + nsec_per_loop) >> 1;   /* media mobile a=0.5, parte da 0 */
   if ((abs(nsec_per_loop - avg_per_loop) * 50) < avg_per_loop)
           return avg_per_loop;                          /* esce al primo 2% di accordo */
   ```
   nessun numero minimo di campioni, nessuna mediana. In più il metodo 1 fa
   `clock_nanosleep` di **1 s** prima di ogni burst: il core esce dal boost e il burst
   successivo viene cronometrato durante la rampa di frequenza. E `max_load_loop` cresce
   di 33333 a ogni tentativo, quindi tentativi diversi campionano regimi diversi.
3. *Bias verso lo stato più veloce.* `calibrate_cpu_cycles()` (rt-app.cpp:536) ritorna
   `min(calib1, calib2)`; il metodo 2 non dorme mai e tiene il core in boost, quindi di
   norma vince lui — cioè il valore meno rappresentativo del regime stazionario.
4. *Contesa.* La calibrazione è pinnata su CPU0 (`calib_cpu 0`) ma CPU0 non è isolata:
   qualunque processo concorrente le sottrae cicli e budget termico.

**Aggiornamento 2026-08-27**: il boost è stato poi disabilitato e la frequenza fissata a
P0 = 2300 MHz con `scripts/utils_isolation/pin_cpu_freq.sh fix 0` (vedi la sezione "Setup di
determinismo della piattaforma" in `CLAUDE.md` per la procedura e i numeri). Dopo il pin il
pLoad passa da 18-21 ns con spread 17 % a **29-30 ns con spread 3.4 %**, e il `run` medio per
una fase da 2000 us scende da +29/+44 % a +6/+9 %. I run di 0.1 e 0.2 documentati sopra sono
quindi **pre-pin** e non vanno confrontati con misure successive.

**Conseguenza operativa per il DoE**: fissare `"calibration": <intero>` nel JSON
(pLoad in ns, senza virgolette — accettato da `rt-app_parse_config.cpp:1238`) per tutte
le config del Task 2. Rende il lavoro per fase identico tra run e salta i ~7-14 s di
calibrazione non deterministica allo startup.

**Nota di igiene sui dati**: rt-app scrive il log nella cwd con nome fisso
`<log_basename>-<task>-<idx>.log` e sovrascrive senza avvisare. `run_doe.sh` deve
lanciare ogni ripetizione in una cartella dedicata (o rinominare subito il log), altrimenti
i risultati si perdono come è successo qui.

## Fatto rilevante per la tesi del progetto (da riprendere ai Task 4-6)

`BatchSpanProcessor` fa l'export su un **thread proprio**
(`otel-installdir/include/opentelemetry/sdk/trace/batch_span_processor.h:193`,
`std::thread worker_thread_`), creato con scheduling di default → **SCHED_OTHER**.
Due conseguenze da verificare sperimentalmente:
1. l'I/O di rete non blocca il thread periodico (coerente con l'assenza di picchi nel
   log a +10 s, dove è caduto il primo export);
2. ma con task HI in SCHED_FIFO che saturano una CPU isolata, il worker OTel è
   il primo a essere starvato → gli span dei task critici sono quelli che si perdono.
   Questo è esattamente l'opposto della prioritizzazione richiesta dalla traccia.
