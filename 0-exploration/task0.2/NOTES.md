# Task 0.2 — rt-app con `RTAPP_TRACE_LEVEL=1` + exporter Zipkin

Stesso task set del 0.1 (`cfg_single.json`: 1 thread `SCHED_OTHER`, run 2 ms / sleep 8 ms,
durata 5 s). Unica variabile cambiata: l'istrumentazione OTel.

## Prerequisito che è stato necessario fare qui
`otel-installdir/` non esisteva, quindi il binario del task 0.1 era linkato con
l'override `rt_app_LDADD="../libdl/libdl.a -lpthread"`. Con `RTAPP_TRACE_LEVEL=1` le
`-lopentelemetry_*` servono davvero, quindi ho costruito opentelemetry-cpp:

```bash
git clone --depth 1 --branch v1.28.0 --recurse-submodules --shallow-submodules \
    https://github.com/open-telemetry/opentelemetry-cpp.git otel-src
cmake -S otel-src -B otel-src/build -DCMAKE_BUILD_TYPE=Release \
      -DWITH_ZIPKIN=ON -DBUILD_TESTING=OFF -DWITH_EXAMPLES=OFF -DWITH_BENCHMARK=OFF \
      -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DCMAKE_CXX_STANDARD=17 \
      -DCMAKE_INSTALL_PREFIX=$PWD/otel-installdir
cmake --build otel-src/build -j8 && cmake --install otel-src/build
```

Librerie statiche, `nlohmann/json` installato dentro il prefix (serve allo Zipkin exporter).
Tutte e 9 le librerie elencate in `src/Makefile.am` esistono, **incluso**
`libopentelemetry_exporter_ostream_span_builder.a` → il `Makefile.am` del docente non va
toccato. `otel-src/` e `otel-installdir/` sono in `.gitignore` (240 MB, rigenerabili).

