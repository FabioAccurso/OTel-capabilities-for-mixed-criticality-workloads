# Blocco 3 del DoE — contesa processor/exporter sotto carico crescente

Campagna del 2026-08-28. **180/180 run**, 12 celle x 15 ripetizioni da 20 s.
Output completo in `results.txt`, script `scripts/measurements/analyze_block3.py`.

## Configurazione

| | |
|---|---|
| trace_level | 0 (controllo) e 3 (volume massimo: main+thread+phase+phase_loop) |
| processor | Batch e **Simple** (solo a trace_level 3) |
| sampler | AlwaysOn |
| exporter | Zipkin (e0), **senza collector in ascolto** |
| n_lo | 0, 1, 4, 8 (LO su cpu6) |
| HI | SCHED_FIFO 90, cpu2, timer assoluto 10 ms |

Piattaforma: 2295 MHz su tutti e 180 i run, `aperf_mhz` 2285-2300 (media 2294.0),
Tctl 49.8 -> 56.1 C.

## Risultato 1 — `SimpleSpanProcessor` fa perdere deadline al task critico

E' il risultato centrale del blocco.

```
deadline miss (dopo lo scarto del transitorio)
braccio                n_lo=0     n_lo=1     n_lo=4     n_lo=8
trace0 (controllo)    0/29993    0/29969    0/29925    0/29862
trace3 Batch          0/29965    0/29950    0/29907    0/29841
trace3 Simple         0/29985    0/29835   12/29624    9/29544

slack minimo osservato [us]
trace0 (controllo)       3292        714       1361        109
trace3 Batch              181         78         65        203
trace3 Simple             441        326      -2453      -3631
```

**Zero miss** in tutte le celle di controllo e in tutte le celle Batch, a
qualunque carico. Con Simple e carico di sottofondo (n_lo >= 4) compaiono **21
deadline miss**, con margini negativi fino a **-3631 us**: il task critico sfora
di 3.6 ms su un periodo di 10 ms.

I miss **non sono un artefatto della terminazione**. I run Simple abortiscono
allo shutdown (vedi sotto) e perdono le ultime ~20 righe di log, quindi bisogna
verificare dove cadono. Sono distribuiti uniformemente:

```
quarto del run    0-25%  #####   5
                 25-50%  ######## 8
                 50-75%  #####   5
                75-100%  ###     3
primo miss a idx 41, ultimo a idx 1960
```

Nessun addensamento in coda: sono miss reali, causati dal processor.

## Risultato 2 — il costo per iterazione: 14 us contro 300

Variabile di risposta: il budget `run + slack` (blocco 1).

```
budget per iterazione [us], mediana [min-max fra le 15 ripetizioni]
braccio                    n_lo=0             n_lo=1             n_lo=4             n_lo=8
trace0 (controllo)  9991 [9991-9992]   9991 [9991-9992]   9992 [9991-9992]   9991 [9991-9992]
trace3 Batch        9977 [9976-9977]   9978 [9978-9979]   9978 [9978-9979]   9979 [9978-9979]
trace3 Simple       9686 [9678-9688]   9691 [9685-9693]   8689 [8683-9672]   9682 [9669-9690]

delta rispetto al controllo, stesso n_lo
trace3 Batch             -14.0              -13.0              -14.0              -12.0
trace3 Simple           -305.0             -300.0            -1303.0             -309.0
```

**Batch costa ~13 us per iterazione**, costante al variare del carico e coerente
con i ~13 us misurati nel blocco 1 per il livello 3. **Simple costa ~300 us**,
cioe' **23 volte tanto**: il 3 % del periodo e il **15 % del lavoro utile** di
2000 us.

**Attenzione alla cella Simple n_lo=4: e' BIMODALE**, non ha un outlier. Otto
ripetizioni stanno a ~8688 e sette a ~9665, con la mediana che cade sul gruppo
basso: il -1303 in tabella non descrive quindi un comportamento unico, e la
non-monotonia rispetto a n_lo=8 (-309) e' apparente. Il secondo modo vale ~980 us
in piu' per iterazione ed e' non spiegato.

## Risultato 3 — perche': 25 543 export sincroni contro 232

```
tentativi di export (righe 'ZIPKIN EXPORTER' su stderr, media per run)
braccio                n_lo=0     n_lo=1     n_lo=4     n_lo=8
trace0 (controllo)        0.0        0.0        0.0        0.0
trace3 Batch              7.9      117.5      236.9      231.5
trace3 Simple          2007.0    16044.9    25520.5    25543.4
```

`SimpleSpanProcessor::OnEnd` chiama `exporter_->Export()` **in modo sincrono, nel
thread che chiude lo span**, sotto uno spin-lock condiviso
(`simple_processor.h:60-70`). Ogni span chiuso da HI paga quindi una connessione
HTTP, e con n_lo=8 i nove thread si contendono lo stesso spin-lock 25 000 volte
per run. `BatchSpanProcessor` accoda e delega a un thread proprio: 232 tentativi
invece di 25 543, e il costo per HI resta a 13 us.

