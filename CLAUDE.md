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

## Stato del repository (leggere prima di toccare git)

Lavoro sul branch **`feat/setup-piattaforma-e-task-0x`**, pushato su
`origin` (`github.com/FabioAccurso/OTel-capabilities-for-mixed-criticality-workloads`).

**`origin/main` NON va merjato in questo branch, e questo branch non va merjato in main.**
Il progetto e' di due persone e i due membri hanno svolto gli stessi task 0.1/0.2 in
parallelo, con strutture di cartelle diverse. Decisione presa il 2026-08-27: **ognuno
prosegue sul proprio ramo, nessun merge**. Concretamente:

- `origin/main` contiene `a044566` (FabioAccurso, 2026-08-27), che ha la stessa
  riorganizzazione `rt-app-cpp/rt-app` -> `rt-app/` piu' i *suoi* task 0.1/0.2 in
  `0-exploration/task0.1/` e `0-exploration/task0.2/` (i nostri stanno in `0-explore/`);
- un merge darebbe conflitti add/add su `CLAUDE.md`, `.gitignore`, `gen_config.py`,
  `isolate_cpus.sh`, `reset_isolation.sh` e sui file di scaffolding (questi ultimi con
  contenuto **identico**, differisce solo il bit di permesso 755/644);
- sul suo ramo `rt-app/src/rt-app_types.h:60` ha una guardia
  `#if (RTAPP_TRACE_LEVEL > 0)` attorno all'include OTel, che **da noi non c'e'**;
- il suo `0-exploration/task0.2/B_fake_collector/fake_zipkin.py` e' un collector Zipkin
  finto che salva gli span in `spans.json`: risolve lo stesso problema del nostro exporter
  ostream (task 0.3) per un'altra strada. Da tenere presente come alternativa al Task 3,
  non da importare.

Non proporre merge, rebase o cherry-pick da `origin/main` senza che l'utente lo chieda.

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

## Topologia SMT: HI e LO devono stare su core FISICI diversi

Il Ryzen 7 3700U ha **4 core fisici e 8 thread SMT**, appaiati consecutivamente:

```
cpu0,1 -> core 0    cpu2,3 -> core 1    cpu4,5 -> core 2    cpu6,7 -> core 3
```

Tutti e 4 i core condividono la stessa L3 (`shared_cpu_list = 0-7`, un solo CCX), quindi
*quali* due core si scelgono e' indifferente; conta solo che siano due core **interi**.

Due conseguenze, entrambe gia' applicate agli script:

1. **`gen_config.py` aveva `--hi-cpu 2 --lo-cpus 3`**, cioe' HI e LO sui due thread SMT
   dello stesso core. I due si contendono unita' di esecuzione, L1 e L2: l'interferenza
   misurata sarebbe stata in buona parte contesa hardware, non scheduling ne' telemetria —
   esattamente l'effetto che l'elaborato deve isolare. Default ora **`--lo-cpus 6`**, e
   `warn_if_smt_shared()` avvisa su stderr se HI e LO ricadono sullo stesso core.
2. **Non isolare mai una CPU lasciando fuori il suo sibling** (es. `isolcpus=2,4`): il
   carico di sistema sul sibling ruba risorse alla CPU "isolata", che quindi lo e' solo
   sulla carta. `isolate_cpus.sh` ora ha un controllo di topologia che lo segnala, e il
   suo default e' passato da `2,3` a **`2,3,6,7`**.

Assegnazione prevista per il DoE: **HI su cpu2** (core 1), **LO su cpu6** (core 3). I
sibling cpu3 e cpu7 restano liberi dentro lo shield ed e' li' che puo' finire il worker
`SCHED_OTHER` del `BatchSpanProcessor` (vedi il finding del task 0.2) — placement da
controllare esplicitamente ai Task 4-6.

Prezzo pagato: l'housekeeping scende a 2 core fisici (cpu 0,1,4,5) per desktop, IRQ,
workqueue e i callback RCU offloaded da 4 CPU. Sul 15 W si sente nell'uso quotidiano, non
nei run a desktop scarico.

