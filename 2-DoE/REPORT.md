# Task 5 — Analisi del DoE

Generato da `report_doe.py` su `results.csv`: **485 run** con dati, 4 campagne.

Variabile di risposta primaria: **`budget` = `duration + slack`**, il tempo consumato per iterazione. I blocchi 1 e 3 hanno mostrato che le colonne native di rt-app non servono allo scopo: `duration` (la colonna `run`) dipende dal layout del binario per ~30 us, piu' del segnale da misurare, e `period` (`end - start` della stessa riga) *si accorcia* dove l'overhead cresce, perche' gli span nascono fuori da quella finestra. Chi misurasse su `period` concluderebbe che il tracing rende il codice piu' veloce.

## Panoramica della campagna

| campagna | run | celle | fattore studiato |
|---|---|---|---|
| block1 | 80 | 4 | granularita' del tracing (`trace_level` 0-3) |
| block2 | 150 | 6 | sampler (AlwaysOff/On, Ratio 0.1-0.7) |
| block3 | 180 | 12 | processor (Batch/Simple) x carico (`n_lo` 0-8) |
| diag | 75 | 3 | diagnostica del regime anomalo (non e' un fattore) |

Piattaforma stabile su tutta la campagna: frequenza fissata a P0 con boost disabilitato, `aperf_mhz` misurata su 255 run (media 2292.3, min 2285, max 2300 MHz).

## Domanda 1 — OTel prioritizza i task critici? **No.**

Il blocco 2 varia il sampler con carico misto (1 HI + 4 LO) ed exporter ostream, che rende gli span contabili.

| sampler | run campionati | frazione | IC 95 % | span HI | span LO | run **parziali** |
|---|---|---|---|---|---|---|
| AlwaysOn | 25/25 | 1.00 | [0.87, 1.00] | 1 | 4 | **0** |
| Ratio 0.1 | 4/25 | 0.16 | [0.06, 0.35] | 1 | 4 | **0** |
| Ratio 0.3 | 11/25 | 0.44 | [0.27, 0.63] | 1 | 4 | **0** |
| Ratio 0.5 | 16/25 | 0.64 | [0.45, 0.80] | 1 | 4 | **0** |
| Ratio 0.7 | 20/25 | 0.80 | [0.61, 0.91] | 1 | 4 | **0** |
| AlwaysOff | 0/25 | 0.00 | [0.00, 0.13] | - | - | **0** |

**Zero run parziali su 150.** Un run e' completo (17 span) o vuoto: quando viene campionato escono sempre 1 span HI e 4 LO, mai un sottoinsieme. Tutti gli span di un run condividono un solo `trace_id`, perche' ogni thread nasce con `span_opts.parent = main_span->GetContext()`.

Il sampler funziona — le frazioni seguono il ratio e ogni IC 95 % contiene il valore nominale — ma **alla granularita' sbagliata**: la decisione e' per-trace, non per-task. Impostare un ratio non significa "conserva piu' span dei task critici", significa "scarta l'intera esecuzione, HI e LO insieme, con probabilita' 1-ratio". A ratio 0.1 nell'84 % dei run **non esiste alcuna traccia del task critico**. E' la motivazione empirica del Task 6.

## Domanda 2 — Quanto costa il monitoraggio?

### Granularita' del tracing (blocco 1, solo HI, nessun carico)

| trace_level | budget mediano [us] | delta vs livello 0 | deadline miss |
|---|---|---|---|
| 0 — nessuno | 9991.0 | +0.0 | 0 |
| 1 — main+thread | 9991.0 | +0.0 | 0 |
| 2 — +phase | 9991.0 | +0.0 | 0 |
| 3 — +phase_loop | 9977.0 | -14.0 | 0 |

I livelli 1 e 2 non sono misurabili. Il livello 3 costa **~13 us per iterazione**: lo 0.13 % del periodo di 10 ms, ma lo **0.7 % del lavoro utile** di 2000 us.

### Processor ed exporter sotto carico (blocco 3)

| braccio | n_lo=0 | n_lo=1 | n_lo=4 | n_lo=8 |
|---|---|---|---|---|
| trace0 (controllo) | 9991 | 9991 | 9992 | 9991 |
| trace3 **Batch** | 9977 | 9978 | 9978 | 9979 |
| trace3 **Simple** | 9686 | 9691 | 8689 | 9682 |

delta rispetto al controllo, stesso carico [us]:

| braccio | n_lo=0 | n_lo=1 | n_lo=4 | n_lo=8 |
|---|---|---|---|---|
| trace3 **Batch** | -14 | -13 | -14 | -12 |
| trace3 **Simple** | -305 | -300 | -1303 | -309 |

**Batch costa ~13 us per iterazione, Simple ~300: 23 volte tanto**, cioe' il 15 % del lavoro utile. Il valore di Batch e' costante al variare del carico e coerente col blocco 1.

> Il **-1303 a `n_lo=4` non va letto come un costo maggiore**: quella cella e' bimodale (8 ripetizioni a ~8688 us, 7 a ~9665) e la mediana cade sul gruppo basso, quindi la non-monotonia rispetto a `n_lo=8` e' apparente. Il costo di Simple e' ~300 us; il secondo modo, che vale altri ~980 us per iterazione, e' non spiegato.

La causa e' architetturale: `SimpleSpanProcessor::OnEnd` chiama `Export()` **sincrono, nel thread che chiude lo span**, sotto spin-lock condiviso; `BatchSpanProcessor` accoda e delega a un thread proprio. I tentativi di export per run lo mostrano direttamente:

| braccio | n_lo=0 | n_lo=1 | n_lo=4 | n_lo=8 |
|---|---|---|---|---|
| trace0 (controllo) | 0 | 0 | 0 | 0 |
| trace3 **Batch** | 8 | 117 | 203 | 209 |
| trace3 **Simple** | 2007 | 16060 | 25568 | 25551 |

Nessun collector era in ascolto: gli export falliscono subito con `ECONNREFUSED` su localhost, che e' il caso **piu' favorevole** a Simple. Con un collector reale il divario sarebbe maggiore.

## Domanda 3 — Il monitoraggio fa violare gli SLO temporali? **Solo con Simple.**

| braccio | n_lo=0 | n_lo=1 | n_lo=4 | n_lo=8 | slack minimo [us] |
|---|---|---|---|---|---|
| trace0 (controllo) | 0/29993 | 0/29969 | 0/29925 | 0/29862 | 109 |
| trace3 **Batch** | 0/29965 | 0/29950 | 0/29907 | 0/29841 | 65 |
| trace3 **Simple** | 0/29985 | 0/29835 | 12/29624 | 9/29544 | -3631 |

Su tutta la campagna i deadline miss sono **22**, di cui 1 fuori dal blocco 3. Tutte le celle di controllo e tutte le celle Batch hanno **zero miss a qualunque carico**; con Simple e carico di sottofondo il task critico sfora fino a **3.6 ms su un periodo di 10 ms**.

I miss non sono un artefatto della terminazione anomala (vedi sotto): sono distribuiti uniformemente lungo il run, non addensati in coda.

## Domanda 4 — Robustezza: `Simple` termina il processo

**40 run su 485** sono terminati con SIGABRT, tutti nel braccio `trace3 Simple`:

| n_lo | run | abortiti |
|---|---|---|
| 0 | 15 | 0 |
| 1 | 15 | 11 |
| 4 | 15 | 14 |
| 8 | 15 | 15 |

Causa verificata nel codice: `__shutdown()` di rt-app termina i thread con `pthread_cancel` (`rt-app.cpp:933`); glibc la implementa come eccezione di *forced unwind*; `SimpleSpanProcessor::OnEnd` e' dichiarato **`noexcept`** (`simple_processor.h:60`), e un unwind che attraversa un `noexcept` chiama `std::terminate()`. Con Simple il thread e' quasi sempre dentro `OnEnd` (export sincrono), con Batch quasi mai.

**La scelta del processor di telemetria non degrada soltanto le prestazioni del task critico: ne termina il processo**, e in modo silenzioso rispetto ai dati, perche' l'abort arriva a lavoro finito. I run abortiti perdono esattamente le ultime 20 iterazioni di log; le analisi usano mediane su ~1974 iterazioni.

## Limiti e questioni aperte

1. **Regime anomalo a 2-3.7x, non spiegato.** Presente in tutte le campagne a un tasso dell'1.1-1.3 %. La colonna `aperf_mhz`, aggiunta apposta, ha **falsificato l'ipotesi frequenza**: i due run anomali del blocco 3 girano a 2286 MHz, cioe' nominali, mentre il lavoro per iterazione cresce di 2-3.3x. Cadono inoltre in celle diverse, una delle quali **senza alcun tracing**: il fenomeno non dipende da OpenTelemetry. Ipotesi residue: contesa SMT sul sibling **cpu3**, dentro lo shield ma non controllato, o pressione su cache/memoria. Si distinguono con i contatori IPC di `perf stat`. `hwlatdetect` e' gia' stato escluso (0 latenze su 435 s) ed e' comunque lo strumento sbagliato per un rallentamento sostenuto, che non produce salti temporali.

2. **La cella `Simple n_lo=4` e' bimodale** (8 ripetizioni a ~8688 us, 7 a ~9665): la sua mediana non descrive un comportamento unico e la non-monotonia apparente rispetto a `n_lo=8` viene da li'.

3. **Un solo collector non e' stato provato.** Tutti i run Zipkin girano senza collector in ascolto. E' il caso piu' favorevole all'overhead misurato: i risultati vanno letti come un **limite inferiore**.

4. **Piattaforma singola**: un ultrabook da 15 W con 4 core fisici. I valori assoluti non si trasferiscono ad altro hardware; i confronti fra celle si'.

