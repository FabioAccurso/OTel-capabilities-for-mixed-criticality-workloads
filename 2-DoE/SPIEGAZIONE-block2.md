# Blocco 2, spiegato per bene

Versione discorsiva. Numeri, comandi e tabelle complete in `NOTES-block2.md`.

## Che domanda facevamo

Il progetto ha una tesi da verificare: **OpenTelemetry riesce a dare priorita' ai task
critici?** Se ho un task che deve rispettare scadenze rigide e quattro task di
sottofondo che possono anche perderne qualcuna, posso chiedere a OTel "raccogli sempre
la telemetria del primo e solo un decimo di quella degli altri"?

Sarebbe la richiesta piu' naturale del mondo. La telemetria costa, quindi la si riduce;
ma la si riduce dove fa meno male, cioe' sui task che non sono critici.

Il blocco 2 pone questa domanda **centocinquanta volte** e registra la risposta.

## Come l'abbiamo posta

Il meccanismo di OTel per ridurre la telemetria si chiama **sampler**, campionatore.
Quello che ci interessa e' il `TraceIdRatioBasedSampler`: gli dici una frazione — 0,3
per esempio — e lui tiene circa il 30% di quel che passa e butta il resto.

Abbiamo fatto girare lo stesso identico carico — un task critico piu' quattro di
disturbo — venticinque volte per ciascuna di sei impostazioni: campionamento sempre
spento, sempre acceso, e le quattro frazioni 0,1 / 0,3 / 0,5 / 0,7.

Poi, per ogni esecuzione, abbiamo contato quanti "span" sono stati effettivamente
esportati. Uno span e' il pezzo di telemetria che dice "questa cosa e' andata da qui a
qui". Un'esecuzione completa ne produce **diciassette**: uno per il programma
principale, uno per la calibrazione, e tre per ciascuno dei cinque thread.

Il numero diciassette e' importante, e ci arriviamo fra un attimo.

## La risposta, in una riga

Su centocinquanta esecuzioni, il conteggio e' stato sempre **o diciassette, o zero.**

Mai quattro. Mai otto. Mai quattordici. Mai un numero che dicesse "ho tenuto il task
critico e buttato gli altri".

## Perche' questo e' la risposta alla domanda

Se il campionatore sapesse distinguere i task per criticita', in un'esecuzione
campionata al 30% dovremmo poter vedere qualcosa di **parziale**: il task critico
dentro e i quattro di disturbo fuori, o una qualsiasi combinazione. Sarebbe un numero
intermedio.

Il fatto che non compaia mai — non raramente, **mai** — significa che la decisione non
viene presa sui singoli task. Viene presa una volta sola, per tutta l'esecuzione:
quando la moneta esce testa entrano tutti e cinque i thread insieme, quando esce croce
non entra nessuno.

Il motivo lo sapevamo gia' leggendo il codice, ed e' il cuore del progetto. Il
campionatore decide guardando il **`trace_id`**, l'identificatore della "traccia", cioe'
dell'insieme di span che raccontano una stessa storia. E in rt-app tutti i thread nascono
come *figli* dello span principale, quindi condividono un unico `trace_id`. Il
campionatore non ha mai visto cinque task di criticita' diversa: ha visto **una** storia,
e ha deciso se raccontarla o no.

Non e' che OTel campioni male. Campiona benissimo — semplicemente l'unita' su cui decide
e' la traccia intera, e per un carico mixed-criticality quell'unita' e' troppo grossa.

## Due affermazioni di forza molto diversa

Qui va fatta una distinzione che conta per la relazione, perche' e' facile scivolare.

**La prima affermazione e' debole**: la frazione osservata segue quella richiesta. E'
vera — abbiamo ottenuto 0%, 8%, 40%, 56%, 76%, 100% per frazioni richieste di 0%, 10%,
30%, 50%, 70%, 100% — e cresce in modo ordinato. Ma con venticinque prove la precisione
e' scarsa: l'intervallo di confidenza attorno a ciascun valore e' largo trenta o quaranta
punti percentuali. Il 40% osservato dove ne chiedevamo 30 non e' un'anomalia, e' rumore
statistico. Quindi in relazione va scritto **"coerente con"**, non "verificato".

Se avessimo voluto misurare *bene* quelle frazioni sarebbero servite centinaia di
ripetizioni per cella. Non era l'obiettivo.

**La seconda affermazione e' fortissima**: il campionatore non separa mai il task critico
dagli altri. Questa non e' una stima con un margine di errore attorno — e' un conteggio,
e fa **zero su centocinquanta**. Basterebbe *un* caso intermedio per smentirla, e in
centocinquanta occasioni non si e' presentato.

E' la differenza fra "abbiamo misurato una quantita' con precisione limitata" e "abbiamo
cercato un fenomeno e non esiste".

## Un dettaglio che ha corretto un nostro errore

Diciassette span, dicevamo. Nel Task 3 ne avevamo contati **otto**, e avevo annotato quel
numero come se fosse una costante.

