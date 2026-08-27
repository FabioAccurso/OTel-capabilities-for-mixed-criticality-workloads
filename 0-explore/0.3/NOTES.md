# Task 0.3 — exporter ostream: guardare uno span vero

## Cosa è stato modificato (e ripristinato)

Unica modifica, `rt-app/src/rt-app.cpp:1976`:

```c
-	InitTracerZipkin();
+	InitTracer();
```

`InitTracer()` (rt-app.cpp:111) era già presente nel codice del docente ma non veniva mai
chiamata: usa `OStreamSpanExporterFactory` (span stampati su `std::cout`),
`BatchSpanProcessor` con opzioni di default e `AlwaysOnSampler` fisso — non legge le macro
`RTAPP_PROCESSOR_TYPE`/`RTAPP_SAMPLER_TYPE`, a differenza di `InitTracerZipkin()`.

**Il sorgente è stato ripristinato** (`InitTracerZipkin()`) e ricompilato a fine task: la
versione pulita con la macro `RTAPP_EXPORTER_TYPE` è il Task 3. Il binario con ostream è
conservato in `bin/rt-app_T1_S0_ostream`.

Verifica funzionale dei due binari in cache (5 s ciascuno):

| binario | righe `ZIPKIN` su stderr | righe `trace_id` su stdout |
|---|---|---|
| `bin/rt-app_T1_S0` (ripristinato) | 1 | 0 |
| `bin/rt-app_T1_S0_ostream` | 0 | 3 |

Nota: `strings` **non** distingue i due binari — sia `rt-app_zipkin` sia `rt-app_console`
sono compilate in entrambi, perché `InitTracer()` è definita anche quando non è chiamata.
Serve una verifica funzionale. (Attenzione anche a `make`: `mv` del backup ripristina l'mtime
vecchio e make non ricompila — serve `touch src/rt-app.cpp`.)

## Come è stato costruito ed eseguito

```
cd rt-app/ && make clean
make CPPFLAGS="-DRTAPP_TRACE_LEVEL=1 -DRTAPP_SAMPLER_TYPE=0"
cd 0-explore/0.3/ && ../../bin/rt-app_T1_S0_ostream cfg_single.json > run_stdout.log 2> run_stderr.log
```

