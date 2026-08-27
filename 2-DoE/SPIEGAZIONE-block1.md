# Blocco 1 spiegato in parole semplici

## Cosa misurava

La domanda più semplice dell'elaborato: **quanto costa accendere OpenTelemetry?**

Un solo task critico, da solo su una CPU isolata, che ogni 10 millisecondi calcola per 2
millisecondi. Nessun disturbo, nessun altro carico. L'unica cosa che cambia fra un
esperimento e l'altro è quanto dettaglio di tracciamento è attivo:

- **livello 0**: niente, nessuna strumentazione — il metro di paragone
- **livello 1**: uno span per il programma e uno per ogni thread
- **livello 2**: in più uno span per ogni fase
- **livello 3**: in più uno span per **ogni singolo giro** del task

Ottanta esecuzioni da venti secondi, venti per livello. Ventinove minuti di macchina.

## Il risultato principale: nessuna scadenza mancata

Su circa **centosessantamila giri** del task critico, non una singola scadenza è stata
mancata. A nessun livello di tracciamento, nemmeno al massimo.

È un risultato importante e va detto per primo, perché è facile aspettarsi il contrario.
Con il task che usa il 20% della sua CPU, c'è abbastanza margine da assorbire tutto quello
che OpenTelemetry gli mette addosso.

## Ma il costo c'è, e si vede in altre metriche

**Il jitter cresce.** Il jitter è la variabilità del periodo: se il task deve svegliarsi
ogni 10 millisecondi esatti, il jitter dice quanto ballano quei 10 millisecondi. È la
misura che risponde più chiaramente:

| livello | jitter | rispetto a "niente" |
|---|---|---|
| 0 | 7,6 µs | — |
| 1 | 11,2 µs | **+47%** |
| 2 | 10,8 µs | +41% |
| 3 | 13,5 µs | **+77%** |

I livelli 1 e 2 sono di fatto identici. Ha senso: al livello 2 gli span di fase sono uno
per ogni *tipo* di fase, non uno per giro, quindi il lavoro in più è quasi nullo — lo
avevamo già visto nel Task 3, dove livello 1 e livello 2 producevano lo stesso numero di
span. Il salto vero arriva al livello 3, dove ogni singolo giro crea il suo span.

**La latenza di risveglio cresce del 60%**, da 17 a 27 microsecondi, appena si accende il
tracing. Poi resta piatta. Il caso peggiore assoluto è stato 165 microsecondi.

**E il costo per giro si misura in modo pulito**: 30 microsecondi ai livelli 1 e 2, 56 al
livello 3. Su un budget di 8 millisecondi è meno dell'1%; sui 2 millisecondi di calcolo
utile è l'1,5% e il 2,8%.

## Una stranezza che non ho risolto, e che cambia come leggere i dati

C'è un numero che va nella direzione sbagliata: al livello 3, cioè con il massimo di
strumentazione, il task risulta calcolare **più velocemente** — 1955 microsecondi contro i
1989 di quando non c'è nessuna strumentazione.

Non è rumore: tutti e venti gli esperimenti hanno dato esattamente 1955. Ed è impossibile
che stia facendo meno lavoro, perché la quantità di calcolo è fissata da un numero nel
file di configurazione.

Avevo un'ipotesi precisa, che veniva dal task 0.4: lì avevamo scoperto che il calcolo in
virgola mobile va il 36% più veloce quando il core "gemello" è occupato. Al livello 3 il
thread che spedisce i dati di telemetria ha molto più lavoro, quindi poteva essere lui a
tenere occupato il gemello.

L'ho verificata invece di darla per buona: ho rilanciato lo stesso esperimento impedendo
al thread di telemetria di usare il core gemello. Risultato: **1955 microsecondi, identico**.
L'ipotesi era sbagliata.

Resta quindi un effetto di stato del processore causato dal codice che la strumentazione
esegue fra un calcolo e l'altro, che non sono riuscito a identificare.

La conseguenza pratica però è chiara, ed è la cosa più utile emersa da questo blocco:
**il tempo di calcolo non è una metrica valida per confrontare livelli di tracciamento
diversi.** La strumentazione altera il comportamento del processore in modo che il
cronometro segna *meno*, non di più. Chi leggesse solo quella colonna concluderebbe che
tracciare rende il sistema più veloce, che è ovviamente assurdo.

Le metriche affidabili sono le altre tre: il margine residuo prima della scadenza, il
jitter e la latenza di risveglio. Tutte e tre crescono in modo ordinato con il livello di
tracciamento.

## Due cose che avevamo deciso prima, e che vanno ricordate nella relazione

**Non c'era nessun server in ascolto** per ricevere i dati. L'exporter ha provato a
connettersi e ha fallito circa otto volte per esperimento. Quindi questo blocco misura il
costo di *creare* i dati di telemetria, non quello di spedirli. È una scelta deliberata,
per non mescolare la variabilità della rete con la misura, ma va dichiarata.

**Il thread che spedisce la telemetria non è vincolato a nessuna CPU**: può girare su una
qualsiasi delle quattro riservate all'esperimento, e cambia da un run all'altro. Anche
questa è una scelta, perché è ciò che succede nei sistemi reali, ma è una fonte di
variabilità che va nominata.

## Cosa serve decidere prima di andare avanti

Il blocco 1 occupa 21 megabyte perché non aveva task di disturbo. I blocchi 2 e 3 ne
avranno fino a otto, e produrranno circa 750 megabyte ciascuno. Prima di lanciarli conviene
decidere se comprimere i log o conservare solo quelli del task critico.
