# Blocco 3 — contesa della pipeline sotto carico crescente

Documento tecnico. Versione discorsiva in `SPIEGAZIONE-block3.md`.
Script: `analyze_block3.py`. Dati grezzi: `block3/`.

## 1. Esecuzione

| | |
|---|---|
| data | 2026-08-28, **14:19:12 -> 15:22:00** |
| durata | **62m48s** |
| esito | exit 0, **180/180 run integri**, zero abort |
| spazio | **320 MB** (stima ~131 MB: sottostimata, vedi §6) |
| condizioni | freq pinnata, shield `2,3,6,7`, exporter **Zipkin senza collector** |

Disegno: `n_lo` in {0,1,4,8} x {`trace_level=0` controllo, `trace_level=3` Batch,
`trace_level=3` Simple}, 15 ripetizioni = 12 celle, 180 run.

**Con i tre blocchi il DoE e' completo: 410 run**, esattamente il preventivo del Task 1.

### 1.1 Primo tentativo abortito

Il lancio delle 13:16 e' morto con **SIGABRT** dopo 27 minuti, a 6 celle su 12, per il
Bug C documentato in `4-fix-shutdown/NOTES.md` §3bis (`pthread_cancel()` che scatta
dentro il codice OpenTelemetry). Dati scartati, blocco rilanciato dal sorgente corretto.

---

## 2. Risultato principale — le uniche deadline miss della campagna

Aggregate **sommando** su tutte le ripetizioni, mai mediando (vedi §5.1).

| n_lo | cella | giri | **miss** | miss% | run con miss | sforo peggiore |
|---|---|---|---|---|---|---|
| 0 | t0 controllo | 29985 | 0 | 0,000% | 0/15 | — |
| 0 | t3 Batch | 29972 | 0 | 0,000% | 0/15 | — |
| 0 | t3 Simple | 29992 | 0 | 0,000% | 0/15 | — |
| 1 | t0 controllo | 29970 | 0 | 0,000% | 0/15 | — |
| 1 | t3 Batch | 29969 | 0 | 0,000% | 0/15 | — |
| **1** | **t3 Simple** | 29952 | **40** | 0,134% | **15/15** | **-14826 us** |
| 4 | t0 controllo | 29955 | 0 | 0,000% | 0/15 | — |
| 4 | t3 Batch | 29940 | 0 | 0,000% | 0/15 | — |
| **4** | **t3 Simple** | 29936 | **6** | 0,020% | 5/15 | **-86040 us** |
| 8 | t0 controllo | 29925 | 0 | 0,000% | 0/15 | — |
| 8 | t3 Batch | 29917 | 0 | 0,000% | 0/15 | — |
| **8** | **t3 Simple** | 29917 | **5** | 0,017% | 5/15 | **-81948 us** |

**Totale: 51 deadline miss, tutte e sole nelle celle `SimpleSpanProcessor`.**

Contesto: nei blocchi 1 e 2, su oltre 460000 giri, non se ne era vista **nessuna**. Il
`BatchSpanProcessor` non ne produce a nessun livello di carico; il Simple si', anche a
`n_lo=1`, dove il carico di fondo e' minimo.

Lo sforo peggiore e' di **86 ms**, cioe' **piu' di otto periodi interi** del task critico.

### 2.1 Il profilo del guasto conta piu' della frequenza

`n_lo=1` ha **piu' miss** (40) ma piu' piccoli (max 14,8 ms); `n_lo=4` e `n_lo=8` ne hanno
meno (6 e 5) ma **catastrofici** (86 e 82 ms). Non e' un degrado graduale che si possa
dimensionare: sono stalli rari e lunghissimi. Per un sistema real-time e' il profilo
peggiore — un jitter costante lo si mette a budget, uno stallo da 86 ms no.

---

## 3. Costo per giro e isolamento dal backend

`slack` mediano; il controllo di ogni gruppo e' il riferimento.

