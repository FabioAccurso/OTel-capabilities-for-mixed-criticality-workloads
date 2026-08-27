# Task 4 — Blocco 1 eseguito: overhead puro della strumentazione

Data: 2026-08-27, 19:39:30 → 20:08:31. Wall time **29m01s**, exit 0.

## 1. Setup

Prima di lanciare, i tre percorsi in cima a `run_doe.sh` sono stati risolti dalla posizione
dello script invece che hardcodati:

```bash
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RTAPP_SRC_DIR="${RTAPP_SRC_DIR:-$PROJECT_ROOT/rt-app/src}"
BIN_CACHE="${BIN_CACHE:-$PROJECT_ROOT/bin}"
DOE_ROOT="${DOE_ROOT:-$PROJECT_ROOT/2-DoE}"
```

Condizioni: frequenza pinnata (1800 MHz, turbo off), shield `cset` su `2,3,6,7`,
`CALIB_NS=139`, `HI_task` SCHED_FIFO 90 su cpu2, **nessun task di disturbo** (`n_lo=0`).

Due scelte metodologiche, confermate prima del lancio:

- **Nessun collector Zipkin in ascolto.** L'exporter fallisce la connessione (misurati
  **7,7 errori `Connection failed` per run** al livello 3, uno per flush del
  BatchSpanProcessor). Il blocco misura quindi creazione degli span, attributi e batching,
  **escluso il costo di trasporto**. Va dichiarato così nella relazione.
- **Thread di export non vincolato.** Eredita la maschera del processo (`2-3,6-7`) e la
  sua collocazione varia da run a run. Lasciato così di proposito: è realistico e fa parte
  di ciò che l'elaborato deve documentare.

## 2. Integrità dei dati

| | |
|---|---|
| run totali | **80** (4 celle × 20 ripetizioni × 20 s) |
| `data_table.csv` | 81 righe (header + 80) |
| log `HI_task` | 80/80 presenti |
| righe per cella | ~39980 su 20 run (≈1999 giri per run) |
| dimensione | 21 MB |

Prima riga di ogni log scartata in tutte le analisi (transitorio di avvio, task 0.5).
Aggregazione per **mediana fra le 20 ripetizioni**, mai su run singoli (task 2).

## 3. Risultati

| livello | run_med [IQR] | period_std [IQR] | wu_lat med | wu_lat peggiore | **miss%** |
|---|---|---|---|---|---|
| 0 (nessuna) | 1989 [1979-2013] | **7,6** [2,7-16,1] | 17 | 61 | **0,00** |
| 1 (main+thread) | 2004 [2004-2005] | **11,2** [10,9-11,3] | 27 | 75 | **0,00** |
| 2 (+phase) | 2004 [2004-2005] | **10,8** [10,5-11,0] | 27 | 165 | **0,00** |
| 3 (+phase_loop) | 1955 [1955-1955] | **13,5** [12,7-14,6] | 28 | 60 | **0,00** |

### 3.1 Nessuna deadline mancata, a nessun livello

**0,00% di miss su tutte e 80 le esecuzioni**, cioè su ~160000 giri. Con
`HI_task` al 20% di utilizzazione su una CPU isolata, la strumentazione OTel — anche al
massimo dettaglio — non è mai arrivata a far sforare la scadenza. È il risultato di
partenza: l'overhead esiste ma, a questa utilizzazione, non è fatale.

### 3.2 Il jitter cresce in modo monotono

`period_std`, la deviazione standard del periodo, è la variabile che risponde più
chiaramente:

| livello | period_std | vs livello 0 |
|---|---|---|
| 0 | 7,6 µs | — |
| 1 | 11,2 µs | **+47%** |
| 2 | 10,8 µs | +41% |
| 3 | 13,5 µs | **+77%** |

Livelli 1 e 2 sono indistinguibili fra loro (11,2 vs 10,8 µs, IQR sovrapposti), il che ha
senso: al livello 2 gli span di fase sono uno per *definizione* di fase, non per giro
(task 3), quindi il lavoro aggiunto rispetto al livello 1 è trascurabile. Il salto vero è
al livello 3, dove ogni giro crea uno span.

