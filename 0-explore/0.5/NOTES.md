# Task 0.5 — un run singolo con gen_config.py + test.sh

Obiettivo: capire com'e' fatta la cartella di output di **un** run, prima di lanciarne
centinaia con `run_doe.sh` nel Task 4.

Piattaforma: cmdline `isolcpus=managed_irq,domain,2,3,6,7 nohz_full=2,3,6,7
rcu_nocbs=2,3,6,7 irqaffinity=0,1,4,5`, `pin_cpu_freq.sh fix 0` applicato,
shield su `2,3,6,7` (`system` = 0-1,4-5).

```bash
python3 scripts/measurements/gen_config.py --n-lo 4 --duration 20 --out 0-explore/0.5/cfg_n4.json
./scripts/measurements/test.sh 0-explore/0.5/run1 "$PWD/bin/rt-app_T0" 0-explore/0.5/cfg_n4.json
```

## Com'e' fatta una cartella di run

```
0-explore/0.5/run1/
├── config.json              copia della config, con logdir riscritto da test.sh
├── rtapp-HI_task-0.log      un log per THREAD, non per run: <basename>-<task>-<istanza>
├── rtapp-LO_noise-1.log     (qui committati .gz, vedi sotto)
├── rtapp-LO_noise-2.log
├── rtapp-LO_noise-3.log
├── rtapp-LO_noise-4.log
├── stdout.log               76 byte: solo il messaggio di cset
└── stderr.log               24 righe: il log operativo di rt-app
```

`test.sh` non passa la config originale a rt-app: la rilegge, ci riscrive
`global.logdir` = cartella del run e `log_basename` = `rtapp`, e salva il risultato in
`<run_dir>/config.json`. E' quella copia a essere eseguita. Due conseguenze buone: ogni run
e' autocontenuto, e la config effettivamente usata resta accanto ai dati. **Risolve il
problema visto al task 0.2**, dove rt-app sovrascriveva un log a nome fisso nella cwd.

Un log **per thread**: con `--n-lo 4` sono 5 file. Le colonne sono quelle gia' viste nel
task 0.1 (`idx perf run period start end rel_st slack c_duration c_period wu_lat`).
Dimensioni: HI 246 KB (1981 righe), ogni LO ~1.18 MB (~9500 righe). Con 30 ripetizioni x
piu' configurazioni il Task 4 produce facilmente qualche GB: da tenere presente.

Nel repo i 4 log LO sono committati **gzippati** (4.7 MB -> 570 KB): sono quattro istanze
identiche della stessa misura e la tabella qui sotto ne riassume il contenuto. Il log HI,
che e' quello interessante, resta in chiaro. Per rileggerli: `gunzip -k rtapp-LO_noise-*.gz`.

**I log sono di proprieta' di `root`**, il resto no:

```
-rw-rw-r-- benny:benny  config.json, stdout.log, stderr.log   <- creati da test.sh (utente)
-rw-r--r-- root:root    rtapp-*.log                            <- creati da rt-app (root)
```

perche' `cset shield --exec` esegue come root. Confermato il finding (f) del task 0.4.
`run_doe.sh` deve fare `chown` a fine run, altrimenti l'analisi gira su file non scrivibili.

## Trappola: `test.sh` chiama `sudo` senza askpass

Prima esecuzione fallita in 0.15 s, con la cartella gia' creata e i log vuoti:

```
sudo: è richiesto un terminale per leggere la password
```

`test.sh:32` invoca `sudo cset shield --exec` dando per scontato un terminale interattivo.
In un contesto non interattivo `set -euo pipefail` fa uscire lo script **dopo** aver creato
la cartella e i due file vuoti: sembra un run riuscito e vuoto. Aggirato con
`SUDO_ASKPASS=<script che stampa la password>` esportato nell'ambiente (sudo usa l'helper
da solo quando non c'e' un tty).

**Per il Task 4**: `run_doe.sh` deve o girare interamente come root, o usare `SUDO_ASKPASS`,
o pre-autenticare `sudo -v` — e in ogni caso **controllare che il log esista e non sia
vuoto** prima di contare il run come valido.

## Risultati: prima misura di sempre con SCHED_FIFO

| task | loop | attesi | run_med | run_max | per_p50 | per_p99 | per_max | jitter |
|---|---|---|---|---|---|---|---|---|
| HI_task-0 (FIFO 90, cpu2) | 1981 | 2000 | 2054 | 2087 | 10062 | 10094 | 10099 | **37** |
| LO_noise-1 (OTHER, cpu6) | 9516 | 20000 | 518 | 3991 | 2093 | 4192 | 5272 | 3179 |
| LO_noise-2 | 9496 | 20000 | 518 | 4320 | 2093 | 4196 | 5277 | 3184 |
| LO_noise-3 | 9484 | 20000 | 518 | 3981 | 2093 | 4192 | 5313 | 3220 |
| LO_noise-4 | 9501 | 20000 | 518 | 4240 | 2093 | 4207 | 5356 | 3263 |

