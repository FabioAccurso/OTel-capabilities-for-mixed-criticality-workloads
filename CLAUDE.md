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
│   ├── utils_isolation/ isolate_cpus.sh, reset_isolation.sh (cset shield),
│   │                    pin_cpu_freq.sh (frequenza fissa via MSR)
│   └── measurements/    gen_config.py, test.sh, run_doe.sh, analyze_doe.py
├── 2-DoE/               data_table.csv, index.txt, risultati dei run
└── bin/                 cache dei binari rt-app compilati per combinazione di macro
```

## Setup di determinismo della piattaforma (prerequisito di ogni misura)

Macchina: ASUS ZenBook UX431DA, AMD Ryzen 7 3700U (8 CPU, ultrabook 15 W), kernel
6.12.79-rt17.

Il kernel RT è compilato con `# CONFIG_CPU_FREQ is not set` e `# CONFIG_CPU_IDLE is not
set`: **non esiste** `/sys/.../cpufreq`, quindi niente governor, niente `cpupower
frequency-set`. Le P-state le gestisce il firmware (SMU) e Linux le osserva soltanto via
`aperfmperf`. Lato positivo: senza cpuidle non ci sono C-state governate dal kernel,
quindi nessun picco di wake-up latency; `constant_tsc`/`nonstop_tsc` sono presenti, quindi
`CLOCK_MONOTONIC` è immune ai cambi di frequenza.

L'unica leva rimasta è MSR-based → `scripts/utils_isolation/pin_cpu_freq.sh`
(`status` | `fix [idx]` | `reset`), che agisce su `HWCR 0xC0010015` bit 25 (`CpbDis`,
disabilita il Core Performance Boost) e su `PStateCtl 0xC0010062` (P-state richiesta).
Richiede `msr-tools` (`sudo apt install msr-tools`) e root. **Le scritture non
sopravvivono al reboot**: vanno rifatte a ogni sessione di misura, e `run_doe.sh` (Task 4)
deve lanciarle e registrarne l'esito nei metadati del run.

P-state definite dal firmware su questa CPU: **P0 = 2300 MHz**, P1 = 1700, P2 = 1400.

Effetto misurato di `pin_cpu_freq.sh fix 0` (2026-08-27):

| | boost attivo | P0 fisso |
|---|---|---|
| MHz live sui core | 2032-2670 (spread 31 %) | 2229-2296 (spread 2.9 %) |
| pLoad su 12 run (2 binari) | 18-21 ns (spread 17 %) | 29-30 ns (spread 3.4 %) |
| loop completati in 5 s | 454-469 | 487-489 |
| `run` medio per `run: 2000` us | 2572-2887 us (+29/+44 %) | 2115-2175 us (+6/+9 %) |
| period p50 / p99 | 10561-10749 / 11572-12305 us | 10053-10124 / 11165-11379 us |

Perché il pLoad *sale* da 18 a 29 ns: 18 ns era una misura presa durante un burst in boost
(2300 × 29/18 ≈ 3700 MHz, coerente col boost di 4.0 GHz del 3700U), mentre il thread
periodico girava poi a frequenza sostenuta. rt-app quindi **sottostimava** il costo per
iterazione e ogni fase durava molto più del richiesto. Con il pin, calibrazione e run
avvengono nello stesso regime.

Limiti residui da tenere presenti:
- l'SMU può ancora scendere sotto P0 per limiti STAPM/termici (15 W, Tctl ~56-65 C): va
  **misurata** la deriva, registrando `grep "cpu MHz" /proc/cpuinfo` e
  `/sys/class/hwmon/hwmon3/temp1_input` (k10temp, Tctl) a ogni run. Se P0 non regge su
  campagne lunghe, `fix 1` (1700 MHz) dà più margine termico: per un confronto di overhead
  contano più i MHz stabili che i MHz alti;
- `perf` oscilla ancora tra 66 e 68 (pLoad 29 vs 30) → serve comunque `"calibration": 29`
  fisso nei JSON del Task 2;
- restano outlier isolati sul `run` max (visto 7266 us) → `SCHED_OTHER` su CPU non
  isolate, se ne occupa il task 0.4;
- **randomizzare/alternare l'ordine dei run** (A/B/A/B, non tutti gli A poi tutti i B), così
  la deriva termica lungo la campagna colpisce entrambi i bracci invece di diventare un
  bias sistematico su uno solo.

## Checklist post-reboot (lo stato di piattaforma NON è persistente)

Dopo ogni riavvio, prima di qualunque misura:

```bash
# 1. frequenza fissa (le scritture MSR non sopravvivono al reboot)
sudo apt install -y msr-tools          # solo la prima volta dopo un'installazione pulita
sudo ./scripts/utils_isolation/pin_cpu_freq.sh fix 0
sudo ./scripts/utils_isolation/pin_cpu_freq.sh status   # atteso: CpbDis=1, tutti P0, ~2300 MHz