## Checklist post-reboot (lo stato di piattaforma NON è persistente)

Dopo ogni riavvio, prima di qualunque misura:

```bash
# 1. frequenza fissa (le scritture MSR non sopravvivono al reboot)
sudo apt install -y msr-tools          # solo la prima volta dopo un'installazione pulita
sudo ./scripts/utils_isolation/pin_cpu_freq.sh fix 0
sudo ./scripts/utils_isolation/pin_cpu_freq.sh status   # atteso: CpbDis=1, tutti P0, ~2300 MHz

# 2. isolamento CPU (il cpuset non sopravvive al reboot)
sudo ./scripts/utils_isolation/isolate_cpus.sh 2,3,6,7   # core fisici 1 e 3 interi
sudo cset shield                        # stato
# ... esperimenti con: sudo cset shield --exec -- <comando>
sudo ./scripts/utils_isolation/reset_isolation.sh
```

**Parametri di boot.** La riga in `/etc/default/grub` e' ora:

```
isolcpus=managed_irq,domain,2,3,6,7  nohz_full=2,3,6,7  rcu_nocbs=2,3,6,7  irqaffinity=0,1,4,5
```

Aggiornata in `/etc/default/grub` + `update-grub` il 2026-08-27 (estensione a 6,7 e aggiunta
di `irqaffinity`) e **in vigore dal reboot dello stesso giorno**. Attenzione: le misure in
`0-explore/0.4-post-boot/` sono state prese con la cmdline *precedente* (sole 2,3, senza
`irqaffinity`), quindi restano una baseline valida ma di un'altra configurazione.

Verifica eseguita e **superata** su questa cmdline (2026-08-27, dopo reboot):

```bash
cat /proc/cmdline
cat /sys/devices/system/cpu/nohz_full        # atteso: 2-3,6-7
cat /sys/devices/system/cpu/isolated         # atteso: 2-3,6-7
cat /sys/devices/virtual/workqueue/cpumask   # atteso: 33 (= 0,1,4,5)
cat /proc/irq/default_smp_affinity           # atteso: 33 — era ff con il solo isolcpus=
grep -E "^\s*(54|55|58|59):" /proc/interrupts  # code NVMe: contatori a ZERO su tutte le CPU
```

Esito: `isolated` e `nohz_full` = `2-3,6-7`; `workqueue/cpumask` e
`default_smp_affinity` entrambi a `33`. **`irqaffinity=` funziona**: `i8042` (irq 1),
`xhci_hcd` (39), `snd_hda` (66) e `amdgpu` (67) nascono affini a `0-1,4-5` e hanno
**zero conteggi** su 2,3,6,7 gia' prima di lanciare `isolate_cpus.sh` — il buco descritto
sotto e' chiuso al boot. Le code NVMe managed che ricadrebbero sulle CPU isolate (q3, q4,
q7, q8) sono tutte a zero; il traffico passa da q1, q2, q5, q6.

Lo script a runtime resta comunque utile come rete di sicurezza per gli IRQ che un driver
riassegni **dopo** l'allocazione, scavalcando la maschera di default.

**Correzione a un'attesa sbagliata annotata qui in precedenza**: `isolcpus=managed_irq`
**non** cambia `/proc/irq/54/smp_affinity_list`, che resta `2`. Gli IRQ managed restano
affini alla loro CPU; `managed_irq` agisce sul lato *submit* (blk-mq non usa le code il cui
IRQ punta a una CPU isolata) e il risultato e' che la coda non spara mai. La verifica
giusta e' quindi il **contatore in `/proc/interrupts`**, non l'affinity.

Tre punti da tenere presenti:
- i kthread per-CPU (`migration/N`, `ksoftirqd/N`, `ktimers/N`, `rcuc/N`, `cpuhp/N`,
  `irq_work/N`, `kworker/N:*`) **continuano a esistere**: sono per-CPU per costruzione e
  nessun parametro di boot li rimuove. L'isolamento cambia *quanto* girano, non *se* esistono;