Si noti che **nessun collector era in ascolto**: gli export falliscono subito con
`ECONNREFUSED` su localhost, che e' il caso *piu' favorevole*. Con un collector
reale il costo di Simple sarebbe piu' alto, non piu' basso.

## Risultato 4 — Simple fa ABORTIRE il processo real-time

**40 run su 180 sono terminati con SIGABRT** (`exit_code` 134), tutti nel braccio
Simple:

```
cella                run   abort
trace3_Simple_n0      15       0
trace3_Simple_n1      15      11
trace3_Simple_n4      15      14
trace3_Simple_n8      15      15
```

Messaggio: `terminate called without an active exception`, subito dopo
`[rt-app] <notice> [0] Exiting.`. **Causa, verificata nel codice:**

1. `__shutdown()` di rt-app termina i thread con `pthread_cancel`
   (`rt-app.cpp:933`);
2. in glibc la cancellazione e' implementata lanciando un'eccezione di *forced
   unwind* nel thread bersaglio, per far girare i distruttori;
3. `SimpleSpanProcessor::OnEnd` e' dichiarato **`noexcept override`**
   (`simple_processor.h:60`), e un unwind che attraversa un `noexcept` chiama
   `std::terminate()`.

Con Simple il thread passa gran parte del tempo dentro `OnEnd` (export sincrono),
quindi il `cancel` lo colpisce li' con alta probabilita'; con Batch `OnEnd`
accoda e ritorna, e la finestra e' minuscola. La probabilita' si accumula col
numero di thread — misurata a parte su 3 tentativi per livello:

| thread | 1 | 2 | 3 | 5 | 9 |
|---|---|---|---|---|---|
| crash | 0/3 | 2/3 | 2/3 | **3/3** | **3/3** |

**Implicazione per l'elaborato**: la scelta del processor di telemetria non
degrada soltanto le prestazioni del task critico, **termina il processo**. E lo
fa in modo silenzioso rispetto ai dati, perche' l'abort arriva a lavoro finito.

**Effetto sui dati**: i run abortiti perdono le ultime **20 iterazioni** di log
(1980 invece di 2000, esattamente, in tutti e 34 i casi -> e' l'ultimo blocco di
buffer non scritto). `run_doe.sh` li accetta perche' valida sul contenuto (soglia
al 99 % delle iterazioni attese) e registra `exit_code`, invece di fermarsi
sull'exit status. Le analisi usano mediane su ~1974 iterazioni: il troncamento
dell'1 % in coda non le sposta, e la verifica sulla posizione dei miss (sopra)
esclude che introduca bias.

## Risultato 5 — l'ipotesi "frequenza" e' FALSIFICATA

Due run in regime anomalo su 180 (1.1 %, in linea con l'1.3 % dei blocchi
precedenti), e per la prima volta con `aperf_mhz` attivo:

```
trace0 (controllo)   n_lo=1  rip.12  run_med=4077 (2.04x)  aperf_mhz=2286
trace3 Batch         n_lo=0  rip.6   run_med=6584 (3.29x)  aperf_mhz=2286
```

**La CPU girava a 2286 MHz, non a 626.** L'ipotesi che il regime a ~3.5x fosse
causato da un calo della frequenza effettiva e' quindi **falsificata**: il lavoro
per iterazione cresce di un fattore 2-3.3 mentre la frequenza resta nominale.

E' il risultato per cui la colonna era stata aggiunta, e arriva senza aver dovuto
riprodurre il fenomeno a comando. Si noti anche che i due run anomali cadono in
celle **diverse** (una di controllo, senza alcun tracing, e una Batch): il
fenomeno **non dipende da OpenTelemetry**.

Ipotesi rimaste, in ordine di plausibilita':
1. **contesa SMT sul sibling cpu3**, dentro lo shield ma non controllato: il
   thread main e il worker del BatchSpanProcessor hanno `Cpus_allowed_list =
   2-3,6-7` (task 0.5). Un thread che finisca su cpu3 ruba unita' di esecuzione a
   HI su cpu2 senza toccare la frequenza — compatibile con un fattore 2-3.3;
2. pressione su cache/memoria.
Entrambe si distinguono con i contatori IPC di `perf stat` (istruzioni ritirate
per ciclo): se il lavoro e' lo stesso e i cicli aumentano, l'IPC crolla.
`hwlatdetect` e' gia' stato escluso (0 latenze su 435 s) ed e' comunque lo
strumento sbagliato per un rallentamento sostenuto.

## Dati

`t<trace>_p<proc>_s0_r0.0_e0_n<n_lo>/run_NN/` con `config.json`, `stdout.log`,
`stderr.log.gz` (tentativi di export), un log per thread. Gzippati: **756 MB ->
66 MB**. Ripartizione: log LO 55.5 MB, log HI 4.2 MB, stderr 1.2 MB.