Nota sulla dispersione: il livello 0 ha l'IQR più largo (2,7-16,1) nonostante la mediana
più bassa. È il fenomeno visto nel task 2 — alcuni run mostrano jitter elevato senza causa
identificata. Ai livelli 1-3 l'IQR è strettissimo, come se la strumentazione dominasse
quel rumore di fondo.

### 3.3 La latenza di risveglio cresce del 60%

Mediana da **17 µs** a **27-28 µs** appena si accende il tracing, e poi resta piatta fra i
livelli. Il caso peggiore assoluto è **165 µs** al livello 2. Su un periodo di 10 ms
resta un contributo piccolo, ma è il primo segnale di interferenza sul percorso di
risveglio del task.

### 3.4 Il costo per giro, misurato sullo slack

`run` misura solo `loadwait()` — `clock_gettime` è preso a filo, e tutto il lavoro degli
span sta **fuori** da quella finestra (`rt-app.cpp:683-693`). Lo `slack`, invece, è
calcolato all'evento `timer`, cioè **dopo** che tutto il giro è stato completato span
inclusi: è quindi la metrica giusta per il costo totale per giro.

| livello | slack_med | slack_min | **costo/giro** |
|---|---|---|---|
| 0 | 7980 | 7926 | — |
| 1 | 7950 | 7916 | **+30 µs** |
| 2 | 7950 | 7917 | **+30 µs** |
| 3 | 7925 | 7866 | **+56 µs** |

Su un budget di 8000 µs: lo 0,4% al livello 1-2, lo 0,7% al livello 3. Rispetto ai 2000 µs
di calcolo utile, l'1,5% e il 2,8%.

## 4. Anomalia non spiegata: `run` DIMINUISCE al livello 3

Al livello 3 il tempo di calcolo misurato scende a **1955 µs** contro i 1989 del livello 0
e i 2004 dei livelli 1-2. Ed è riproducibile in modo assoluto: **IQR nullo**, tutti e 20 i
run a 1955.

Il lavoro svolto è per costruzione identico (`load_count = exec*1000/p_load` con
`p_load=139` fisso), e la finestra di misura esclude il codice degli span. Quindi lo
stesso identico loop `ldexp` gira più veloce quando la strumentazione è al massimo.

**Ipotesi testata e scartata**: che fosse il thread di export su cpu6, il gemello SMT di
cpu2 — l'effetto FPU/SMT del task 0.4, dove un gemello occupato rendeva il loop in virgola
mobile il 36% più veloce. Ho rilanciato lo stesso binario di livello 3 con lo shield
ristretto a `2,3`, così che il thread di export non possa usare il gemello:

```
shield 2,3,6,7 (gemello disponibile): run_med = 1955 us
shield 2,3     (gemello escluso)    : run_med = 1955 us
```

Identici. **Non è l'SMT.** Resta un effetto di stato del core (cache, predittori, o stato
di alimentazione delle unità FP) indotto dal codice non-FP che la strumentazione esegue
fra un `loadwait()` e il successivo. Non l'ho identificato.

### Conseguenza pratica, importante per il Task 5

`analyze_doe.py` riporta `max_duration_us` e `mean_duration_us` come variabili di
risposta principali, ed entrambe derivano dalla colonna `run`. **Non sono affidabili per
confrontare livelli di tracing diversi**: la strumentazione altera lo stato
microarchitetturale e fa misurare *meno* lavoro, non di più. Le metriche da usare sono
`slack` (costo per giro), `period_jitter_std_us` e `wu_latency`.

## 5. Cosa resta aperto

- **Task 5**: usare `slack` come metrica di overhead; trattare `max_duration_us` con
  cautela per il motivo del §4.
- **Spazio disco**: il blocco 1 occupa 21 MB con `n_lo=0`. I blocchi 2 e 3, con fino a 8
  task di disturbo, produrranno ~750 MB ciascuno (stima del Task 1). Va deciso **prima**
  di lanciarli se comprimere i log o tenere solo `HI_task`.
- Rilanciare un blocco già eseguito sovrascrive i `run_NN` ma **aggiunge** righe a
  `data_table.csv`: svuotare `2-DoE/block1/`, `data_table.csv` e `index.txt` prima di
  ripetere.