- **i parametri di boot non sostituiscono `isolate_cpus.sh`, lo completano**: `managed_irq`
  copre solo gli IRQ managed, mentre `amdgpu` (irq 67), `xhci_hcd` (39), `i8042` (1) e
  `snd_hda_intel` (66) continuano a finire su 2,3 finche' lo script non ne riscrive
  `smp_affinity` a runtime;
- `nohz_full` **serve, ed e' stato misurato** (non piu' un'assunzione): delta di `LOC` in
  5 s di run dentro lo shield = **106 tick su CPU2** (dove gira rt-app con 497 wakeup) e
  **2 su CPU3**, contro 5000 di tick pieno a `CONFIG_HZ=1000` e 623-1216 sulle CPU
  housekeeping. Nello stesso run `CAL`=1 e `IWI`=6 su CPU2.

### Baseline di riferimento (shield attivo, `SCHED_OTHER` 2000/8000 us, 5 s, 3 rip.)

| metrica, idle DENTRO lo shield | pre-boot | post-boot |
|---|---|---|
| loop completati /500 | 495 | **497** |
| run_med (us) | 2012-2013 | 1984-1985 |
| run_max (us) | 2057-2183 | **2016-2020** |
| period p99 (us) | 10115-10122 | **10086-10089** |
| period max (us) | 10133-10261 | **10099-10117** |
| jitter `max - p50` (us) | 51-180 | **47-63** |

I parametri di boot valgono **~30 us su p99 e ~150 us sul `run` peggiore**: poco in valore
assoluto, ma `run_max`/`p99`/`period max` danno insiemi disgiunti e i loop passano da 495
(6 rip. su 6) a 497 (6 su 6). Il guadagno vero e' sulla **riproducibilita'**: il jitter
passa da un range 51-180 a 47-63, quindi meno varianza dello stimatore e meno ripetizioni
necessarie nel Task 4. Sotto rumore, dentro lo shield: 497 loop, jitter 34-65 us.

**Nota per il Task 2**: `run_med` post-boot e' 1984 us contro 2000 nominali, perche'
`"calibration": 29` e' fisso e i 2012 us pre-boot contenevano ~28 us di interferenza ora
sparita. Il costo per iterazione pulito e' ~28.8 ns: o si accetta il -0.8 % sistematico o
si ritara la costante.

Dati completi in `0-explore/0.4-post-boot/` (`NOTES.md`, `results.txt`, `logs/`,
`metadata.txt` con MHz e Tctl per ogni run). Deriva termica sulla campagna (~3 min):
nessun throttling, 2296 MHz inchiodati, Tctl 51 -> 61 C sotto rumore.

**Attenzione: questa tabella descrive una piattaforma che non esiste piu'.** Entrambe le
colonne sono state misurate con la cmdline a sole 2,3 e senza `irqaffinity`, e con un solo
thread `SCHED_OTHER`. Va rifatta prima del Task 4 (vedi sotto).

### Perche' NON conviene limitarsi a rieseguire la batteria 0.4 (deciso il 2026-08-27)

Nella campagna `0.4-post-boot` lo shield era attivo, e `isolate_cpus.sh` aveva gia' scritto
`0,1,4,5,6,7` su tutte le `smp_affinity_list`: `amdgpu`, `xhci_hcd` e `snd_hda` erano
**gia' fuori** dalle CPU isolate durante i run misurati. `irqaffinity=` quindi non migliora
la finestra di misura — chiude quella *prima* dello shield e fa nascere su housekeeping gli
IRQ allocati a caldo (es. una periferica USB collegata dopo). E' robustezza, non latenza.
L'altra novita', cpu6,7 isolate, non tocca la CPU su cui girava rt-app (cpu2). Rifare gli
stessi 12 run misurerebbe un delta atteso sotto il rumore.

**Quello che invece non e' mai stato misurato**, e che blocca i task successivi:

1. **`SCHED_FIFO`.** Ogni conclusione del task 0.4 porta la clausola "da riverificare con
   task HI in SCHED_FIFO". `ktimers/N`, `ksoftirqd/N` e `rcuc/N` girano a priorita' FIFO e
   possono preemptare un task critico; a `SCHED_OTHER` con 8 ms di sleep su 10 non si
   vedono. E' il numero che conta di piu' per l'elaborato ed e' ignoto.
