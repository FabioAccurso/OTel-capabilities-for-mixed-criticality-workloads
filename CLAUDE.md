# Progetto RTSIA — A5: Assessing OpenTelemetry per workload mixed-criticality

## Regole operative per Claude Code (leggere prima di fare qualunque cosa)

- Esegui **solo** il task che l'utente nomina esplicitamente nel prompt (es. "fai il task 0.2",
  "procedi con il task 2"). Non incatenare automaticamente i task successivi, anche se il
  prossimo passo ti sembra ovvio.
- Se un task ha già `[x]` (fatto) in questo file, NON rifarlo: verifica solo che lo stato
  descritto sia coerente con i file attuali. Rifallo da capo solo se l'utente lo chiede
  esplicitamente dicendo che non è soddisfatto.
- Al termine di un task, aggiorna il suo checkbox (`[ ]` → `[x]`) e la riga "Stato" sotto di
  esso in questo file, con una frase breve su cosa è stato fatto/dove sono i risultati.
- Non modificare i file `rt-app*.cpp/.h` in `src/` in modo distruttivo: sono forniti dal
  docente, già in C++ e già con hook OTel parziali. Estendi, non riscrivere da zero.
- Se un comando fallisce, riporta l'errore esatto invece di provare a "indovinare" un fix
  senza spiegarlo.

## L'elaborato (traccia originale, riassunta)

Corso: Real Time Systems and Industrial Applications — Team 1-2 persone, durata 4 settimane.

**Obiettivo**: valutare le capacità di OpenTelemetry (OTel) nel monitorare workload
*mixed-criticality* (task real-time con criticità/priorità diverse), verificando in
particolare se OTel è in grado di **prioritizzare i task critici** rispetto a quelli
best-effort nella pipeline di telemetria (tracing volume, sampling rate, ecc.), e
valutando l'**overhead del monitoraggio sul WCET**.

**Compiti richiesti dalla traccia**:
1. Impostare una campagna sperimentale che fornisca evidenza empirica della (eventuale)
   prioritizzazione dei task da parte di OTel.
2. Se l'evidenza mostra capacità inefficienti o assenti, analizzare il codebase di OTel e
   proporre miglioramenti architetturali concreti.

**Cosa si impara (dichiarato dalla traccia)**: uso di strumenti di monitoraggio reali su
vincoli real-time; impatto del monitoring overhead sul rispetto degli SLO; configurazioni
diverse di OTel in contesti mixed-criticality.

**Strumenti richiesti**: OS real-time (PREEMPT-RT Linux) bare-metal — soddisfatto (dual
boot, kernel 6.12.79-rt17); RT-POSIX; OpenTelemetry Framework.

**Deliverable attesi**: codice sorgente e file di configurazione; dati/evidenze della
campagna sperimentale; **10-30 ripetizioni per misura** per rilevanza statistica.

## Punto di partenza fornito

