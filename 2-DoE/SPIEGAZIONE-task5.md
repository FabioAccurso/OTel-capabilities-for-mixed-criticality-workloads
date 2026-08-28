# Task 5, spiegato per bene

Versione discorsiva. Tabelle complete, numeri e comandi in `NOTES-task5.md`.

## Cosa c'era da fare

Tre campagne di misura, quattrocentodieci esecuzioni, quasi mezzo miliardo di
microsecondi cronometrati. Il Task 5 e' il momento in cui tutto questo deve diventare
**tre o quattro frasi che si possano difendere davanti a un esaminatore**.

Il lavoro e' stato in tre parti: sistemare lo strumento di analisi, che era rotto in
quattro punti; estrarre le tabelle; e disegnare i grafici.

## Parte prima: lo strumento era rotto, e in modo pericoloso

`analyze_doe.py` aveva quattro difetti. Nessuno di questi avrebbe fatto crashare
niente — ed e' proprio questo il problema. Avrebbero prodotto **numeri plausibili e
sbagliati**, che e' il tipo peggiore di errore, perche' non si annuncia.

### Il transitorio di avvio

La prima riga di ogni log di rt-app non vale niente. Il programma inizializza il
riferimento temporale del primo giro in un modo che rende la prima misura di margine
priva di senso, tipicamente un numero negativo di qualche millisecondo.

Un numero negativo, in questa campagna, significa "scadenza mancata". Quindi **ogni
singola cella dell'esperimento avrebbe riportato una scadenza mancata su duemila
giri**, sempre, costantemente, in tutte e dodici le configurazioni.

Il guaio non e' l'errore in se': e' che avrebbe seppellito il risultato vero. Le
cinquantuno scadenze realmente mancate nel blocco 3 sarebbero state indistinguibili
dal rumore di fondo che lo strumento si generava da solo.

### Il conteggio degli span, che contava doppio

Questo l'aveva segnalato un tuo compagno di corso, e l'avevamo verificato: la funzione
cercava il nome del task come **sottostringa in tutto il file**. Il problema e' che
ogni span porta il nome due volte, una come proprio nome e una come attributo. Quindi
il conteggio usciva esattamente raddoppiato.

Ma c'era un secondo difetto, piu' grave, che era sfuggito a tutti. Su diciassette span
esportati da un'esecuzione, **solo cinque portano il nome di un task**; gli altri
dodici sono discendenti anonimi — i "loop", le "fasi". Cercando il nome, quei dodici
non venivano contati **affatto**.

Quindi il vecchio conteggio dava contemporaneamente troppo (fattore due) e troppo poco
(dodici span invisibili). Ora si contano le righe che dichiarano un nome di span, e i
numeri tornano: diciassette totali, uno per il task critico, quattro per i disturbi.

### Due statistiche mancanti, che si sono rivelate decisive

Ho aggiunto il **conteggio** delle scadenze mancate, non solo la percentuale, e lo
**scarto interquartile** accanto alla deviazione standard. Sembravano dettagli. Sono
diventati i due strumenti che hanno impedito di scrivere due sciocchezze — la storia
sta piu' sotto.

## Parte seconda: i tre risultati

### Primo — strumentare costa poco, e in modo prevedibile

| livello di tracing | costo per giro |
|---|---|
| nessuno | — |
| span di thread | +30 µs |
| + span di fase | +30 µs |
| + uno span per giro | **+56 µs** |

Cinquantasei microsecondi sono lo **zero virgola sette per cento** del tempo
disponibile fra due scadenze. Zero scadenze mancate su centosessantamila giri.

Il primo e il secondo livello sono identici perche' gli span di fase sono uno *per
definizione*, non uno per giro: solo al terzo livello si comincia a produrne uno a ogni
iterazione, e li' il costo raddoppia.

La conclusione onesta e': **al livello di dettaglio normale, OpenTelemetry non e' un
problema per un task real-time.**

### Secondo — OpenTelemetry non sa distinguere i task critici