1. **I kthread RT non si vedono.** Era la domanda lasciata aperta dal task 0.4: `ktimers/N`,
   `ksoftirqd/N` e `rcuc/N` girano a priorita' FIFO e potrebbero preemptare un task HI.
   Con HI a `SCHED_FIFO` prio 90 su cpu2 il jitter e' **37 us**, cioe' *meglio* del baseline
   `SCHED_OTHER` (47-63 us), e `run_max - run_med` = 33 us. Nessun segno di preemption.
   n=1, quindi e' un indizio forte, non una prova: va confermato con ripetizioni.
2. **Il carico LO e' saturo per costruzione, e non tocca HI.** 4 istanze da `run 500 /
   sleep 500` sulla sola cpu6 chiedono il 200 % di una CPU: infatti completano ~9500 loop
   su 20000 e il periodo mediano e' 2093 us invece di 1000. E' il comportamento voluto per
   il rumore best-effort. HI su cpu2 resta indisturbato — **core fisici diversi**, come
   deciso nella sezione SMT.

### Pinning verificato a runtime

Campionando `/proc/<pid>/task/*/status` durante il run:

| thread | Cpus_allowed_list | CPU |
|---|---|---|
| `rt-app_T0` (main) | 2-3,6-7 | 2 |
| `HI_task-0` | **2** | 2 |
| `LO_noise-1..4` | **6** | 6 |

Il thread main resta libero su tutto il cpuset. **Nota per i Task 4-6**: il worker
`SCHED_OTHER` del `BatchSpanProcessor` eredita l'affinita' del processo, quindi potra'
girare su 2,3,6,7 — in pratica sui sibling liberi cpu3 e cpu7. Va deciso esplicitamente
se lasciarlo li' o confinarlo altrove.

## `"calibration": "CPU0"` non fa quello che dice

`gen_config.py` genera `"calibration": "CPU0"`. Il codice (`rt-app.cpp:2071-2082`):

```c
CPU_ZERO(&calib_set);
CPU_SET(opts.calib_cpu, &calib_set);
sched_getaffinity(0, sizeof(cpu_set_t), &orig_set);
sched_setaffinity(0, sizeof(cpu_set_t), &calib_set);   /* valore di ritorno NON controllato */
p_load = calibrate_cpu_cycles(CLOCK_MONOTONIC);
sched_setaffinity(0, sizeof(cpu_set_t), &orig_set);
log_notice("pLoad = %dns : calib_cpu %d", p_load, opts.calib_cpu);
```

Dentro un cpuset che non contiene la CPU 0 la `sched_setaffinity` **fallisce**, l'errore non
viene controllato, la calibrazione avviene sulla CPU corrente (una delle isolate) e il log
stampa comunque `calib_cpu 0`. **Il messaggio e' fuorviante.** Misurato:

```
dentro lo shield (CPU0 irraggiungibile) : pLoad = 28ns : calib_cpu 0
fuori  dallo shield (CPU0 raggiungibile): pLoad = 29ns : calib_cpu 0
```

Qui la differenza e' piccola perche' la macchina e' scarica; a macchina carica la
calibrazione su CPU0 dava 58-63 ns (task 0.2). Il punto e' che **la CPU di calibrazione non
e' sotto controllo** e il log non permette di accorgersene.

### E cambia il lavoro davvero eseguito

`loadwait()` calcola `load_count = run * 1000 / p_load`, quindi il pLoad determina quante
iterazioni vengono eseguite per una stessa `"run": 2000`:

| | load_count | run_med misurato |
|---|---|---|
| pLoad = 28 (questo run, auto) | 71428 | 2054 us |
| pLoad = 29 (baseline 0.4, fisso) | 68965 | 1984 us |

rapporto atteso `29/28` = 1.0357, osservato `2054/1984` = **1.0353**. Il modello torna: una
differenza di 1 ns nella costante di calibrazione sposta il lavoro reale del **3.5 %**.

**Conseguenza diretta per il Task 2**: le config del DoE devono usare `"calibration": <int>`
fisso, non `"CPU0"`. Altrimenti due bracci dell'esperimento eseguono quantita' di lavoro
diverse e l'overhead di OTel finisce confuso con il rumore della calibrazione. Va anche
scelto il valore: 29 (baseline esistente) o 28 (misurato sulla CPU isolata dove il lavoro
gira davvero). **28 e' il numero piu' difendibile**, ma cambiarlo invalida il confronto con
le tabelle gia' raccolte.

Costo aggiuntivo: la calibrazione automatica ha aggiunto **~8 s** ai 20 s di durata
(28.3 s totali), non deterministici.

## Il `deadline_miss_ratio` del Task 5 e' strutturalmente sempre 0

Domanda nata leggendo la tabella: il task critico ha rispettato la deadline? La risposta
sul merito e' si' con ampio margine (2087 us di lavoro peggiore su un periodo di 10 000 →
utilizzazione 21 %, periodo mai oltre 10 099 us). Ma la domanda ha fatto emergere che
**la metrica che dovrebbe misurarlo non funziona**.

`analyze_doe.py:62`:

```python
"deadline_miss_ratio": sum(1 for s in slacks if s < 0) / len(slacks),
```

legge la colonna `slack` del log. In `rt-app.cpp:727-746` lo `slack` viene calcolato
**solo** dentro `case rtapp_timer:` / `case rtapp_timer_unique:`, come differenza fra
l'istante assoluto della prossima attivazione (`res.timer.t_next`) e adesso:

```c
rdata->res.timer.t_next = timespec_add(&rdata->res.timer.t_next, &t_period);
clock_gettime(CLOCK_MONOTONIC, &t_now);
t_slack = timespec_sub(&rdata->res.timer.t_next, &t_now);
ldata->slack = timespec_to_usec_long(&t_slack);
```

Le config di `gen_config.py` usano `"sleep": 8000`, cioe' un evento `rtapp_sleep`: una
`clock_nanosleep` **relativa** eseguita dopo il `run`. Nessun `t_next`, nessuno slack.
Verificato sui log del run:

```
HI_task-0    slack = 0 su tutte le 1981 righe
LO_noise-1   slack = 0 su tutte le 9516 righe
```

Quindi `deadline_miss_ratio` verrebbe **0.0 per costruzione**, non perche' le deadline sono
rispettate ma perche' il numero non viene mai calcolato. E' una metrica che non puo'
assumere un valore diverso da zero: se fosse arrivata cosi' al Task 5, la conclusione
"nessuna deadline persa in nessuna configurazione" sarebbe stata un artefatto.

### Secondo effetto: con `sleep` il task non e' davvero periodico

Con `sleep` il periodo e' `run + sleep + overhead`, quindi **eredita l'errore del run**.
E' esattamente il +62 us osservato: il `run` e' durato 2054 us invece di 2000 (pLoad 28),
2054 + 8000 + ~8 = 10062, che e' il `per_p50` misurato. Il task si auto-ritma invece di
inseguire una griglia fissa: un ritardo non viene recuperato, viene assorbito allungando il
periodo. Non c'e' proprio una deadline da mancare.

### Rimedio, verificato

Sostituire `"sleep"` con un evento `timer` (sintassi da `rt-app_parse_config.cpp:587-618`:
`ref`, `period`, `mode` fra `relative` — default — e `absolute`):

```json
"HI_task": {
  "policy": "SCHED_FIFO", "priority": 90, "cpus": [2], "loop": -1,
  "run": 2000,
  "timer": { "ref": "unique", "period": 10000, "mode": "absolute" }
}
```

Nota: il `period` del timer e' il periodo **completo** (10 000), non lo sleep (8 000),
perche' il timer aspetta fino al prossimo istante di attivazione assoluto.

Prova eseguita (3 s, `"calibration": 29`, FIFO 90 su cpu2):

```
#idx  perf   run  period        start          end   rel_st   slack  c_duration  c_period
   0    68  1985    1987   2362694275   2362696262    10757   -2582        2000     10000
   0    68  1985    7418   2362696268   2362703686    12751    5426        2000     10000
   0    68  1983    9998   2362703688   2362713686    20171    8008        2000     10000

