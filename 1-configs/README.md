# Config definitive del DoE (Task 2)

Generate con `scripts/measurements/gen_config.py`. `run_doe.sh` **le rigenera da solo** in
ogni cella (`run_cell()` chiama `gen_config.py --n-lo <n> --duration <d>`): questi file
servono a ispezionare e rivedere il risultato senza lanciare la campagna.

```bash
for n in 0 1 4 8; do
  python3 scripts/measurements/gen_config.py --n-lo $n --duration 20 --out 1-configs/cfg_n${n}.json
done
```

`n_lo` copre i valori usati dai tre blocchi: 0 (block1 e il controllo di block3), 4
(block2), e 0/1/4/8 (block3).

## Le tre scelte di progetto

**1. HI usa un evento `timer` assoluto, non `sleep`.**

```json
"run": 2000,
"timer": { "ref": "unique", "period": 10000, "mode": "absolute" }
```

Il `period` e' quello **completo** (10 000), non lo sleep: il timer aspetta fino al prossimo
istante di attivazione assoluto. Senza questo lo `slack` resta 0 su ogni riga e il
`deadline_miss_ratio` del Task 5 sarebbe 0 per costruzione (task 0.5, finding (h)).

Effetto misurato sul task HI (n_lo=4, 20 s, dentro lo shield):

| | iterazioni | period p50 | jitter | slack |
|---|---|---|---|---|
| `"sleep": 8000` | 1981/2000 | 10062 us | 37 us | **0 su tutte le righe** |
| `timer` absolute | **2000/2000** | **9999 us** | **10 us** | med 8008 us |

Il jitter scende da 37 a 10 us e le iterazioni tornano esatte, perche' le attivazioni sono
agganciate a una griglia fissa invece di derivare da `run + sleep`, che ne ereditava la
varianza.

**2. LO resta su `sleep`, di proposito.** E' volutamente sovraccarico (con `--n-lo 4` sono
4 x 50 % su una sola CPU). Con un timer `absolute` un task in ritardo non dorme mai piu':
`t_next` resta indietro e ogni iterazione salta l'attesa, trasformando il rumore da duty
cycle del 50 % a busy loop puro. Sul task LO non misuriamo deadline, quindi lo slack non
serve.

**3. `"calibration": 29`** fisso (task 0.6). Elimina anche gli ~8 s di startup non
deterministico: un run da `duration: 20` ora dura 20.2 s invece di 28.3 s.

## Transitorio di avvio: da gestire nell'analisi

Le **prime iterazioni di HI hanno sempre slack negativo**, e non sono deadline perse.
Causa (`rt-app.cpp:1434-1449`): il thread `ind == 0` — cioe' HI — fissa `t_zero` e subito
dopo si blocca su `pthread_barrier_wait` finche' tutti i thread sono pronti; quando riparte,
`t_first = t_zero` e' gia' vecchio di tutto il tempo di avvio degli altri.

**Il numero di righe fasulle scala col numero di thread**, misurato:

| n_lo | thread | ritardo iniziale | iterazioni negative |
|---|---|---|---|
| 0 | 1 | 2 579 us | 1 |
| 1 | 2 | 11 080 us | 2 |
| 4 | 5 | 36 751 us | 5 |
| 8 | 9 | 76 972 us | 10 |

Questo e' **il motivo per cui non basta scartare la prima riga**: block3 varia `n_lo` fra
0, 1, 4 e 8, quindi un scarto fisso lascerebbe 0, 1, 4 e 9 falsi miss nelle quattro celle —
un bias sistematico **correlato proprio col fattore in studio**, che si leggerebbe come
"piu' carico di sottofondo -> piu' deadline perse".

**Regola corretta per `analyze_doe.py`**: scartare le righe iniziali finche' lo slack non
diventa >= 0 la prima volta, e registrare quante ne sono state scartate. Dopo il recupero,
uno slack negativo e' un miss vero.

### Cosa NON funziona: l'opzione `delay`

Provata e scartata. `"delay"` (`rt-app_parse_config.cpp:1081`, applicata a
`rt-app.cpp:1505-1511`) sposta `t_first` in avanti **e** fa dormire il thread fino a li',
quindi muove entrambi i termini dello slack e il divario resta:

| delay su HI (n_lo=8) | rel_st | slack[0] | iterazioni negative |
|---|---|---|---|
| nessuno | 85 216 us | -76 972 | 10 |
| 100 000 us | — | -73 878 | 10 |
| 200 000 us | 277 003 us | -68 828 | 9 |

Con 200 ms di delay `rel_st` cresce di ~192 ms ma lo slack migliora solo di 8 ms. Il
residuo e' il setup (mlock, impostazione della policy) che avviene **dopo** la sleep del
delay: un delay non puo' compensarlo. Il rimedio resta lato analisi.