Build di rt-app (nessun override, il `Makefile.am` funziona così com'è):
```bash
cd rt-app && make clean && make CPPFLAGS="-DRTAPP_TRACE_LEVEL=1 -DRTAPP_SAMPLER_TYPE=0"
```
Verifica: `nm -C src/rt-app | grep -c opentelemetry` → 1232 simboli (nel 0.1 erano 0).

## Cosa fa `RTAPP_TRACE_LEVEL=1`
Solo tre span per l'intera esecuzione, nessuna istrumentazione dentro il ciclo:
- `main` — aperto in `rt-app.cpp:1976` subito dopo `InitTracerZipkin()`, chiuso all'uscita;
- `calibration` — attorno a `calibrate_cpu_cycles()` (`rt-app.cpp:2065`–`2089`);
- uno span per thread, `solo_task-0`, aperto in `thread_body` (`rt-app.cpp:1460`) con
  `span_opts.parent = main_span->GetContext()`.

## Esperimento A — nessun collector in ascolto (`A_no_collector/`)
```
[  0.01] [rt-app] <notice> Calibrate ns per loop
[  5.08] [rt-app] <notice> pLoad = 59ns : calib_cpu 0
[  5.08] [rt-app] <notice> [0] Starting with SCHED_OTHER policy with priority 0
[ 10.01] [Error] .../zipkin_exporter.cc:111 ZIPKIN EXPORTER] Zipkin Exporter: Connection failed
[ 10.08] [rt-app] <notice> [0] Exiting.
[ 10.08] [Error] .../zipkin_exporter.cc:111 ZIPKIN EXPORTER] Zipkin Exporter: Connection failed
```
- **Il collector NON serve perché rt-app funzioni**: exit code 0, log `log_timing`
  completo e identico per struttura a quello del 0.1, nessun crash, nessun blocco.
- **Il fallimento non è del tutto silenzioso, ma è silenzioso dove conta**: due righe
  `[Error] ... Connection failed` su **stderr** (le stampa l'exporter, non rt-app), e
  nient'altro. Nessun retry, nessun exit code diverso, nessun contatore di span persi
  visibile al programma: `span->End()` ritorna void e il `BatchSpanProcessor` scarta il
  batch. Chi lancia rt-app in uno script che non guarda stderr non si accorge di nulla.
- Rischio pratico per il DoE: se il collector non è su, un run "riesce" ma produce
  **zero telemetria**. Serve un check esplicito, non ci si può fidare del return code.

## Esperimento B — collector finto in ascolto (`B_fake_collector/`)
`fake_zipkin.py` = server HTTP su `127.0.0.1:9411` che accetta `POST /api/v2/spans`,
risponde `202` e salva il JSON (`spans.json`, `collector.log`).
```
[  5.97] POST /api/v2/spans   302 byte  1 span: ['calibration']
[  9.02] POST /api/v2/spans  1421 byte  2 span: ['solo_task-0', 'main']
```
Nessuna riga `[Error]`, stessa durata totale (8.06 s). Tutti e 3 gli span arrivano.

### Perché due batch e non uno: il `BatchSpanProcessor` in azione
`InitTracerZipkin()` usa `schedule_delay_millis = 5000` (`rt-app.cpp:154`). Il thread di
export si sveglia ogni 5 s: al primo giro (t≈5 s) trova in coda `calibration` (chiuso a
t≈3 s) e lo manda; `solo_task-0` e `main` chiudono solo a fine run e partono con il
**flush di shutdown** (t≈9 s). Quindi **uno span chiuso può restare in coda fino a 5 s
prima di essere esportato**: il ritardo osservato dal backend non è il ritardo del task.
Da tenere presente nel Blocco 2 del DoE quando si contano gli span esportati.

### Evidenza diretta dell'ipotesi centrale del progetto
```
name=calibration   traceId=d0c1...52cc  id=96a3...70d5  parentId=0a12...701e
name=solo_task-0   traceId=d0c1...52cc  id=d88a...e621  parentId=0a12...701e
name=main          traceId=d0c1...52cc  id=0a12...701e  parentId=None
```
**Un solo `traceId` per tutta l'esecuzione**, e ogni span di thread è figlio di `main`.
Con più task (HI e LO) la struttura sarà la stessa: un'unica trace. Poiché
`TraceIdRatioBasedSampler` decide sull'hash del `traceId`, con quel sampler la decisione
sarà **tutto-o-niente sull'intero processo**, non per task/criticità. Qui il sampler è
`AlwaysOn`, quindi la verifica sperimentale vera resta al DoE, ma la premessa strutturale
(trace unica condivisa) è ora confermata sul campo, non solo letta nel codice.

Attributi utili già presenti sullo span di thread: `config.sched_data.policy`,
`config.sched_data.priority`, `config.index`, `config.name`, `config.num_instances`,
`cancellation`. Sono esattamente le chiavi su cui potrebbe decidere il sampler custom
del Task 6.

## Impatto sull'esecuzione (rispetto al baseline)
Stesso config, tre run (`Z_baseline/` = binario `RTAPP_TRACE_LEVEL=0`):

| run | loops | run medio (µs) | run max (µs) | period medio (µs) | RSS max |
|---|---|---|---|---|---|
| Z baseline (trace 0) | 396 | 4486 | 4927 | 12583 | 4.3 MB |
| A trace 1, no collector | 406 | 4194 | 4462 | 12295 | 13.6 MB |
| B trace 1, collector | 398 | 4443 | 4803 | 12538 | 13.5 MB |

- **Nessun overhead per-loop misurabile**, come atteso: a livello 1 non c'è codice OTel
  dentro il ciclo. Le differenze (±7%) sono più piccole del rumore DVFS documentato nel
  0.1 (il baseline risulta perfino il più lento dei tre).
- **RSS ×3** (4.3 → 13.6 MB): il costo dell'SDK è di memoria e di thread, non di CPU nel
  path critico. Rilevante con `lock_pages` attivo.
- La durata totale del processo (8–13 s per un run da 5 s) è dominata dalla
  **calibrazione**, che da sola prende 3–5 s ed è variabile a causa del DVFS: non è OTel.
  Misurato con lo stesso metodo sul binario baseline: calibrazione 3.05 s, run 5 s.

## Cosa portarsi al DoE
1. Verificare esplicitamente che il collector risponda prima di ogni run, o contare gli
   span ricevuti: l'exit code di rt-app non dice nulla sulla telemetria.
2. `schedule_delay_millis = 5000` con run brevi significa che quasi tutto l'export avviene
   nel flush di shutdown → col `BatchSpanProcessor` l'overhead cade **fuori** dalla
   finestra di misura. È esattamente il confronto interessante con `SimpleSpanProcessor`
   (`RTAPP_PROCESSOR_TYPE=1`), che esporta in linea e paga il costo dentro il task.
3. Per misurare overhead sul WCET serve `RTAPP_TRACE_LEVEL` ≥ 2: a livello 1 non c'è
   nulla da misurare nel ciclo.
