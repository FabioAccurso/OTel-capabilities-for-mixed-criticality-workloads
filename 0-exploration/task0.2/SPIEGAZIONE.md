# Task 0.2 — spiegazione in linguaggio semplice

Versione discorsiva di `NOTES.md`, che invece riporta comandi, numeri e file.

## 1. Il vocabolario minimo

OpenTelemetry serve a registrare **cosa fa un programma mentre gira**. L'unità base è lo
**span**: un intervallo di tempo con un nome, un istante di inizio, una durata e delle
etichette. "Il thread `solo_task-0` è vissuto 5,000012 secondi ed era SCHED_OTHER con
priorità 0" è uno span.

Gli span si annidano: uno span può essere **figlio** di un altro. Tutti gli span
discendenti da uno stesso antenato formano una **trace**, e la trace ha un identificativo
unico, il `trace_id`. È l'equivalente del "numero di pratica" che tiene insieme dei
documenti sparsi.

Dentro il programma la telemetria attraversa tre stadi, in quest'ordine:

- il **sampler** decide se uno span vale la pena di essere registrato o va buttato subito
  (serve a non affogare nei dati);
- il **processor** raccoglie gli span sopravvissuti e decide *quando* spedirli: `Simple`
  li spedisce uno per uno appena chiudono, `Batch` li accumula in una coda e li spedisce
  a gruppi ogni tot secondi;
- l'**exporter** li spedisce davvero, fuori dal processo, verso un server esterno.

Il server esterno qui è **Zipkin**, che ascolta su `localhost:9411`. Non fa parte di
rt-app: è un programma separato che dovresti avere avviato tu. È il **collector**.

## 2. Cosa è cambiato rispetto al task 0.1

Nel 0.1 rt-app era compilato con `RTAPP_TRACE_LEVEL=0`, cioè con tutto il codice
OpenTelemetry **cancellato dal preprocessore**: il binario non conteneva neanche un
simbolo OTel. Era il baseline pulito.

Il 0.2 chiedeva di ricompilare con `RTAPP_TRACE_LEVEL=1`, che riaccende il livello più
leggero di istrumentazione: **tre span in tutto**, e nessuno dentro il ciclo di lavoro.
Sono `main` (tutta l'esecuzione), `calibration` (la fase in cui rt-app misura quanto è
veloce la CPU) e uno span per ogni thread — qui uno solo, `solo_task-0`. Il task set è
rimasto identico a quello del 0.1, così l'unica cosa cambiata è l'istrumentazione.

## 3. Perché è stato necessario compilare opentelemetry-cpp

Con `RTAPP_TRACE_LEVEL=0` il codice OTel spariva, quindi il binario si linkava anche
senza avere le librerie OpenTelemetry sul disco (nel 0.1 infatti era stato usato un
override del linker per saltarle). Con `RTAPP_TRACE_LEVEL=1` quel codice torna nel
binario e le librerie servono davvero — e sul sistema non c'erano, né in
`otel-installdir/` né installate globalmente.

Quindi sono state costruite: clone di opentelemetry-cpp v1.28.0 in `otel-src/`,
compilazione con l'exporter Zipkin attivo, installazione in `otel-installdir/`. È
formalmente un pezzo del Task 1, ma senza non c'era modo di fare il 0.2. Le due cartelle
pesano 240 MB e sono ricostruibili da zero, per cui sono in `.gitignore`.

Un dettaglio utile: il `src/Makefile.am` scritto dal docente elenca nove librerie
OpenTelemetry da linkare, e una di quelle (`ostream_span_builder`) sembrava a rischio di
non essere prodotta da una build normale. Invece c'è. Vuol dire che **quel file non va
toccato**: compila così com'è.

## 4. I tre esperimenti

Stesso identico task set tre volte, cambiando una cosa per volta.

### Primo: binario istrumentato, nessun collector in ascolto

Era la domanda esplicita del task — se manca Zipkin, rt-app si pianta, si lamenta, o fa
finta di niente?

Risposta: rt-app **finisce regolarmente**. Codice di uscita 0, file di log delle
temporizzazioni scritto per intero e identico per struttura a quello del 0.1. L'unica
traccia del problema sono due righe su stderr:

```
[Error] ... ZIPKIN EXPORTER] Zipkin Exporter: Connection failed
```

E le stampa la libreria OpenTelemetry, non rt-app. Non c'è nessun tentativo di riprovare,
nessun codice di uscita diverso, nessun contatore di span persi che il programma possa
leggere. Il metodo `span->End()` non restituisce niente: il programma **non ha modo di
sapere** che la sua telemetria è finita nel nulla.

Conseguenza pratica: quando si lanceranno centinaia di run automatici nel Task 4, uno
script che guarda solo il codice di uscita dirà "tutto ok" anche per un run che ha
prodotto **zero dati**. Va controllato a parte che il collector risponda, o vanno contati
gli span ricevuti.

### Secondo: stesso binario, ma con qualcosa in ascolto sulla porta 9411

