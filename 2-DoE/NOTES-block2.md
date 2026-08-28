# Blocco 2 — granularita' di campionamento

Documento tecnico. Versione discorsiva in `SPIEGAZIONE-block2.md`.
Script: `analyze_block2.py`. Dati grezzi: `block2/`, indice in `data_table.csv`.

## 1. Esecuzione

| | |
|---|---|
| data | 2026-08-28, **12:10:11 -> 13:05:21** |
| durata | **55m10s** (stima era ~55 min) |
| esito | exit 0, **150/150 run integri** |
| spazio | **134 MB** (stima era ~126 MB) |
| condizioni | freq pinnata (`turbo disabled: yes` agli atti nel runlog), shield `2,3,6,7`, `n_lo=4` |
| binari | 6 combinazioni `_e1` (exporter ostream), ricompilate dal sorgente **dopo** i fix di `4-fix-shutdown/` |

Disegno: `trace_level=2`, `processor=Batch`, 1 HI + 4 LO, 6 celle x 25 ripetizioni.
Fattore: il sampler (AlwaysOff, AlwaysOn, e ratio 0,1 / 0,3 / 0,5 / 0,7).

### 1.1 Primo tentativo abortito

Il primo lancio (11:01) e' morto con SIGSEGV al run 12/25. Due bug di memoria trovati
e corretti, vedi `4-fix-shutdown/`. Dati parziali scartati, blocco rilanciato da zero.
Questa esecuzione e' quella buona: **zero crash, zero run interrotti**.

### 1.2 Controlli di integrita'

```
run completi                        150 / 150
righe block2 in data_table.csv      150
log LO non gzippati                   0     <- un run interrotto li lascerebbe in chiaro
dimensioni distinte di HI_task-0.log  1     <- 247752 byte su tutti e 150
crash nel runlog                      0
```

La dimensione unica e' il controllo piu' forte: un processo morto lascia un log
troncato a un multiplo di 4096 (il run crashato del primo tentativo era 245760).

**Marcatore di run completo**: `test.sh` gzippa i log `LO_noise` come **ultimo** passo,
quindi la presenza dei `.gz` distingue in modo affidabile un run concluso da uno in
corso. Usato in `analyze_block2.py`.

---

## 2. Risultato principale — il sampler non separa mai HI da LO

| cella | n | campionati | osservato | IC 95% (Wilson) | nominale | **intermedi** |
|---|---|---|---|---|---|---|
| AlwaysOff | 25 | 0 | 0,0% | [0,0 – 13,3] | 0% | **0** |
| ratio 0,1 | 25 | 2 | 8,0% | [2,2 – 25,0] | 10% | **0** |
| ratio 0,3 | 25 | 10 | 40,0% | [23,4 – 59,3] | 30% | **0** |
| ratio 0,5 | 25 | 14 | 56,0% | [37,1 – 73,3] | 50% | **0** |
| ratio 0,7 | 25 | 19 | 76,0% | [56,6 – 88,5] | 70% | **0** |
| AlwaysOn | 25 | 25 | 100,0% | [86,7 – 100,0] | 100% | **0** |

Il conteggio per run e' **17 span oppure 0, mai altro**, su tutti e 150.

### 2.1 Perche' 17 e non 8

Il task 3 aveva misurato 8 span perche' girava con 2 thread. La formula e'
**`2 + n_thread x 3`**: `main` + `calibration`, piu' per ogni thread lo span del thread,
`thread_loop` e `phase`. Con `n_lo=4` sono 5 thread -> `2 + 15 = 17`.

Composizione verificata su un run campionato:

```
5 x thread_loop[0]     5 x phase[0]
1 x main               1 x calibration
1 x HI_task-0          4 x LO_noise-1..4
```

Questo conferma **direttamente** il bug di `count_exported_spans()`: solo lo span *del
thread* porta il nome della task, i 10 discendenti no. Vedi `3-exporter/NOTES.md` §8.

### 2.2 Come si legge il risultato

Vanno tenute separate due affermazioni di forza molto diversa.

**Debole — la frazione osservata segue il ratio nominale.** Vera e monotona
(0 -> 8 -> 40 -> 56 -> 76 -> 100%), e ogni valore nominale cade dentro l'IC di Wilson
della sua cella. Ma quegli intervalli sono **larghi 30-40 punti**: 25 ripetizioni non
bastano per affermare che il sampler campioni "esattamente il 30%". Nella relazione va
scritto **"coerente con"**, mai "verificato".

**Forte — il sampler non distingue mai HI dai LO.** Questa non e' una stima con un
intervallo attorno: e' un conteggio esatto, e fa **0 su 150**. Un valore intermedio
(diverso da 0 e da 17) sarebbe l'unica prova possibile che il sampler puo' dare destini
diversi ai due livelli di criticita'. Non si e' mai presentato.

I due controlli agli estremi rendono il dato piu' stretto: quando il campionamento e'
acceso entrano **tutti e cinque i thread**, quando e' spento **nessuno**.

### 2.3 Causa, gia' nota dal codice

`TraceIdRatioBasedSampler` decide guardando il `trace_id`. In rt-app ogni thread nasce
figlio di `main_span` (`span_opts.parent = main_span->GetContext()`), quindi HI e i
quattro LO **condividono un solo `trace_id`**. Il sampler non ha mai visto cinque task:
ha visto una trace, e l'ha accettata o scartata in blocco.

Il blocco 2 trasforma questa deduzione in misura: 150 occasioni, zero separazioni.

### 2.4 Corollario operativo

