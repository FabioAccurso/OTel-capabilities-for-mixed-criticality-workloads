# Relazione sui grafici del DoE

Otto figure generate da `scripts/measurements/plot_doe.py` a partire da
`2-DoE/results.csv` (485 run) e, dove serve la distribuzione completa, dai log
per-thread di `HI_task`. Sorgenti in `2-DoE/figures/`.

Le figure sono raggruppate per domanda: **1-2** rispondono alla domanda della
traccia sulla prioritizzazione, **3-5** all'overhead e agli SLO, **6** alla
robustezza, **7-8** alla validita' delle misure stesse.

---

## 1 — `01_all_or_nothing.png` · La decisione di campionamento e' per-trace

**Cosa mostra.** Ogni punto e' uno dei 150 run del blocco 2. In ascissa il
sampler configurato, in ordinata quanti span quel run ha effettivamente
esportato. La banda rosa copre l'intera regione fra 1 e 16 span.

**Come leggerlo.** I punti si dispongono su **due sole righe**: 0 span (grigio)
oppure 17 span (blu). La banda rosa e' vuota in tutte e sei le colonne.

**Perche' e' significativo.** E' la verifica sperimentale dell'ipotesi centrale
del progetto, e il grafico piu' importante dell'elaborato. Se
`TraceIdRatioBasedSampler` sapesse distinguere fra task — cioe' se potesse
tenere gli span del task critico e scartare quelli best-effort — esisterebbero
run con un numero di span **intermedio**. Non ce n'e' nemmeno uno su 150.

Il motivo e' nel codice: ogni thread nasce con
`span_opts.parent = main_span->GetContext()`, quindi tutti gli span di
un'esecuzione condividono lo stesso `trace_id`, e il sampler decide in funzione
del solo `trace_id`. La decisione e' presa **una volta per esecuzione**, non per
span. Quando un run e' campionato escono sempre esattamente 1 span HI e 4 LO.

**Cosa non dice.** Non dice che il sampler sia rotto: dice che opera alla
granularita' sbagliata per un contesto mixed-criticality. La figura 2 completa
il quadro.

---

## 2 — `02_sampling_fraction.png` · Il sampler rispetta la probabilita' richiesta

**Cosa mostra.** Frazione di run che hanno esportato qualcosa, contro il ratio
richiesto. Barre d'errore: intervallo di confidenza al 95 % di Wilson su n=25.
La diagonale tratteggiata e' il comportamento atteso se la probabilita' fosse
rispettata.

**Come leggerlo.** Tutti i punti cadono sulla diagonale entro il proprio
intervallo di confidenza: 0.16 a fronte di 0.1, 0.44 di 0.3, 0.64 di 0.5, 0.80
di 0.7, piu' i due estremi esatti (AlwaysOff a 0, AlwaysOn a 1).

**Perche' e' significativo.** Va letto **insieme alla figura 1**, e insieme le
due dicono una cosa che nessuna delle due direbbe da sola: il meccanismo
*funziona correttamente* — la probabilita' e' quella richiesta — ma si applica
all'**intera esecuzione**. Impostare `ratio = 0.1` non significa "conserva il
10 % degli span": significa "scarta tutto, task critico compreso, con
probabilita' del 90 %".

**Conseguenza operativa.** A ratio 0.1, in 21 run su 25 non esiste **alcuna**
traccia del task critico. In un sistema mixed-criticality e' il comportamento
peggiore possibile, ed e' la motivazione empirica del Task 6.

---

## 3 — `03_overhead_processor.png` · Il costo lo decide il processor

**Cosa mostra.** Costo per iterazione del task critico, misurato come
differenza di `budget` (= `run + slack`) rispetto alla cella di controllo senza
tracing, allo stesso carico. Pannello destro: stessa cosa con la scala espansa.

**Come leggerlo.** `Batch` resta piatto a **12-14 us** a ogni livello di carico.
`Simple` sta a **~300 us**: circa 23 volte tanto, il 3 % del periodo di 10 ms e
il **15 % del lavoro utile** di 2000 us.

**Perche' e' significativo.** Sposta la conclusione dell'elaborato: non e' la
*quantita'* di telemetria a determinare il costo, ma **come** viene consegnata.
Lo stesso `trace_level=3`, con lo stesso numero di span, costa 13 us o 300 a
seconda del solo processor.

**Cautela sulla barra a `n_lo=4`.** Il valore 1303 e' segnalato in figura perche'
**non va letto come un costo maggiore a quel carico**: quella cella e' bimodale
(8 ripetizioni intorno a 8688 us di budget, 7 intorno a 9665) e la mediana cade
sul gruppo basso. La non-monotonia rispetto a `n_lo=8` e' quindi apparente. Il
costo di Simple e' ~300 us; il secondo modo, che vale altri ~980 us per
iterazione, resta non spiegato.

---

