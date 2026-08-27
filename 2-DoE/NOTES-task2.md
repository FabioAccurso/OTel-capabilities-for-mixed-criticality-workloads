# Task 2 — le config JSON definitive del DoE

Data: 2026-08-27. Frequenza pinnata, shield `cset` su `2,3,6,7`, binario
`RTAPP_TRACE_LEVEL=0` (qui si valida il taskset, non la telemetria).

## 1. La modifica a `gen_config.py`: da `sleep` a `timer`

È la correzione decisa nel task 0.5. Prima:

```json
"HI_task":  { ..., "run": 2000, "sleep": 8000 }
"LO_noise": { ..., "run": 500,  "sleep": 500  }
```

Adesso:

```json
"HI_task":  { ..., "run": 2000, "timer": { "ref": "unique", "period": 10000 } }
"LO_noise": { ..., "run": 500,  "timer": { "ref": "unique", "period": 1000  } }
```

Il motivo, in breve: `sleep` è un'attesa **relativa** dopo la fine del calcolo, quindi non
esiste nessuna scadenza assoluta e rt-app lascia `slack`, `c_period` e `wu_latency` a zero
su ogni riga (`rt-app.cpp:727-757` li scrive solo nel ramo `case rtapp_timer:`).
`analyze_doe.py:62` ricava il `deadline_miss_ratio` da `slack < 0`: con le config vecchie
sarebbe stato **0,000 in ogni cella** della campagna.

Attenzione a due dettagli della sintassi, entrambi verificati a sorgente
(`rt-app_parse_config.cpp:587-620`):

- `period` è il **periodo intero**, non il tempo di attesa. Con `run: 2000` e
  `period: 10000` il task calcola 2 ms e si risveglia 10 ms dopo l'inizio del giro
  precedente — non 10 ms dopo la fine.
- `ref: "unique"` crea un timer **per-thread** (`rtapp_timer_unique`). Serve perché le
  N istanze di `LO_noise` non condividano la stessa scadenza. Un `ref` qualsiasi altro
  creerebbe un timer condiviso.

Le costanti sono ora esplicite in cima al file:

```python
HI_RUN, HI_PERIOD = 2000, 10000     # utilizzazione 20%
LO_RUN, LO_PERIOD = 500,  1000      # 50% per istanza
```

È stata aggiunta l'opzione **`--pacing {timer,sleep}`**, default `timer`. `--pacing sleep`
riproduce esattamente il comportamento precedente ed esiste solo per poter rifare il
confronto del task 0.5; stampa un WARNING esplicito perché non va usata per una cella del
DoE.

`run_doe.sh:83` chiama `gen_config.py` **senza** `--pacing`, quindi eredita il default
`timer`: nessuna modifica necessaria a `run_doe.sh`.

## 2. Le quattro config definitive

Il DoE usa `duration=20` in tutte le celle e `n_lo` ∈ {0, 1, 4, 8}, quindi le config
distinte sono quattro. Copie di riferimento in `2-DoE/configs/` (`run_doe.sh` le rigenera
comunque per ogni cella, queste servono a ispezione e revisione).

| file | task | HI utilizzazione | LO domanda su cpu3 |
|---|---|---|---|
| `cfg_n0.json` | solo HI_task | 20% su cpu2 | — |
| `cfg_n1.json` | HI + 1×LO | 20% su cpu2 | 50% |
| `cfg_n4.json` | HI + 4×LO | 20% su cpu2 | **200%** |
| `cfg_n8.json` | HI + 8×LO | 20% su cpu2 | **400%** |

La sovrascrizione di `LO_noise` è voluta: è il fattore "carico di disturbo" del blocco 3.

## 3. Validazione: eseguite tutte e quattro

Un run da 20 s per ciascuna, dentro lo shield. Prima riga di ogni log scartata (è il
transitorio di avvio individuato nel task 0.5).