2. **La topologia HI su cpu2 / LO su cpu6** non e' mai stata eseguita, nemmeno una volta.
3. **`"calibration": 29` contro i ~28.8 ns misurati** (vedi la nota per il Task 2 sopra).

Piano concordato: prima il **task 0.5** (che per costruzione e' il primo run con HI in
`SCHED_FIFO` su cpu2 e le istanze LO su cpu6), poi una **baseline nuova sulla cmdline
attuale con un braccio `SCHED_FIFO` accanto a quello `SCHED_OTHER`**, da fare prima del
Task 4.

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
      preemptare un task critico. Contromisura **già applicata** il 2026-08-27
      (`isolcpus=managed_irq,domain,2,3 nohz_full=2,3 rcu_nocbs=2,3` + reboot): batteria
      rimisurata in `0-explore/0.4-post-boot/`, vedi la tabella di baseline sopra;
  (f) note operative: `cset shield --status` **non esiste** (usare `cset shield` nudo o
      `cset set -l`); i processi lanciati con `cset shield --exec` girano come **root**,
      quindi i log di rt-app risultano di proprietà di root → da gestire in `run_doe.sh`.

- [x] **0.5** — Generare a mano una config con `gen_config.py --n-lo 4` e lanciarla UNA
  volta con `test.sh` (non `run_doe.sh`), ispezionando manualmente la cartella di output.
  Obiettivo: capire la struttura di un run prima di lanciarne centinaia in automatico.
  Stato: **FATTO**. Config in `0-explore/0.5/cfg_n4.json`, run in `0-explore/0.5/run1/`,
  analisi in `0-explore/0.5/NOTES.md`.
  (a) **Struttura di un run**: `test.sh` non esegue la config originale — la rilegge, ci
      riscrive `global.logdir` sulla cartella del run e salva `<run_dir>/config.json`, che
      e' quella eseguita. Ogni run e' quindi autocontenuto e la config usata resta accanto
      ai dati (risolve la sovrascrittura del log a nome fisso vista al task 0.2). Dentro:
      `config.json`, **un log per thread** `rtapp-<task>-<istanza>.log` (5 file con
      `--n-lo 4`), `stdout.log`, `stderr.log`. Pesi: HI 246 KB, ogni LO ~1.18 MB → il Task 4
      con 30 ripetizioni produrra' qualche GB;
  (b) **i log sono di proprieta' di root**, il resto della cartella no, perche'
      `cset shield --exec` esegue come root → `run_doe.sh` deve fare `chown` a fine run;
  (c) **trappola in `test.sh:32`**: invoca `sudo` dando per scontato un terminale. Senza tty
      fallisce in 0.15 s **dopo** aver creato la cartella e due file vuoti — sembra un run
      riuscito e vuoto. Aggirato con `SUDO_ASKPASS`. `run_doe.sh` deve gestirlo e comunque
      **verificare che il log esista e non sia vuoto** prima di contare il run come valido;
  (d) **prima misura di sempre con `SCHED_FIFO`, e risponde alla domanda aperta del task
      0.4**: HI a FIFO prio 90 su cpu2 da jitter **37 us**, cioe' *meglio* del baseline
      `SCHED_OTHER` (47-63 us), con `run_max - run_med` = 33 us. I kthread RT per-CPU
      (`ktimers/N`, `ksoftirqd/N`, `rcuc/N`) **non si vedono**. n=1, quindi indizio forte e
      non prova: da confermare con ripetizioni;
  (e) le 4 istanze LO saturano cpu6 per costruzione (200 % di richiesta): 9500 loop su
      20000 e periodo mediano 2093 us invece di 1000. **HI resta indisturbato** — conferma
      sul campo che HI e LO su core fisici diversi funziona;
  (f) **pinning verificato a runtime** (`/proc/<pid>/task/*/status`): `HI_task-0`
      `Cpus_allowed_list = 2`, i 4 `LO_noise` `= 6`, il thread main `= 2-3,6-7`. Quindi il
      worker `SCHED_OTHER` del `BatchSpanProcessor` ereditera' `2-3,6-7` e potra' girare sui
      sibling liberi cpu3/cpu7: **placement da decidere esplicitamente ai Task 4-6**;
  (g) **`"calibration": "CPU0"` non fa quello che dice.** In `rt-app.cpp:2071-2082` la
      `sched_setaffinity` verso la sola CPU0 **non ha il controllo del valore di ritorno**:
      dentro un cpuset che non contiene la CPU 0 fallisce, la calibrazione avviene sulla CPU
      corrente e il log stampa comunque `calib_cpu 0`. Misurato: 28 ns dentro lo shield,
      29 ns fuori. Inoltre costa **~8 s** non deterministici (28.3 s totali per
      `duration: 20`);
  (h) **il `deadline_miss_ratio` del Task 5 sarebbe stato sempre 0, per costruzione.**
      `analyze_doe.py:62` conta le righe con `slack < 0`, ma `rt-app.cpp:727-746` calcola lo
      `slack` **solo** dentro `case rtapp_timer:`. Le config di `gen_config.py` usano
      `"sleep": 8000` (evento `rtapp_sleep`, `clock_nanosleep` relativa dopo il `run`):
      niente `t_next`, niente slack. Verificato: `slack = 0` su tutte le 1981 righe di HI e
      tutte le 9516 di LO. Vedi il rimedio verificato in `0-explore/0.5/NOTES.md`.

