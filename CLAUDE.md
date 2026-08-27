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
│   ├── utils_freq/      cpu_freq.py (pin/reset frequenza via MSR), measure_ploop.sh,
│   │                    tune_calib.sh (ricava il ns-per-loop a ciclo chiuso)
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

## Prerequisito di misura: frequenza fissa + calibrazione saltata (FATTO)

Risolto fuori dalla numerazione dei task, su richiesta esplicita, dopo i finding di 0.1 e
0.3. Documentazione ed evidenze in `0-exploration/freq-calibrazione/`
(`NOTES.md` tecnico, `SPIEGAZIONE.md` discorsivo).

- Il kernel RT è compilato **senza** `CONFIG_CPU_FREQ` e `CONFIG_CPU_IDLE`:
  `/sys/.../cpufreq` non esiste, nessun governor, `cpupower` inutile. Unico canale: gli
  MSR (`CONFIG_X86_MSR=m`). HWP è **disattivato**, quindi si usa l'interfaccia legacy
  `IA32_PERF_CTL` + bit 38 di `IA32_MISC_ENABLE` per spegnere il turbo.
- `sudo` non funziona senza TTY in questa sessione: i comandi privilegiati vanno lanciati
  con **`pkexec`** (apre un popup grafico).

  ```
  pkexec /usr/bin/python3 scripts/utils_freq/cpu_freq.py pin      # prima del DoE
  pkexec /usr/bin/python3 scripts/utils_freq/cpu_freq.py info     # verifica
  pkexec /usr/bin/python3 scripts/utils_freq/cpu_freq.py reset    # a fine sessione
  ```

  Effetto misurato (APERF/MPERF, sotto carico): 2587-2652 MHz -> **1794-1805 MHz**,
  spread tra CPU dal 2,5% allo 0,3%.
- La frequenza fissa **non basta**: `calibrate_cpu_cycles_1()` (`rt-app.cpp:451`) usa una
  media mobile che parte da 0 e un test di uscita al 2%, quindi richiede **k >= 6
  iterazioni** per costruzione, ognuna preceduta da `clock_nanosleep` di 1 s. Pavimento
  ~6 s anche a macchina ferma.
- Soluzione: `"calibration": <intero>` in `global` (`rt-app_parse_config.cpp:1238`) salta
  del tutto la calibrazione. Il valore si ricava a ciclo chiuso con
  `scripts/utils_freq/tune_calib.sh` (inverte `load_count = exec*1000/p_load`,
  `rt-app.cpp:580`), non dalla calibrazione stessa.
- **Valore per questa macchina a ~1800 MHz: `139` ns/loop.** Verificato identico sotto
  `SCHED_OTHER` e `chrt -f 90`. Cablato in `run_doe.sh` come `CALIB_NS=139` e passato a
  `gen_config.py --calib`; generando config a mano senza `--calib` lo script avvisa.
- `run_doe.sh` ha un guard che **rifiuta di partire** (exit 1) se il turbo è ancora
  attivo, perché `CALIB_NS` è stato misurato a frequenza fissa: senza pin rt-app
  eseguirebbe silenziosamente ~30% di lavoro in meno del richiesto. Da root il guard
  legge `IA32_MISC_ENABLE` bit 38; da utente normale non può e stampa solo un warning.
- **Il pin va rifatto a ogni riavvio**: gli MSR tornano ai valori di power-on.
- Risultato: `run` misurato 1990-1991 µs su 5 run (spread **0,05%**, era 35%), wall time
  5,01 s contro 13,40 s. Il task 0.1 misurava ~4150 µs per 2000 configurati.
