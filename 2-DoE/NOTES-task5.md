# Task 5 — analisi complessiva del DoE

Documento tecnico. Versione discorsiva in `SPIEGAZIONE-task5.md`.

| | |
|---|---|
| dati | `results.csv` — **410 run**, una riga per esecuzione, 39 colonne |
| estrattore | `scripts/measurements/analyze_doe.py` (riscritto, vedi §1) |
| aggregatore | `2-DoE/aggregate.py` — tabelle di sintesi |
| grafici | `2-DoE/make_plots.py` -> `2-DoE/plots/*.svg` (5 figure) |

Copertura: blocco 1 (80 run), blocco 2 (150), blocco 3 (180). Nessun run mancante,
nessun log illeggibile.

---

## 1. Correzioni a `analyze_doe.py`

Lo script originale aveva quattro problemi. Tutti e quattro avrebbero prodotto
numeri **plausibili e sbagliati**, cioe' il tipo peggiore.

### 1.1 Il transitorio di avvio (bug silenzioso)

`t_next` viene inizializzato a `*t_first` (`rt-app.cpp:737`), quindi il **primo**
`slack` di ogni log e' privo di senso — tipicamente qualche migliaio di microsecondi
negativo. Vale da solo **1 deadline miss su ~2000 in ogni cella del DoE**.

Senza scartarlo, ogni cella avrebbe riportato ~0,05% di miss costante, e i 51 miss
veri del blocco 3 sarebbero stati indistinguibili dal fondo.

### 1.2 `count_exported_spans()` (bug segnalato da un compagno di corso, verificato)

Contava `content.count(nome)` sull'intero file. Due errori sovrapposti:

```
run campionato del blocco 2, valori reali:
  vecchia: content.count('HI_task')  = 2     <- lo span porta il nome DUE volte
  nuova:   hi_spans_exported         = 1        (campo `name` + attributo `config.name`)
  vecchia: content.count('LO_noise') = 8     <- stesso fattore 2
  nuova:   lo_spans_exported         = 4
  span REALMENTE esportati            = 17    <- 12 discendenti mai contati
```

Il fattore 2 e' esatto e riproducibile. Il problema piu' grave e' il secondo: solo lo
span *del thread* porta il nome della task; `thread_loop`, `phase` e (al livello 3) le
migliaia di `phase_loop` non lo portano e non venivano contati affatto.

Correzione: si contano le righe che matchano `^  name\s*:\s*(\S+)` — due spazi
iniziali, mentre gli attributi usano un TAB — e si riporta sia il totale sia la
ripartizione per nome.

### 1.3 Miss come conteggio, non solo come rapporto

Aggiunta la colonna `hi_deadline_miss_count`. Serve perche' i miss vanno **sommati**
fra ripetizioni: vedi §4.1.

### 1.4 IQR accanto alla deviazione standard

Aggiunta `hi_period_iqr_us`. Serve a distinguere degrado diffuso da incidenti
isolati: vedi §4.2.

### 1.5 Altre modifiche

- log `LO_noise` letti da `.gz` (decisione del 2026-08-28) e aggregati su tutte le
  istanze -> famiglia di colonne `lo_*`;
- aggiunta `hi_slack_min_us` (lo sforo peggiore) e `hi_wu_latency_p99_us`;
- `max_duration_us` / `mean_duration_us` **restano** nel CSV per continuita' ma sono
  marcate come **da non usare** per confrontare livelli di tracing: derivano da `run`,
  che al livello 3 *scende* per un effetto microarchitetturale non spiegato
  (`NOTES-block1.md` §4, ipotesi SMT testata e scartata).

---

## 2. Blocco 1 — costo dell'instrumentazione

Figura: `plots/fig1-overhead-per-livello.svg`.

| trace_level | run | slack | costo/giro | jitter std | IQR | wu med | wu max | miss |
|---|---|---|---|---|---|---|---|---|
| 0 nessuno | 20 | 7980 | — | 7,6 | 0 | 17 | 61 | 0 |
| 1 main+thread | 20 | 7950 | **+30 µs** | 11,2 | 1 | 27 | 75 | 0 |
| 2 +phase | 20 | 7950 | **+30 µs** | 10,8 | 1 | 27 | 165 | 0 |
| 3 +phase_loop | 20 | 7925 | **+56 µs** | 13,5 | 5 | 28 | 60 | 0 |