Fork C++ di `scheduler-tools/rt-app` (https://github.com/scheduler-tools/rt-app) con
tracing OTel già parzialmente instrumentato dal docente. Non è un progetto da zero: è da
completare/estendere/valutare.

## Layout del progetto

```
project/
├── rt-app/              sorgente C++ (src/), scaffolding autotools (Makefile.am radice,
│                        autogen.sh, README.in, COPYING.in, libdl/, doc/workgen,
│                        configure.ac già presente e corretto per C++17)
├── otel-installdir/     build+install locale di opentelemetry-cpp (WITH_ZIPKIN=ON)
├── scripts/
│   ├── utils_isolation/ isolate_cpus.sh, reset_isolation.sh (cset shield)
│   └── measurements/    gen_config.py, test.sh, run_doe.sh, analyze_doe.py
├── 2-DoE/               data_table.csv, index.txt, risultati dei run
└── bin/                 cache dei binari rt-app compilati per combinazione di macro
```

## Cosa già sappiamo del codice (rt-app_types.h, rt-app.cpp)

- 4 macro di compilazione controllano l'istrumentazione (NON sono opzioni runtime/JSON):
  `RTAPP_TRACE_LEVEL` (0=off, 1=main+thread span, 2=+phase, 3=+phase_loop),
  `RTAPP_PROCESSOR_TYPE` (0=Batch, 1=Simple), `RTAPP_SAMPLER_TYPE` (0=AlwaysOn, 1=Ratio,
  2=AlwaysOff), `RTAPP_SAMPLER_RATIO`. Si passano via `make CPPFLAGS="-DRTAPP_..."`.
- In `main()`, `main_span = tracer->StartSpan("main")`; in `thread_body()` ogni thread è
  **figlio** di `main_span` (`span_opts.parent = main_span->GetContext()`), quindi tutta
  l'esecuzione (task HI e LO insieme) condivide un solo `trace_id`.
- **Ipotesi centrale del progetto, da verificare sperimentalmente (non darla per assodata
  senza dati)**: `TraceIdRatioBasedSampler` decide in base al `trace_id`, identico per
  tutta la trace → il sampling ratio potrebbe non differenziare per task/criticità, ma
  campionare/scartare l'intera esecuzione in blocco. Un commento nel codice a
  `rt-app.cpp` (~riga 1595, "To get each phase loop on a different trace (to test
  Sampler)") mostra che l'autore originale se n'era accorto per i phase_loop ma non a
  livello di thread/criticità.
- `InitTracerZipkin()` è la funzione chiamata in `main()`; `InitTracer()` (ostream) esiste
  nel codice ma non è invocata — serve per il Task 3.

## Task 0.x — esplorativi/didattici (NON producono deliverable, servono a capire il setup)

Vanno fatti uno alla volta, a mano, per costruire intuizione su rt-app/OTel prima di
automatizzare. Ogni task 0.x deve concludersi con una spiegazione in linguaggio semplice di
cosa è successo e perché, non solo con l'esecuzione del comando.

- [x] **0.1** — Compilare rt-app SENZA tracing (`RTAPP_TRACE_LEVEL=0`, default) e lanciarlo
  con un task set banale (1 solo thread `SCHED_OTHER`, run/sleep semplice, durata 5s).
  Obiettivo: vedere rt-app funzionare e capire il formato del suo log nativo
  (`log_timing`), prima di aggiungere OTel nell'equazione.
  Stato: FATTO. Scaffolding autotools spostato dalla radice dentro `rt-app/`. Build con
  `./autogen.sh && ./configure && make rt_app_LDADD="../libdl/libdl.a -lpthread"`
  (override che salta le `-lopentelemetry_*`, non ancora disponibili). Due fix minimi:
  guardia `#if (RTAPP_TRACE_LEVEL > 0)` sull'include OTel in `rt-app_types.h:60` e
  `extern "C"` sui prototipi in `libdl/dl_syscalls.h`. Run 5 s + spiegazione del formato
  di log in `0-exploration/task0.1/` (`cfg_single.json`, `rtapp-solo_task-0.log`,
  `NOTES.md`). Finding: `run` misurato ~4150 µs vs 2000 configurati per effetto DVFS/turbo
  → il WCET empirico va protetto (isolamento + frequenza fissa) prima del DoE.

- [x] **0.2** — Ricompilare con `RTAPP_TRACE_LEVEL=1` e `RTAPP_SAMPLER_TYPE=0` (AlwaysOn),
  stesso task set di 0.1, con l'exporter Zipkin attivo (quello di default). Obiettivo:
  osservare cosa cambia nell'esecuzione (log, eventuale output/errore se non c'è un
  collector Zipkin in ascolto) — capire se serve un collector attivo o se OTel fallisce
  silenziosamente in sua assenza.
  Stato: FATTO. Prerequisito svolto qui: build di opentelemetry-cpp v1.28.0 in
  `otel-src/` → `otel-installdir/` (WITH_ZIPKIN=ON, statiche); il `src/Makefile.am` del
  docente linka senza modifiche. Build rt-app con
  `make CPPFLAGS="-DRTAPP_TRACE_LEVEL=1 -DRTAPP_SAMPLER_TYPE=0"`. Risultati in
  `0-exploration/task0.2/` (`NOTES.md` tecnico, `SPIEGAZIONE.md` discorsivo,
  `A_no_collector/`, `B_fake_collector/` con
  `fake_zipkin.py` + `spans.json`, `Z_baseline/`). Findings: (a) senza collector rt-app
  esce con 0 e log invariato, l'unico segnale sono due `[Error] Connection failed` su
  stderr → il collector NON serve per eseguire, ma la telemetria si perde senza che il
  programma lo sappia; (b) i 3 span (`main`, `calibration`, thread) condividono **un solo
  traceId** e il thread è figlio di `main` → confermata sul campo la premessa
  dell'ipotesi centrale sul `TraceIdRatioBasedSampler`; (c) col `BatchSpanProcessor`
  (`schedule_delay=5 s`) l'export cade quasi tutto nel flush di shutdown, fuori dalla
  finestra di misura; (d) a livello 1 nessun overhead per-loop misurabile (differenze
  sotto il rumore DVFS), ma RSS ×3 (4.3 → 13.6 MB).

