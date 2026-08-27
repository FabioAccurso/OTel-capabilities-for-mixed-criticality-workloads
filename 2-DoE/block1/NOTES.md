# Blocco 1 — overhead puro di strumentazione

80 run: 4 livelli di tracing x 20 ripetizioni x 20 s. Solo il task HI
(`SCHED_FIFO` prio 90 su cpu2, `run 2000` / `timer` assoluto 10 000 us), nessun carico di
sottofondo, sampler AlwaysOn, processor Batch, exporter Zipkin senza collector.
Livelli: 0 = nessuna strumentazione, 1 = span di main e thread, 2 = + span di fase,
3 = + span di phase_loop.

Ripetizioni **interlacciate** (rep 1: t0 t1 t2 t3; rep 2: t0 t1 t2 t3; ...) e non a blocchi,
cosi' un'eventuale deriva lungo la campagna colpisce tutte le celle allo stesso modo.

## Stabilita' della piattaforma

Frequenza **2295 MHz su tutti e 80 i run**, Tctl da 51.4 a 50.0 C: la macchina si e'
raffreddata durante la campagna invece di scaldarsi (un solo task al 20 % di utilizzazione
su una CPU isolata). Nessun throttling STAPM, nessuna deriva da correggere.

## Risultato 1: nessuna deadline persa, mai

**0 deadline miss su 80 run** a tutti e quattro i livelli, scartato il transitorio di avvio.
Il periodo resta agganciato alla griglia: la mediana del delta fra `start` consecutivi e'
**esattamente 10 000 us** a ogni livello. Il jitter (`period max - p50`) sta fra 7.6 e
11.4 us ovunque. La strumentazione **non degrada la periodicita'**.

## Risultato 2: la colonna `run` NON misura l'overhead

Mediana di `run` per cella (media su 20 ripetizioni), con gli intervalli min-max:

| trace | run_med | intervallo |
|---|---|---|
| 0 | 1986.2 | [1983, 1996] |
| 1 | **1954.8** | **[1953, 1970]** |
| 2 | 1984.4 | [1983, 1996] |
| 3 | 1994.6 | [1984, 2000] |

Il livello 1 e' **piu' veloce** del livello 0, con intervalli **disgiunti**: impossibile per
un overhead. E' un artefatto di *layout del binario* — ogni livello e' un eseguibile diverso,
e l'allineamento del codice di `waste_cpu_cycles()` cambia. Vale ~30 us (1.6 %), cioe' piu'
di qualunque segnale di strumentazione a questi livelli.

Il motivo di fondo: `run` cronometra **solo** il busy loop di `loadwait()`, mentre gli span
vengono creati **fuori** da quella finestra.

## Risultato 3: dove si vede davvero, e quanto costa

La metrica giusta e' `slack` (margine residuo misurato all'evento timer, dopo tutto il
lavoro dell'iterazione). La somma `slack_med + run_med` e' il budget consumato per
iterazione:

| trace | slack_med | run_med | **somma** | delta vs livello 0 |
|---|---|---|---|---|
| 0 | 8001.6 | 1986.2 | 9987.8 | — |
| 1 | 8033.6 | 1954.8 | 9988.4 | +0.6 |
| 2 | 8004.4 | 1984.3 | 9988.8 | +1.0 |
| 3 | 7979.9 | 1994.6 | **9974.5** | **-13.3** |

Per i livelli 0, 1 e 2 la somma e' **costante entro 1 us**: quello che `run` guadagna,
`slack` lo perde, esattamente. Conferma che le differenze del punto 2 sono artefatto.

Il livello 3 consuma **~13 us in piu' per iterazione**. Sul periodo di 10 ms e' lo 0.13 %,
ma sui 2 ms di lavoro utile e' lo **0.7 %**. Livelli 1 e 2: non misurabile.

Perche' il 2 non costa nulla pur creando 2 span per iterazione (thread_loop + phase, ~4000
span sul run) mentre il 3 ne aggiunge uno solo e costa 13 us: il `BatchSpanProcessor` ha
`max_queue_size = 2048` e l'export fallisce (nessun collector), quindi la coda si satura
presto e gran parte delle creazioni diventa uno scarto a basso costo. Da riprendere al
Blocco 3, dove il processor e' un fattore.

## Risultato 4: rt-app sotto-riporta il proprio overhead

La colonna `period` di rt-app e' `end - start` della **stessa riga**, non il delta fra start
consecutivi. Con il livello 3 gli span si creano fuori dalla finestra `[start, end]`, quindi:

```
trace=0   end-start = 9998    delta start-start = 10000
trace=3   end-start = 9976    delta start-start = 10000
```

Il ciclo reale resta 10 ms, ma `period` **si accorcia** di ~15-24 us proprio dove l'overhead
aumenta. Chi leggesse la sola colonna `period` concluderebbe che il livello 3 e' piu'
*veloce*. Il timer assoluto assorbe la differenza nella sleep.

**Conseguenza per i Blocchi 2 e 3**: usare `slack` (o `slack + run`) come variabile di
risposta per l'overhead, non `period` e non `run` da soli.

## Un outlier non spiegato

`trace=1`, ripetizione 2: le **prime 840 iterazioni** (8.4 s dei 20) hanno `run` ~7270 us
invece di ~1970, cioe' **3.7x**, poi rientro **istantaneo** alla norma (riga 840: 7244,
riga 841: 1953). 1 run su 80.

Escluso: deriva termica (sarebbe graduale, e Tctl era 50 C), frequenza (2295 MHz registrati),
latenza di risveglio (`wu_lat` 6-10 us come sempre), periodicita' (`period` regolare e slack
positivo per tutte le 840 righe, il task rispettava comunque la deadline con 2.7 ms di
margine).

Ipotesi principale, **non verificata**: contesa sul sibling SMT. HI gira su cpu2 e il suo
sibling cpu3 e' dentro lo shield ma non controllato — il task 0.5 ha verificato che il thread
main di rt-app (e quindi il worker `SCHED_OTHER` del `BatchSpanProcessor`) ha
`Cpus_allowed_list = 2-3,6-7`, quindi puo' finire proprio li'. E' il rischio segnalato dal
task 0.2 e va reso un controllo esplicito nei blocchi successivi: pinnare i thread non-HI
lontano dal sibling di HI, oppure isolare `nosmt`.

L'outlier non altera le conclusioni: la mediana della ripetizione 2 e' 1970 us contro
1953-1955 delle altre, e la somma `slack + run` resta nella norma.