- [x] **0.6** — Scegliere la costante di calibrazione prima del Task 2. `loadwait()` fa
  `load_count = run * 1000 / p_load`, quindi il pLoad decide quante iterazioni girano per la
  stessa `"run": 2000`: **1 ns di differenza sposta il lavoro reale del 3.5 %**, piu'
  dell'overhead di OTel che il progetto deve misurare. Mai `"CPU0"`: fa partire
  l'auto-calibrazione, che costa ~8 s non deterministici e dentro un cpuset senza la CPU 0
  calibra altrove senza dirlo (finding (g) del task 0.5).
  Stato: **FATTO. Scelto `"calibration": 29`**, applicato come default in `gen_config.py`
  (nuova opzione `--calibration`, sovrascrivibile). Motivazione: due campagne indipendenti
  danno lo stesso costo sottostante.

  | campagna | pLoad usato | load_count | run misurato | ns/iterazione |
  |---|---|---|---|---|
  | task 0.5 | 28 (auto) | 71428 | 2054 us | **28.756** |
  | task 0.4-post-boot | 29 (fisso) | 68965 | 1984 us | **28.768** |

  Il costo reale e' quindi ~28.76 ns. Il parser accetta **solo interi**
  (`rt-app_parse_config.cpp:1237`: un float finisce nel ramo `sscanf("CPU%d")` e provoca
  `EXIT_INV_CONFIG`), percio' la scelta e' fra 28 e 29:

  | | iterazioni | run risultante | errore sui 2000 nominali |
  |---|---|---|---|
  | `calibration: 28` | 71428 | 2054.3 us | +2.71 % |
  | `calibration: 29` | 68965 | 1983.4 us | **-0.83 %** |

  29 e' ~3x piu' vicino al nominale e **mantiene confrontabili** le tabelle di baseline di
  `0-explore/0.4/` e `0-explore/0.4-post-boot/`, prese proprio con 29. Da non confondere:
  28 e' il valore che l'*auto*-calibrazione produce quando gira sulla CPU isolata invece che
  su CPU0 — e' un fatto su *dove* calibra, non su quale intero approssimi meglio il costo.
  Per l'overhead di OTel conta comunque soprattutto che la costante sia **fissa e identica
  in tutti i bracci**.

## Task 1.x-5.x — verso il deliverable finale