- SMT e isolamento: **risolto nel task 0.4**. La cmdline ora e'
  `isolcpus=domain,managed_irq,2,3,6,7 nohz_full=2,3,6,7 irqaffinity=0,1,4,5` (due core
  fisici interi all'esperimento, due al sistema). `CALIB_NS=139` e' stato **riverificato**
  in questa configurazione: rt-app misura 1982 us per 2000 configurati (-0,9%), quindi
  resta valido. Attenzione: con il fratello SMT occupato scenderebbe a 1302 us (-35%),
  vedi `0-exploration/task0.4/NOTES.md` §5.

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

- [x] **0.4** — Provare `sudo scripts/utils_isolation/isolate_cpus.sh 2,3` e verificare a
  mano (es. `cat /proc/irq/*/smp_affinity_list`, `taskset -c 2 ...`) che l'isolamento
  abbia effetto reale, poi `reset_isolation.sh`. Obiettivo: capire cosa fa lo script prima
  di fidarsene dentro il DoE automatizzato.
  Stato: FATTO. Risultati in `0-exploration/task0.4/` (`NOTES.md`, `SPIEGAZIONE.md`,
  `evidence/` con i micro-benchmark e i log rt-app). Svolto **dopo** che la cmdline GRUB
  era gia' stata cambiata in `isolcpus=domain,managed_irq,2,3,6,7 nohz_full=2,3,6,7
  irqaffinity=0,1,4,5`, quindi il task ha verificato sia il kernel sia lo script.
  Findings: (a) `isolcpus` funziona — 8 spinner senza affinity si ammassano su 0,1,4,5 e
  non toccano mai 2,3,6,7; `taskset -c 2` funziona comunque, come serve a rt-app;
  (b) `nohz_full` funziona — 1000 Hz di tick su cpu0/1 contro **1 Hz** su cpu2/3/6/7;
  (c) `cset` funziona nonostante cgroup v2 puro (si monta da solo una gerarchia v1 in
  `/cpusets`), il confinamento con `cset shield --exec` e' reale (affinity 2,3), i 189
  task rimasti in root sono **tutti** kthread; ma con `isolcpus` gia' attivo lo shield e'
  in gran parte ridondante; (d) `reset_isolation.sh` funziona ma **non ripristina le
  affinity IRQ** e lascia `/cpusets` montato; (e) **due bug corretti in
  `isolate_cpus.sh`**: `nproc` letto *dopo* `cset shield` ritorna 6 invece di 8 (la shell
  e' gia' nel cpuset `system`) e lo script enumerava indici invece di id CPU; una volta
  corretto, portava gli IRQ su 6,7 cioe' sui fratelli SMT delle CPU RT — ora esclude anche
  i fratelli e stampa un WARNING se isoli una CPU senza il suo gemello. **Va chiamato con
  `2,3,6,7`, non `2,3`**; (f) **finding principale**: `waste_cpu_cycles()` di rt-app usa
  `ldexp` e il suo throughput dipende dallo stato della FPU — con il fratello SMT occupato
  lo stesso lavoro va il **36% piu' veloce** a frequenza identica (1800 MHz verificati via
  APERF/MPERF), mentre un loop intero non cambia (0,3%). Su rt-app vero: `run` misurato
  1982 us con cpu6 vuota contro 1302 us con cpu6 occupata, per 2000 us configurati, **senza
  alcun errore nei log**. E' il motivo per cui isolare 2,3 senza 6,7 avrebbe reso
  incomparabili le celle del DoE, ed e' un limite metodologico di rt-app da citare nella
  relazione; (g) stabilita' ottenuta: cpu2 ripete 2171,8 us di mediana su run diversi
  (max/med 1,02x) anche sotto carico pieno, mentre cpu0 arriva a max/med **12,96x**
  (20,5 ms contro 1,6 ms di mediana).

- [x] **0.5** — Generare a mano una config con `gen_config.py --n-lo 4` e lanciarla UNA
  volta con `test.sh` (non `run_doe.sh`), ispezionando manualmente la cartella di output.
  Obiettivo: capire la struttura di un run prima di lanciarne centinaia in automatico.
  Stato: FATTO. Risultati in `0-exploration/task0.5/` (`NOTES.md`, `SPIEGAZIONE.md`,
  `cfg_n4.json`, `run_n4/`, piu' la controprova `cfg_n4_timer.json` + `run_n4_timer/`;
  i log `LO_noise` sono gzippati, quelli `HI_task` in chiaro). Binario senza tracing
  (`RTAPP_TRACE_LEVEL=0`, verificato: zero simboli otel), shield `cset` su 2,3,6,7 attivo,
  run da 20 s in 20,34 s di wall time (calibrazione saltata). Findings:
  (a) struttura di un run — `test.sh` archivia la config eseguita dentro la cartella,
  produce **un log per thread** (`instance: 4` -> 4 file) per **5,0 MB per run da 20 s**,
  da tenere presente al Task 4; (b) documentate tutte le 11 colonne di `log_timing`
  (`rt-app_utils.cpp:151`), fra cui `perf` = `exec/p_load` (`rt-app.cpp:563`) che e' una
  quantita' **configurata**, non misurata (14 per HI, 3 per LO); (c) HI_task 1998 loop,
  `run` 1979 us per 2000 configurati, periodo 9987 us con std **10,3 us** — questo e' il
  rumore di fondo contro cui misurare OTel; LO_noise ha periodo 2022 us invece di 1000
  perche' 4 istanze al 50% su una CPU sola chiedono il 200% (saturazione voluta);
  (d) **finding principale**: `slack`, `c_period` e `wu_lat` sono **0 su tutte le 41321
  righe**, perche' sono scritti solo nel ramo `case rtapp_timer:` (`rt-app.cpp:727-757`)
  e `gen_config.py` genera `run`+`sleep`, non `timer`. `analyze_doe.py:62` calcola
  `deadline_miss_ratio` da `slack<0` -> **sarebbe 0,000 in ogni cella del DoE**;
  (e) controprova eseguita con `timer` (sintassi verificata in
  `rt-app_parse_config.cpp:587-620`: `"timer":{"ref":"unique","period":10000}`): la
  metrica si accende e dice la cosa giusta — HI_task 0 miss su 1997, LO_noise **53,8%**
  di miss; compare la wake-up latency (HI: med 7 us, p99 12, **max 23 us**); e il jitter
  del periodo scende da 10,3 a **3,3 us** perche' i risvegli sono su griglia assoluta;
  (f) l'unico slack negativo di HI_task e' la **riga 1**, artefatto di avvio
  (`t_next` inizializzato a `*t_first`, `rt-app.cpp:737`) -> `analyze_doe.py` deve
  scartarla, altrimenti riporta 0,05% di miss come costante in ogni cella.

## Task 1.x-5.x — verso il deliverable finale

- [x] **Task 1** — Build completa: `autogen.sh && ./configure && make` in `rt-app/`;
  compilare `otel-installdir/` se assente (cmake -DWITH_ZIPKIN=ON -DBUILD_TESTING=OFF
  -DCMAKE_INSTALL_PREFIX=.../otel-installdir). Pacchetti apt: autoconf autoconf-archive
  automake libtool libcurl4-openssl-dev libnuma-dev libjson-c-dev cpuset cmake
  (`libjson-c-dev` obbligatorio, `configure` fallisce senza).
  Stato: FATTO. Documentazione in `1-build/` (`NOTES.md`, `SPIEGAZIONE.md`). Tutti i 9
  pacchetti apt gia' presenti; `otel-installdir/` gia' costruito nel task 0.2 (12 MB, le 7
  librerie richieste da `src/Makefile.am` verificate una a una). Da albero pulito
  (`make distclean`) la catena `./autogen.sh && ./configure && make` funziona **senza
  override**: chiuso il workaround `rt_app_LDADD=...` del task 0.1. Findings:
  (a) `autogen.sh` stampa 5 `fatal: Nessun nome trovato` ma esce 0 — e' `configure.ac:1`
  che ricava la versione da `git describe --tags` e il repo non ha tag, quindi
  `PACKAGE_VERSION` resta vuoto (innocuo, si risolve con un `git tag`); (b) 5 warning
  identici `"_GNU_SOURCE" redefined` (`libdl/dl_syscalls.h:20`), uno per unita' di
  compilazione, innocui; (c) il binario di default ha **zero** simboli otel (340 KB): la
  guardia `#if (RTAPP_TRACE_LEVEL > 0)` funziona e la baseline "senza strumentazione" e'
  davvero tale; (d) **tutte e 6 le combinazioni di macro** che i tre blocchi useranno
  compilano; attivare il tracing costa **15x di binario** (340 K -> 5,2 M) e **7,5x di
  compilazione** (5 s -> 38 s); (e) verificato che le macro abbiano effetto **a runtime**,
  non solo in compilazione: stesso taskset, `SAMP=2` (AlwaysOff) fa **0** tentativi di
  export, `SAMP=0` (AlwaysOn) ne fa 1 (`Connection failed`, nessun collector);
  (f) **preventivo del Task 4** dai dati misurati: 22 celle, **410 run**, 13 binari
  distinti -> ~2 h 30 min di macchina (di cui ~7 min di sole compilazioni) e **~1,5 GB**
  di log, piu' gli span del blocco 2 non ancora stimabili. Da lanciare in tre sessioni.
  **Resta aperto per il Task 4**: `RTAPP_SRC_DIR`/`BIN_CACHE`/`DOE_ROOT` in cima a
  `run_doe.sh` puntano a `$HOME/rtsia-project/project/...` che non esiste su questa
  macchina; `bin/` esiste ma e' di proprieta' di root. `2-DoE/data_table.csv` con la sola
  intestazione e' invece corretto: e' un file di **output** che `run_doe.sh:88` riempie.
  Albero lasciato con la build di default (`RTAPP_TRACE_LEVEL=0`).

- [x] **Task 2** — Scrivere le config JSON definitive per il DoE (HI su SCHED_FIFO,
  LO_noise repliche via `instance`), verificandole con `gen_config.py`.
  Stato: FATTO. Documentazione in `2-DoE/NOTES-task2.md` e `SPIEGAZIONE-task2.md`,
  config in `2-DoE/configs/` (`cfg_n{0,1,4,8}.json`), log di validazione gzippati in
  `2-DoE/validation/`. `gen_config.py` ora emette
  `"timer": {"ref":"unique","period":<us>}` invece di `"sleep"`, con le costanti esplicite
  (`HI_RUN,HI_PERIOD = 2000,10000` -> util 20%; `LO_RUN,LO_PERIOD = 500,1000` -> 50% per
  istanza) e una nuova opzione **`--pacing {timer,sleep}`** (default `timer`; `sleep`
  riproduce il vecchio comportamento per il solo confronto e stampa un WARNING).
  `run_doe.sh:83` non passa `--pacing` quindi eredita il default: **nessuna modifica a
  `run_doe.sh`**. Validazione (un run da 20 s per config, dentro lo shield):
  (a) **HI_task non manca mai una scadenza** — 0,0% di miss con n_lo 0/1/4/8, cioe' anche
  con 8 thread best-effort che chiedono il 400% di cpu3; `run` mediano 1979 us contro 2000
  configurati a ogni livello di carico -> `CALIB_NS=139` regge e il carico su cpu3 non
  ruba lavoro a cpu2; (b) `LO_noise` manca il 53% delle scadenze appena e' sovrascritto;
  (c) **avvertenza per il Task 5**: il `miss%` di LO **satura** (53,0% a n4, 52,9% a n8)
  perche' il timer in `mode` default `"relative"` riaggancia `t_next` all'istante corrente
  dopo uno sforo (`rt-app.cpp:752-756`) -> non e' una misura lineare del carico; cio' che
  cresce in modo monotono e' `wu_latency` (154 us -> 7135 -> 19425) e il periodo mediano
  (984 -> 2021 -> 2519 us). Se servisse un miss ratio crescente si passa a
  `"mode":"absolute"`, ma va deciso **prima** della campagna; (d) **un singolo run non e'
  rappresentativo**: ripetendo n0 e n1 tre volte ciascuno, 4 run su 10 mostrano jitter
  elevato (std 18-30 us invece di 4-5) **indipendentemente da `n_lo`** (compare anche a
  carico zero); causa non identificata (cpu2 isolata, freq fissa, fratello SMT vuoto ->
  resta qualcosa a livello di package). Il `miss%` di HI resta 0,0% in tutti e 10. Quindi
  le 15-25 ripetizioni per cella servono davvero, e nel Task 5 i confronti vanno fatti su
  **mediane fra ripetizioni**, mai fra run singoli.

- [x] **Task 3** — Introdurre una macro `RTAPP_EXPORTER_TYPE` (0=Zipkin default,
  1=ostream) e in `main()` sostituire la chiamata diretta a `InitTracerZipkin()` con un
  `#if RTAPP_EXPORTER_TYPE == 0 ... #else InitTracer() ... #endif`. Serve al Blocco 2 del
  DoE per contare a video gli span esportati.
  Stato: FATTO. Documentazione ed evidenze in `3-exporter/` (`NOTES.md`,
  `SPIEGAZIONE.md`, `evidence/` con gli stdout dei quattro binari + le 12 ripetizioni del
  ratio sampler). Macro aggiunta in `rt-app_types.h` con default **0** (verificato con
  `gcc -E -dM`: un `make` senza flag si comporta come prima) e switch con `#error` sul
  caso invalido in `main()`. **Risolto il blocco del task 0.3**: `InitTracer()` aveva
  AlwaysOn e Batch cablati e ignorava `RTAPP_SAMPLER_TYPE`/`_RATIO`/`RTAPP_PROCESSOR_TYPE`.
  Invece di duplicare gli `#if` nelle due funzioni ho estratto la coda comune in
  `InstallTracerProvider(exporter, service_name)` — entrambe le factory restituiscono
  `std::unique_ptr<trace_sdk::SpanExporter>`, quindi cambia solo exporter e `service.name`;
  le due funzioni pubbliche restano entrambe (45 righe aggiunte, 41 rimosse).
  Findings: (a) a `trace_level=2` un run campionato esporta **8 span fissi**
  (`main`, `calibration`, e per ogni thread lo span del thread + `thread_loop` + `phase`)
  **indipendentemente dalla durata**; a `trace_level=3` lo stesso run da 5 s passa a
  **5508 span / 4,7 MB** di stdout. `graceful-shutdown` **non e' uno span**, e' un evento
  dentro `main`; (b) **bug in `count_exported_spans()` (`analyze_doe.py:70`)**, segnalato
  da un compagno di corso e verificato sui nostri stdout: `content.count("HI_task")` conta
  la sottostringa in tutto il file, e lo span del thread porta il nome **due volte**
  (campo `name` + attributo `config.name`) -> **fattore 2 esatto** a entrambi i livelli.
  Problema piu' serio: solo lo span *del thread* si chiama come la task, i discendenti
  (`thread_loop`, `phase`, e a livello 3 le migliaia di `phase_loop`) non ne portano il
  nome e non vengono contati -> a livello 3 HI produce >2700 span e la funzione ne riporta
  2. Ricaduta su questo DoE limitata: il blocco 2 e' l'unico su ostream ed e' a livello 2,
  dove il valore resta un indicatore binario corretto (2 se campionato, 0 altrimenti).
  Correzione proposta in `3-exporter/NOTES.md` §8.4;
  (c) le macro ora hanno effetto: AlwaysOn 8 span, AlwaysOff 0, Zipkin 0 su stdout;
  (d) **FINDING CENTRALE DEL PROGETTO, ora sperimentale e non piu' dedotto dal codice**:
  12 ripetizioni con `TraceIdRatioBasedSampler(0.5)` -> 4 run campionati su 12, e in
  **nessuno** dei 12 HI e LO hanno avuto destini diversi (sempre 8 span o 0, mai un valore
  intermedio, mai HI senza LO). Il ratio sampler decide sul `trace_id`, condiviso da tutta
  l'esecuzione perche' ogni thread e' figlio di `main_span` -> **OTel standard non puo'
  prioritizzare i task critici**. Materiale diretto per il Task 6.
  **Cablato nel DoE**: `run_doe.sh` `build_bin()` accetta un quinto argomento `exporter`
  (default 0) **incluso nel tag della cache** (`..._e1`), `run_cell()` un nono argomento,
  e le 6 celle di `block2` passano 1. Rimosso il commento che diceva di modificare a mano
  `main()`. Blocchi 1 e 3 invariati su Zipkin.

- [~] **Task 4** — Eseguire il DoE (`scripts/measurements/run_doe.sh`): editare
  RTAPP_SRC_DIR/BIN_CACHE/DOE_ROOT in cima allo script, isolare le CPU, lanciare
  block1/block2/block3 (uno alla volta, su richiesta esplicita — non tutti insieme).
  Stato: **BLOCCO 1 FATTO**, blocchi 2 e 3 da lanciare. Percorsi risolti da
  `PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"` invece che
  hardcodati, quindi il repo funziona ovunque sia clonato. Risultati e analisi in
  `2-DoE/NOTES-block1.md`, `SPIEGAZIONE-block1.md`, `analyze_block1.py`; dati grezzi in
  `2-DoE/block1/` (80 run, 21 MB) e `data_table.csv`.
  Blocco 1 eseguito il 2026-08-27 19:39-20:08, **29m01s**, exit 0, 80/80 run integri.
  Condizioni: freq pinnata, shield `2,3,6,7`, `n_lo=0`, **nessun collector Zipkin**
  (7,7 `Connection failed` per run al livello 3 -> misura la creazione degli span, non il
  trasporto) e **thread di export non vincolato** (maschera `2-3,6-7`): entrambe scelte
  confermate dall'utente, da dichiarare nella relazione.
  Risultati: (a) **0,00% di deadline miss a ogni livello di tracing**, su ~160000 giri —
  a 20% di utilizzazione l'overhead non e' mai fatale; (b) **il jitter cresce in modo
  monotono**: `period_std` 7,6 -> 11,2 -> 10,8 -> 13,5 us (**+47%, +41%, +77%**); livelli
  1 e 2 indistinguibili, coerente col task 3 (al livello 2 gli span di fase sono uno per
  definizione, non per giro); (c) **wake-up latency +60%** (17 -> 27-28 us mediani, caso
  peggiore 165 us al livello 2); (d) **costo per giro misurato sullo `slack`**: +30 us ai
  livelli 1-2, **+56 us** al livello 3 (0,4% e 0,7% del budget di 8000 us; 1,5% e 2,8%
  dei 2000 us di calcolo).
  **ANOMALIA NON SPIEGATA, rilevante per il Task 5**: al livello 3 `run` **scende** a
  1955 us contro 1989 del livello 0, con **IQR nullo** (tutti e 20 i run identici). Il
  lavoro e' per costruzione identico e la finestra di misura esclude il codice degli span
  (`rt-app.cpp:683-693`). Ipotesi SMT **testata e scartata**: rilanciando il livello 3 con
  shield ristretto a `2,3` (thread di export escluso dal gemello di cpu2) il valore resta
  **1955 identico**, quindi non e' l'effetto FPU/SMT del task 0.4. Resta un effetto di
  stato del core non identificato. **Conseguenza**: `max_duration_us` e `mean_duration_us`
  di `analyze_doe.py`, che derivano da `run`, **non sono affidabili per confrontare livelli
  di tracing** — usare `slack`, `period_jitter_std_us` e `wu_latency`.
  **Da decidere prima dei blocchi 2 e 3**: il blocco 1 occupa 21 MB con `n_lo=0`, i
  blocchi 2 e 3 stimati ~750 MB ciascuno -> comprimere i log o tenere solo `HI_task`.
  Nota: rilanciare un blocco sovrascrive i `run_NN` ma **aggiunge** righe a
  `data_table.csv` -> svuotare prima `block*/`, `data_table.csv` e `index.txt`.

- [ ] **Task 5** — Analisi: `analyze_doe.py` → `2-DoE/results.csv` (deadline_miss_ratio,
  max_duration_us, period_jitter_std_us, hi/lo_spans_exported). Statistiche
  descrittive/confronti tra configurazioni.
  **Da fare qui (dai task 0.5, 2 e 3)**: (1) scartare la prima riga di ogni log, e' un
  transitorio di avvio che vale da solo 1 deadline miss su 1998 in ogni cella;
  (2) aggregare per **mediana fra ripetizioni**, mai confrontare run singoli: 4 run su 10
  mostrano jitter elevato in modo casuale (task 2); (3) non leggere il
  `deadline_miss_ratio` di LO come misura lineare del carico, satura al ~53% — usare
  `wu_latency` e il periodo mediano; (4) `hi/lo_spans_exported` del blocco 2 e' **binario
  per run** (8 span o 0, task 3) -> trattarlo come proporzione binomiale su 25 ripetizioni,
  non come conteggio continuo; (5) **correggere `count_exported_spans()`**, che conta la
  sottostringa in tutto il file e quindi raddoppia (`name` + attributo `config.name`):
  contare solo le righe `name`, vedi `3-exporter/NOTES.md` §8; (6) **non usare
  `max_duration_us`/`mean_duration_us` per confrontare livelli di tracing**: derivano da
  `run`, che al livello 3 *scende* per un effetto microarchitetturale non spiegato
  (blocco 1 §4) — usare `slack`, `period_jitter_std_us`, `wu_latency`.
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
