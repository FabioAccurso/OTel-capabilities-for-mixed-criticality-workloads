# Indicazioni post-incontro con i docenti (2026-09-04)

**A chi e' rivolto questo file**: all'agente Claude Code che lavora su questo branch
(`feat/setup-piattaforma-e-task-0x`) insieme a Benito. Descrive **due esperimenti nuovi**
richiesti dai docenti dopo la presentazione dei risultati attuali, e li descrive in modo
operativo: cosa costruire, cosa variare, cosa misurare, e quali trappole sono gia' state
individuate leggendo il codice.

**Chi ha scritto questo file non ha eseguito nulla.** Tutte le affermazioni sul codice sono
state verificate leggendo i sorgenti reali su questo branch, e riportano `file:riga` proprio
perche' tu possa ricontrollarle invece di fidarti. Tutte le affermazioni sui *risultati*
vengono da `2-DoE/REPORT.md` e da `2-DoE/results.csv`, che sono stati riverificati sui dati
grezzi (485 run, 40 abort, 22 deadline miss, 0 run parziali su 150: tornano).

---

## 0. Regole d'ingaggio

Prima di toccare qualunque cosa:

1. **Leggi `CLAUDE.md`**, in particolare "Regole operative", "Stato del repository" e le
   sezioni Task 4 e Task 5. Le regole di quel file valgono anche qui: un task alla volta,
   su richiesta esplicita, e niente merge da `origin/main`.
2. **Non rifare i blocchi 1, 2 e 3.** Sono chiusi, analizzati e presentati. I dati stanno in
   `2-DoE/block{1,2,3}/` e `2-DoE/diag/`. Le campagne nuove si **aggiungono** come `block4` e
   `block5`, non sostituiscono niente.
3. **`data_table.csv` si accoda, non si riscrive.** `run_doe.sh` ha gia' la migrazione
   automatica dello schema con backup (`*.pre-aperf.bak`, `*.pre-exitcode.bak`): se aggiungi
   colonne, segui lo stesso schema.
4. **La piattaforma e' quella di Benito** (ASUS UX431DA, Ryzen 7 3700U). Il pin di frequenza
   e le costanti (`calibration: 29`, P0 = 2300 MHz) valgono solo li'. `pin_cpu_freq.sh` si
   rifiuta di girare su CPU non AMD, quindi non c'e' rischio di eseguire per sbaglio altrove,
   ma **le campagne vanno lanciate sulla stessa macchina delle precedenti**, altrimenti i
   confronti con i blocchi 1-3 non reggono.
5. **Preflight sempre**: `run_doe.sh` si ferma da solo se manca lo shield o se il boost e'
   riattivato. Non aggirarlo.

---

## 1. Cosa hanno chiesto i docenti

Testualmente, due aggiunte:

> **(1)** Fare esperimenti aggiungendo un backend che *veramente* riceve gli span, per
> valutarne l'impatto sia con `Batch` sia con `Simple`, e studiare il compromesso migliore
> per scegliere quale delle due strategie sia preferibile (pro e contro). Provare backend
> che raccolgono span **sia su rete sia su file**, per capire la strategia migliore.
>
> **(2)** Partire dalla configurazione dei parametri che riteniamo migliore sulla base delle
> analisi fatte, e cercare di capire come migliorarla, eventualmente usando il **meccanismo
> di labeling che rt-app gia' possiede** per riconoscere task ad alta e bassa priorita'.

La richiesta (1) colma un limite che avevamo **gia' dichiarato** in `2-DoE/REPORT.md`
("Limiti e questioni aperte", punto 3): tutta la campagna e' girata **senza collector in
ascolto**. La richiesta (2) e' la verifica sperimentale della proposta del Task 6, che oggi
esiste solo su carta in `3-report/body6.tex`.

---

## 2. Blocco 4 — backend reale, rete contro file

### 2.1 Perche' serve, in una frase

Oggi tutti i numeri di consegna sono presi contro un endpoint **irraggiungibile**: gli export
falliscono immediatamente con `ECONNREFUSED` su `localhost`. E' il caso **piu' favorevole**
possibile, e va detto che i ~300 us/iterazione del `SimpleSpanProcessor` sono quindi un
**limite inferiore**: non il costo di esportare, ma il costo di *tentare* un export che
fallisce subito. Con un backend che risponde davvero, il costo puo' solo salire.