- [ ] **Task 1** — Build completa: `autogen.sh && ./configure && make` in `rt-app/`;
  compilare `otel-installdir/` se assente (cmake -DWITH_ZIPKIN=ON -DBUILD_TESTING=OFF
  -DCMAKE_INSTALL_PREFIX=.../otel-installdir). Pacchetti apt: autoconf autoconf-archive
  automake libtool libcurl4-openssl-dev libnuma-dev libjson-c-dev cpuset cmake
  (`libjson-c-dev` obbligatorio, `configure` fallisce senza).
  Stato:

- [ ] **Task 2** — Scrivere le config JSON definitive per il DoE (HI su SCHED_FIFO,
  LO_noise repliche via `instance`), verificandole con `gen_config.py`.
  **Due correzioni obbligatorie emerse dal task 0.5**, entrambe da applicare a
  `gen_config.py`:
  1. **`"sleep"` → evento `timer`**, altrimenti lo `slack` resta 0 e il
     `deadline_miss_ratio` del Task 5 e' sempre 0 per costruzione (finding (h) del 0.5).
     Sintassi verificata (`rt-app_parse_config.cpp:587-618`), con il periodo **completo**:
     ```json
     "run": 2000,
     "timer": { "ref": "unique", "period": 10000, "mode": "absolute" }
     ```
     `mode: absolute` tiene la griglia di attivazione fissa, cosi' un'iterazione lunga erode
     lo slack invece di spostare le successive; `relative` (default) ri-ancora e perdona.
  2. **`"calibration"`**: gia' fatto — `gen_config.py` ora emette l'intero fisso **29**
     di default (task 0.6). Verificare solo che le config definitive non lo sovrascrivano.
  Nominare inoltre i task con prefisso `hi_*` / `lo_*` (finding (b) del task 0.3), cosi' il
  sampler custom del Task 6 puo' decidere sul nome dello span.
  Stato:

- [ ] **Task 3** — Introdurre una macro `RTAPP_EXPORTER_TYPE` (0=Zipkin default,
  1=ostream) e in `main()` sostituire la chiamata diretta a `InitTracerZipkin()` con un
  `#if RTAPP_EXPORTER_TYPE == 0 ... #else InitTracer() ... #endif`. Serve al Blocco 2 del
  DoE per contare a video gli span esportati.
  Stato:

- [ ] **Task 4** — Eseguire il DoE (`scripts/measurements/run_doe.sh`): editare
  RTAPP_SRC_DIR/BIN_CACHE/DOE_ROOT in cima allo script, **applicare `pin_cpu_freq.sh fix 0`**
  (non sopravvive al reboot, vedi "Setup di determinismo della piattaforma"), isolare le CPU
  con `isolate_cpus.sh 2,3,6,7`, lanciare block1/block2/block3 (uno alla volta, su richiesta
  esplicita — non tutti insieme). Lo script deve dare a ogni ripetizione una cartella propria
  (rt-app sovrascrive il log a nome fisso) e registrare MHz + Tctl per ogni run.
  **Prerequisito**: baseline rifatta sulla cmdline attuale con un braccio `SCHED_FIFO`
  (vedi "Perche' NON conviene limitarsi a rieseguire la batteria 0.4"). La tabella di
  baseline attuale e' di una configurazione di piattaforma precedente.
  Stato:

- [ ] **Task 5** — Analisi: `analyze_doe.py` → `2-DoE/results.csv` (deadline_miss_ratio,
  max_duration_us, period_jitter_std_us, hi/lo_spans_exported). Statistiche
  descrittive/confronti tra configurazioni.
  **Prerequisito**: le config del Task 2 devono usare l'evento `timer`, altrimenti
  `deadline_miss_ratio` e' 0.0 a prescindere (vedi finding (h) del task 0.5).
  **Da correggere in `analyze_doe.py`**: scartare la **prima iterazione**. Con il `timer`
  la prima riga ha sempre slack negativo (`t_next` inizializzato a `t_first`, prima
  attivazione gia' passata: misurato -2582 us), che e' un transitorio di avvio e non una
  deadline persa — su 300 iterazioni darebbe un `deadline_miss_ratio` fasullo dello 0.33 %.
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
