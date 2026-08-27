# Task 0.5 — anatomia di UN run: da `gen_config.py` a `test.sh` alla cartella di output

Data: 2026-08-27. Frequenza pinnata (1800 MHz), cmdline con
`isolcpus=domain,managed_irq,2,3,6,7`, shield `cset` su `2,3,6,7` attivo durante il run.
Binario `rt-app/src/rt-app` compilato **senza** tracing (`RTAPP_TRACE_LEVEL=0`, verificato:
zero simboli `opentelemetry` nel binario) — qui interessa la struttura del run, non OTel.

## 1. La config generata

```
python3 scripts/measurements/gen_config.py --n-lo 4 --duration 20 --calib 139 \
        --out 0-exploration/task0.5/cfg_n4.json
```

```json
{
  "tasks": {
    "HI_task":  { "policy":"SCHED_FIFO", "priority":90, "cpus":[2],
                  "loop":-1, "run":2000, "sleep":8000 },
    "LO_noise": { "instance":4, "policy":"SCHED_OTHER", "cpus":[3],
                  "loop":-1, "run":500,  "sleep":500 }
  },
  "global": { "duration":20, "default_policy":"SCHED_OTHER",
              "calibration":139, "logdir":"./", "log_basename":"rtapp" }
}
```

Da leggere così:

- **`HI_task`** — un thread, `SCHED_FIFO` prio 90, inchiodato su cpu2. Periodo nominale
  10 ms (2 ms di calcolo + 8 ms di attesa), utilizzazione 20%. È la variabile di risposta
  del DoE.
- **`LO_noise`** — `"instance": 4` genera **quattro** thread `SCHED_OTHER`, tutti su cpu3,
  ciascuno 0,5 ms + 0,5 ms → duty cycle 50% ciascuno. Quattro × 50% = **200% di domanda su
  una sola CPU**: il rumore è sovrascritto di proposito.
- **`"loop": -1`** — ripeti finché `global.duration` (20 s) non scade.
- **`"calibration": 139`** — salta la calibrazione (task freq-calibrazione).

## 2. Cosa fa `test.sh`

```
test.sh <run_dir> <rt-app-binary> <config.json>
```

Tre cose, in ordine:

1. **Riscrive la config** dentro `run_dir/config.json` forzando `logdir` = `run_dir` e
   `log_basename` = `rtapp`. Ogni run resta autocontenuto: la config effettivamente
   eseguita è archiviata insieme ai suoi log, non c'è modo di confondersi su quale
   configurazione ha prodotto quali numeri.
2. **Esegue rt-app dentro lo shield** se `cset` esiste ed è attivo
   (`sudo cset shield --exec`), altrimenti in chiaro.
3. **Separa gli stream**: `stdout.log` e `stderr.log`.

Nota operativa: il ramo con `cset` usa `sudo`, che in questa sessione non ha un TTY. Il run
va lanciato con `pkexec /bin/bash <script>`, e da root `sudo` passa senza chiedere nulla.

## 3. La cartella prodotta

```
run_n4/
├── config.json              528 B    la config REALMENTE eseguita
├── stdout.log                76 B    solo il messaggio di cset
├── stderr.log               942 B    i <notice> di rt-app
├── rtapp-HI_task-0.log      242 KB   1999 righe
├── rtapp-LO_noise-1.log     1,2 MB   9844 righe
├── rtapp-LO_noise-2.log     1,2 MB   9837 righe
├── rtapp-LO_noise-3.log     1,2 MB   9847 righe
└── rtapp-LO_noise-4.log     1,2 MB   9794 righe
```

**Un file di log per thread**, non uno per task: `"instance": 4` produce quattro file
distinti, numerati da 1. Il nome è `<log_basename>-<nome_thread>-<indice>.log`.

Dimensione: **5,0 MB per un singolo run da 20 s**. Da tenere presente per il Task 4: una
campagna con decine di celle × 10-30 ripetizioni arriva facilmente a qualche GB.

`stdout.log` è vuoto di contenuto utile perché il binario non ha tracing; sarà lui a
contenere gli span nel Blocco 2 del DoE (exporter ostream, Task 3). `stderr.log` conferma
`pLoad = 139ns` e le politiche di scheduling effettivamente applicate:

```
[rt-app] <notice> pLoad = 139ns
[rt-app] <notice> [0] Starting with SCHED_FIFO policy with priority 90
[rt-app] <notice> [1] Starting with SCHED_OTHER policy with priority 0   (×4)
[rt-app] <notice> [0] Locking pages in memory
```

## 4. Il formato del log (`rt-app_utils.cpp:151`, `log_timing`)

```
#idx  perf   run  period      start        end     rel_st  slack  c_duration  c_period  wu_lat
   0    14  1988   10000 2096315375 2096325375      23213      0        2000         0       0
```

