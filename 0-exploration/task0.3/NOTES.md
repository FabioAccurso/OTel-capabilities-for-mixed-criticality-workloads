# Task 0.3 — exporter ostream: guardare uno span da vicino

Obiettivo: sostituire temporaneamente `InitTracerZipkin()` con `InitTracer()` (exporter
ostream) e vedere per la prima volta la struttura di uno span stampata a video, senza
ancora introdurre la macro `RTAPP_EXPORTER_TYPE` (quella è il Task 3).

## Modifica applicata (temporanea, poi annullata)

Una sola riga, `rt-app/src/rt-app.cpp:1976`:

```c
-	InitTracerZipkin();
+	InitTracer();	// TASK 0.3 TEMP: ostream exporter invece di Zipkin
```

`InitTracer()` era già presente nel codice del docente (`rt-app.cpp:111`) ma non veniva
mai chiamata. Differenze rispetto a `InitTracerZipkin()`:

| | `InitTracer()` | `InitTracerZipkin()` |
|---|---|---|
| exporter | `OStreamSpanExporterFactory` → stdout | `ZipkinExporterFactory` → HTTP :9411 |
| `service.name` | `rt-app_console` | `rt-app_zipkin` |
| processor | Batch, opzioni di default | Batch/Simple secondo `RTAPP_PROCESSOR_TYPE` |
| sampler | AlwaysOn cablato | secondo `RTAPP_SAMPLER_TYPE`/`_RATIO` |

**Nota importante per il Task 3 e per il Blocco 2 del DoE**: `InitTracer()` ignora
completamente le macro `RTAPP_PROCESSOR_TYPE`, `RTAPP_SAMPLER_TYPE` e
`RTAPP_SAMPLER_RATIO` — ha AlwaysOn e Batch cablati nel codice. Se il Blocco 2 conta gli
span esportati su stdout per misurare l'effetto del sampler, `InitTracer()` così com'è
**non serve**: il Task 3 dovrà replicarci dentro gli stessi `#if` di
`InitTracerZipkin()`, cambiando solo l'exporter.

## Build ed esecuzione

```
cd rt-app && make clean && make CPPFLAGS="-DRTAPP_TRACE_LEVEL=1 -DRTAPP_SAMPLER_TYPE=0"
cd 0-exploration/task0.3 && /usr/bin/time -v ../../rt-app/src/rt-app cfg_single.json \
    2> stderr.log | awk '{printf "[t+%02ds] %s\n", systime()-S, $0}' > stdout_timed.log
```

Stesso `cfg_single.json` di 0.1/0.2 (1 thread `SCHED_OTHER`, run 2000 µs / sleep 8000 µs,
`duration: 5`). Exit code 0.

File: `stdout.log` (output pulito), `stdout_timed.log` (stesso output con il tempo
relativo di apparizione di ogni riga), `stderr.log`, `rtapp-solo_task-0.log`.

## Anatomia di uno span (dall'output reale)

```
{
  name          : solo_task-0
  trace_id      : c4bf15997b7dee527d16f7662b0060da
  span_id       : e368a36d85fbd58f
  tracestate    :
  parent_span_id: 9e9b810e59720524
  start         : 1787823804274865811
  duration      : 4999990957
  ...
  attributes    :
	config.sched_data.policy: SCHED_OTHER
	config.sched_data.priority: 0
	cancellation: force_terminate
	...
  resources     :
	service.name: rt-app_console
	telemetry.sdk.version: 1.28.0
  instr-lib     : rt-app-tracer
}
```

Campi, uno per uno:

- `name` — nome dello span. Qui coincide col nome del thread rt-app (`solo_task-0`).
- `trace_id` (128 bit) / `span_id` (64 bit) — identità. `parent_span_id` costruisce
  l'albero; `0000000000000000` significa span radice.
- `start` — nanosecondi da epoch (`CLOCK_REALTIME`), non microsecondi come nel log nativo
  di rt-app.
- `duration` — nanosecondi.
- `span kind: Internal` — nessuno degli span è client/server: rt-app non fa RPC.
- `status: Unset` — il codice non chiama mai `SetStatus()`; nessuno span è marcato Ok/Error,
  quindi **una deadline miss oggi non è visibile in OTel**, solo nel log nativo di rt-app.