C'e' pero' un secondo effetto, opposto e piu' interessante, che senza backend **non e'
osservabile per costruzione**: il `BatchSpanProcessor` ha una coda finita
(`max_queue_size = 2048`, cablata in `rt-app.cpp:127` e `rt-app.cpp:173`) e quando e' piena
**scarta gli span in silenzio** (documentato in
`otel-installdir/include/opentelemetry/sdk/trace/batch_span_processor_options.h:68`). Oggi non
lo vediamo perche' senza collector nessuno conta cosa e' arrivato. Con un backend vero
possiamo confrontare **span prodotti contro span arrivati**.

Questa e' la vera tesi del blocco 4, ed e' esattamente il "pro e contro" che i docenti
chiedono:

> **Batch protegge il task critico ma puo' perdere telemetria; Simple consegna tutto ma fa
> perdere le scadenze e termina il processo.** Il compromesso non e' fra due livelli di
> prestazione: e' fra *perdere dati* e *perdere deadline*.

Se i dati confermano questa asimmetria, e' un risultato forte e presentabile. Se invece Batch
non perde nulla nemmeno sotto carico, il risultato e' altrettanto utile: significa che Batch
domina Simple su tutti gli assi e la scelta e' obbligata. **Vanno bene entrambi gli esiti:
non spingere i dati verso il primo.**

### 2.2 I tre backend da confrontare

| braccio | come | cosa isola |
|---|---|---|
| `none` | nessun collector (stato attuale) | riferimento, gia' misurato nei blocchi 1-3 |
| `file` | exporter ostream su `std::ofstream` | serializzazione + scrittura locale |
| `net` | exporter Zipkin verso un collector reale | serializzazione + HTTP + syscall di rete |

Consiglio di aggiungere una **quarta variante diagnostica**, poco costosa e molto informativa:
`file` su **tmpfs** (`/dev/shm/...`) accanto a `file` su disco. La differenza fra le due
separa il costo di *formattare* lo span da quello di *scriverlo su un dispositivo*. Se sono
uguali, il collo di bottiglia e' la serializzazione e il disco non c'entra.

### 2.3 Come si realizza il backend "file" — e' piu' semplice di quanto sembri

**Non serve una libreria nuova, non serve toccare `Makefile.am`.** L'exporter ostream ha gia'
una factory che accetta uno stream qualunque, verificato in
`otel-installdir/include/opentelemetry/exporters/ostream/span_exporter_factory.h:32`:

```cpp
static std::unique_ptr<opentelemetry::sdk::trace::SpanExporter> Create(std::ostream &sout);
```

Oggi `InitTracer()` (`rt-app.cpp:118`) chiama la versione senza argomenti, che scrive su
`std::cout`. Nel blocco 2 lo stdout veniva rediretto su `stdout.log` da `test.sh`, quindi in
un certo senso un "backend file" c'e' gia' stato — ma **passava dal terminale**, e stdout puo'
essere bufferizzato diversamente da un file aperto direttamente.

Due strade, in ordine di preferenza:

- **(a) Estendere `RTAPP_EXPORTER_TYPE`** con un valore nuovo (es. `2 = ostream su file`), che
  apre un `std::ofstream` verso un percorso preso da variabile d'ambiente (es.
  `RTAPP_SPAN_FILE`, con un default sensato). Lo stream deve avere **durata di vita almeno
  pari a quella del provider**: un `static std::ofstream` dentro la funzione va bene, una
  variabile locale **no** (l'exporter conserva il riferimento e scriverebbe su uno stream
  distrutto). Questo e' il punto in cui e' piu' facile introdurre un bug silenzioso: fai
  attenzione.
- **(b)** Tenere `RTAPP_EXPORTER_TYPE=1` e limitarsi a redirigere stdout su file, accettando
  che si stia misurando anche il percorso stdout. Piu' rapido, meno pulito. Se scegli questa,
  **dichiaralo** nel `NOTES.md` del blocco.