| colonna | significato | nel nostro run |
|---|---|---|
| `idx` | indice di fase dentro il loop | sempre 0 (una sola fase) |
| `perf` | **`exec / p_load`** (`rt-app.cpp:563`) — quantità di lavoro *configurata*, non misurata | HI 14 (2000/139), LO 3 (500/139) |
| `run` | µs realmente spesi a calcolare | la misura di WCET |
| `period` | µs fra l'inizio di questo loop e il precedente | la misura di jitter |
| `start`/`end`/`rel_st` | timestamp assoluti e relativi, µs | |
| `slack` | margine rispetto alla scadenza | **sempre 0**, vedi §6 |
| `c_duration` | durata configurata | 2000 / 500 |
| `c_period` | periodo configurato | **sempre 0**, vedi §6 |
| `wu_lat` | latenza di risveglio | **sempre 0**, vedi §6 |

## 5. I numeri del run

| thread | loop | run med | run max | period med | period std | period max |
|---|---|---|---|---|---|---|
| **HI_task-0** | 1998 | **1979 µs** | **2050 µs** | **9987 µs** | **10,3 µs** | 10060 µs |
| LO_noise-1 | 9843 | 499 | 4644 | 2022 | 496,2 | 5201 |
| LO_noise-2 | 9836 | 499 | 3767 | 2022 | 499,6 | 4642 |
| LO_noise-3 | 9846 | 499 | 3696 | 2022 | 491,2 | 4586 |
| LO_noise-4 | 9793 | 499 | 3799 | 2022 | 503,7 | 5008 |

Distribuzione del periodo:

```
HI_task    min 9986 | p1 9986 | med  9987 | p99 10036 | max 10060   (configurato 10000)
LO_noise-1 min 1055 | p1 1062 | med  2022 | p99  3632 | max  5201   (configurato  1000)
```

Tre letture:

1. **HI_task è protetto.** 1998 loop in 20 s (attesi 2000), `run` a 1979 µs contro 2000
   configurati (−1%, coerente con il task 0.4), periodo entro **74 µs** di escursione
   totale su 10 ms. La deviazione standard del periodo è **10,3 µs**: è il livello di
   rumore di fondo contro cui andrà confrontato l'overhead di OTel.
2. **LO_noise è saturo, come da progetto.** Il periodo mediano è 2022 µs invece di 1000:
   quattro thread che chiedono il 50% di una CPU ciascuno ne chiedono il 200%, e la CPU ne
   dà 100%. Il fattore 2 è esattamente la sovrascrizione. Il `run` mediano resta 499 µs —
   il lavoro per giro è giusto, è la *cadenza* a slittare.
3. **HI e LO non si disturbano**, perché sono su core fisici diversi (cpu2 e cpu3) con i
   fratelli SMT (6 e 7) isolati e vuoti. Il DoE dovrà comunque verificare che questo resti
   vero quando si aggiunge la pipeline OTel, che gira su thread propri.

## 6. Finding principale: tre metriche su sei sono strutturalmente zero

`slack`, `c_period` e `wu_lat` valgono **0 su tutte le 41321 righe** dei cinque log.
Non è un bug: leggendo `rt-app.cpp:727-757`, quei tre campi sono scritti **solo** dentro
il ramo `case rtapp_timer:`

```c
case rtapp_timer:
    t_period = usec_to_timespec(event->duration);
    ldata->c_period += event->duration;
    ...
    t_slack = timespec_sub(&rdata->res.timer.t_next, &t_now);
    ldata->slack = timespec_to_usec_long(&t_slack);
    if (timespec_lower(&t_now, &rdata->res.timer.t_next)) {
        clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &rdata->res.timer.t_next, NULL);
        ...
        ldata->wu_latency += timespec_to_usec(&t_wu);
    }
```

La config prodotta da `gen_config.py` usa `run` + **`sleep`**, che sono eventi
`rtapp_run` / `rtapp_sleep`: non passano mai di lì. `sleep` dorme una durata *relativa*
dopo la fine del calcolo — non esiste nessuna scadenza assoluta da mancare.

**Conseguenza diretta sul DoE**: `analyze_doe.py:62` calcola

```python
"deadline_miss_ratio": sum(1 for s in slacks if s < 0) / len(slacks),
"mean_wu_latency_us": st.mean(r["wu_latency"] for r in rows),
```

Con le config attuali entrambe darebbero **0,000 in ogni cella**, e il
`deadline_miss_ratio` è la variabile di risposta principale della campagna. Sopravvivono
solo `max_duration_us`, `mean_duration_us` e `period_jitter_std_us`.

### La correzione (per il Task 2)

Sostituire `sleep` con un evento `timer`. Sintassi verificata a sorgente
(`rt-app_parse_config.cpp:587-620`):

```json
"HI_task": { "policy":"SCHED_FIFO", "priority":90, "cpus":[2], "loop":-1,
             "run":2000,
             "timer": { "ref":"unique", "period":10000, "mode":"relative" } }
```

