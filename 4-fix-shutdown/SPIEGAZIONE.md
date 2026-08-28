# Cosa e' successo, spiegato per bene

Versione discorsiva. I dettagli tecnici, i comandi e i log stanno in `NOTES.md`.

## Il fatto

Abbiamo lanciato il blocco 2 del DoE. Dopo circa cinque minuti si e' fermato da solo:
`rt-app` era morto con un **segmentation fault** al dodicesimo run su venticinque.

Un segmentation fault e' il sistema operativo che dice a un programma "hai provato a
toccare della memoria che non e' tua, ti fermo". Non e' un errore che il programma
puo' gestire: e' terminazione immediata.

La prima cosa da capire era **quando** fosse morto, perche' cambia tutto. Se fosse
morto durante la misura, i dati sarebbero da buttare in blocco. Tre indizi dicono
invece che e' morto **in chiusura**, a lavoro finito:

- il suo log di errore arriva fino a `[2] Exiting.`, cioe' i thread stavano gia'
  terminando ordinatamente;
- i log dei task di disturbo erano rimasti non compressi, segno che lo script si era
  interrotto prima di arrivare al passo di compressione;
- il log del task critico era esattamente 240 KiB, un numero troppo tondo per essere
  vero: e' quel che resta quando un processo muore senza svuotare i suoi buffer.

## Il primo tentativo, che e' fallito

L'istinto e' stato: rilanciamolo tante volte e vediamo quanto spesso capita. Ho
provato tre volte, e vale la pena raccontare come e' andata perche' e' istruttivo.

Il **primo tentativo era proprio sbagliato**: ho eseguito rt-app senza i privilegi di
root. Senza root il programma non puo' assegnarsi la priorita' real-time, quindi
moriva subito per un motivo completamente diverso da quello che stavo studiando.
Venti fallimenti su venti che non c'entravano niente. Se mi fossi fermato li' avrei
concluso una sciocchezza.

Il **secondo e il terzo** erano fatti bene — come root, dentro l'isolamento delle CPU,
con la configurazione vera del DoE — e hanno dato **zero crash su venti**, sia con il
codice difettoso sia con quello corretto.

Zero su venti non vuol dire "non succede". Mettendo insieme tutto siamo a **un crash
su trentadue esecuzioni**: e' un evento raro, e con eventi rari venti tentativi non
bastano a concludere niente. Se il tasso vero fosse uno su dodici, la probabilita' di
non vederne nemmeno uno in venti prove sarebbe comunque del 17%.

Morale: la caccia statistica era lo strumento sbagliato. Serviva qualcosa che vedesse
il difetto **anche quando non causa un crash**.

## Lo strumento giusto: AddressSanitizer

AddressSanitizer e' un controllore che si compila dentro il programma. Ogni volta che
il programma tocca la memoria, lui verifica che quel pezzo di memoria esista davvero
e sia ancora valido. Se trova un accesso illecito lo segnala **subito**, con tanto di
elenco delle funzioni che hanno portato li', anche se senza controllore il programma
sarebbe sopravvissuto per puro caso.

E' la differenza fra aspettare che un ponte crolli e andare a misurare le crepe.

Ha trovato **due** bug distinti. Il secondo e' quello che cercavo; il primo e' saltato
fuori per strada.

## Bug A: leggere 128 byte da una scatola da 8

Prima di iniziare a lavorare, ogni thread di rt-app si chiede su quali CPU ha il
permesso di girare. Si salva la risposta in una "maschera": una sequenza di bit, uno
per CPU, acceso se quella CPU e' utilizzabile.

Il codice alloca lo spazio per questa maschera cosi':

> conta quante CPU sono accese nella maschera, e alloca spazio per quel numero di CPU.

Sembra ragionevole ed e' sbagliato. Nel nostro esperimento le CPU utilizzabili sono la
2, la 3, la 6 e la 7: sono **quattro**, ma il numero piu' alto e' **sette**. Allocare
spazio "per quattro CPU" significa allocare spazio per le CPU da 0 a 3, mentre la
maschera deve poter rappresentare anche la 6 e la 7. E' come comprare uno scaffale da
quattro caselle perche' hai quattro libri, quando i libri sono numerati 2, 3, 6 e 7 e
tu vuoi metterli nella casella col loro numero.

Su questa macchina il danno non si vede, perche' l'allocatore arrotonda comunque a 8
byte e 8 byte bastano per 64 CPU. Ma su una macchina con piu' di 64 processori la
maschera verrebbe troncata.

Il guaio vero e' un altro. Piu' avanti il codice confronta due maschere per sapere se
l'affinita' e' cambiata, e usa una funzione che confronta **sempre 128 byte**, perche'
e' pensata per maschere di dimensione fissa. Su una scatola da 8 byte, sono 120 byte
letti oltre il bordo: roba che appartiene a qualcun altro.

Nel nostro caso questa lettura abusiva **non ha cambiato i risultati**, e l'ho
verificato invece di darlo per scontato. Contando le chiamate di sistema per impostare
l'affinita', il programma difettoso e quello corretto ne fanno esattamente cinque, una
per thread, all'avvio. Il motivo e' che quasi sempre le due maschere confrontate sono
*la stessa maschera*, e confrontare una cosa con se stessa da' "uguale" comunque.