A ratio 0,1 il task critico perde la telemetria nel **90% delle esecuzioni** — non il
90% dei suoi span, il 90% delle esecuzioni *intere*. Con OTel standard non e'
esprimibile la politica che servirebbe davvero a un sistema mixed-criticality:
"HI sempre, LO al 10%". Materiale diretto per il **Task 6**.

---

## 3. Esperimento naturale — quanto costa l'export al task critico

Dentro le celle a ratio, stesso binario e stessa config: i run campionati e quelli
scartati differiscono **solo per l'esito del sorteggio**. Confrontarli isola il costo
di *esportare* da quello di *strumentare*.

| gruppo | run | run_med | per_std | slack_med | wu_med | wu_max | miss% |
|---|---|---|---|---|---|---|---|
| campionati (17 span) | 45 | 1963 | 2,1 | 8026 | 6 | 37 | 0,00 |
| scartati (0 span) | 55 | 1963 | 2,1 | 8026 | 7 | 35 | 0,00 |
| **delta** | | **+0** | **+0,0** | **+0** | **-1** | | |

**Identici.** Stessa cosa fra i due controlli:

| cella | run_med | per_std | slack_med | wu_med |
|---|---|---|---|---|
| AlwaysOff | 1955 | 2,1 | 8034 | 7 |
| AlwaysOn | 1955 | 2,1 | 8034 | 6 |
| **delta** | **+0** | **+0,0** | **+0** | **-1** |

**Conclusione**: a `trace_level=2` registrare ed esportare 17 span non ha **alcun costo
misurabile** sul task critico. Coerente con l'architettura — 17 span in 20 s sono
nulla, e il `BatchSpanProcessor` svuota la coda allo shutdown, fuori dalla finestra di
misura. I +30 us/giro misurati nel blocco 1 al livello 2 sono quindi il costo di
**creare** gli hook di instrumentazione, non di esportarli.

Questo e' un risultato negativo pulito e va riportato come tale: al livello 2 il
sampler e' gratuito. Il blocco 3, a `trace_level=3` (uno span per giro) e con il
processor Simple, e' il posto dove ci si aspetta che il costo si veda.

---

## 4. Il task critico sotto carico

```
run analizzati        150
giri totali        299400
deadline miss    0,000%  su TUTTE le celle
slack mediano      8026 us   (minimo osservato 7906)
wu_latency peggiore  40 us
```

`HI_task` non ha mai mancato una scadenza, con 4 thread best-effort che chiedono il
400% di cpu3 e con la telemetria attiva. Coerente con la validazione del task 2.

---

## 5. ANOMALIA APERTA — il jitter e' 5x MINORE sotto carico

Confronto a parita' di `trace_level=2`:

| | n | mediana | min | max |
|---|---|---|---|---|
| blocco 1, `n_lo=0` | 20 | **10,8 us** | 10,1 | 12,3 |
| blocco 2, `n_lo=4` | 50 | **2,1 us** | 2,0 | 3,9 |

Il task critico e' **piu' stabile con quattro thread di disturbo che a macchina
scarica**. Controintuitivo e robusto: 50 run contro 20, distribuzioni che non si
sovrappongono nemmeno agli estremi (max del blocco 2 = 3,9; min del blocco 1 = 10,1).

Si lega alla bimodalita' trovata nel blocco 1 alla baseline (meta' dei run a ~2,7 us,
meta' a ~16, niente in mezzo): **il valore "buono" del blocco 1 (~2,7) coincide con
quello del blocco 2 (2,1)**. Sembra che il carico di fondo *inchiodi* la macchina nel
regime buono, invece di degradarla.

### 5.1 Due spiegazioni possibili, non distinguibili con questi dati

1. **Effetto del carico.** Con cpu3 occupata il package resta in uno stato di
   alimentazione/frequenza costante, evitando transizioni che a macchina scarica
   introducono jitter.
2. **Confondente dell'exporter.** Il blocco 1 usava **Zipkin** (`_e0`), il blocco 2
   usa **ostream** (`_e1`). Senza collector, il `BatchSpanProcessor` di Zipkin tenta
   una connessione HTTP a ogni flush periodico (`schedule_delay` 5 s), cioe' **durante**
   il run; ostream scrive su stdout allo shutdown. I tentativi di connessione falliti
   potrebbero essere loro la sorgente del jitter.

**Non si puo' decidere con i dati attuali** e non va scritto in relazione finche' non
e' risolto.

### 5.2 Il blocco 3 e' il test

Il blocco 3 usa Zipkin (`_e0`) e ha celle a `trace_level=0` — **nessun tracing, nessun
exporter** — a `n_lo` = 0, 1, 4, 8. Se il jitter scende in modo monotono al crescere di
`n_lo` anche li', l'ipotesi 1 e' confermata e l'ipotesi 2 esclusa, perche' a
`trace_level=0` non c'e' nessun exporter.

**Da verificare esplicitamente in sede di analisi del blocco 3.**

---

## 6. Ricadute sul Task 5

1. `hi/lo_spans_exported` del blocco 2 e' **binario: 17 o 0**, non 8 o 0 (quello era il
   task 3 con 2 thread). Trattarlo come proporzione binomiale, con IC di Wilson.
2. `stdout.log` resta **vuoto finche' il run non e' finito** (flush allo shutdown):
   non contare gli span di un run in corso. Usare i `.gz` dei log LO come marcatore
   di completamento.
3. Il costo dell'export al livello 2 e' **zero misurabile**: non cercarlo nei dati del
   blocco 2, semmai nel blocco 3.
4. L'anomalia del §5 va risolta con i dati del blocco 3 prima di scrivere qualunque
   cosa sul jitter in funzione del carico.