Se estendi la macro, ricordati che `run_doe.sh` include `RTAPP_EXPORTER_TYPE` **nel tag della
cache dei binari** (`build_bin()`, `..._e<N>`): il valore nuovo produce un binario nuovo senza
che tu debba fare niente, ma **svuota `bin/`** se cambi la semantica di un valore esistente.

### 2.4 Come si realizza il backend "rete"

**Non serve ricompilare per cambiare endpoint.** `ZipkinExporterOptions` legge la variabile
d'ambiente `OTEL_EXPORTER_ZIPKIN_ENDPOINT`, verificato in
`otel-installdir/include/opentelemetry/exporters/zipkin/zipkin_exporter_options.h:19-30 e 43`.
Il default e' `http://localhost:9411/api/v2/spans`. Quindi porta e host si scelgono da
`run_doe.sh` senza toccare il sorgente.

**Quale collector.** Serve qualcosa che regga il volume. Dal blocco 3 sappiamo che a
`trace_level=3`, `n_lo=8`, `Simple` fa **25 543 tentativi di export per run da 20 s**, cioe'
~1 300 POST sincrone al secondo, ognuna con attesa della risposta. In ordine di preferenza:

1. **Zipkin ufficiale in Docker** (`openzipkin/zipkin`), che e' il backend per cui l'exporter
   e' scritto e regge quel carico senza problemi;
2. **OpenTelemetry Collector** con receiver `zipkin`, se preferite lo strumento "di famiglia";
3. un server HTTP scritto da voi **solo se multi-thread o asincrono**.

> **Trappola, gia' pagata sull'altro ramo del progetto.** Un `HTTPServer` Python monothread
> come collector diventa lui il collo di bottiglia, *dentro* il percorso critico del task RT
> quando il processor e' `Simple`: staresti misurando la lentezza del tuo collector finto, non
> il costo di OpenTelemetry. Se usi una soluzione fatta in casa, **misura prima quanti POST/s
> regge a vuoto** e documentalo. Se non arriva comodamente sopra i 1 300/s, non usarla.

### 2.5 Dove far girare il collector — non e' un dettaglio

**Il collector deve girare sulle CPU di housekeeping (0,1,4,5), mai dentro lo shield.**

Se finisce su 2,3,6,7 stai misurando la contesa fra collector e task critico sullo stesso
core, che e' un altro esperimento e confonde tutto. Il modo giusto e' lanciarlo con
`taskset -c 0,1,4,5` **fuori** da `cset shield --exec`, e **verificare** dopo l'avvio che il
suo `Cpus_allowed_list` sia davvero quello (`grep Cpus_allowed_list /proc/<pid>/status`).

Aggiungi questa verifica al **preflight** di `run_doe.sh` per il solo blocco 4: se il
collector non risponde, oppure risponde ma gira sulle CPU sbagliate, la campagna deve
**fermarsi**, non proseguire. E' esattamente il tipo di errore che si scopre a campagna
finita — `CLAUDE.md` (Task 4) racconta gia' un caso in cui 80 run sono stati buttati per un
motivo analogo.

### 2.6 La metrica di consegna va rifatta da capo

**Questo e' il punto piu' importante di tutta la sezione. Leggilo due volte.**

La colonna `export_attempts` oggi conta le righe `ZIPKIN EXPORTER` su `stderr`
(`analyze_doe.py`, costante `ZIPKIN_RE`), cioe' conta i **fallimenti di connessione**. Con un
collector che funziona quelle righe **non compaiono**: `export_attempts` andra' a **0** in
tutti i run del braccio `net`.

Se non te ne accorgi, leggerai "zero export" e concluderai che non e' stato esportato niente,
mentre e' vero l'esatto contrario. La colonna va **mantenuta** (nel braccio `none` serve
ancora) ma **rinominata mentalmente** in "tentativi falliti", e affiancata da una misura vera.

Le tre quantita' da avere, per ogni run:

| quantita' | come si ottiene |
|---|---|
| **span prodotti** | analitica: a `trace_level=2` sono `2 + 3 x n_thread` (17 con `n_lo=4`, verificato sul campo nel blocco 2). A `trace_level=3` si deriva dal numero di iterazioni nei log |
| **span consegnati** | lato **backend**: interrogando l'API del collector, oppure contando le righe di intestazione nel file del braccio `file` |
| **span persi** | differenza fra i due |