| n_lo | controllo | Batch | Simple | conn. fallite/run (Batch / Simple) |
|---|---|---|---|---|
| 0 | 8010 | 7925 (**-85**) | 7593 (**-417**) | 8 / 2006 |
| 1 | 8010 | 8002 (**-8**) | 7672 (**-338**) | 143 / 21819 |
| 4 | 8010 | 8002 (**-8**) | 7676 (**-334**) | 331 / 24291 |
| 8 | 8010 | 8002 (**-8**) | 7670 (**-340**) | 336 / 24632 |

Il Batch costa **8 us per giro** e resta piatto al crescere del carico. Il Simple ne costa
**~340**, cioe' **40 volte tanto**: il 4,3% del budget di 8000 us e il **17% dei 2000 us
di calcolo effettivo**.

Il rapporto fra le connessioni fallite e' il meccanismo: a `n_lo=8` il Batch ne fa 336 per
run, il Simple **24632**, un fattore **73**. Il Batch accoda in memoria e svuota ogni 5 s,
quindi il numero di tentativi non dipende da quanti span produci; il Simple esporta ogni
span in linea, dentro il percorso critico.

**Conclusione architetturale**: il `BatchSpanProcessor` **isola** il task critico da un
backend irraggiungibile, il `SimpleSpanProcessor` **gliene propaga addosso il costo**.
Vale indipendentemente da quanto sia veloce il collector, perche' riguarda la struttura
del disaccoppiamento, non la sua velocita'.

### 3.1 Cosa NON dicono questi numeri