Livelli 1 e 2 indistinguibili: al livello 2 gli span di fase sono uno **per
definizione**, non per giro (confermato al Task 3). Il salto e' al livello 3, che
genera uno span per ogni giro.

Costo in prospettiva: 56 µs sono lo **0,7% del budget** di 8000 µs e il **2,8% dei
2000 µs di calcolo**. Zero deadline miss su ~160000 giri.

**L'IQR e' 0-5 µs contro una std di 7-13**: anche qui il grosso della dispersione sta
nelle code, non nel corpo.

---

## 3. Blocco 2 — il campionamento non distingue le criticita'

Figure: `plots/fig2-campionamento-binario.svg`.

| cella | run | campionati | osservato | IC 95% Wilson | nominale | **intermedi** |
|---|---|---|---|---|---|---|
| AlwaysOff | 25 | 0 | 0,0% | [0,0 – 13,3] | 0% | **0** |
| ratio 0,1 | 25 | 2 | 8,0% | [2,2 – 25,0] | 10% | **0** |
| ratio 0,3 | 25 | 10 | 40,0% | [23,4 – 59,3] | 30% | **0** |
| ratio 0,5 | 25 | 14 | 56,0% | [37,1 – 73,3] | 50% | **0** |
| ratio 0,7 | 25 | 19 | 76,0% | [56,6 – 88,5] | 70% | **0** |
| AlwaysOn | 25 | 25 | 100,0% | [86,7 – 100,0] | 100% | **0** |

### 3.1 Due affermazioni di forza diversa — non confonderle in relazione

**Debole**: la frazione osservata segue quella nominale. Vero e monotono, e ogni
valore nominale cade dentro l'IC della sua cella. Ma quegli intervalli sono **larghi
30-40 punti**: 25 ripetizioni non bastano per dire "campiona il 30%". Scrivere
**"coerente con"**, mai "verificato". Per misurare bene quelle frazioni servirebbero
centinaia di ripetizioni per cella; non era l'obiettivo.

**Fortissima**: il sampler non separa mai HI dai LO. Non e' una stima con un
intervallo attorno, e' un **conteggio esatto: 0 su 150**. Basterebbe *un* valore
diverso da 0 e da 17 per smentirla.

### 3.2 Causa

`TraceIdRatioBasedSampler` decide sul `trace_id`. In rt-app ogni thread nasce figlio
di `main_span` (`span_opts.parent = main_span->GetContext()`), quindi HI e i quattro
LO **condividono un solo `trace_id`**. Il sampler non ha mai visto cinque task: ha
visto una trace e l'ha accettata o scartata in blocco.

### 3.3 Corollario per un sistema mixed-criticality

A ratio 0,1 il task critico perde la telemetria nel **90% delle esecuzioni** — non il
90% dei suoi span, il 90% delle esecuzioni *intere*. Con OTel standard la politica che
servirebbe ("HI sempre, LO al 10%") **non e' esprimibile**. -> Task 6.

### 3.4 Il costo dell'export al livello 2 e' zero misurabile

Esperimento naturale: dentro le celle a ratio, i run campionati e quelli scartati sono
la **stessa esecuzione**, cambia solo l'esito del sorteggio.

| gruppo | run | run_med | per_std | slack_med |
|---|---|---|---|---|
| campionati (17 span) | 45 | 1963 | 2,1 | 8026 |
| scartati (0 span) | 55 | 1963 | 2,1 | 8026 |

Identici. Idem fra AlwaysOff e AlwaysOn. I +30 µs/giro del blocco 1 al livello 2 sono
quindi il costo di **creare** gli hook, non di esportarli.

---

## 4. Blocco 3 — l'architettura della pipeline decide

Figure: `plots/fig3-batch-vs-simple-costo.svg`, `plots/fig4-deadline-miss.svg`.