Per il braccio `file` il conteggio e' identico a quello che `analyze_doe.py` fa gia' su
`stdout.log` (regex `NAME_RE`, `^  name +: ...`): riusa quella, non riscriverla.

Per il braccio `net` serve un modo di contare lato collector. Va deciso **prima** di lanciare:
se usi Zipkin, l'API di interrogazione delle tracce; se usi un collector fatto in casa, un
contatore interno che scrivi su file a fine run. **Azzera o isola lo stato del collector fra
un run e l'altro**, altrimenti i conteggi si sommano fra ripetizioni.

Suggerimento pratico: fai fare il conteggio a `run_doe.sh` subito dopo ogni run, e scrivilo
come colonna nuova in `data_table.csv` (es. `spans_delivered`). Ricostruirlo dopo, a campagna
finita, e' molto piu' fragile.

> **Nota su `Batch` e i conteggi.** `export_attempts` per Batch non e' un numero di span: il
> Batch spedisce **lotti**, quindi 209 "tentativi" possono contenere migliaia di span. Non
> confrontare mai direttamente `export_attempts` di Batch con quelli di Simple come se fossero
> la stessa unita' di misura. Il blocco 3 li usa correttamente solo come indicatore di
> *frequenza di contatto col backend*, ed e' bene che resti cosi'.

### 2.7 Disegno proposto

Fattori: **backend** {`none`, `file`, `file-tmpfs`, `net`} x **processor** {Batch, Simple}.

Suggerisco `trace_level=3` (volume massimo, e' li' che le differenze si vedono) e **due**
livelli di carico, `n_lo` {0, 4}, per non far esplodere la matrice. Il braccio `none` e'
gia' misurato nel blocco 3 per `n_lo` 0 e 4: **riusalo invece di rifarlo**, verificando pero'
che le condizioni siano identiche (stesso binario, stesso `trace_level`, stesso `n_lo`).