Config identica a 0.1/0.2. Frequenza CPU già fissata a P0 = 2300 MHz (vedi "Setup di
determinismo della piattaforma" in `CLAUDE.md`) → `pLoad = 29 ns`.

File: `run_stdout.log` (i 3 span), `run_stderr.log` (log nativo rt-app), `run2_ts.log`
(secondo run con timestamp relativi per vedere *quando* avviene l'export).
`rtapp-thread0-0.log` è quello del **secondo** run: rt-app sovrascrive il log a nome fisso.

## La struttura di uno span

```
{
  name          : thread0-0                            <- discriminante disponibile al Sampler
  trace_id      : 9a7fad0c0711fe571400addf9a6c60ed     <- 16 byte, IDENTICO per tutti e 3 gli span
  span_id       : 1ac0382bb378666a                     <- 8 byte, univoco per span
  parent_span_id: b4d917053bd322dd                     <- = span_id di "main"
  start         : 1787824628383222828                  <- ns dall'epoch Unix
  duration      : 4999942919                           <- ns (= 5.000 s, la "duration" del JSON)
  span kind     : Internal
  status        : Unset
  attributes    :
	cancellation: force_terminate
	config.sched_data.policy: SCHED_OTHER               <- la criticita' e' QUI
	config.sched_data.priority: 0
	config.name: thread0-0
	... (14 attributi in totale)
  events        :                                      <- (main ha "graceful-shutdown")
  resources     :
	service.name: rt-app_console                       <- da InitTracer(); Zipkin usa rt-app_zipkin
	telemetry.sdk.{name,language,version}: opentelemetry / cpp / 1.28.0
  instr-lib     : rt-app-tracer                        <- da get_tracer()
}
```

`cancellation: force_terminate` **non è un errore**: è il percorso normale quando scade la
`duration` del caso d'uso (rt-app.cpp:891-903, `__shutdown(true)`). Lo span `main` chiude
invece per la via "graceful" (rt-app.cpp:985-988), con tanto di evento.

## Gerarchia osservata (3 span, livello 1)

```
main            span_id b4d9…  parent 0000000000000000   (root)   9.041 s
├── calibration span_id 7366…  parent b4d9…                       4.039 s
└── thread0-0   span_id 1ac0…  parent b4d9…                       5.000 s
```

Albero piatto a 2 livelli: un thread = un figlio di `main`, non uno span per loop. Lo span
`thread0-0` dura esattamente la `duration` configurata; `main` ≈ calibrazione + thread.

## Finding 1 — trace_id unico: l'ipotesi centrale del progetto è confermata

Tutti e tre gli span portano `trace_id = 9a7fad0c0711fe571400addf9a6c60ed`. È la prova
diretta di ciò che `CLAUDE.md` dava come ipotesi da verificare: poiché in `thread_body()`
ogni thread nasce con `span_opts.parent = main_span->GetContext()` (rt-app.cpp:1462-1464),
**l'intera esecuzione condivide una sola trace**.

Conseguenza per `TraceIdRatioBasedSampler` (`RTAPP_SAMPLER_TYPE=1`): la decisione è una
funzione del solo `trace_id`, quindi con N task HI e M task LO nella stessa trace il
sampler non può che campionare **o tutto o niente**. Non esiste ratio che tenga i task
critici e scarti i best-effort. Da misurare quantitativamente al Blocco 2 del DoE, ma il
meccanismo è già visibile qui.

## Finding 2 — gli attributi NON sono visibili al Sampler (vincolo per il Task 6)

Lo span del thread porta `config.sched_data.policy` e `config.sched_data.priority`: la
criticità del task **è** nella telemetria. Ma non è utilizzabile per campionare, perché
l'interfaccia è:

```c
// otel-installdir/include/opentelemetry/sdk/trace/sampler.h:98
virtual SamplingResult ShouldSample(
    const SpanContext &parent_context, TraceId trace_id, nostd::string_view name,
    SpanKind span_kind, const KeyValueIterable &attributes,
    const SpanContextKeyValueIterable &links) noexcept = 0;
```

`ShouldSample` riceve solo gli attributi passati **dentro la chiamata a `StartSpan`**, e
rt-app non ne passa nessuno: `tracer->StartSpan(std::string(data->name), span_opts)`
(riga 1464) con `span_opts` che contiene solo il parent. Tutti i `SetAttribute` arrivano
**dopo** (righe 1470-1496), quando la decisione di campionamento è già stata presa.

Quindi un sampler custom per il Task 6 ha due sole strade:
1. **decidere sul `name`** — che `ShouldSample` riceve, ed è `data->name`, cioè il nome del
   task nel JSON. Costo zero sul codice esistente: basta chiamare i task HI e LO con un
   prefisso convenzionale (es. `hi_*` / `lo_*`) nelle config del Task 2;
2. **passare la criticità come attributo a `StartSpan`**, il che richiede di modificare la
   riga 1464 (`StartSpan(name, attributes, span_opts)`).

La strada 1 è preferibile: non tocca il codice del docente e va decisa nel Task 2.

## Finding 3 — l'ostream exporter è utilizzabile per contare gli span

Nessun collector richiesto, nessun errore, gli span finiscono su **stdout** mentre il log
nativo di rt-app resta su **stderr**: i due flussi sono separabili con una redirezione.
È esattamente ciò che serve al Blocco 2 del DoE (`hi_spans_exported` / `lo_spans_exported`
= `grep -c` sul nome dello span), e risolve il problema di 0.2 dove l'exit status 0 non
diceva nulla sull'effettivo export. Conferma che il Task 3 (macro `RTAPP_EXPORTER_TYPE`)
serve davvero.

## Finding 4 — quando avviene l'export (run con timestamp)

`run2_ts.log`:

```
[  0.014s] Calibrate ns per loop
[  5.186s] pLoad = 29ns : calib_cpu 0
[  5.194s] [0] Starting with SCHED_OTHER policy with priority 0
[ 10.194s] {  name : calibration     <- tutti e 3 gli span in un colpo solo,
[ 10.194s] {  name : thread0-0          al flush di shutdown
[ 10.195s] {  name : main
```

A differenza di 0.2 (dove un export cadde a ~10 s durante il run) qui **non c'è nessun
export durante l'esecuzione**: lo span `calibration` ha chiuso a 5.186 s, cioè appena
*dopo* il tick a 5 s del BatchSpanProcessor, e ha trovato la coda vuota. Tutto è uscito al
flush finale. Con 3 soli span di lunga durata l'export è quindi essenzialmente un evento
di shutdown, e il suo timing dipende da dove cade la fine della calibrazione rispetto al
tick — un'altra ragione per fissare `"calibration": 29` invece di lasciarla variare.

Nota collegata: la calibrazione ha impiegato **4.039 s** nel primo run e **5.172 s** nel
secondo (span `calibration`), pur con la frequenza fissata. Il pin di frequenza ha reso
deterministico il *valore* di pLoad (29 ns in entrambi) ma non il *tempo* impiegato a
trovarlo: l'euristica di `calibrate_cpu_cycles_1()` esce dopo un numero variabile di
tentativi da 1 s l'uno.

## Cosa portare avanti

- Task 2: nominare i task nel JSON con prefisso `hi_`/`lo_` — abilita il sampler per nome
  del Task 6 senza modificare il codice del docente.
- Task 3: macro `RTAPP_EXPORTER_TYPE` (0=Zipkin, 1=ostream), sostituendo la riga 1976.
- Task 4: contare gli span con `grep -c` su stdout; `"calibration": 29` in tutte le config.
- Task 6: il sampler custom deve agire su `name` (o su attributi passati a `StartSpan`),
  non su `trace_id`.
