# Blocco 3, spiegato per bene

Versione discorsiva. Numeri e tabelle complete in `NOTES-block3.md`.

## Che domanda facevamo

I primi due blocchi avevano risposto a "quanto costa strumentare" e "OTel sa dare
priorita' ai task critici". Restava la terza domanda, che e' quella architetturale:
**come deve essere costruita la pipeline di telemetria perche' non danneggi il task
critico?**

OpenTelemetry offre due modi di consegnare gli span a chi li raccoglie.

Il **SimpleSpanProcessor** e' l'onesto: appena uno span e' pronto, lo spedisce. Subito,
sul posto, aspettando che la spedizione finisca.

Il **BatchSpanProcessor** e' il pragmatico: mette gli span in una coda in memoria e ogni
cinque secondi li spedisce tutti insieme, da un thread separato.

Il blocco 3 li ha messi a confronto sotto carico crescente: zero, uno, quattro e otto
task di disturbo, con il livello di tracing massimo — uno span per ogni singolo giro.

## La risposta, in una tabella

Su tutta la campagna — quattrocentodieci esecuzioni, oltre un milione di giri fra i tre
blocchi — il task critico ha mancato una scadenza **cinquantuno volte**.

**Tutte e cinquantuno nelle celle con il SimpleSpanProcessor.**

| | scadenze mancate |
|---|---|
| nessun tracing | 0 |
| tracing massimo, **Batch** | 0 |
| tracing massimo, **Simple** | **51** |

Zero contro cinquantuno. Non e' una differenza di grado, e' una differenza di natura.

## Quanto sono gravi

Molto piu' di quanto il numero suggerisca. Lo sforo peggiore e' stato di **86
millisecondi**: il task critico doveva ripartire ogni dieci millisecondi ed e' rimasto
fermo per piu' di **otto periodi interi**.

E c'e' un dettaglio che rende il quadro peggiore, non migliore. Con un solo task di
disturbo le scadenze mancate sono di piu' (quaranta) ma piccole; con quattro e otto sono
poche (sei e cinque) ma enormi. Non e' un degrado graduale che si possa mettere a
preventivo: sono **stalli rari e lunghissimi**.

Per un sistema real-time e' il profilo peggiore possibile. Un ritardo costante di
trecento microsecondi lo si dimensiona: si allarga il budget e si va avanti. Uno stallo
da ottantasei millisecondi che capita una volta ogni cinquemila giri non si dimensiona —
o lo si elimina, o il sistema non e' affidabile.

## Perche' il Batch se la cava

Il meccanismo si legge in una colonna sola: quante volte il programma ha provato a
contattare il collector, che nel nostro esperimento non c'e'.

| | tentativi falliti, per esecuzione |
|---|---|
| **Batch** | 336 |
| **Simple** | **24632** |

Settantatre volte tanto. E la ragione e' strutturale: il Batch spedisce **ogni cinque
secondi**, quindi in venti secondi ci prova quattro volte a prescindere da quanti span
abbia prodotto. Il Simple spedisce **ogni span**, quindi il numero di tentativi cresce
col carico di lavoro.

Il costo che ne segue e' proporzionato:

| | costo per giro |
|---|---|
| **Batch** | 8 microsecondi |
| **Simple** | **340 microsecondi** |

Quaranta volte tanto, e sono il diciassette per cento del tempo di calcolo effettivo del
task critico.

Detto in una frase: **il Batch isola il task critico da un guasto del sistema di
monitoraggio, il Simple glielo scarica addosso.** E la cosa vale a prescindere da quanto
sia veloce il collector, perche' riguarda la *struttura* del disaccoppiamento, non la sua
velocita'.

## Una cosa che questi numeri NON dicono

Va detto chiaramente, perche' e' facile scriverlo male nella relazione.

I trecentoquaranta microsecondi del Simple **non sono "quanto costa esportare uno span"**.
Sono quanto costa *provare* a esportarlo verso un collector che non risponde, e riprovare.

La campagna e' girata deliberatamente senza collector. Per il Batch la scelta e'
irrilevante (quattro tentativi ogni venti secondi), e per il blocco 2 pure (usava un
esportatore che scrive su schermo). Diventa determinante solo per il Simple.

Abbiamo valutato di accendere un collector e abbiamo deciso di no: con otto task di
disturbo servirebbero ottomila richieste HTTP al secondo, e il nostro collector finto e'
un server Python a thread singolo che riscrive un file a ogni richiesta. Diventerebbe lui
il collo di bottiglia, e siccome il Simple **aspetta la risposta dentro il percorso
critico**, staremmo misurando la lentezza del nostro server invece del costo di
OpenTelemetry. Una misura falsata in modo piu' insidioso, perche' sembrerebbe legittima.

Quindi: limite dichiarato dello studio, **non abbiamo un numero per il costo di un export
che riesce**. Quello che abbiamo, e che vale, e' il confronto fra le due architetture
nella stessa identica condizione.

## Il mistero del blocco 2, risolto