Sbagliato: il Task 3 girava con due thread, questo blocco con cinque. La formula e'
"due, piu' tre per ogni thread". Con due thread fanno otto, con cinque fanno diciassette.

La composizione di quei diciassette e' interessante di per se':

```
5 x thread_loop     5 x phase
1 x main            1 x calibration
1 x HI_task-0       4 x LO_noise-1..4
```

Solo **cinque span su diciassette** portano il nome del task a cui appartengono. Gli
altri dodici — i `thread_loop` e i `phase` — sono figli anonimi. E' la conferma diretta,
osservata sul campo, del bug che il tuo compagno di corso aveva segnalato in
`count_exported_spans()`: quella funzione conta le occorrenze del nome del task nel file,
quindi da un lato conta doppio (il nome compare sia come `name` sia come attributo
`config.name`) e dall'altro **non vede affatto** i discendenti.

## Quanto costa la telemetria al task critico? Qui, niente

C'e' un esperimento gratuito nascosto in questi dati, e vale la pena raccontarlo perche'
e' elegante.

Nelle celle a frazione, alcune esecuzioni vengono campionate e altre no. Ma sono **la
stessa identica esecuzione**: stesso programma, stessa configurazione, stesso carico.
L'unica differenza e' l'esito di un sorteggio. Confrontare i due gruppi isola esattamente
il costo di *esportare* la telemetria, separandolo dal costo di *averla compilata dentro*.

Risultato: **identici**. Stesso tempo di calcolo, stesso jitter, stesso margine sulla
scadenza. Zero differenza misurabile.

Ha senso: a questo livello di dettaglio l'intera esecuzione da venti secondi produce
diciassette span, e vengono spediti tutti insieme alla chiusura, fuori dalla finestra in
cui misuriamo. I trenta microsecondi per giro che avevamo misurato nel blocco 1 sono
quindi il costo di **avere gli hook di instrumentazione nel codice**, non di usarli.

E' un risultato negativo, ma pulito e utile: dice dove *non* cercare il costo. Il posto
dove aspettarselo e' il blocco 3, che genera uno span per ogni singolo giro invece di
diciassette in tutto.

Da segnalare anche che il task critico **non ha mai mancato una scadenza**: zero su
299400 giri, con quattro thread che chiedevano il 400% di una CPU e la telemetria attiva.

## Una stranezza che non so ancora spiegare

Confrontando il jitter di questo blocco con quello del blocco 1, a parita' di livello di
tracing, salta fuori una cosa che sembra sbagliata:

| | jitter |
|---|---|
| blocco 1, **nessun** task di disturbo | 10,8 µs |
| blocco 2, **quattro** task di disturbo | **2,1 µs** |

Il task critico e' **cinque volte piu' stabile quando la macchina e' carica**. E non e'
un caso isolato: cinquanta esecuzioni contro venti, e le due distribuzioni non si toccano
nemmeno agli estremi.

Si collega a un'altra stranezza gia' vista nel blocco 1, dove il jitter a vuoto era
*bimodale*: meta' delle esecuzioni a 2,7 µs e meta' a 16, senza vie di mezzo. Il valore
buono di allora coincide con il valore di adesso. Sembra che il carico di fondo
**inchiodi la macchina nel regime buono** invece di degradarla.

Ho due spiegazioni possibili e **non riesco a scegliere fra le due** con questi dati:

1. e' davvero il carico, che tenendo occupato il processore evita transizioni di stato
   che a macchina scarica introducono irregolarita';
2. e' un confondente: il blocco 1 usava l'esportatore Zipkin, che senza un collector in
   ascolto tenta una connessione di rete ogni cinque secondi *durante* l'esecuzione,
   mentre il blocco 2 usa l'esportatore su schermo, che scrive tutto alla fine. Potrebbero
   essere quei tentativi falliti a produrre il jitter.

Non lo scrivo in relazione finche' non e' risolto. Per fortuna **il blocco 3 e'
esattamente l'esperimento giusto**: usa Zipkin e include celle senza alcun tracing, a
carico 0, 1, 4 e 8. Se anche li' il jitter scende quando il carico sale, la prima
spiegazione e' confermata e la seconda esclusa, perche' senza tracing non c'e' nessun
esportatore a disturbare.

## Una nota sul fatto che questa volta sia andata liscia

Il primo tentativo di questo blocco, un'ora prima, era morto a un terzo del percorso per
un errore di memoria. Dopo le due correzioni documentate in `4-fix-shutdown/`,
centocinquanta esecuzioni su centocinquanta, zero crash, tutti i file della stessa
dimensione al byte.

Non lo considero una dimostrazione che le correzioni fossero necessarie — quella e' data
dallo strumento diagnostico, che segnalava l'errore cinque volte su cinque prima e zero
volte su cinque dopo. Ma e' il riscontro sul campo che ci si aspettava di vedere.