Questo e' il cuore del progetto.

Su **centocinquanta esecuzioni**, il numero di span esportati e' stato sempre **o
diciassette, o zero**. Mai un numero intermedio. Mai il task critico dentro e i
disturbi fuori.

Il campionatore di OpenTelemetry decide guardando l'identificatore della *traccia*, e
in rt-app tutti i thread appartengono a un'unica traccia perche' nascono figli dello
stesso span principale. Quindi non ha mai visto cinque task di criticita' diverse: ha
visto una storia sola, e ha deciso se raccontarla o buttarla via.

Qui va fatta una distinzione che conta molto per la relazione, perche' e' facile
scivolare.

Dire "il campionatore tiene il trenta per cento quando gli chiedi il trenta per cento"
e' un'affermazione **debole**. E' vera — abbiamo ottenuto 0, 8, 40, 56, 76 e 100 per
cento a fronte di 0, 10, 30, 50, 70 e 100 — ma con venticinque prove la precisione e'
scarsissima: l'intervallo di confidenza e' largo trenta o quaranta punti. Il quaranta
per cento osservato dove ne chiedevamo trenta e' rumore, non un'anomalia. Va scritto
**"coerente con"**, mai "verificato".

Dire "il campionatore non separa mai il task critico dagli altri" e' invece
**fortissimo**, perche' non e' una stima: e' un conteggio, e fa **zero su
centocinquanta**. Bastava un caso per smentirlo.

E' la differenza fra "abbiamo misurato una quantita' male" e "abbiamo cercato un
fenomeno e non c'e'".

Il corollario pratico e' scomodo: chiedendo il dieci per cento di campionamento, il
task critico perde la telemetria nel **novanta per cento delle esecuzioni** — non il
novanta per cento dei suoi dati, il novanta per cento delle esecuzioni *intere*. La
politica che servirebbe davvero — "il task critico sempre, i disturbi al dieci per
cento" — con OpenTelemetry standard **non si puo' nemmeno esprimere**.

### Terzo — come costruisci la pipeline decide se il sistema e' sicuro

Su tutta la campagna, il task critico ha mancato una scadenza **cinquantuno volte**.
Tutte e cinquantuno con il `SimpleSpanProcessor`. Zero con il `BatchSpanProcessor`,
zero senza tracing, a ogni livello di carico.

| | costo per giro | scadenze mancate | stallo peggiore |
|---|---|---|---|
| **Batch** | 8 µs | **0** | — |
| **Simple** | 340 µs | **51** | **86 ms** |

Ottantasei millisecondi: il task doveva ripartire ogni dieci, ed e' rimasto fermo per
piu' di otto periodi interi.

Il meccanismo si legge in una colonna sola — quante volte il programma ha provato a
contattare il collector, che nel nostro esperimento non c'era: il Batch **336** volte
per esecuzione, il Simple **24632**. Il Batch spedisce ogni cinque secondi
indipendentemente da quanti dati abbia prodotto; il Simple spedisce ogni singolo span,
aspettando la risposta, dentro il percorso critico.

**Il Batch isola il task critico da un guasto del sistema di monitoraggio, il Simple
glielo scarica addosso.**

## Parte terza: due volte ho quasi scritto il contrario del vero

Vale la pena raccontarlo, perche' sono due errori speculari e insegnano la stessa cosa.

### La mediana che nasconde i guasti

Guardando i primi risultati del blocco 3 avevo riportato "zero scadenze mancate". Il
numero veniva dalla mediana fra le quindici ripetizioni: dieci esecuzioni su quindici
non ne avevano nessuna, quindi la mediana faceva zero — e cancellava le sei che
c'erano.

La mediana e' una statistica **robusta**, cioe' progettata apposta per ignorare i casi
estremi. Ma per la sicurezza di un sistema real-time i casi estremi **sono il punto**.
Usare la mediana li' significa usare uno strumento che fa esattamente il contrario di
quello che serve.

I guasti si **sommano**, non si mediano.

