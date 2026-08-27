# Task 0.3 spiegato con parole semplici

## Il problema che avevamo

Nel task 0.2 avevamo acceso il tracing, ma per *vedere* qualcosa siamo dovuti ricorrere a
un trucco: scrivere un finto server Zipkin in Python che si mettesse in ascolto e
stampasse quello che rt-app gli spediva. Funzionava, ma è un giro lungo: i dati passavano
per la rete, venivano tradotti nel formato che Zipkin si aspetta, e solo alla fine li
vedevamo noi.

OpenTelemetry ha una scorciatoia pensata apposta per questo: un exporter che, invece di
mandare gli span da qualche parte, li **stampa e basta**. Si chiama exporter "ostream"
(output stream, cioè lo schermo). Nel codice del docente c'era già una funzione pronta,
`InitTracer()`, che lo configura — solo che nessuno la chiamava mai. Il compito di oggi
era chiamarla.

## Cosa abbiamo fatto

Abbiamo cambiato **una riga sola** in `rt-app.cpp`: dove c'era scritto "inizializza il
tracing verso Zipkin" abbiamo scritto "inizializza il tracing verso lo schermo".
Ricompilato, rilanciato lo stesso identico esperimento dei task precedenti (un thread
solo, cinque secondi), e questa volta gli span sono comparsi direttamente nel terminale.
Poi abbiamo rimesso il codice esattamente com'era: era una prova, non una modifica da
tenere.

## Cos'è uno span, guardandolo

Uno span è la registrazione di "una cosa che è durata un po' di tempo". Nel nostro caso ne
sono usciti tre:

- **`main`** — tutto il programma, dall'inizio alla fine: 15,3 secondi.
- **`calibration`** — la taratura iniziale: 10,3 secondi.
- **`solo_task-0`** — il nostro thread che lavora davvero: 5,0 secondi.

Ogni span porta con sé un'etichetta di identità: un `trace_id`, un `span_id` e il
`parent_span_id` di chi lo ha generato. È come un albero genealogico: `main` è il capostipite
(non ha genitore), e gli altri due sono i suoi figli.

Poi ci sono gli **attributi**, che sono le informazioni che rt-app ha attaccato allo span:
con che politica di scheduling girava il thread, con che priorità, quanto doveva durare.
E le **resources**, che descrivono il programma nel suo insieme e vengono ripetute
identiche su ogni span. Sullo span `main` c'è anche un **evento**, `graceful-shutdown`:
un evento è un istante preciso, non un intervallo — il momento esatto in cui il programma
si è chiuso in modo pulito.

## Tre cose interessanti che sono saltate fuori

**Prima: la conferma del sospetto centrale del progetto.** Tutti e tre gli span hanno lo
stesso `trace_id`. Lo avevamo già intuito in 0.2, ma ora si legge nero su bianco. Perché è
importante? Perché il sampler "a percentuale" di OpenTelemetry (quello che dice "tienimi
solo il 10% delle tracce") decide guardando il `trace_id`. Se il `trace_id` è uno solo per
tutta l'esecuzione, quel sampler non può tenere il task critico e scartare quello
best-effort: o tiene tutto, o butta tutto. Ed è esattamente il limite che il progetto deve
dimostrare con i numeri.

**Seconda: la calibrazione dura più del lavoro vero.** Dieci secondi di taratura per
cinque secondi di esperimento — e nel run del task 0.2 la stessa taratura ne aveva
impiegati tre. Non è un errore: rt-app misura quanto è veloce la CPU prima di iniziare, e
se la CPU cambia frequenza da un momento all'altro (come fa la tua senza isolamento) quel
tempo balla. È rumore che va tolto prima del DoE.

**Terza: gli span escono tutti insieme alla fine.** Abbiamo marcato ogni riga di output
con l'istante in cui è comparsa: sono tutte al secondo 15, cioè alla chiusura del
programma. Il motivo è il "batch processor": OpenTelemetry non spedisce gli span uno alla
volta, li accumula in una coda e li manda a blocchi. Per contarli va benissimo; per capire
*quando* sono stati prodotti, no.

## Un problema che abbiamo scoperto per il futuro

`InitTracer()`, così com'è scritta dal docente, ha il sampler e il processor **fissi nel
codice**: qualunque macro le passi, lei usa sempre AlwaysOn e Batch. Va bene per sbirciare
l'output, come oggi. Non va bene per il Blocco 2 del DoE, dove l'idea era proprio di
contare gli span a video al variare del sampling ratio: conteremmo sempre gli stessi
identici span.

Quindi il Task 3 non dovrà solo aggiungere un interruttore per scegliere l'exporter: dovrà
anche far sì che l'exporter ostream rispetti le stesse impostazioni di sampler e processor
di quello Zipkin. Meglio saperlo adesso che dopo aver lanciato duecento run inutili.