## 4 — `04_export_attempts.png` · Perche' Simple costa 23 volte tanto

**Cosa mostra.** Numero di tentativi di export per run, in scala logaritmica,
contato dalle righe che l'exporter Zipkin lascia su `stderr`.

**Come leggerlo.** Il controllo sta a zero. `Batch` cresce da 8 a ~230 al
crescere del carico. `Simple` arriva a **25 500**: due ordini di grandezza sopra.

**Perche' e' significativo.** E' il **meccanismo** dietro la figura 3, non una
sua ripetizione. `SimpleSpanProcessor::OnEnd` chiama `Export()` in modo
**sincrono, nel thread che ha appena chiuso lo span**, sotto uno spin-lock
condiviso fra tutti i thread; `BatchSpanProcessor` accoda e delega a un thread
proprio, che sveglia a intervalli. Il task critico quindi, con Simple, paga di
persona una connessione HTTP per ogni span che chiude, e si contende lo spin-lock
con i nove thread applicativi.

**Un dettaglio che rende il risultato conservativo.** Nessun collector era in
ascolto: gli export falliscono immediatamente con `ECONNREFUSED` su localhost.
E' il caso **piu' favorevole** a Simple. Con un collector reale, che accetta la
connessione e risponde, il divario sarebbe maggiore — i valori misurati sono un
limite inferiore.

---

## 5 — `05_slack_distribution.png` · Dove il margine va sotto zero

**Cosa mostra.** Distribuzione cumulativa empirica dello `slack` — il margine
residuo prima della deadline — su tutte le ~29 800 iterazioni di HI per ciascun
braccio, al carico massimo (`n_lo = 8`). Il pannello destro ingrandisce la coda
sinistra.

**Come leggerlo.** Controllo e Batch (grigio tratteggiato e blu, sovrapposti)
salgono verticalmente intorno a 8000 us e **non toccano mai lo zero**: ogni
iterazione chiude con almeno 65 us di margine. Simple ha una coda che attraversa
la linea rossa dello zero.

**Perche' e' significativo.** E' l'unica figura che mostra il *margine*, non solo
il conteggio dei fallimenti. Un conteggio di 9 miss su 29 544 iterazioni
(0.03 %) puo' sembrare trascurabile; la curva mostra che la distribuzione di
Simple e' **strutturalmente diversa**, con una coda che si estende fino a
−3631 us. Il task critico non "occasionalmente sfora": ha un profilo di rischio
qualitativamente diverso, con iterazioni che sforano di oltre un terzo del
periodo.

Mostra anche il rovescio: la separazione fra Batch e Simple e' netta e non c'e'
sovrapposizione nella coda, quindi il risultato non dipende da come si sceglie
una soglia.

---

## 6 — `06_abort_rate.png` · Il processo non rallenta: muore

**Cosa mostra.** Percentuale di run terminati con SIGABRT nel braccio Simple, in
funzione del numero di thread applicativi.

**Come leggerlo.** Con un solo thread nessun crash (0/15). Da due thread in su la
probabilita' sale rapidamente: 11/15, 14/15, e a nove thread **15/15**. Batch e
controllo: zero abort su 120 run.

**Perche' e' significativo.** E' il risultato piu' netto dell'intera campagna, e
cambia la natura del problema. Le figure 3 e 5 misurano una *degradazione*;
questa mostra che una configurazione di telemetria **termina il processo
real-time**.

**La causa, verificata nel codice**, e' un'interazione a tre:

1. `__shutdown()` di rt-app termina i thread con `pthread_cancel`
   (`rt-app.cpp:933`);
2. in glibc la cancellazione e' implementata lanciando un'eccezione di *forced
   unwind* nel thread bersaglio, per far girare i distruttori;
3. `SimpleSpanProcessor::OnEnd` e' dichiarato **`noexcept`**
   (`simple_processor.h:60`), e un unwind che attraversa una funzione `noexcept`
   chiama `std::terminate()`.

La dipendenza dal numero di thread e' esattamente cio' che il meccanismo prevede:
con Simple ogni thread passa gran parte del suo tempo dentro `OnEnd` (l'export
sincrono della figura 4), quindi la probabilita' che il `cancel` lo colpisca li'
cresce col numero di thread; con Batch `OnEnd` accoda e ritorna, e la finestra e'
minuscola.

**Nota metodologica.** L'abort avviene **dopo** che tutti i log sono stati
scritti, quindi i dati dei run abortiti sono validi (perdono le ultime 20
iterazioni su 2000). E' anche il motivo per cui e' un problema insidioso: nulla
nei dati segnala che qualcosa e' andato storto.

---

## 7 — `07_metric_artifact.png` · Perche' la metrica ovvia porta a una conclusione falsa

**Cosa mostra.** Blocco 1, quattro livelli di tracing. A sinistra la colonna
`run` che rt-app riporta nativamente; a destra il `budget` (`run + slack`)
relativo al livello 0.

