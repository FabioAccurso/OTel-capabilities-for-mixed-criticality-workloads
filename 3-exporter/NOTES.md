# Task 3 — macro `RTAPP_EXPORTER_TYPE` e sblocco del Blocco 2

Data: 2026-08-27. Frequenza pinnata, shield `cset` su `2,3,6,7`.

## 1. La macro

`rt-app_types.h`, accanto alle altre quattro:

```c
#ifndef RTAPP_EXPORTER_TYPE		// 0 = Zipkin (needs a collector), 1 = ostream
#define RTAPP_EXPORTER_TYPE 0	// (spans printed on stdout, greppable)
#endif
```

Default 0: un `make` senza flag si comporta esattamente come prima. Verificato
(`gcc -E -dM`): `RTAPP_EXPORTER_TYPE 0` insieme a `TRACE_LEVEL 0`, `PROCESSOR_TYPE 0`,
`SAMPLER_TYPE 0`, `SAMPLER_RATIO 0.5`.

In `main()` la chiamata diretta è stata sostituita dallo switch:

```c
	#if (RTAPP_EXPORTER_TYPE == 0)
	InitTracerZipkin();
	#elif (RTAPP_EXPORTER_TYPE == 1)
	InitTracer();
	#else
	#error "RTAPP_EXPORTER_TYPE must be 0 (Zipkin) or 1 (ostream)"
	#endif
```

## 2. Il blocco vero: `InitTracer()` ignorava tre macro su quattro

Questo era il finding (e) del task 0.3. `InitTracer()` aveva `AlwaysOnSampler` e
`BatchSpanProcessor` **cablati nel corpo della funzione** e non consultava
`RTAPP_SAMPLER_TYPE`, `RTAPP_SAMPLER_RATIO` né `RTAPP_PROCESSOR_TYPE`. Siccome il Blocco 2
del DoE fa variare esattamente quelle macro e conta gli span stampati dall'exporter
ostream, ogni cella avrebbe esportato gli stessi span: 150 run per misurare nulla.

Invece di duplicare i blocchi `#if` nelle due funzioni — che sarebbe la strada più corta
ma le farebbe divergere alla prima modifica — ho estratto la coda comune in un helper.
Entrambe le factory degli exporter restituiscono
`std::unique_ptr<opentelemetry::sdk::trace::SpanExporter>` (verificato negli header
installati), quindi fra Zipkin e ostream cambia solo l'exporter e il `service.name`:

```c
static void InstallTracerProvider(std::unique_ptr<trace_sdk::SpanExporter> exporter,
				  const char *service_name);

void InitTracer()       { InstallTracerProvider(OStream..., "rt-app_console"); }
void InitTracerZipkin() { InstallTracerProvider(Zipkin...,  "rt-app_zipkin");  }
```

I blocchi `#if` su processore e sampler vivono ora in un solo posto. Le due funzioni
pubbliche restano entrambe, quindi nessun chiamante esistente si rompe. Diff complessivo:
45 righe aggiunte, 41 rimosse su due file.

## 3. Anatomia di ciò che viene esportato

Config di prova: 1 HI + 1 LO, 5 s, `trace_level=2`, Batch, AlwaysOn.

```
main                                   (radice)
├── calibration
├── HI_task-0            attributo config.name: HI_task-0
│   └── thread_loop[0]
│       └── phase[0]
└── LO_noise-1           attributo config.name: LO_noise-1
    └── thread_loop[0]
        └── phase[0]

8 span in totale, tutti con lo STESSO trace_id
```

Attenzione: `graceful-shutdown` **non è uno span**, è un *evento* dentro lo span `main`
(riga 208-210 di `evidence/spans_alwayson_level2.log`). Compare fra i nomi se si conta con
`grep name`, ma le graffe aperte sono 8.

**Il conteggio non dipende dalla durata.** A `trace_level=2` gli span di fase sono uno per
*definizione* di fase, non uno per giro. Un run da 5 s e uno da 20 s esportano entrambi 8
span. A `trace_level=3` compaiono invece gli span per-giro:

| livello | span esportati (5 s) | stdout |
|---|---|---|
| 2 | **8** | 8 KB |
| 3 | **5508** (di cui 5499 `phase_loop[N]`) | **4,7 MB** |

Il nome degli span di thread è il nome **univoco** del thread (`HI_task-0`,
`LO_noise-1`). **Ma `analyze_doe.py:70` non li conta correttamente**: vedi §8.

Verifica incrociata: con `RTAPP_EXPORTER_TYPE=0` (Zipkin) lo `stdout.log` resta di 77 byte
(solo il messaggio di `cset`), come deve essere — gli span vanno in rete.

## 4. Le macro adesso funzionano davvero

| binario | sampler | span su stdout |
|---|---|---|
| `ostream_on` | AlwaysOn | **8** |
| `ostream_off` | AlwaysOff | **0** |
| `ostream_r05` | Ratio 0.5 | 0 o 8, vedi sotto |
| `zipkin_on` | AlwaysOn | 0 (vanno in rete) |

Il blocco del task 0.3 è chiuso: cambiando solo `RTAPP_SAMPLER_TYPE`, il numero di span
esportati cambia.

## 5. Finding principale: il ratio sampler NON distingue le criticità

Dodici ripetizioni dello stesso taskset con `TraceIdRatioBasedSampler(0.5)`:

| rep | span HI | span LO | totale |
|---|---|---|---|
| r01 | 0 | 0 | 0 |
| r02 | 1 | 1 | 8 |
| r03 | 0 | 0 | 0 |
| r04 | 1 | 1 | 8 |
| r05 | 0 | 0 | 0 |
| r06 | 0 | 0 | 0 |
| r07 | 0 | 0 | 0 |
| r08 | 0 | 0 | 0 |
| r09 | 0 | 0 | 0 |
| r10 | 1 | 1 | 8 |
| r11 | 0 | 0 | 0 |
| r12 | 1 | 1 | 8 |