300 righe: slack medio 7955 us, min -2582, max 8009, negativi 1
```

Tre cose cambiano rispetto al run con `sleep`:

1. **`slack` diventa un numero vero** (~7955 us di margine medio su 10 000 di periodo,
   coerente con i ~2000 us di lavoro) → `deadline_miss_ratio` diventa calcolabile;
2. **`c_period` passa da 0 a 10000**: rt-app ora sa qual e' il periodo nominale;
3. **il periodo si aggancia alla griglia**: 9998 us invece dei 10062 us derivati. Con
   `mode: absolute` un'iterazione lunga non sposta le successive, erode lo slack.

`mode`: in entrambi i modi lo slack viene calcolato, ma su un ritardo `relative` ri-ancora
`t_next` ad adesso (perdona lo scivolamento) mentre `absolute` tiene la griglia originale e
il ritardo si accumula. Per misurare deadline miss serve **`absolute`**.

### Trappola residua: la prima riga e' sempre un falso positivo

L'unico slack negativo dei 300 e' alla **prima iterazione** (-2582 us): `t_next` viene
inizializzato a `t_first` e la prima attivazione risulta gia' passata. E' un transitorio di
avvio, non una deadline persa. Su 300 iterazioni darebbe un `deadline_miss_ratio` fasullo
dello 0.33 %. **`analyze_doe.py` deve scartare la prima iterazione** (come gia' si fa qui
per il primo `period`).