- `attributes` — i `config.*` che rt-app allega allo span; sono la configurazione, non la
  misura. Notare `config.sched_data.policy` e `config.sched_data.priority`: sono già lì e
  sono esattamente ciò che distinguerà HI da LO nel DoE.
- `resources` — attributi dell'intero processo, ripetuti su ogni span.
- `events` — sullo span `main` c'è `graceful-shutdown` con timestamp: un evento è un punto
  nel tempo dentro lo span, non un intervallo.
- `links` — sempre vuoto qui.

## I tre span e la loro gerarchia

```
main            9e9b810e59720524   parent 0000000000000000   dur 15.340 s
├── calibration b5f4b7b7b65c25c1   parent 9e9b810e59720524   dur 10.339 s
└── solo_task-0 e368a36d85fbd58f   parent 9e9b810e59720524   dur  5.000 s
```

Tutti e tre con lo stesso `trace_id` `c4bf...60da` — **riconferma diretta dell'ipotesi
centrale del progetto**, già vista in 0.2 attraverso Zipkin: se il `trace_id` è uno solo,
un `TraceIdRatioBasedSampler` prende una sola decisione per tutta l'esecuzione.

Da notare anche che `calibration` (10.34 s) è più lunga del workload vero (5.00 s):
lo span `calibration` (`rt-app.cpp:2066-2090`) avvolge `calibrate_cpu_cycles()`, cioè la
fase di taratura *prima* che parta qualunque thread. Nel DoE va escluso dalle misure: non
è carico, è setup. La sua durata è pure instabile — 10.34 s qui contro 3.05 s nel run di
0.2 — ennesima conferma che serve frequenza fissa.

## Quando escono gli span

`stdout_timed.log` mostra tutte e 100 le righe con prefisso `[t+15s]`: i tre span vengono
stampati **insieme, a fine processo**, non man mano che finiscono. È il
`BatchSpanProcessor` con le opzioni di default (`schedule_delay` 5 s): l'export avviene nel
flush di `CleanupTracer()`. Stesso comportamento visto in 0.2 col collector finto.

Conseguenza pratica: contare gli span leggendo stdout **funziona** (arrivano tutti), ma il
loro istante di apparizione non dice nulla su quando lo span è stato prodotto.

## ostream vs Zipkin: stessi dati, resa diversa

Confronto con `../task0.2/B_fake_collector/spans.json`:

| | ostream | Zipkin |
|---|---|---|
| `attributes` | sezione `attributes` | campo `tags` (stesse chiavi: 17 su `solo_task-0`, 19 su `main`) |
| `resources` | stampate su ogni span | **perse**, tranne `service.name` in `localEndpoint` |
| tempi | nanosecondi | microsecondi |
| trasporto | scrittura su stdout, in-process | POST HTTP, può fallire in silenzio |

L'exporter ostream è quindi *più* informativo del Zipkin (mostra le resources) ed è
l'unico che non può fallire per motivi di rete: per il Blocco 2 del DoE è la scelta giusta.

## Stato del sorgente

`rt-app.cpp` è stato **ripristinato** alla versione del docente (`git diff` vuoto): la
modifica di questo task era esplorativa e temporanea. La versione pulita e parametrica
arriverà col Task 3 (`RTAPP_EXPORTER_TYPE`).

## Cosa portarsi al DoE

1. `InitTracer()` va reso parametrico nel Task 3, altrimenti il Blocco 2 misura sempre
   AlwaysOn+Batch qualunque macro si passi.
2. Escludere lo span `calibration` dalle analisi, o eliminare la calibrazione fissando
   `calib_ns_per_loop` in config (elimina 3-10 s di rumore per run).
3. Contare gli span da stdout è affidabile; misurarne la latenza di export no, col Batch.
4. `status` mai impostato e `sched_data.policy`/`priority` già negli attributi: entrambi
   utili per il Task 6 (un sampler che decide su attributi invece che su trace_id avrebbe
   già il dato che gli serve).