| config | thread | loop | run med | period med | period std | **miss%** | wu_max |
|---|---|---|---|---|---|---|---|
| n0 | HI_task-0 | 1999 | 1979 | 9996 | 5,3 | **0,0%** | 28 |
| n1 | HI_task-0 | 1998 | 2019 | 9983 | 18,6 | **0,0%** | 59 |
| n1 | LO_noise-1 | 19999 | 495 | 984 | 24,7 | 0,0% | 154 |
| n4 | HI_task-0 | 1997 | 1979 | 9996 | 3,9 | **0,0%** | 27 |
| n4 | LO_noise-1 | 9848 | 499 | 2021 | 1558,3 | **53,0%** | 7135 |
| n8 | HI_task-0 | 1995 | 1979 | 9996 | 3,9 | **0,0%** | 16 |
| n8 | LO_noise-1 | 4948 | 499 | 2519 | 4230,5 | **52,9%** | 19425 |

Le config funzionano e il quadro mixed-criticality è quello atteso: **HI_task non manca
mai una scadenza**, nemmeno con 8 thread best-effort che chiedono il 400% della CPU
accanto; `LO_noise` ne manca più della metà appena diventa sovrascritto.

Il `run` mediano di HI resta 1979 µs contro 2000 configurati (−1%) a ogni livello di
carico: `CALIB_NS=139` regge, e il carico su cpu3 non ruba lavoro a cpu2.

### 3.1 Due avvertenze sull'interpretazione

**(a) Il `miss%` di LO satura intorno al 53% e non cresce.** Da n4 (200% di domanda) a n8
(400%) passa da 53,0% a 52,9%, cioè non si muove, mentre `wu_max` esplode da 7,1 ms a
19,4 ms. Il motivo è il `mode` di default del timer, `"relative"`: dopo uno sforo rt-app
riaggancia `t_next` all'istante corrente (`rt-app.cpp:752-756`), quindi il ritardo non si
accumula e il rapporto di miss si assesta invece di tendere al 100%.

**Conseguenza per il Task 5**: il `deadline_miss_ratio` di LO **non è una misura lineare
del carico**. Per quantificare quanto LO è in ritardo si guardino `wu_latency` e il
periodo mediano, che invece crescono in modo monotono (984 → 2021 → 2519 µs).
Per HI_task, che non sfora mai, il problema non si pone.

**(b) Un singolo run non è rappresentativo.** Il caso `n1` della tabella sopra sembrava
anomalo (run 2019 invece di 1979, jitter 18,6 invece di ~4). Ho ripetuto `n0` e `n1` tre
volte ciascuno:

| config | rep | run med | period std |
|---|---|---|---|
| n0 | 1 | 1979 | 5,4 |
| n0 | 2 | **2020** | **19,1** |
| n0 | 3 | 1983 | **30,2** |
| n1 | 1 | 1979 | **18,0** |
| n1 | 2 | 1979 | 3,9 |
| n1 | 3 | 1979 | 4,0 |

L'anomalia **non dipende da `n_lo`**: compare anche a carico zero. Su 10 run complessivi,
**4 mostrano un jitter elevato** (18-30 µs di deviazione standard invece di 4-5), in modo
apparentemente casuale. Il `miss%` di HI resta 0,0% in tutti e 10.

Non ho identificato la causa: cpu2 è isolata, la frequenza è fissa e il fratello SMT è
vuoto, quindi resta qualcosa di condiviso a livello di package (L3, bus di memoria,
attività di sistema sulle CPU housekeeping) che si manifesta a intermittenza.

**Conseguenze pratiche**: (1) le 15-25 ripetizioni per cella previste dal DoE non sono
una formalità statistica, servono davvero; (2) nel Task 5 il confronto fra configurazioni
va fatto su **mediane fra ripetizioni**, mai fra run singoli, e conviene riportare anche
la dispersione fra ripetizioni; (3) `period_jitter_std_us` ha una distribuzione a code
pesanti a livello di run: un test non parametrico è più prudente di una media.

## 4. Cosa resta aperto

- **Task 5**: `analyze_doe.py` deve scartare la prima riga di ogni log (transitorio di
  avvio) e aggregare per mediana fra ripetizioni.
- Se in fase di analisi servisse un `deadline_miss_ratio` che cresce col carico invece di
  saturare, si può passare a `"mode": "absolute"` nel timer — ma va deciso **prima** di
  lanciare la campagna, non dopo.
- I log di validazione sono in `2-DoE/validation/` (solo `HI_task`, gzippati, piu' una
  istanza di `LO_noise` per n4).