Con 3 backend nuovi x 2 processor x 2 carichi x 15 ripetizioni = **180 run**, cioe' la stessa
taglia del blocco 3 (~63 minuti li'). E' una sessione sola. Se il tempo stringe, taglia
`file-tmpfs` prima di tagliare le ripetizioni.

**Ordine interlacciato**, come gia' fa `run_doe.sh`: ripetizione 1 di tutte le celle, poi
ripetizione 2, eccetera. Non tutte le ripetizioni di una cella in fila.

### 2.8 Cosa aspettarsi (ipotesi, non conclusioni)

Scritte qui perche' tu sappia cosa guardare, **non** perche' le dai per vere:

- `Simple` + `net` dovrebbe essere il caso peggiore in assoluto: ogni span paga un round-trip
  HTTP **completo** dentro il thread che chiude lo span, sotto spin-lock condiviso
  (`simple_processor.h:60-70`, `Export()` sincrono dentro `OnEnd` con
  `std::lock_guard<SpinLockMutex>`). Aspettati **molto** peggio dei ~300 us attuali, e
  probabilmente deadline miss anche a `n_lo=0`.
- `Simple` + `file` dovrebbe essere sensibilmente meno grave: niente rete, niente attesa di
  risposta. Se anche li' il costo resta alto, il problema e' la serializzazione e lo spin-lock,
  non il trasporto — che sarebbe un risultato piu' profondo e va detto.
- `Batch` dovrebbe restare piatto (~13 us) in tutti i bracci, **ma perdere span** dove il
  volume supera la coda. Il punto in cui inizia a perdere e' il risultato piu' interessante
  dell'intero blocco 4.
- Gli abort da `SIGABRT` dovrebbero **aumentare** nel braccio `Simple` + `net`: la causa e' che
  il thread viene cancellato mentre si trova dentro `OnEnd`, e con la rete ci passa piu' tempo.
  Registra `exit_code` come gia' si fa.

---

## 3. Blocco 5 — dalla configurazione migliore a una consapevole della criticita'

### 3.1 Punto di partenza: qual e' "la nostra configurazione migliore"

Dai dati dei blocchi 1-3, la configurazione che il progetto raccomanderebbe oggi e':

| parametro | valore | perche' |
|---|---|---|
| `RTAPP_PROCESSOR_TYPE` | **0 (Batch)** | 13 us/iterazione contro 300, 0 abort contro 40, 0 deadline miss a qualunque carico |
| `RTAPP_TRACE_LEVEL` | **2** | overhead non misurabile (blocchi 1 e 2); il livello 3 costa ~13 us/iterazione |
| `RTAPP_SAMPLER_TYPE` | **0 (AlwaysOn)** | il ratio non protegge il task critico: a ratio 0.1 nell'84 % dei run non esiste alcuna traccia di HI |
| `RTAPP_EXPORTER_TYPE` | 0 (Zipkin) | caso d'uso realistico |

**Fai confermare questa scelta a Fabio e Benito prima di costruirci sopra**, perche' e'
un'inferenza mia dai loro dati, non una loro dichiarazione esplicita.

Il limite di questa configurazione e' evidente e va enunciato cosi': **l'unico modo di
ridurre il volume di telemetria e' il campionamento proporzionale, che pero' e' cieco alla
criticita' — quindi si e' costretti ad AlwaysOn, cioe' a pagare per intero anche la
telemetria dei task best-effort che non interessa a nessuno.** Il blocco 5 rimuove
esattamente questo vincolo.

### 3.2 Il "labeling" di rt-app: cosa c'e' davvero — leggi con attenzione

I docenti hanno accennato a un meccanismo di labeling gia' presente in rt-app. **Esiste, e si
chiama `taskgroup`**, ma ha un vincolo che ne impedisce l'uso diretto nel nostro scenario.
Verificato nel codice, non dedotto:

- `taskgroup` e' una chiave JSON valida per un task o una fase, letta da
  `parse_taskgroup_data()` in `rt-app_parse_config.cpp:923-948`;
- e' implementato con i **cgroup**: `rt-app_taskgroups.{h,cpp}`, piu' gli helper
  `enter_cgroup()` / `exit_cgroup()` in `rt-app.cpp:249-291`, che agiscono su
  `/sys/fs/cgroup/rt-app-cgroup/`;
- **e non e' compatibile con le politiche real-time.** `check_taskgroup_policy_dep()`
  (`rt-app_parse_config.cpp:950-977`) contiene questo controllo:

  ```c
  if (policy != other && policy != idle) {
          log_critical(PIN2 "No taskgroup support for policy %s", ...);
          exit(EXIT_INV_CONFIG);
  }
  ```

  Cioe': **un task con `taskgroup` che non sia `SCHED_OTHER` o `SCHED_IDLE` fa uscire rt-app
  con errore di configurazione.** Il nostro `HI_task` e' `SCHED_FIFO` priorita' 90, quindi
  `taskgroup` **non e' applicabile al task critico** senza rinunciare alla politica RT, che e'
  il cuore dell'elaborato.

**Questo va riportato ai docenti**, non nascosto: e' un risultato in se'. Il meccanismo di
etichettatura che rt-app possiede e' pensato per il *raggruppamento in cgroup ai fini dello
scheduling*, non per l'osservabilita', ed e' mutuamente esclusivo con le politiche real-time
nella validazione di rt-app stesso.

### 3.3 Il labeling che invece si puo' usare

Tre fatti, tutti verificati, che insieme definiscono lo spazio delle soluzioni.

**Fatto 1 — il sampler vede solo il nome.** `ShouldSample` riceve il nome dello span e i soli
attributi passati *dentro* `StartSpan`. In `thread_body()` la creazione e':

```cpp
data->span = tracer->StartSpan(std::string(data->name), span_opts);   // rt-app.cpp:1484
```

senza attributi, e i `SetAttribute` con politica e priorita' arrivano **dopo**
(`rt-app.cpp:1490-1516`), quando la decisione di campionamento e' gia' stata presa. Quindi
**oggi l'unico discriminante disponibile al sampler e' il nome del task**, che nelle nostre
config e' gia' `HI_task` / `LO_noise`. Il finding e' del task 0.3, `0-explore/0.3/NOTES.md`.

**Fatto 2 — i discendenti non portano l'identita' del task.** Gli span interni si chiamano
`thread_loop[N]`, `phase[N]`, `phase_loop[N]` (`rt-app.cpp:1598`, `1607`, `1623`): nessuno
contiene il nome della task. Un sampler basato sul nome saprebbe filtrare **lo span del
thread**, ma **non i suoi discendenti**, che a `trace_level=3` sono la quasi totalita' del
volume. Questo e' il motivo tecnico per cui il solo intervento sul nome **non basta**, ed e'
piu' sottile di come e' scritto oggi in `3-report/body6.tex`: vale la pena precisarlo li'.

**Fatto 3 — c'e' gia' una traccia di come separare le trace.** In `rt-app.cpp:1615-1621` c'e'
un blocco **commentato** dall'autore originale che stacca il contesto corrente
(`RuntimeContext::Attach(empty_context)`) per far nascere ogni `phase_loop` su una trace
propria, con tanto di commento "To get each phase loop on a different trace (to test
Sampler)". E' il meccanismo giusto applicato al livello sbagliato: a noi serve **per thread**,
non per phase loop. Leggilo prima di reinventarlo.