Non è stato installato Zipkin vero — sono state scritte venti righe di Python
(`fake_zipkin.py`) che accettano la richiesta HTTP, rispondono "ricevuto" e salvano su
file esattamente il JSON che rt-app ha spedito. Serviva a vedere il contenuto, non ad
avere un backend funzionante.

Sono arrivati tutti e tre gli span, in due spedizioni separate:

```
[  5.97] POST /api/v2/spans   302 byte  1 span: ['calibration']
[  9.02] POST /api/v2/spans  1421 byte  2 span: ['solo_task-0', 'main']
```

Questa spaccatura non è un caso, ed è la cosa più istruttiva del run. Il codice del
docente configura il processor `Batch` con un intervallo di 5 secondi. Lo span
`calibration` chiude presto (intorno al terzo secondo), va in coda, e resta lì ad
aspettare il primo risveglio del thread di export, che avviene al quinto secondo. Gli
altri due chiudono solo alla fine del programma e partono nello svuotamento finale della
coda.

Tradotto: **uno span già chiuso può restare fermo in coda fino a cinque secondi prima di
uscire dal processo**. Il ritardo che si vede sul backend non è il ritardo del task. E
soprattutto: con il processor `Batch`, il costo della spedizione ricade quasi tutto
*dopo* la fine del lavoro, cioè fuori dalla finestra in cui si sta misurando. Con
`Simple` ricadrebbe dentro. È esattamente il confronto che il DoE deve fare.

### Terzo: il vecchio binario non istrumentato

Rilanciato per avere un termine di paragone pulito sulle stesse condizioni di macchina.

## 5. Le tre cose che contano per il progetto

### La prima è la più importante

Guardando il JSON salvato dal collector finto, i tre span risultano così:

```
name=calibration   traceId=d0c1...52cc   parentId=0a12...701e
name=solo_task-0   traceId=d0c1...52cc   parentId=0a12...701e
name=main          traceId=d0c1...52cc   parentId=(nessuno)
```

Stesso `traceId` per tutti e tre, e lo span del thread è figlio di `main`. Con più task
sarà uguale: un thread HI critico e un thread LO best-effort finiranno **nella stessa
identica trace**, con lo stesso `traceId`.

Perché è un problema? Perché il sampler da testare, `TraceIdRatioBasedSampler`, prende la
sua decisione calcolando un hash **del `trace_id`**. Se il `trace_id` è uno solo, quel
calcolo dà un solo risultato per tutta l'esecuzione: o si tiene tutto, o si butta tutto.
Non può tenere gli span dei task critici e scartare quelli dei task best-effort, che è
esattamente la "prioritizzazione" che l'elaborato chiede di valutare.

Attenzione: qui il sampler era `AlwaysOn`, quindi **questa non è ancora la prova
sperimentale**. È la conferma della *premessa* su cui poggia il sospetto: prima era stata
solo letta nel codice, adesso è stata vista nei dati veri. La prova vera arriva nel DoE,
quando si accenderà il sampler a ratio.

C'è anche una buona notizia collegata. Fra le etichette dello span di thread ci sono già
`config.sched_data.policy` e `config.sched_data.priority`, cioè la politica di scheduling
e la priorità. Sono informazioni che distinguono un task HI da un task LO **e che sono
già presenti sullo span**. Se al Task 6 servirà proporre un sampler custom che decide
sulla criticità invece che sul `trace_id`, i dati su cui farlo decidere ci sono già: non
serve inventare nuova istrumentazione.

### La seconda

L'istrumentazione a livello 1 **non rallenta il lavoro**. I tempi di esecuzione misurati
nei tre run stanno tutti fra 4194 e 4486 µs, e il baseline non istrumentato è addirittura
il più lento dei tre. Non è una sorpresa ed è coerente col codice: a livello 1 non c'è
una sola riga OpenTelemetry dentro il ciclo di lavoro, quindi non c'è niente da
rallentare. Le differenze che si vedono sono il rumore DVFS già documentato nel 0.1. Il
corollario è che **per misurare l'overhead sul WCET bisognerà salire almeno a
`RTAPP_TRACE_LEVEL=2`**: a livello 1 non c'è overhead da misurare.

Quello che cambia è la memoria: l'occupazione passa da 4,3 a 13,6 MB, tre volte tanto. Il
costo dell'SDK è di memoria e di thread, non di CPU nel percorso critico. Con
`lock_pages` attivo — che blocca le pagine in RAM — è un numero da tenere d'occhio.

### La terza è una nota a margine

Emersa strada facendo, non richiesta dal task ma utile: un run configurato per durare 5
secondi occupa 8-13 secondi di orologio. Non è colpa di OpenTelemetry. Cronometrando le
fasi, è la **calibrazione iniziale** a prendersi da sola 3-5 secondi, con una variabilità
enorme — sempre lo stesso DVFS del 0.1. Se nel DoE si mettono dei timeout, va tenuto
conto.