Il blocco 2 aveva lasciato una domanda aperta e fastidiosa. Il task critico risultava
**cinque volte piu' stabile sotto carico** che a macchina scarica — il contrario di quel
che ci si aspetta. Due spiegazioni possibili: o e' davvero il carico, oppure era colpa
dell'esportatore usato nel blocco 1, che tenta connessioni di rete durante l'esecuzione.

Il blocco 3 aveva esattamente l'esperimento giusto: le celle **senza alcun tracing**, dove
nel programma non c'e' nemmeno una riga di OpenTelemetry, ripetute a tutti i livelli di
carico.

| task di disturbo | jitter | esecuzioni "buone" |
|---|---|---|
| 0 | 4,8 µs | 9 su 15 |
| 1 | 9,4 µs | 3 su 15 |
| **4** | **2,0 µs** | **15 su 15** |
| **8** | **2,1 µs** | **15 su 15** |

**L'ipotesi dell'esportatore e' esclusa.** Qui non c'e' niente da esportare, e l'effetto
c'e' lo stesso. Il valore con quattro task di disturbo — 2,0 — coincide con il 2,1 che
avevamo misurato nel blocco 2 con un esportatore completamente diverso, in una campagna
diversa.

E non e' solo che il numero scende: **sparisce la dispersione**. A carico pieno tutte e
quindici le esecuzioni stanno fra 2,0 e 2,6; a vuoto vanno da 2,5 a 20,5. Il carico non
sposta la media, **elimina il caso cattivo**.

C'e' pero' un dettaglio che impedisce di chiudere la questione: **l'effetto non e'
monotono**. Con *un solo* task di disturbo le cose vanno peggio che a vuoto. La lettura
plausibile e' che conti non la quantita' di carico ma la sua **continuita'**: un thread
al cinquanta per cento fa alternare la CPU vicina fra attiva e inattiva, quattro thread la
tengono costantemente satura, e quel regime stabile e' quello che aiuta. Ma e'
un'interpretazione, non una misura, e come tale va scritta.

## Una stranezza che resta aperta, e che ho imparato a rispettare

A carico basso il jitter del task critico e' **bimodale**: le esecuzioni si dividono in due
gruppi netti, uno attorno a 2,5 microsecondi e uno attorno a 15-25, senza niente in mezzo,
circa meta' e meta'.

L'abbiamo vista in **tre campagne indipendenti** a ore diverse della giornata. Non e'
rumore.

E ci ha teso una trappola che vale la pena raccontare. Confrontando la cella di controllo
fra il tentativo abortito e il rilancio, i numeri erano molto diversi: jitter da 12,6 a
4,8, latenza di risveglio da 27 a 7 microsecondi. Sembrava che qualcosa fosse cambiato.
Non era cambiato niente: quel programma e' **identico** nei due casi, perche' la
correzione che avevamo applicato e' racchiusa in una condizione che a tracing spento non
viene nemmeno compilata.

La differenza era solo **come era caduta la moneta**: sette esecuzioni buone su quindici
la prima volta, nove la seconda. E siccome la mediana di una distribuzione a due gruppi
cade nel vuoto in mezzo, basta uno spostamento della ripartizione per farla saltare da una
parte all'altra.

La lezione, che vale per tutta la relazione: **le celle di controllo non vanno riassunte
con la mediana.** Vanno descritte con le due mode e la loro proporzione. Altrimenti si
finisce per attribuire al tracing differenze che sono solo il caso.

Sulla causa ho un sospetto — lo stato viene deciso all'avvio e resta fisso per tutta
l'esecuzione, il che fa pensare al modo in cui la memoria viene disposta a ogni
avvio — ma **non l'ho testato**, e il test sarebbe facile: rilanciare disabilitando la
randomizzazione degli indirizzi. Lo lascio scritto come lavoro da fare, non come
spiegazione.

## Un errore di lettura che ho fatto, e come si evita

Guardando i primi risultati avevo riportato "jitter 874 microsecondi, zero scadenze
mancate". Sbagliate tutte e due, e nello stesso modo.

Il **jitter di 874** sembrava dire che il task critico era diventato irregolare. Guardando
meglio, i periodi erano strettissimi attorno a 9648 microsecondi, con un massimo di 9657.
Lo scarto veniva da **cinque giri su duemila** con periodo dimezzato — il timer che si
riaggancia dopo uno stallo. Non irregolarita' diffusa: due o tre incidenti isolati che
gonfiano la statistica.

Le **zero scadenze mancate** venivano dall'aver preso la mediana fra le quindici
ripetizioni. Dieci esecuzioni su quindici non ne avevano nessuna, quindi la mediana faceva
zero — e cancellava le sei che c'erano. Sommandole invece di mediarle, saltano fuori.

Sono lo stesso errore visto da due lati: **una statistica robusta e' esattamente quella
sbagliata quando cio' che cerchi sono gli eventi rari.** Per la sicurezza di un sistema
real-time non conta il comportamento tipico, conta il caso peggiore — e mediane e
deviazioni standard sono costruite apposta per nasconderlo.

Nella relazione i deadline miss vanno **sommati** su tutte le ripetizioni, e il jitter va
riportato con due numeri, la deviazione standard e lo scarto interquartile: quando
divergono di due ordini di grandezza, il fenomeno e' fatto di incidenti isolati e non di
degrado continuo.
