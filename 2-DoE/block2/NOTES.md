# Blocco 2 del DoE — il sampler di OTel sa proteggere il task critico?

Campagna del 2026-08-28. **150/150 run**, 6 celle x 25 ripetizioni da 20 s.
Output completo dell'analizzatore in `results.txt`, script in
`scripts/measurements/analyze_block2.py`.

## Configurazione

| | |
|---|---|
| trace_level | 2 (main + thread + phase) |
| processor | Batch (`max_queue_size` 2048, `schedule_delay` 5000 ms) |
| exporter | **ostream** (`RTAPP_EXPORTER_TYPE=1`), span contabili su `stdout.log` |
| task set | 1 HI (SCHED_FIFO 90, cpu2, timer assoluto 10 ms) + 4 LO (cpu6) |
| calibration | 29 (fissa) |
| fattore | sampler: AlwaysOff, AlwaysOn, Ratio 0.1 / 0.3 / 0.5 / 0.7 |

Piattaforma: shield `CPUSPEC(2-3,6-7)`, boost disabilitato (`CpbDis=1`),
**2295 MHz su tutti e 150 i run**, Tctl 48.1 -> 57.0 C. Tutti i run hanno
completato **2000/2000** iterazioni.

## Risultato 1 — la decisione di campionamento e' per-trace, non per-task

E' la conferma sperimentale, su 150 run, dell'ipotesi centrale del progetto
(formulata al task 0.3 su un singolo run).

Un run e' **completo** (17 span) o **vuoto** (0 span). Mai una via di mezzo:

```
sampler       run a 0 span   run completi   run parziali
AlwaysOn                 0             25              0
Ratio 0.1               21              4              0
Ratio 0.3               14             11              0
Ratio 0.5                9             16              0
Ratio 0.7                5             20              0
AlwaysOff               25              0              0
                                        run parziali totali: 0 su 150
```

**Zero run parziali su 150.** Quando un run viene campionato escono sempre
esattamente 1 span HI e 4 span LO; quando viene scartato non esce nulla. I 17
span di un run condividono **un solo `trace_id`** (verificato: 1.00 trace_id
distinti per run in tutte le celle), perche' ogni thread nasce con
`span_opts.parent = main_span->GetContext()`.

Il sampler *funziona*, ma alla granularita' sbagliata. La frazione di run
campionati segue fedelmente il ratio richiesto, e ogni intervallo di confidenza
al 95 % (Wilson, n=25) contiene il valore nominale:

| ratio | run campionati | frazione | IC 95 % |
|---|---|---|---|
| 0.1 | 4/25 | 0.16 | [0.06, 0.35] |
| 0.3 | 11/25 | 0.44 | [0.27, 0.63] |
| 0.5 | 16/25 | 0.64 | [0.45, 0.80] |
| 0.7 | 20/25 | 0.80 | [0.61, 0.91] |

**Conseguenza per l'elaborato**: `TraceIdRatioBasedSampler` non e' un
meccanismo di prioritizzazione. Impostare un ratio non significa "tieni piu'
span dei task critici", significa "butta via l'intera esecuzione, HI e LO
insieme, con probabilita' 1-ratio". In un sistema mixed-criticality reale
questo e' il comportamento peggiore possibile: nel 84 % dei run a ratio 0.1 non
esiste **nessuna** traccia del task critico. E' esattamente il caso d'uso che
il Task 6 deve risolvere.

## Risultato 2 — a trace_level=2 l'overhead non e' misurabile