| n_lo | cella | slack | costo/giro | std | IQR | **MISS** | run | sforo peggiore |
|---|---|---|---|---|---|---|---|---|
| 0 | controllo | 8010 | — | 4,8 | 0 | 0 | 0/15 | — |
| 0 | Batch | 7925 | −85 | 16,1 | 6 | 0 | 0/15 | — |
| 0 | Simple | 7593 | −417 | 15,3 | 4 | 0 | 0/15 | — |
| 1 | controllo | 8010 | — | 9,4 | 0 | 0 | 0/15 | — |
| 1 | Batch | 8002 | −8 | 5,7 | 2 | 0 | 0/15 | — |
| **1** | **Simple** | 7672 | **−338** | 172,0 | 3 | **40** | **15/15** | **−14826 µs** |
| 4 | controllo | 8010 | — | 2,0 | 0 | 0 | 0/15 | — |
| 4 | Batch | 8002 | −8 | 5,0 | 2 | 0 | 0/15 | — |
| **4** | **Simple** | 7676 | **−334** | 873,9 | 27 | **6** | 5/15 | **−86040 µs** |
| 8 | controllo | 8010 | — | 2,1 | 0 | 0 | 0/15 | — |
| 8 | Batch | 8002 | −8 | 5,5 | 2 | 0 | 0/15 | — |
| **8** | **Simple** | 7670 | **−340** | 1015,6 | 1020 | **5** | 5/15 | **−81948 µs** |

**51 deadline miss in tutta la campagna, tutte e sole nelle celle Simple.** Nei
blocchi 1 e 2, su oltre 460000 giri, non ce n'era **nessuna**.

Il meccanismo sta nelle connessioni fallite per run (`n_lo=8`): Batch **336**, Simple
**24632**, fattore **73**. Il Batch accoda e svuota ogni 5 s — il numero di tentativi
non dipende dal volume di span; il Simple esporta ogni span in linea, nel percorso
critico.

**Conclusione architetturale**: il `BatchSpanProcessor` **isola** il task critico da
un backend irraggiungibile, il `SimpleSpanProcessor` **gliene propaga addosso il
costo**. Vale indipendentemente dalla velocita' del collector, perche' riguarda la
struttura del disaccoppiamento.

### 4.1 I miss vanno SOMMATI, mai mediati

La cella Simple a `n_lo=4` ha 6 miss distribuite su 5 run di 15. La **mediana** del
`deadline_miss_ratio` fra ripetizioni vale **0,00%**, perche' 10 run su 15 non ne
hanno. Aggregare per mediana avrebbe cancellato l'unico risultato di sicurezza
dell'intera campagna.

E' lo specchio dell'errore opposto del §3: la' i conteggi binari andavano trattati
come proporzione, qui i conteggi rari vanno sommati. **Una statistica robusta e'
esattamente quella sbagliata quando cerchi eventi rari.**

### 4.2 Std e IQR insieme, altrimenti si legge male

A `n_lo=1` e `n_lo=4` il Simple ha std 172 e 874 ma **IQR 3 e 27**: il corpo della
distribuzione e' strettissimo (periodi fra 9641 e 9657 su un nominale di 10000). Lo
scarto viene da pochi giri con periodo quasi dimezzato — il timer in modalita'
`relative` che si riaggancia dopo uno sforo (`rt-app.cpp:752-756`). Uno stallo lungo
genera un periodo corto subito dopo, e la coppia gonfia la deviazione standard.

A `n_lo=8` invece l'**IQR sale a 1020**: li' il degrado e' reale e diffuso. E' l'unico
punto del DoE in cui il Simple destabilizza il task critico in modo continuo.

### 4.3 Il profilo del guasto

`n_lo=1` ha **piu'** miss (40, in 15 run su 15) ma piccole; `n_lo=4` e `8` ne hanno
meno (6 e 5) ma **catastrofiche** (86 e 82 ms, cioe' piu' di otto periodi interi).

Per un sistema real-time e' il profilo peggiore: un ritardo costante si mette a
budget, uno stallo da 86 ms no.

---

## 5. I task LO: il miss% satura, servono altre metriche

| n_lo | cella | LO miss% | LO periodo mediano | LO wu p99 |
|---|---|---|---|---|
| 1 | controllo | 0,0% | 984 | 113 |
| 4 | controllo | **53,3%** | 2031 | 4994 |
| 8 | controllo | **53,2%** | 2526 | 15733 |

Il `deadline_miss_ratio` di LO **satura al ~53%** e non e' una misura lineare del
carico: in modalita' `relative` il timer riaggancia `t_next` all'istante corrente dopo
uno sforo, quindi al massimo si perde una scadenza su due. Cio' che cresce in modo
monotono e' il **periodo mediano** (984 -> 2031 -> 2526) e la **wake-up latency p99**
(113 -> 4994 -> 15733). Usare quelle.

---

## 6. Questioni aperte, dichiarate

### 6.1 Bimodalita' del jitter (riproducibile, non spiegata)

