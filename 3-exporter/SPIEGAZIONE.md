# Task 3 spiegato in parole semplici

## Il problema pratico

OpenTelemetry, così com'è configurato in rt-app, manda i dati di tracciamento a un server
esterno (si chiama Zipkin) attraverso la rete. Va benissimo in produzione, ma per gli
esperimenti è scomodo: se vuoi **contare** quanti dati sono stati prodotti, devi tirarli
fuori da un server.

Esiste però un'alternativa già presente nel codice: un exporter che stampa tutto a video.
In quel caso contare è banale — basta contare le righe.

Il problema era che la scelta fra i due era scritta a mano dentro il programma. Per
cambiarla bisognava modificare il sorgente, ricompilare, e ricordarsi di rimettere tutto a
posto dopo. Nel task 0.3 l'avevo fatto proprio così, come esperimento usa e getta.

Questo task rende la scelta un'opzione di compilazione, `RTAPP_EXPORTER_TYPE`, come le
altre quattro che il progetto già usa. Il valore predefinito è quello di prima, quindi
chiunque compili senza specificare nulla ottiene esattamente il comportamento originale.

## Il problema vero, che era nascosto

Nel task 0.3 avevo notato una cosa che allora avevo solo annotato: la funzione che
configura l'exporter a video **ignorava tre delle quattro opzioni**. Aveva il tipo di
campionatore e il tipo di processore scritti fissi dentro il corpo, e non guardava affatto
cosa gli chiedevi.

Questo sarebbe stato disastroso, perché il secondo blocco della campagna sperimentale fa
esattamente questo: cambia il campionatore e conta gli span stampati a video. Con quella
funzione, tutte le sei configurazioni avrebbero stampato le stesse cose. Centocinquanta
esperimenti, due ore di macchina, per misurare niente — e senza nessun errore a segnalarlo.

La soluzione poteva essere copiare i blocchi di configurazione dalla funzione che li fa
bene a quella che li ignorava. Ho preferito estrarre la parte comune in una funzione sola
che entrambe chiamano: fra le due versioni cambia soltanto l'exporter e il nome del
servizio, tutto il resto è identico. Così non possono più divergere quando qualcuno ne
modifica una sola.

## Cosa esporta davvero rt-app

Con un esperimento di 5 secondi, un task critico e uno di disturbo, tracciamento a
livello 2, ecco tutto quello che finisce a video:

```
1 main
1 calibration
1 graceful-shutdown
1 HI_task-0
1 LO_noise-1
2 phase
2 thread_loop
```

Otto span. E qui c'è una cosa da sapere: **quel numero non dipende dalla durata**. Un
esperimento da 20 secondi ne produce sempre otto. A livello 2 gli span descrivono la
*struttura* del programma, non i singoli giri.

Salendo a livello 3 la situazione cambia radicalmente: compaiono gli span di ogni singolo
giro, e lo stesso esperimento da 5 secondi passa da 8 span a **5508**, da 8 kilobyte a
**4,7 megabyte** di output. Utile saperlo prima di lanciare la campagna.

## Il risultato che conta

E adesso la parte importante, quella che è il cuore dell'intero elaborato.

Il campionatore "a percentuale" di OpenTelemetry serve a ridurre il volume di dati: gli
dici "tienimi il 50%" e lui scarta il resto. La domanda del progetto è: **può usarlo per
tenere il 100% dei dati del task critico e solo il 10% di quelli dei task secondari?**

Ho impostato il campionatore al 50% e ho ripetuto lo stesso esperimento dodici volte,
contando ogni volta quanti span erano stati prodotti dal task critico e quanti da quello
di disturbo. Il risultato:

| | task critico | task di disturbo |
|---|---|---|
| 4 esperimenti su 12 | presente | presente |
| 8 esperimenti su 12 | assente | assente |

**Mai, nemmeno una volta, uno dei due è stato tenuto senza l'altro.** Il totale è sempre
otto span o zero, mai un valore intermedio.

Il motivo è che quel campionatore non decide guardando lo span: decide guardando
l'identificativo della traccia. E in rt-app tutta l'esecuzione ha un solo identificativo,
perché ogni thread viene creato come figlio dello span principale. Quindi la decisione
viene presa una volta sola, all'inizio, per tutto quanto: o si tiene tutto, o si butta
tutto.

Questa era l'ipotesi di partenza del progetto. Finora l'avevamo dedotta leggendo il
codice; adesso è un dato sperimentale.

**La risposta alla domanda dell'elaborato è quindi: no.** Con gli strumenti standard,
OpenTelemetry non è in grado di dare priorità ai task critici nella pipeline di telemetria.
Non li tratta diversamente perché non li *vede* diversamente: per il campionatore sono
tutti la stessa traccia.

Ed è esattamente la premessa del Task 6, dove si dovrà proporre un campionatore che decida
guardando il nome o gli attributi dello span invece dell'identificativo della traccia.

## L'ultimo passo

Aggiungere l'opzione non basta se poi nessuno la usa. Ho quindi collegato la macro dentro
lo script della campagna: le sei celle del blocco 2 adesso chiedono automaticamente
l'exporter a video, e la nota che diceva *"ricordati di modificare a mano il sorgente
prima di lanciare questo blocco"* non serve più. I blocchi 1 e 3 restano su Zipkin, come
prima.

Un dettaglio che valeva la pena curare: lo script tiene una cache dei binari già compilati
per non ricompilare inutilmente. Ho aggiunto l'exporter alla chiave della cache, altrimenti
due binari diversi si sarebbero sovrascritti a vicenda e il blocco 2 avrebbe potuto girare
con il binario sbagliato.