- [x] **0.3** — Aggiungere temporaneamente una chiamata a mano a `InitTracer()` (ostream)
  al posto di `InitTracerZipkin()` in `main()`, ricompilare, rilanciare lo stesso task
  singolo. Obiettivo: vedere per la prima volta uno span stampato a video e capirne la
  struttura (nome, trace_id, span_id, attributi) — SENZA ancora introdurre la macro
  `RTAPP_EXPORTER_TYPE` del Task 3 (quella è la versione "pulita" da fare dopo, questo è
  solo per guardare l'output).
  Stato: FATTO. Modifica temporanea di una riga (`rt-app.cpp:1976`,
  `InitTracerZipkin()` → `InitTracer()`), build con
  `make CPPFLAGS="-DRTAPP_TRACE_LEVEL=1 -DRTAPP_SAMPLER_TYPE=0"`, stesso task set di
  0.1/0.2; sorgente poi **ripristinato** (`git diff` vuoto). Risultati in
  `0-exploration/task0.3/` (`NOTES.md`, `SPIEGAZIONE.md`, `stdout.log`,
  `stdout_timed.log` con l'istante di apparizione di ogni riga, `stderr.log`,
  `rtapp-solo_task-0.log`). Findings: (a) anatomia dello span letta sul campo — `status`
  non è mai impostato (una deadline miss oggi NON è visibile in OTel) mentre
  `config.sched_data.policy`/`priority` sono già negli attributi, materiale pronto per il
  Task 6; (b) i 3 span (`main` radice, `calibration` e thread suoi figli) condividono un
  solo `trace_id` — riconferma dell'ipotesi centrale, stavolta letta direttamente;
  (c) tutte le righe escono a `t+15s`, cioè nel flush di shutdown del BatchSpanProcessor:
  contare gli span da stdout è affidabile, misurarne la latenza no; (d) lo span
  `calibration` dura 10.3 s contro i 5.0 s del workload (era 3.0 s in 0.2) → è setup, non
  carico: va escluso dalle misure o eliminato fissando `calib_ns_per_loop`;
  (e) **da tenere presente per il Task 3**: `InitTracer()` ha AlwaysOn e Batch **cablati**
  e ignora `RTAPP_SAMPLER_TYPE`/`_RATIO`/`RTAPP_PROCESSOR_TYPE` → così com'è il Blocco 2
  conterebbe sempre gli stessi span; il Task 3 deve replicarci dentro gli `#if` di
  `InitTracerZipkin()`.

- [ ] **0.4** — Provare `sudo scripts/utils_isolation/isolate_cpus.sh 2,3` e verificare a
  mano (es. `cat /proc/irq/*/smp_affinity_list`, `taskset -c 2 ...`) che l'isolamento
  abbia effetto reale, poi `reset_isolation.sh`. Obiettivo: capire cosa fa lo script prima
  di fidarsene dentro il DoE automatizzato.
  Stato:

- [ ] **0.5** — Generare a mano una config con `gen_config.py --n-lo 4` e lanciarla UNA
  volta con `test.sh` (non `run_doe.sh`), ispezionando manualmente la cartella di output.
  Obiettivo: capire la struttura di un run prima di lanciarne centinaia in automatico.
  Stato:

## Task 1.x-5.x — verso il deliverable finale

- [ ] **Task 1** — Build completa: `autogen.sh && ./configure && make` in `rt-app/`;
  compilare `otel-installdir/` se assente (cmake -DWITH_ZIPKIN=ON -DBUILD_TESTING=OFF
  -DCMAKE_INSTALL_PREFIX=.../otel-installdir). Pacchetti apt: autoconf autoconf-archive
  automake libtool libcurl4-openssl-dev libnuma-dev libjson-c-dev cpuset cmake
  (`libjson-c-dev` obbligatorio, `configure` fallisce senza).
  Stato:

- [ ] **Task 2** — Scrivere le config JSON definitive per il DoE (HI su SCHED_FIFO,
  LO_noise repliche via `instance`), verificandole con `gen_config.py`.
  Stato:

- [ ] **Task 3** — Introdurre una macro `RTAPP_EXPORTER_TYPE` (0=Zipkin default,
  1=ostream) e in `main()` sostituire la chiamata diretta a `InitTracerZipkin()` con un
  `#if RTAPP_EXPORTER_TYPE == 0 ... #else InitTracer() ... #endif`. Serve al Blocco 2 del
  DoE per contare a video gli span esportati.
  Stato:

- [ ] **Task 4** — Eseguire il DoE (`scripts/measurements/run_doe.sh`): editare
  RTAPP_SRC_DIR/BIN_CACHE/DOE_ROOT in cima allo script, isolare le CPU, lanciare
  block1/block2/block3 (uno alla volta, su richiesta esplicita — non tutti insieme).
  Stato:

- [ ] **Task 5** — Analisi: `analyze_doe.py` → `2-DoE/results.csv` (deadline_miss_ratio,
  max_duration_us, period_jitter_std_us, hi/lo_spans_exported). Statistiche
  descrittive/confronti tra configurazioni.
  Stato:

- [ ] **Task 6** — Proposta di miglioramento architetturale (parte finale della
  consegna): sketch di un `Sampler` custom che decide su nome/attributi dello span
  invece che sul trace_id, così HI e LO possono avere ratio di campionamento indipendenti
  pur restando nella stessa trace causale. Solo se i dati del Task 5 mostrano che serve.
  Stato:

## Note

- Non inventare/assumere nomi di funzioni OTel non verificati nel codice: leggere sempre
  il sorgente reale prima di modificarlo.
- I run del DoE vero (Task 4) presuppongono i task 0.x completati almeno una volta a mano.