**Come leggerlo.** A sinistra il livello 1 misura **1954 us contro i 1984 del
livello 0**: risulterebbe piu' veloce del codice *senza alcun tracing*. A destra,
la stessa identica campagna dice che i livelli 1 e 2 non sono misurabili e solo
il livello 3 costa ~13 us.

**Perche' e' significativo.** E' una figura sulla **validita' delle misure**, non
sul sistema sotto test, e giustifica la scelta della variabile di risposta usata
in tutte le altre. Un overhead non puo' rendere il codice piu' veloce: il
risultato di sinistra e' un artefatto di **layout del binario** — ogni livello e'
un eseguibile diverso, e l'allineamento del codice del busy-loop cambia — e vale
~30 us, cioe' **piu' del segnale da misurare**.

La colonna `run` cronometra solo il busy-loop, mentre gli span nascono fuori da
quella finestra. Lo stesso vale per `period` (`end - start` della stessa riga),
che al livello 3 *si accorcia* di 15-24 us proprio dove l'overhead cresce.
Sommando `slack` si recupera l'intero tempo dell'iterazione, e l'artefatto si
cancella: cio' che `run` guadagna, `slack` lo perde esattamente.

**Implicazione pratica.** Chi analizzasse questo DoE con le colonne native di
rt-app concluderebbe che la strumentazione OTel migliora le prestazioni.

---

## 8 — `08_anomalous_regime.png` · L'ipotesi "e' un calo di frequenza" e' falsificata

**Cosa mostra.** Ogni punto e' un run: in ascissa la frequenza effettiva misurata
durante quel run tramite i contatori `APERF`/`MPERF`, in ordinata la durata
mediana dell'iterazione. I due rombi rossi sono i run in regime anomalo; i rombi
vuoti arancioni segnano dove sarebbero caduti **se** la causa fosse stata la
frequenza.

**Come leggerlo.** I due run anomali impiegano 2 e 3.3 volte il tempo normale per
iterazione, ma stanno a **2286 MHz**, in mezzo a tutti gli altri. La banda
arancione a ~700 MHz, dove l'ipotesi li collocherebbe, e' vuota.

**Perche' e' significativo.** Durante tutta la campagna era comparso un regime
anomalo in cui il busy-loop rallenta di un fattore 2-3.7, in circa l'1.2 % dei
run. L'ipotesi naturale era un calo di frequenza (il fattore 3.67 corrisponde
esattamente a 2296/626 MHz) e non era verificabile, perche' `mhz_med` viene letto
**dopo** il run. La colonna `aperf_mhz` e' stata aggiunta apposta, con le letture
fuori dalla finestra di misura per non perturbare l'esperimento, e ha risposto
alla prima occasione utile: **il lavoro per iterazione cresce, i MHz no.**

**Un secondo fatto, altrettanto rilevante.** I due run anomali cadono in celle
diverse, e **uno dei due e' una cella di controllo senza alcun tracing**. Il
fenomeno quindi **non dipende da OpenTelemetry** e non inquina i confronti fra
bracci: colpisce tutte le configurazioni allo stesso modo.

**Cosa resta aperto.** Ipotesi residue: contesa SMT sul sibling **cpu3** — che
sta dentro il cpuset isolato ma non e' controllato, e su cui puo' finire il
worker del `BatchSpanProcessor` — oppure pressione su cache/memoria. Si
distinguono con i contatori IPC di `perf stat`: se il lavoro e' lo stesso e i
cicli aumentano, l'IPC crolla. `hwlatdetect` e' gia' stato escluso (0 latenze su
435 s di campionamento) ed e' comunque lo strumento sbagliato, perche' rileva
*buchi* temporali e non rallentamenti sostenuti.

---

## Riepilogo: cosa dicono le otto figure insieme

| # | domanda | risposta |
|---|---|---|
| 1, 2 | OTel prioritizza i task critici? | **No.** La decisione e' per-trace: 0 run parziali su 150 |
| 3, 4 | Quanto costa il monitoraggio? | 13 us/iterazione con Batch, ~300 con Simple; la causa e' l'export sincrono |
| 5 | Fa violare gli SLO temporali? | Solo con Simple, e con una coda fino a −3631 us |
| 6 | E' sicuro? | Con Simple no: **fino al 100 % dei run termina con SIGABRT** |
| 7 | Le misure sono valide? | Solo con `run + slack`; le colonne native invertono il segno del risultato |
| 8 | Il regime anomalo inquina i risultati? | No: e' a frequenza nominale e compare anche **senza** tracing |

La raccomandazione che ne discende per un sistema mixed-criticality: usare
`BatchSpanProcessor` (13 us, zero miss, zero crash), **non** affidarsi al sampler
per proteggere i task critici, e — se serve una prioritizzazione reale — un
sampler che decida sul nome dello span, oggetto del Task 6.