I ~340 us/giro del Simple **non sono il costo di esportare**: sono il costo di *tentare*
un export verso un backend irraggiungibile e riprovare. La campagna e' girata senza
collector, scelta dichiarata e coerente coi blocchi 1 e 2 (che ne sono praticamente
immuni: 8 e 2 connessioni per run il primo, zero il secondo perche' usa ostream).

Perche' non si e' aggiunto un collector: a `n_lo=8` il Simple chiederebbe ~8000 POST
sincrone al secondo e il `fake_zipkin.py` del task 0.2 (HTTPServer Python monothread che
riscrive un file a ogni POST) diventerebbe il collo di bottiglia, propagando la propria
lentezza dentro il percorso critico. Misureremmo il collector, non OTel.

**Limite dichiarato dello studio: non abbiamo un numero per il costo di un export che
riesce.**

---

## 4. L'anomalia del blocco 2, RISOLTA

Domanda aperta da `NOTES-block2.md` §5: il jitter di HI era 10,8 us a `n_lo=0` (blocco 1,
Zipkin) e 2,1 us a `n_lo=4` (blocco 2, ostream). Effetto del carico, o confondente
dell'exporter?

Celle `trace_level=0` — **nessun tracing, nessun exporter, zero simboli otel nel binario**
(verificato al Task 1):

| n_lo | mediana | run nel modo basso (<6 us) | min | max |
|---|---|---|---|---|
| 0 | 4,8 | 9/15 | 2,5 | 20,5 |
| 1 | 9,4 | 3/15 | 2,4 | 22,2 |
| **4** | **2,0** | **15/15** | 2,0 | 2,6 |
| **8** | **2,1** | **15/15** | 2,0 | 4,3 |

**L'ipotesi del confondente Zipkin e' esclusa**: qui non c'e' nessun exporter e l'effetto
c'e' lo stesso. Il valore a `n_lo=4` (2,0) coincide con quello del blocco 2 (2,1), misurato
con exporter diverso in una campagna diversa.

Con carico sufficiente il jitter non si limita a scendere: **la dispersione sparisce del
tutto** (15 run su 15 fra 2,0 e 2,6, contro un intervallo 2,5-20,5 a vuoto). Il carico
**elimina il modo cattivo**.

### 4.1 L'effetto NON e' monotono

`n_lo=1` e' il caso **peggiore** (mediana 9,4, solo 3 run su 15 nel modo buono), peggio
sia di 0 che di 4. Interpretazione plausibile, **non verificata**: cio' che conta non e'
quanto carico c'e' ma se l'occupazione della CPU vicina e' **continua**. Un thread al 50%
di utilizzazione fa alternare cpu3 fra attivo e inattivo; quattro thread che chiedono il
200% la tengono satura, e quel regime costante stabilizza il task critico.

### 4.2 Bimodalita': riproducibile, non spiegata

A carico basso il jitter del controllo e' **bimodale** — un gruppo a ~2,5 us e uno a
~12-27, niente in mezzo, ripartizione circa 50/50. Riprodotta in **tre** campagne
indipendenti: blocco 1 (2026-08-27 19:39), primo tentativo blocco 3 (13:16), rilancio
(14:19). Non e' rumore.

**Conseguenza metodologica**: la mediana di una distribuzione bimodale cade nel vuoto fra
le due mode e salta a seconda della ripartizione. Nel primo tentativo il controllo dava
12,6 (7 run bassi su 15), nel rilancio 4,8 (9 su 15) — **con binario identico**, perche'
il fix del Bug C e' guardato da `#if RTAPP_TRACE_LEVEL > 0` e in quella build non viene
compilato. Le celle di controllo **non vanno riassunte con la mediana**.

Ipotesi non testata: lo stato viene deciso all'avvio e mantenuto per tutta l'esecuzione,
con probabilita' ~50/50 -> profuma di layout di memoria (ASLR) o di stato del package
(frequenza uncore, C-state). **Test proposto**: rilanciare la cella di controllo con
`setarch -R` per disabilitare la randomizzazione. Da fare, non fatto.

---

## 5. Il jitter va letto separando corpo e code

| n_lo | cella | per_std | **IQR** | per_med | giri < 5000 us |
|---|---|---|---|---|---|
| 1 | t3 Simple | 172,0 | **3** | 9645 | 1179 |
| 4 | t3 Simple | 873,9 | **27** | 9648 | 77 |
| 8 | t3 Simple | 1015,6 | **1020** | 9643 | 209 |
| 8 | t3 Batch | 5,5 | 2 | 9964 | 0 |

A `n_lo=1` e `n_lo=4` il `per_std` di centinaia di microsecondi **non e' irregolarita'
diffusa**: l'IQR e' 3 e 27 us, cioe' il corpo della distribuzione e' strettissimo. Lo
scarto viene da pochi giri con periodo quasi dimezzato — il timer in modalita' `relative`
che si riaggancia dopo uno sforo (`rt-app.cpp:752-756`). Uno stallo lungo genera un
periodo corto subito dopo, e la coppia gonfia la deviazione standard.

A `n_lo=8` invece l'**IQR sale a 1020**: li' il degrado e' reale e diffuso, non piu' solo
code. E' l'unico punto del DoE in cui il Simple destabilizza il task critico in modo
continuo.

### 5.1 I miss vanno sommati, non mediati

La cella Simple a `n_lo=4` ha 6 miss distribuite su 5 run su 15. La **mediana** del
`deadline_miss_ratio` fra ripetizioni vale **0,00%**, perche' 10 run su 15 non ne hanno.
Aggregare per mediana avrebbe cancellato l'unico risultato di sicurezza della campagna.

E' lo specchio dell'errore opposto del blocco 2, dove i conteggi binari andavano trattati
come proporzione binomiale e non come media.

---

## 6. Note operative

- **Spazio**: 320 MB contro i ~131 MB stimati. La stima non teneva conto dello `stderr`
  delle celle Simple: **4,5 MB per run** di soli messaggi "Connection failed", 15 run x 4
  celle. Da tenere presente se si rilancia.
- Totale `2-DoE/`: **474 MB** con tutti e tre i blocchi.
- Zero run interrotti (nessun log `LO_noise` non gzippato), zero abort nel runlog.

---

## 7. Ricadute sul Task 5

1. **Sommare** i deadline miss fra ripetizioni, mai mediarli.
2. Riportare per il jitter sia `per_std` sia **IQR**: dove divergono di due ordini di
   grandezza il fenomeno e' a code, non diffuso.
3. Le celle di controllo a `n_lo` 0 e 1 sono **bimodali**: descriverle con le due mode e
   la ripartizione, non con la mediana. Non usarle come baseline di confronto senza
   dichiararlo.
4. Le celle Simple vanno intitolate **"comportamento a backend irraggiungibile"**, non
   "costo dell'export".
5. Il confronto Batch vs Simple e' internamente valido: stessa condizione dichiarata per
   entrambi.