### La deviazione standard che inventa un guasto che non c'e'

Sempre nel blocco 3 avevo riportato un jitter di ottocentosettantaquattro
microsecondi, che avrebbe voluto dire un task critico completamente destabilizzato.

Guardando meglio: i periodi erano strettissimi attorno a 9648 microsecondi, con un
massimo di 9657. Lo scarto veniva da **cinque giri su duemila** con periodo quasi
dimezzato — il timer che si riaggancia dopo uno stallo. Non irregolarita' diffusa: due
o tre incidenti isolati che gonfiano la statistica.

Lo si vede subito affiancando lo scarto interquartile, che ignora le code: deviazione
standard 874, interquartile **27**. Quando i due divergono di due ordini di grandezza,
il fenomeno e' fatto di incidenti, non di degrado.

C'e' un caso pero' in cui non divergono: con otto task di disturbo l'interquartile sale
a **1020**. Li' il degrado e' reale, ed e' l'unico punto dell'esperimento in cui il
Simple destabilizza il task critico in modo continuo.

### La lezione

Le due statistiche piu' comuni — mediana e deviazione standard — hanno mentito in
direzioni opposte sullo stesso dato. La prima ha nascosto guasti veri, la seconda ne ha
inventato uno falso.

Non e' un difetto delle statistiche: e' che erano quelle sbagliate per la domanda. Per
un sistema real-time la domanda non e' mai "come va di solito", e' **"quanto va male
nel caso peggiore"**.

## Una stranezza che resta aperta, e che ho scelto di non spiegare

A carico basso il jitter del task critico e' **bimodale**: le esecuzioni si dividono in
due gruppi netti, uno attorno a 2,5 microsecondi e uno attorno a 13, senza niente in
mezzo, circa meta' e meta'. L'abbiamo vista in **tre campagne indipendenti** a ore
diverse: non e' rumore.

E il carico la fa sparire. Con quattro o piu' task di disturbo, **tutte e quindici** le
esecuzioni finiscono nel gruppo buono.

Questa stranezza ci ha teso una trappola concreta. Confrontando la cella di controllo
fra due esecuzioni della stessa identica campagna, i numeri erano molto diversi: jitter
12,6 contro 4,8, latenza di risveglio 27 contro 7. Sembrava che qualcosa fosse
cambiato. Non era cambiato niente — il programma era **lo stesso identico binario**.
Era cambiato solo come era caduta la moneta: sette esecuzioni buone su quindici la
prima volta, nove la seconda. E siccome la mediana di una distribuzione a due gruppi
cade nel vuoto in mezzo, basta uno spostamento della ripartizione per farla saltare da
una parte all'altra.

Ho un sospetto sulla causa — lo stato sembra deciso all'avvio e poi congelato, il che
fa pensare a come la memoria viene disposta a ogni lancio — ma **non l'ho testato**. Il
test sarebbe di mezz'ora: rilanciare disabilitando la randomizzazione degli indirizzi.
L'ho lasciato scritto come lavoro da fare, non come spiegazione, perche' un'ipotesi
plausibile scritta come conclusione e' esattamente il genere di cosa che un esaminatore
smonta in trenta secondi.

## Cosa portiamo al Task 6

Due cose, sostenute da dati e non da ragionamenti.

La prima: **il campionamento di OpenTelemetry lavora sull'unita' sbagliata.** Decide
sulla traccia, mentre in un sistema mixed-criticality servirebbe decidere sul task. La
proposta architetturale e' un campionatore che guardi nome e attributi dello span
invece dell'identificatore della traccia — cosi' il task critico e quelli di
sottofondo possono avere frazioni di campionamento indipendenti **pur restando nella
stessa traccia causale**, che e' quello che rende la traccia utile.

La seconda: **la coda asincrona non e' un dettaglio implementativo, e' un requisito di
sicurezza.** Il confronto fra i due processori non e' una questione di prestazioni: e'
la differenza fra un sistema che rispetta le scadenze e uno che non le rispetta.