- `ref: "unique"` → timer **per-thread** (`rtapp_timer_unique`); un `ref` qualsiasi altro
  crea un timer *condiviso* fra i thread che lo nominano.
- `period` in µs. Attenzione: è il **periodo intero**, non il tempo di attesa. Con
  `run: 2000` e `period: 10000` il task calcola 2 ms e si risveglia 10 ms dopo l'inizio,
  non 10 ms dopo la fine.
- `mode` default `"relative"`: se un giro sfora, `t_next` viene riagganciato all'istante
  corrente e il ritardo non si accumula. Con `"absolute"` la griglia temporale resta fissa
  e i ritardi si propagano. In **entrambi** i casi lo `slack` negativo viene registrato.

Non ho modificato `gen_config.py`: scrivere le config definitive è il Task 2.
In questa cartella c'è `cfg_n4_timer.json`, la variante a `timer` usata per la controprova.

## 7. Controprova sperimentale

Ho scritto a mano `cfg_n4_timer.json`, identica alla precedente ma con `timer` al posto di
`sleep`, e l'ho lanciata con lo stesso `test.sh` (`run_n4_timer/`).

| config | thread | righe | slack != 0 | slack < 0 | slack_min | wu_lat med | c_period |
|---|---|---|---|---|---|---|---|
| `sleep` | HI_task-0 | 1998 | **0** | 0 (0,0%) | 0 | 0,0 | 0 |
| `sleep` | LO_noise-1 | 9843 | **0** | 0 (0,0%) | 0 | 0,0 | 0 |
| `timer` | HI_task-0 | 1998 | **1998** | 1 (0,1%) | −14780 | 7,1 | 10000 |
| `timer` | LO_noise-1 | 9874 | **9873** | **5316 (53,8%)** | −7623 | 1002,1 | 1000 |

La metrica si accende. E dice esattamente ciò che deve dire in uno scenario
mixed-criticality: **HI_task rispetta le scadenze, LO_noise le manca nel 53,8% dei giri**
perché quattro thread al 50% su una CPU sola non ci stanno.

Tre cose emerse dalla controprova.

**(a) L'unico slack negativo di HI_task è la riga 1.**

```
riga 1: slack=-14780  period=1982
```

È un transitorio di avvio: `rdata->res.timer.t_next` viene inizializzato a `*t_first`
(`rt-app.cpp:737`), cioè *prima* che il primo `run` sia stato eseguito, quindi la prima
scadenza è già passata quando la si valuta. Scartando la riga 1, HI_task ha **zero**
deadline miss su 1997 giri.

**Da correggere nel Task 5**: `analyze_doe.py` non scarta la prima riga, quindi
riporterebbe un `deadline_miss_ratio` di 1/1998 = 0,05% in *ogni* cella del DoE come
artefatto costante.

**(b) Compare la wake-up latency, che è una misura RT vera.** HI_task, `SCHED_FIFO` 90 su
CPU isolata, kernel PREEMPT_RT:

```
wu_lat:  min 6 | med 7 | p99 12 | MAX 23 us
slack :  min 7931 | med 8010 | max 8014 us   (budget 10000-2000 = 8000)
```

23 µs di latenza di risveglio nel caso peggiore, e un margine minimo di 7931 µs sugli 8000
disponibili. Con `sleep` questa colonna era zero e la misura non esisteva.

**(c) Il timer riduce anche il jitter del periodo di 3 volte.**

| | min | med | max | **std** |
|---|---|---|---|---|
| `sleep` | 9986 | 9987 | 10060 | **10,3 µs** |
| `timer` | 9948 | 9996 | 10013 | **3,3 µs** |

Con `sleep` il periodo è "fine del calcolo + 8 ms", quindi eredita ogni fluttuazione del
tempo di calcolo. Con `timer` il risveglio è su una griglia assoluta e le fluttuazioni non
si sommano. È un argomento in più per il cambio: `period_jitter_std_us` è una delle
variabili di risposta del DoE, e partire da 3,3 µs invece che da 10,3 µs di rumore di
fondo rende molto più facile far emergere l'overhead di OTel.


## 8. Cosa resta aperto

- **Task 2**: `gen_config.py` deve emettere `timer` invece di `sleep`, altrimenti due
  delle sei variabili di risposta sono costanti a zero (e la terza ha 3× piu' rumore).
- **Task 5**: `analyze_doe.py` deve scartare la prima riga di ogni log, altrimenti
  riporta un `deadline_miss_ratio` di 0,05% come artefatto di avvio in ogni cella.
- **Task 4**: 5 MB di log per run × numero di celle × ripetizioni. Valutare se comprimere
  o se ridurre `duration`.
- Il binario in `rt-app/src/` è senza tracing: per i blocchi 2 e 3 del DoE va ricompilato
  con le macro giuste (`run_doe.sh` lo fa da sé tramite `BIN_CACHE`).