### 3.4 I due interventi, e perche' servono entrambi

**Intervento A — rendere la criticita' visibile al momento della decisione.**

Due strade:

- *per convenzione sul nome*: costo zero sul codice, funziona subito perche' le config usano
  gia' `HI_task` / `LO_noise`. Fragile: lega la politica a una convenzione di naming;
- *passando la criticita' come attributo dentro `StartSpan`*: una riga in `rt-app.cpp:1484`,
  usando l'overload che accetta attributi. Piu' pulito e piu' difendibile in relazione.

Suggerimento: **implementa il sampler in modo che accetti entrambe** (prima cerca l'attributo,
in mancanza ricade sul prefisso del nome). Costa poco e rende l'esperimento robusto.

**Intervento B — dare a ogni thread la propria trace.**

E' quello essenziale, per il Fatto 2. Finche' i discendenti ereditano il contesto di un unico
`main_span`, non esiste modo di distinguerli per criticita'. Ogni thread deve **iniziare una
trace propria** (span radice), mantenendo la relazione causale con l'esecuzione principale
tramite un **Link** invece che tramite la parentela.

Conseguenza da non perdere di vista: cambiando la struttura delle trace, **il conteggio degli
span del blocco 2 non e' piu' confrontabile** con quello nuovo (la formula `2 + 3 x n_thread`
vale per l'albero attuale). Va ricalcolata e documentata.

Nota sulla composizione col sampler: se ogni thread ha la sua trace e vuoi che i discendenti
**ereditino** la decisione presa sulla radice, il sampler custom va composto con
`ParentBasedSampler` (radice = sampler consapevole della criticita', figli = eredita). E' il
modo pulito per non dover riconoscere la criticita' su `phase_loop[7]`. Verifica l'API reale
in `otel-installdir/include/opentelemetry/sdk/trace/samplers/parent.h` **prima** di scrivere
codice: non dare per buona la mia descrizione.

### 3.5 Cosa misurare

L'esperimento chiave e' **la ripetizione dell'Esperimento 2 con il sampler nuovo**, ed e' bello
perche' la figura che oggi documenta il limite diventa la verifica del suo superamento.

Configurazione: identica al blocco 2 (`trace_level=2`, Batch, exporter ostream, 1 HI + 4 LO,
25 ripetizioni), cambiando **solo** il sampler. Ratio applicato ai soli LO: 0.1 / 0.3 / 0.5 /
0.7, con HI sempre conservato.

Il risultato atteso e' che i punti si dispongano **nella banda intermedia** della
figura `2-DoE/figures/01_all_or_nothing.png`, oggi vuota: span di HI presenti in **25 run su
25** a ogni ratio, span di LO ridotti secondo la proporzione. La condizione di successo va
scritta **prima** di guardare i dati, ed e' netta:

> **span HI presenti in 25/25 run a ogni livello di ratio** (contro i 4/25 di oggi a ratio 0.1),
> con la frazione di span LO coerente col ratio nominale.

E poi il costo, con l'impostazione dell'Esperimento 1: un sampler che esamina nome o attributi
e' piu' oneroso di uno che valuta un intero, e la decisione si prende a **ogni** creazione di
span. Ci si aspetta che sia trascurabile, ma su un sistema real-time va misurato e non dato per
acquisito. Usa `budget_med_us` come sempre, **mai** `run` o `period` (vedi §3.6).

### 3.6 Avvertenze metodologiche che valgono per entrambi i blocchi

Sono gia' costate errori a questo progetto. Non ripeterli:

1. **La variabile di risposta e' `budget = duration + slack`**, mai `run` da sola (dipende dal
   layout del binario per ~30 us, piu' del segnale) e mai `period` (si *accorcia* dove
   l'overhead cresce). Vedi `analyze_doe.py`, nota 4 nel docstring.
2. **Lo scarto del transitorio di avvio e' variabile**, non fisso: scala col numero di thread
   (1, 2, 5, 10 righe per `n_lo` 0, 1, 4, 8). `analyze_doe.py` lo gestisce gia' scartando
   finche' lo slack non diventa >= 0 e registrando `warmup_rows`. **Non sostituirlo con uno
   scarto fisso.**
3. **I deadline miss si SOMMANO fra ripetizioni, mai si mediano.** La mediana di una cella con
   6 miss su 5 run di 15 vale 0,00 % e cancellerebbe il risultato.
4. **Riporta sia deviazione standard sia IQR** per il jitter: dove divergono di due ordini di
   grandezza il fenomeno e' fatto di incidenti isolati, non di degrado diffuso.
5. **Le celle bimodali non si riassumono con la mediana.** Ne conosciamo gia' una (`Simple`,
   `n_lo=4`, blocco 3): descrivila con le due mode e la ripartizione.
6. **Il regime anomalo a 2-3.7x esiste**, si presenta all'1.1-1.3 % dei run, **non** dipende da
   OpenTelemetry (compare anche in celle senza tracing) e l'ipotesi frequenza e' gia'
   **falsificata** da `aperf_mhz`. Se ricompare, registralo ed escludilo dalle mediane
   dichiarandolo; non spenderci la campagna.
7. **Un solo `NOTES.md` per blocco**, nella cartella del blocco, piu' l'aggiornamento di
   `CLAUDE.md`. E, come da preferenza di Fabio, **anche una `SPIEGAZIONE.md` discorsiva**
   accanto alle note tecniche.

---

## 4. Ordine di lavoro consigliato

1. **Far confermare** a Fabio e Benito la "configurazione migliore" di §3.1 e la scelta del
   collector di §2.4. Sono le due decisioni che condizionano tutto il resto.
2. **Blocco 4 prima del blocco 5.** Il blocco 4 non richiede modifiche al sampler e chiude un
   limite gia' dichiarato in relazione; il blocco 5 e' piu' invasivo e conviene affrontarlo
   con lo strumento di misura gia' ricalibrato sul backend reale.
3. Dentro il blocco 4: prima il braccio **`file`** (nessuna infrastruttura esterna, si valida
   la catena di conteggio degli span consegnati), poi il braccio **`net`**.
4. Dentro il blocco 5: prima l'**Intervento A** da solo — e' istruttivo verificare sul campo
   che **non basta**, ed e' un buon paragrafo di relazione — poi A+B insieme.
5. Aggiornare `3-report/body6.tex`, che oggi descrive la proposta come progetto: con i dati del
   blocco 5 diventa una proposta **verificata**. E precisare li' il Fatto 2 di §3.3.

## 5. Cosa NON fare

- Non rilanciare i blocchi 1, 2, 3 e `diag`.
- Non introdurre un collector dentro lo shield.
- Non "sistemare" il `SIGABRT` di `Simple` correggendo `pthread_cancel`: su questo branch
  **e' un risultato**, con una curva dose-risposta misurata (0/15, 11/15, 14/15, 15/15). Se lo
  correggi, il risultato sparisce.
- Non usare `export_attempts` come conteggio di span consegnati (§2.6).
- Non mergiare `origin/main`.
- Non presentare come "verificata" una frazione stimata su 25 ripetizioni: l'IC di Wilson e'
  largo 30-40 punti, si scrive "coerente con".