Variabile di risposta: `slack`, e il **budget** = `run + slack` (motivazione nel
blocco 1: `run` risente del layout del binario e `period` = end-start si
accorcia proprio dove l'overhead cresce).

```
sampler        budget   run_med   slack_med   miss
AlwaysOn       9991.0    1999.0      7993.0      0
Ratio 0.1      9991.0    1969.0      8023.0      0
Ratio 0.3      9991.0    1969.0      8023.0      0
Ratio 0.5      9991.0    1969.0      8023.0      0
Ratio 0.7      9991.0    1969.0      8023.0      1
AlwaysOff      9991.0    1999.0      7993.0      0
```

**Il budget e' 9991.0 us in tutte e sei le celle**, AlwaysOff compreso.
Coerente con il blocco 1, dove i livelli 1 e 2 non erano misurabili e solo il
livello 3 costava ~13 us/iterazione.

Si noti ancora l'artefatto di layout: `run_med` vale 1999 per AlwaysOn e
AlwaysOff e 1969 per le quattro celle Ratio (30 us, 1.5 %), ma `slack` si sposta
della stessa quantita' in senso opposto e il budget resta identico. Chi
misurasse l'overhead sulla sola colonna `run` concluderebbe che AlwaysOff, che
disattiva tutto, e' il **piu' lento**.

### Il confronto piu' pulito del blocco

Dentro le sole celle Ratio, i run si dividono in due gruppi in base all'esito
del sorteggio del sampler. Stesso binario, stessa cella, stessa config: i due
gruppi differiscono **solo** per il fatto che uno ha esportato gli span e
l'altro no. Isola il costo dell'export senza alcun confondimento da layout:

```
campionati    n=51   budget mediano   9991.0 us
scartati      n=49   budget mediano   9991.0 us
delta                              +0.0 us per iterazione
```

**Esportare gli span non costa nulla di misurabile al task critico.** Il motivo
e' architetturale ed e' il finding del task 0.2: il `BatchSpanProcessor` esporta
su un thread proprio, quindi il lavoro di export non e' sul percorso critico di
HI. Il rovescio della medaglia resta quello gia' segnalato: quel thread e'
`SCHED_OTHER`, quindi sotto pressione e' il primo a essere starvato.

## Risultato 3 — due run in un regime a ~3.5x, non diagnosticati

```
Ratio 0.3      rip.14   run_med=6491  (cella=1969, 3.30x)   miss=0
AlwaysOff      rip.1    run_med=7273  (cella=1999, 3.64x)   miss=0
                                          2 run su 150 (1.3 %)
```

E' lo **stesso fenomeno gia' visto nel blocco 1** (trace=1 rep 2, ~840
iterazioni a ~7270 us), quindi non e' un incidente isolato ma un secondo regime
riproducibile. Cosa e' stato accertato:

- **non e' il binario ne' l'avvio**: nel run AlwaysOff le prime iterazioni sono
  normali (1986, 1984, 1984) e il regime subentra dopo; nel blocco 1 avveniva
  l'opposto, con rientro istantaneo dopo 840 iterazioni. Entra ed esce;
- **non e' il lavoro nominale**: `perf`=68 su tutte e 2000 le righe, identico ai
  run normali, quindi `load_count` e' lo stesso;
- **non e' termico**: Tctl 48.1 -> 50.5 C nel run anomalo, il piu' freddo della
  campagna;
- **non e' la periodicita'**: `period` resta 9998-10000 us e le 2000 iterazioni
  sono tutte completate;
- **non produce deadline miss**: `slack` resta positivo (2718 us). Il budget di
  10 ms assorbe un rallentamento di 3.6x del busy loop.

Il fattore 3.67 corrisponde a 2296/626 MHz, il che rende la **frequenza
effettiva** l'ipotesi principale. Il pin MSR era attivo e verificato dal
preflight, ma `pin_cpu_freq.sh` scrive la P-state *richiesta*: l'SMU puo'
scendere sotto P0 per i limiti STAPM del package da 15 W. La lettura di
`mhz_med` avviene **dopo** il run e riporta 2295, quindi non falsifica nulla.

**Contromisura per il blocco 3**: campionare `aperf`/`mperf` *durante* il run,
non dopo. E' l'unica misura che distingue "la CPU era lenta" da "il codice ha
fatto piu' lavoro".

## Risultato 4 — un solo deadline miss in tutta la campagna

Ratio 0.7, rip. 7, iterazione 1713:

```
run=1953   period=9999    slack=8038    wu_lat=7
run=1969   period=9998    slack=8022    wu_lat=7
run=1953   period=10031   slack=8038    wu_lat=39     <- wu_lat anomalo
run=11093  period=11094   slack=-1142   wu_lat=0      <- MISS
run=5631   period=8861    slack=3219    wu_lat=11
run=2638   period=9994    slack=7349    wu_lat=7
run=1986   period=9998    slack=8005    wu_lat=7      <- rientrato
```

Un evento singolo di ~9 ms su una CPU isolata, con HI in `SCHED_FIFO` 90 e boost
disabilitato: **1 miss su ~299 000 iterazioni** (tasso 3.3e-6). L'attivazione
era arrivata puntuale (delta fra `start` = 10040 us), quindi il ritardo e' nel
*lavoro*, non nello scheduling. La riga precedente ha `wu_lat`=39 contro i 7
abituali, quindi qualcosa disturbava gia' prima.

Non attribuibile a OTel: e' la cella Ratio 0.7, e le celle con piu' export
(AlwaysOn, 25/25 campionati) hanno **zero** miss.

Ipotesi non verificata: latenza di origine firmware (SMI), invisibile al kernel
e capace di durare millisecondi su un ultrabook con gestione termica via EC.
Lo strumento giusto e' `hwlatdetect` (pacchetto `rt-tests`), che misura proprio
le finestre in cui la CPU sparisce senza che il kernel se ne accorga. Da
eseguire una volta sulla piattaforma, indipendentemente dal DoE.

## Dati

`t2_p0_s<sampler>_r<ratio>_e1_n4/run_NN/` con `config.json`, `stdout.log.gz`
(span esportati), `stderr.log`, e un log per thread. Log gzippati: **739 MB ->
90 MB**. Ripartizione: log LO 82.5 MB, log HI 3.1 MB, stdout 0.1 MB — i log LO
pesano il 92 % e nel blocco 2 non sono analizzati.