# 2. isolamento CPU (il cpuset non sopravvive al reboot)
sudo ./scripts/utils_isolation/isolate_cpus.sh 2,3
sudo cset shield                        # stato
# ... esperimenti con: sudo cset shield --exec -- <comando>
sudo ./scripts/utils_isolation/reset_isolation.sh
```

**Modifica GRUB in corso (2026-08-27)**: l'utente ha modificato a mano
`/etc/default/grub` e lanciato `update-grub`, per mitigare i 26 kthread per-CPU e i 2 IRQ
NVMe non spostabili trovati nel task 0.4. Al primo boot successivo **verificare**:

```bash
cat /proc/cmdline
cat /sys/devices/system/cpu/nohz_full        # atteso: 2-3 (se nohz_full=2,3)
cat /sys/devices/system/cpu/isolated         # atteso: 2-3 (solo se c'e' isolcpus=)
cat /sys/devices/virtual/workqueue/cpumask   # atteso: f3 invece di ff (solo con isolcpus=)
cat /proc/irq/54/smp_affinity_list           # atteso: non piu' 2 (solo con isolcpus=managed_irq)
```

Attenzione a tre punti già verificati nel task 0.4 e nella discussione successiva:
- i kthread per-CPU (`migration/N`, `ksoftirqd/N`, `ktimers/N`, `rcuc/N`, `cpuhp/N`,
  `irq_work/N`, `kworker/N:*`) **continueranno a esistere**: sono per-CPU per costruzione e
  nessun parametro di boot li rimuove. L'isolamento cambia *quanto* girano, non *se* esistono;
- l'unica leva contro gli IRQ managed NVMe (`irq 54 → nvme0q3`, `irq 55 → nvme0q4`, che a
  runtime rifiutano la riassegnazione con EPERM) è `isolcpus=managed_irq,...`;
- `nohz_full` ferma il tick solo quando c'è **un solo task runnable**: il thread di rt-app
  dorme 8 ms su 10, quindi il beneficio su questo workload va misurato, non assunto.

Baseline con cui confrontare il dopo-reboot (task 0.4, shield attivo, senza parametri di
boot): jitter `period max − p50` = **51-180 us** a macchina idle, **130-186 us** sotto
rumore, 495 loop su 500, run medio 2008-2013 us su 2000 nominali.

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
  Stato: **FATTO**. Binario in `rt-app/src/rt-app`, config in `0-explore/0.1/cfg_single.json`,
  log del run in `0-explore/0.1/rtapp-thread0-0.log` (454 righe, 4.978 s coperti) e stdout in
  `0-explore/0.1/run_stdout.log`. Per arrivarci sono serviti 3 fix di setup, tutti fuori dai
  file del docente:
  (a) lo scaffolding autotools era stato estratto nella radice del progetto invece che in
      `rt-app/` — spostati `Makefile.am`, `autogen.sh`, `README.in`, `COPYING.in`, `libdl/`,
      `doc/` dentro `rt-app/`;
  (b) `AC_INIT` usa `m4_esyscmd_s([git describe --tags HEAD])`, che falliva su un repo senza
      tag → creato il tag locale `rtapp-doe-0.1`;
  (c) link error `undefined reference to sched_setattr(int, sched_attr const*, unsigned int)`:
      `libdl/dl_syscalls.c` è compilato come C e esporta il simbolo non-mangled, ma
      `dl_syscalls.h` non aveva le guardie `extern "C"` → aggiunte (solo attorno ai 2
      prototipi).
  Nota su `otel-installdir`: `src/Makefile.am` linka `-lopentelemetry_exporter_ostream_span_builder`,
  target che **non esiste** in opentelemetry-cpp fino alla v1.23.0 e compare solo da **v1.24.0**;
  installata quindi la **v1.28.0** (`-DWITH_ZIPKIN=ON -DBUILD_TESTING=OFF -DWITH_EXAMPLES=OFF
  -DCMAKE_CXX_STANDARD=17`), lib statiche in `otel-installdir/lib/`.
  Finding utile per il DoE: `"calibration": "CPU0"` invoca `calibrate_cpu_cycles()`, che in
  `calibrate_cpu_cycles_1()` fa `clock_nanosleep` di **1 s per tentativo** fino a convergenza →
  ~10-14 s di startup non deterministico per run (misurati: 11.1 s wall per `duration:1`,
  19.1 s per `duration:5`). `rt-app_parse_config.cpp:1238` accetta `"calibration": <int>` (pLoad
  in ns, senza virgolette) che salta del tutto la calibrazione: qui pLoad misurato = 18 ns.

- [x] **0.2** — Ricompilare con `RTAPP_TRACE_LEVEL=1` e `RTAPP_SAMPLER_TYPE=0` (AlwaysOn),
  stesso task set di 0.1, con l'exporter Zipkin attivo (quello di default). Obiettivo:
  osservare cosa cambia nell'esecuzione (log, eventuale output/errore se non c'è un
  collector Zipkin in ascolto) — capire se serve un collector attivo o se OTel fallisce
  silenziosamente in sua assenza.
  Stato: **FATTO**. `make clean && make CPPFLAGS="-DRTAPP_TRACE_LEVEL=1 -DRTAPP_SAMPLER_TYPE=0"`,
  binari salvati in `bin/rt-app_T0` e `bin/rt-app_T1_S0`. Run e analisi in `0-explore/0.2/`
  (`NOTES.md`, `run_stderr.log`, `run2_stderr_ts.log`, `rtapp-thread0-0.log`). Risultati:
  (a) il binario passa da 1.99 MB a 5.31 MB (OTel+libcurl linkati staticamente);
  (b) **OTel non fallisce in silenzio ma nemmeno in modo bloccante**: senza collector su
      `localhost:9411` (endpoint di default hardcoded in `zipkin_exporter_options.h:22`)
      stampa su stderr `ZIPKIN EXPORTER: Connection failed`, una riga per tentativo di
      export, non ritenta, non bufferizza, e rt-app esce comunque con **status 0** → il
      conteggio degli span non può basarsi sull'exit code, serve il collector o l'exporter
      ostream (task 0.3 / Task 3);
  (c) con stderr timestampato si vede che i tentativi cadono a ~10 s (tick del
      BatchSpanProcessor, `schedule_delay_millis = 5000`, con in coda lo span `calibration`)
      e allo shutdown (span `thread0-0` + `main`). A livello 1 gli span sono solo **3** in
      totale, nessun lavoro OTel dentro il loop periodico;
  (d) confronto timing 0.1 vs 0.2 (dati rivisti il 2026-08-27, ricalcolati sui log
      effettivamente presenti; colonne in **us**): entrambi i run hanno `perf=111` → stesso
      pLoad=18 ns e stesso lavoro nominale per fase, ma run medio 2887 vs 2572 us (+12 % di
      rumore) e massimi ~2x la media in entrambi → con n=1 e CPU non isolate **non si può
      concludere nulla sull'overhead**. Il pLoad misura lo stato della macchina, non il
      binario: 12 run alternati dei due binari danno 18-21 ns in entrambi i casi, mentre con
      8 busy-loop in background sale a 58-63 ns. Cause: euristica di convergenza che esce al
      primo 2 % di accordo con `clock_nanosleep(1 s)` tra i burst (`calibrate_cpu_cycles_1`,
      rt-app.cpp:451-486) e `min(calib1, calib2)` che premia lo stato in boost. Conferma che
      servono le 10-30 ripetizioni + task 0.4 + `"calibration": <int>` fisso.
      **Attenzione**: rt-app sovrascrive `<log_basename>-<task>-<idx>.log` nella cwd senza
      avvisare — un run non registrato ha già distrutto il log originale di 0.2; `run_doe.sh`
      deve dare a ogni ripetizione una cartella propria.
  **Finding da riprendere ai Task 4-6**: `BatchSpanProcessor` esporta su un thread proprio
  (`batch_span_processor.h:193`, `std::thread worker_thread_`) creato con scheduling di
  default → **SCHED_OTHER**. Quindi l'export non blocca il thread periodico, ma con task HI
  in SCHED_FIFO che saturano una CPU isolata il worker OTel è il primo a essere starvato:
  si perderebbero proprio gli span dei task critici — l'opposto della prioritizzazione che
  la traccia chiede di valutare.

- [x] **0.3** — Aggiungere temporaneamente una chiamata a mano a `InitTracer()` (ostream)
  al posto di `InitTracerZipkin()` in `main()`, ricompilare, rilanciare lo stesso task
  singolo. Obiettivo: vedere per la prima volta uno span stampato a video e capirne la
  struttura (nome, trace_id, span_id, attributi) — SENZA ancora introdurre la macro
  `RTAPP_EXPORTER_TYPE` del Task 3 (quella è la versione "pulita" da fare dopo, questo è
  solo per guardare l'output).
  Stato: **FATTO**. Modificata solo `rt-app.cpp:1976` (`InitTracerZipkin()` → `InitTracer()`),
  ricompilato, eseguito, **sorgente ripristinato e ricompilato**. Binario ostream conservato
  in `bin/rt-app_T1_S0_ostream`. Output e analisi in `0-explore/0.3/` (`NOTES.md`,
  `run_stdout.log` con i 3 span, `run2_ts.log` con timestamp). Findings:
  (a) **l'ipotesi centrale del progetto è confermata**: i 3 span (`main`, `calibration`,
      `thread0-0`) condividono lo stesso `trace_id` (`9a7fad0c…`), perché ogni thread nasce
      con `span_opts.parent = main_span->GetContext()`. Con `TraceIdRatioBasedSampler` la
      decisione è funzione del solo trace_id → o si campiona tutta l'esecuzione o niente,
      nessun ratio può separare HI da LO. Da quantificare al Blocco 2 del DoE;
  (b) **vincolo forte per il Task 6**: `ShouldSample` (`sdk/trace/sampler.h:98`) riceve
      `name` + solo gli attributi passati **dentro** `StartSpan`. rt-app non ne passa
      (riga 1464) e mette `config.sched_data.policy`/`.priority` con `SetAttribute` alle
      righe 1470-1496, cioè **dopo** la decisione di campionamento. Quindi il sampler custom
      deve decidere sul **nome dello span** (= nome del task nel JSON) → nel Task 2 nominare
      i task con prefisso convenzionale `hi_*` / `lo_*`, così il Task 6 non deve toccare il
      codice del docente;
  (c) l'exporter ostream scrive gli span su **stdout** mentre il log nativo di rt-app resta
      su **stderr**: separabili con redirezione, quindi `grep -c` su stdout è il metodo per
      contare gli span esportati nel Blocco 2 (risolve il problema di 0.2, dove l'exit
      status 0 non diceva nulla). Conferma che il Task 3 serve;
  (d) con 3 soli span di lunga durata l'export è di fatto un evento di **shutdown**: nel run
      timestampato tutti e tre escono insieme a +10.194 s perché lo span `calibration` ha
      chiuso a 5.186 s, appena dopo il tick a 5 s del BatchSpanProcessor;
  (e) il pin di frequenza rende deterministico il *valore* di pLoad (29 ns in entrambi i run)
      ma **non il tempo** per calcolarlo (span `calibration`: 4.039 s vs 5.172 s) → serve
      comunque `"calibration": 29` fisso.
  Trappole di setup incontrate: `strings` **non** distingue il binario Zipkin da quello
  ostream (entrambe le funzioni sono compilate in ogni caso) → serve una verifica funzionale;
  e `mv` del file di backup ripristina un mtime vecchio, quindi `make` non ricompila → serve
  `touch src/rt-app.cpp`.

- [x] **0.4** — Provare `sudo scripts/utils_isolation/isolate_cpus.sh 2,3` e verificare a
  mano (es. `cat /proc/irq/*/smp_affinity_list`, `taskset -c 2 ...`) che l'isolamento
  abbia effetto reale, poi `reset_isolation.sh`. Obiettivo: capire cosa fa lo script prima
  di fidarsene dentro il DoE automatizzato.
  Stato: **FATTO**. Analisi, misure e uso operativo in `0-explore/0.4/NOTES.md`
  (+ `results.txt`, `logs/`). Sistema lasciato pulito (shield rimosso, IRQ ripristinati,
  cpuset restituito a cgroup v2); il pin di frequenza resta attivo.
  (a) **Lo shield funziona, e bene.** 3 ripetizioni per condizione, `"calibration": 29`,
      1 thread SCHED_OTHER 2000/8000 us. Jitter (`period max − p50`): fuori 1420-2418 us,
      **dentro 51-180 us** (~15x meglio); loop completati 479-483 → **495** su 500 teorici;
      `run` medio da +12/+16 % a **+0.6 %** sui 2000 us richiesti. Con 8 busy-loop sulle CPU
      non isolate, fuori il periodo mediano sale a 14085 us con picchi a 24 ms e un terzo
      dei loop persi, **dentro i numeri restano identici al caso idle** → il confine del
      cpuset regge;
  (b) `cset` 1.6 è uno strumento **cgroup v1** e il sistema è cgroup v2 puro, ma funziona
      lo stesso: monta una gerarchia v1 in `/cpusets`. Effetto collaterale: il controller
      `cpuset` sparisce da `/sys/fs/cgroup/cgroup.controllers` finché resta montata;
  (c) **3 bug corretti in `isolate_cpus.sh`** (originali salvati in `*.sh.orig`): usava
      `nproc`, che è *affinity-aware* → a shield attivo tornava 6 invece di 8 e calcolava
      `NON_ISO='0,1,4,5'` invece di `0,1,4,5,6,7`; `grep -vFf` senza `-x` fa match di
      **sottostringa** (isolando la CPU 1 con ≥10 CPU escluderebbe anche 10-19); con la
      sintassi a intervallo `2-3` (accettata da cset) nessun pattern faceva match e le CPU
      isolate restavano in `NON_ISO` → **gli IRQ non venivano spostati affatto, in
      silenzio**. Ora `nproc --all`, `grep -vxFf` e una `expand_cpus()` che normalizza;
  (d) `reset_isolation.sh` **non ripristinava le affinità IRQ** (restavano cambiate fino al
      reboot): ora `isolate_cpus.sh` le salva in `/var/tmp/rtapp-isolation/irq_affinity.bak`
      e il reset le rimette (28 ripristinate) e smonta `/cpusets`;
  (e) **Cosa resta non isolabile**: 2 IRQ *managed* del driver NVMe (`irq 54 → nvme0q3` su
      CPU 2, `irq 55 → nvme0q4` su CPU 3; scrittura rifiutata con EPERM, 11 rifiuti su 39) e
      26 kernel thread per-CPU (`migration/N`, `ktimers/N`, `ksoftirqd/N`, `rcuc/N`,
      `irq_work/N`, `cpuhp/N`, `backlog_napi/N`, `kworker/N:*`, più `irq/25-AMD-Vi`).
      A 10 ms con SCHED_OTHER non si vedono, **ma vanno riverificati ai Task 4-6 con task HI
      in SCHED_FIFO**: `ktimers/N`, `ksoftirqd/N` e `rcuc/N` girano a priorità FIFO e possono
      preemptare un task critico. Contromisura se serve: `isolcpus=2,3 nohz_full=2,3
      rcu_nocbs=2,3` sulla cmdline GRUB + reboot;
  (f) note operative: `cset shield --status` **non esiste** (usare `cset shield` nudo o
      `cset set -l`); i processi lanciati con `cset shield --exec` girano come **root**,
      quindi i log di rt-app risultano di proprietà di root → da gestire in `run_doe.sh`.

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
  RTAPP_SRC_DIR/BIN_CACHE/DOE_ROOT in cima allo script, **applicare `pin_cpu_freq.sh fix 0`**
  (non sopravvive al reboot, vedi "Setup di determinismo della piattaforma"), isolare le CPU,
  lanciare block1/block2/block3 (uno alla volta, su richiesta esplicita — non tutti insieme).
  Lo script deve dare a ogni ripetizione una cartella propria (rt-app sovrascrive il log a
  nome fisso) e registrare MHz + Tctl per ogni run.
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