Figura: `plots/fig5-bimodalita-controllo.svg`.

| n_lo | run nel modo basso (<6 µs) | mediana modo basso | mediana modo alto |
|---|---|---|---|
| 0 | 9/15 | 2,8 | 13,5 |
| 1 | 3/15 | 4,0 | 10,4 |
| 4 | **15/15** | 2,0 | — |
| 8 | **15/15** | 2,1 | — |

Riprodotta in **tre campagne indipendenti** (blocco 1 del 27/08, primo tentativo
blocco 3, rilancio). Non e' rumore.

**Il carico elimina il modo cattivo**, e l'effetto **non e' monotono**: `n_lo=1` e' il
caso peggiore. Interpretazione plausibile **non verificata**: conta la *continuita'*
dell'occupazione della CPU vicina, non la sua entita'.

**Trappola verificata sul campo**: fra il tentativo abortito del blocco 3 e il
rilancio, la cella di controllo dava jitter 12,6 vs 4,8 µs e wu_med 27 vs 7 **con
binario identico** (il fix del Bug C e' guardato da `#if RTAPP_TRACE_LEVEL > 0` e in
quella build non viene compilato), solo perche' la ripartizione fra le due mode era
7/15 invece di 9/15. **Le celle di controllo non vanno riassunte con la mediana.**

Ipotesi non testata: lo stato viene deciso all'avvio e mantenuto per tutta
l'esecuzione, ~50/50 -> layout di memoria (ASLR) o stato del package (frequenza
uncore, C-state). **Test proposto e NON eseguito: rilanciare con `setarch -R`.**

### 6.2 Il calo di `run` al livello 3

Al livello 3 la colonna `run` **scende** a 1955 µs contro 1989 del livello 0, con IQR
nullo. Ipotesi SMT testata e scartata (shield ristretto a `2,3`: valore identico).
Causa non identificata. **Conseguenza**: `max_duration_us`/`mean_duration_us` non
vanno usate per confrontare livelli di tracing.

### 6.3 Nessun numero per il costo di un export riuscito

La campagna e' girata **senza collector**, scelta dichiarata. Per Batch e per il
blocco 2 e' irrilevante (8 e 2 connessioni/run, zero il secondo). Per le celle Simple
e' determinante: i ~340 µs/giro **non sono il costo di esportare** ma di *tentare* un
export verso un backend irraggiungibile.

Perche' non si e' aggiunto un collector: a `n_lo=8` il Simple chiederebbe ~8000 POST
sincrone/s e `fake_zipkin.py` (HTTPServer Python monothread che riscrive un file a
ogni POST) diventerebbe il collo di bottiglia, propagando la propria lentezza dentro
il percorso critico. Misureremmo il collector, non OTel.

**Le celle Simple vanno intitolate "comportamento a backend irraggiungibile".**

---

## 7. Sintesi per la relazione

1. **L'instrumentazione costa poco e in modo prevedibile**: 30-56 µs per giro, cioe'
   meno dell'1% del budget. Zero deadline miss in 240000 giri (blocchi 1-2).
2. **OTel standard non sa prioritizzare per criticita'**: 0 separazioni su 150
   occasioni. Il ratio sampler decide sulla trace, non sul task.
3. **L'architettura della pipeline decide la sicurezza**: Batch 0 miss, Simple 51,
   con stalli fino a 86 ms. Il disaccoppiamento non e' un dettaglio implementativo.
4. Tre questioni aperte dichiarate (§6), con il test proposto per la prima.

I punti 2 e 3 sono il materiale del **Task 6**: servono un sampler che decida su
nome/attributi dello span invece che sul `trace_id`, e la conferma che la coda
asincrona non e' opzionale.

---

## 8. Note sulla riproduzione

```
python3 scripts/measurements/analyze_doe.py --data-table 2-DoE/data_table.csv \
                                            --out 2-DoE/results.csv     # ~2 min
python3 2-DoE/aggregate.py                                              # tabelle
python3 2-DoE/make_plots.py                                             # 5 SVG
```

I grafici sono SVG generati in Python puro: su questa macchina **matplotlib e numpy
non sono installati**, e il vettoriale si scala meglio nella relazione. Palette: quella
di riferimento della skill `dataviz`, usata senza modifiche (il validator richiede
node, non disponibile; non avendo sostituito le tinte, i valori documentati come
validati restano tali). Ogni SVG e' autonomo e porta la propria variante per tema
scuro.