**Quindi il blocco 1, che avevamo gia' eseguito, resta valido e non va rifatto.** Era
la domanda che mi preoccupava di piu'.

## Bug B: chiudere due volte la stessa porta

Questo e' il bug che ha causato il crash, ed e' nel codice aggiunto per OpenTelemetry.

Ogni thread ha il suo **span**, l'oggetto che rappresenta "questo thread e' stato vivo
da qui a qui" nella telemetria. Lo span e' gestito con uno `shared_ptr`, un puntatore
che tiene il conto di quanti proprietari ha e libera la memoria quando l'ultimo se ne
va. E' un meccanismo automatico proprio per non doverci pensare.

Il codice, pero', ci pensava lo stesso. Faceva due operazioni in fila:

1. chiamava a mano il distruttore dello `shared_ptr`;
2. subito dopo gli assegnava `nullptr`.

Il punto 2 da solo sarebbe stato corretto e sufficiente: assegnare `nullptr` a uno
`shared_ptr` **e' gia'** il modo di rilasciarlo, e lo lascia in uno stato valido e
vuoto. Il punto 1 invece termina la vita dell'oggetto. Farli entrambi significa
rilasciare due volte la stessa risorsa.

E' come chiudere una porta e poi girare di nuovo la maniglia per chiuderla ancora: la
seconda volta stai manovrando una porta che non esiste piu'.

C'e' un secondo strato. Questo teardown e' scritto in **due posti diversi** del
programma, per due scenari diversi: quello che gestisce la terminazione forzata e
quello che gestisce l'uscita naturale del thread. Il primo si protegge con un lucchetto
(un mutex), il secondo **non si protegge affatto**. Quindi i due possono capitare nello
stesso momento sullo stesso oggetto.

Chi ha scritto il codice ci aveva pensato — c'e' perfino un commento che dice "chiudilo
solo se non l'ha gia' chiuso l'altro" — ma il controllo che ha usato e' una semplice
lettura, e fra il momento in cui leggi e il momento in cui agisci l'altro thread puo'
essersi mosso. E' il classico errore di concorrenza: guardare non e' prenotare.

Questo spiega perche' il crash era raro e perche' non si era mai visto prima. Serve che
due thread arrivino esattamente nello stesso istante allo stesso punto. Col blocco 1
c'era **un thread solo**, quindi non poteva proprio capitare. Col blocco 2 ce ne sono
cinque, e infatti e' capitato.

## Le correzioni, e la prova che funzionano

Sono minime: tolto il distruttore chiamato a mano in entrambi i punti, e messo attorno
al teardown non protetto lo stesso lucchetto che usa l'altro. In tutto **37 righe
aggiunte e 13 rimosse** in un solo file.

Ho controllato che il lucchetto in piu' non crei un blocco circolare: chi lo teneva
prima lo rilascia sempre prima di mettersi ad aspettare gli altri thread, quindi
nessuno puo' restare in attesa di se stesso.

La prova e' un confronto controllato: stesso programma, stesse impostazioni, cambia
solo la presenza del fix.

| versione | esecuzioni con errore rilevato |
|---|---|
| con il bug | **5 su 5** |
| con il fix | **0 su 5** |

Cinque su cinque, non uno su trentadue. E' il vantaggio dello strumento giusto: il
difetto c'era sempre, semplicemente quasi sempre non faceva abbastanza danno da
fermare il programma.

Vale la pena notare una cosa: il bug si manifesta **anche quando il campionamento e'
completamente spento**. Con il sampler disattivato gli span non vengono registrati, ma
il codice che li distrugge male viene eseguito lo stesso. Ed e' esattamente nella cella
di controllo "campionamento spento" che il blocco 2 e' morto.

## Perche' questo conta per la tesi del progetto

Il progetto chiede di valutare OpenTelemetry su carichi mixed-criticality, e in
particolare l'impatto del monitoraggio.

Finora avevamo misurato un impatto sulle **prestazioni**: piu' jitter, piu' latenza di
risveglio, qualche decina di microsecondi per giro. Tutti costi previsti e governabili.

Questi due bug aggiungono una dimensione diversa: un impatto sull'**affidabilita'**. Il
codice di instrumentazione puo' far morire l'applicazione monitorata, in modo non
deterministico, e con una probabilita' che **cresce col numero di task monitorati** —
proprio la direzione sbagliata per un sistema mixed-criticality, dove i task sono tanti
e alcuni sono critici.

Va detto con onesta' che questi difetti sono della traduzione C++ di rt-app, non della
libreria OpenTelemetry. Ma la lezione generalizza, ed e' materiale diretto per il
Task 6: il codice di telemetria vive nello stesso spazio di indirizzamento
dell'applicazione, e un suo errore non degrada il servizio, lo interrompe. Un
osservatore che puo' uccidere l'osservato non e' un osservatore neutrale.

## Cosa succede adesso

- i binari gia' compilati vanno buttati, sono tutti costruiti dal sorgente difettoso;
- gli 11 run del blocco 2 raccolti prima del crash vanno buttati per lo stesso motivo;
- **il blocco 1 si tiene**, per la verifica raccontata sopra;
- il blocco 2 va rilanciato da zero, e il blocco 3 — che arriva a nove thread — adesso
  ha una possibilita' concreta di arrivare in fondo.