(«span HI» = span il cui campo `name` è `HI_task-0`, cioè uno per run campionato.
`analyze_doe.py` ne riporterebbe 2, vedi §8.)

**In nessuna delle 12 ripetizioni HI e LO hanno avuto destini diversi.** O sono presenti
entrambi, o è assente tutto. Mai HI senza LO, mai LO senza HI. Il totale è sempre 8 o 0,
mai un valore intermedio.

È l'ipotesi centrale del progetto verificata sul campo, non più per lettura del codice:
`TraceIdRatioBasedSampler` decide in base al `trace_id`, e in rt-app **tutta l'esecuzione
condivide un solo `trace_id`** perché ogni thread è figlio di `main_span`. La decisione
è quindi presa una volta sola, per l'intera esecuzione: o si tiene tutto, o si butta
tutto. Non esiste alcun modo, con il sampler standard, di campionare i task critici più
dei task best-effort.

Frequenza campionata: 4 run su 12 (33%) contro un ratio configurato di 0,5. Con n=12 la
differenza è dentro il rumore binomiale, e comunque il punto qualitativo non dipende da
essa.

**Questo è il materiale per il Task 6**: un sampler custom che decidesse in base al *nome*
o agli *attributi* dello span invece che al `trace_id` permetterebbe a HI e LO di avere
ratio indipendenti pur restando nella stessa trace causale.

## 6. Cablaggio nel DoE

`run_doe.sh` non usava la macro, quindi la macro sarebbe rimasta inerte. Modificato:

- `build_bin()` accetta un quinto argomento `exporter` (default 0) e lo mette **nel tag
  della cache** (`t2_p0_s1_r0.5_e1`): due binari che differiscono solo per l'exporter sono
  binari diversi e non devono sovrascriversi.
- `run_cell()` accetta un nono argomento, sempre default 0.
- Le sei celle di `block2` lo passano a **1**. Il commento che diceva *"you must
  temporarily switch main() to use the ostream exporter"* è stato sostituito: non serve
  più toccare il sorgente.

Blocchi 1 e 3 restano su Zipkin (default 0), invariati.

## 7. Ricadute su Task 4 e Task 5

- **Stima disco del Task 1 aggiornata**: il blocco 2 usa `trace_level=2`, quindi 8 KB di
  `stdout.log` per run × 150 run ≈ **1,2 MB**. Trascurabile. Il caso da 4,7 MB si
  presenterebbe solo con `trace_level=3` **e** exporter ostream, combinazione che nessun
  blocco usa (il blocco 3 è a livello 3 ma su Zipkin, quindi stdout vuoto).
- **Il conteggio degli span del blocco 2 è binario per run** (8 o 0). Su 25 ripetizioni la
  frazione di run campionati stima il ratio con una precisione di circa ±0,1. È
  sufficiente per la domanda che il blocco pone, ma nel Task 5 va trattato come una
  proporzione binomiale, non come un conteggio continuo: media e deviazione standard sui
  conteggi grezzi non hanno senso qui.
- `analyze_doe.py` non richiede modifiche per il conteggio: i nomi degli span contengono
  già `HI_task` e `LO_noise`.

## 8. Bug trovato in `count_exported_spans()` (`analyze_doe.py:70`)

Segnalato da un compagno di corso e verificato sui nostri stdout reali. La funzione fa:

```python
content = f.read()
return content.count(name_substr)     # name_substr = "HI_task" / "LO_noise"
```

Conta le occorrenze della **sottostringa in tutto il file**, non gli span. Due problemi.

### 8.1 Conta doppio

Lo span del thread porta il nome della task **due volte**: nel campo `name` e
nell'attributo `config.name`.

```
  name          : HI_task-0
	config.name: HI_task-0
```

Misurato sui file in `evidence/`:

| livello | span veri con quel nome | `content.count()` | fattore |
|---|---|---|---|
| 2 | 1 | 2 | **2×** |
| 3 | 1 | 2 | **2×** |

Il fattore è esattamente 2 e costante, perché `config.name` è presente solo sullo span del
thread e mai sugli altri.

### 8.2 Problema più serio: non conta gli span della task

Solo lo span *del thread* si chiama come la task. I suoi discendenti —
`thread_loop[0]`, `phase[0]`, e a livello 3 le migliaia di `phase_loop[N]` — appartengono
alla task ma non ne portano il nome, quindi non vengono contati affatto.

A `trace_level=3`, HI_task produce **oltre 2700 span** e la funzione ne riporta **2**.

Per attribuire correttamente gli span alla task bisogna risalire la catena
`parent_span_id`, ricostruita in §3.

### 8.3 Ricaduta reale su questo DoE

Limitata, per fortuna. Il blocco 2 è l'unico che usa l'exporter ostream ed è a
`trace_level=2`, dove per run campionato si ha un solo span per task. Quindi
`hi_spans_exported` vale **2 se il run è stato campionato, 0 altrimenti**: sbagliato come
conteggio, ma pur sempre un indicatore binario corretto di "questo run è stato
campionato". La conclusione del §5 non cambia — HI e LO restano sempre entrambi 2 o
entrambi 0.

### 8.4 Correzione proposta (Task 5)

Minima, sufficiente per il blocco 2:

```python
return sum(1 for line in content.splitlines()
           if line.strip().startswith("name") and name_substr in line)
```

Restituisce 0 o 1 per run, cioè l'indicatore binario, senza il fattore 2. Se in futuro si
volesse contare davvero gli span per task (necessario solo se si usasse ostream a
`trace_level=3`), servirebbe risalire i `parent_span_id`.
