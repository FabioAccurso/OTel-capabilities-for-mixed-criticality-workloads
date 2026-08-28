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

## Un terzo bug, trovato lanciando il blocco 3

Qualche ora dopo, il blocco 3 si e' fermato a meta' — sei celle su dodici — con un errore
diverso: non un segmentation fault ma un **abort**, con il messaggio

```
terminate called without an active exception
```

Stavolta il difetto e' piu' sottile e piu' interessante, perche' non e' un errore di
distrazione: e' l'incontro fra due meccanismi che presi da soli sono corretti.

### Il primo meccanismo: come rt-app ferma i suoi thread

Quando l'esperimento finisce, rt-app deve fermare i thread. Lo fa in **due** modi
contemporaneamente. Alza una bandierina (`continue_running` va a zero) che i thread
controllano a ogni giro e che li fa uscire spontaneamente; e in piu' chiama
`pthread_cancel()`, che e' il modo brutale: "termina, adesso".

La bandierina da sola basterebbe. I nostri thread la controllano ogni millisecondo o
ogni dieci, quindi escono comunque quasi subito.

### Il secondo meccanismo: come funziona davvero `pthread_cancel`

Qui c'e' la sottigliezza. `pthread_cancel()` **non uccide sul colpo**: lascia una
richiesta in sospeso, che viene eseguita quando il thread arriva a un cosiddetto "punto
di cancellazione" — tipicamente una chiamata che aspetta qualcosa: dormire, leggere,
scrivere sulla rete.

E quando quella richiesta scatta, Linux non fa semplicemente sparire il thread: **srotola
lo stack**, cioe' ripercorre a ritroso tutte le funzioni aperte per chiuderle per bene.
Usa lo stesso identico meccanismo delle eccezioni C++.

### Lo scontro

Mettiamo insieme i pezzi. Il thread ha finito il lavoro e sta chiudendo i suoi span. Con
il processore "Simple", chiudere uno span significa spedirlo *subito* al collector. Ma il
collector non c'e', la connessione fallisce, e il codice di OpenTelemetry si mette ad
aspettare un attimo prima di rinunciare.

Quell'attesa e' un punto di cancellazione. La richiesta in sospeso scatta proprio li', e
lo srotolamento parte **da dentro il codice di OpenTelemetry** — codice che non e' stato
scritto per essere interrotto in quel modo. Lo srotolamento non riesce a completare, e il
runtime C++ fa l'unica cosa che sa fare quando non sa cosa fare: chiama `abort()`.

L'ho visto letteralmente, col debugger, riga per riga. Il thread era `HI_task-0` e il suo
stato era `(Exiting)`: aveva gia' finito, stava solo mettendo in ordine.

### Perche' proprio quella cella e non le altre

Perche' la probabilita' dipende da **quanto tempo il thread passa dentro il codice di
OpenTelemetry**, e quello dipende da quanti span deve spedire uno per uno:

| configurazione | tentativi di connessione falliti, per esecuzione | esito |
|---|---|---|
| Batch, nessun disturbo | 8 | 15 su 15 |
| Batch, un disturbo | 157 | 15 su 15 |
| Simple, nessun disturbo | 2007 | 15 su 15 |
| Simple, un disturbo | **21943** | morto alla seconda |

Ventiduemila tentativi falliti in venti secondi, e quattro megabyte di messaggi d'errore.
Con quattro e otto task di disturbo sarebbero stati ottantamila e centosessantamila: quelle
celle non avevano speranza.

### La correzione

Tre righe: dire al thread che **non e' cancellabile**, quando il tracing e' compilato.
La bandierina basta gia', quindi non perdiamo nulla.

La cosa di cui vado piu' contento e' la condizione `quando il tracing e' compilato`:
significa che le esecuzioni **senza** telemetria mantengono un comportamento identico a
prima, quindi tutti i dati di controllo gia' raccolti restano confrontabili senza bisogno
di giustificazioni.

Verifica, con due programmi identici a meno di quelle tre righe, venti esecuzioni ciascuno:

| | crash |
|---|---|
| senza la correzione | **9 su 20** |
| con la correzione | **0 su 20** |

Il 45% di fallimenti: stavolta il difetto era facile da riprodurre, al contrario del
precedente che si vedeva una volta su trentadue.

### Quello che questo bug ci insegna sul progetto

Al di la' della correzione, il conteggio dei tentativi falliti dice una cosa importante e
generale.

Il **Batch** accumula gli span e li spedisce ogni cinque secondi: se il collector non
risponde, se ne accorge otto volte in venti secondi e il task critico non se ne accorge
affatto. Il **Simple** spedisce ogni span appena e' pronto, dentro il percorso critico: se
il collector non risponde, il task critico paga ventiduemila fallimenti.

Detto in una frase: **il Batch isola il task critico da un guasto del backend, il Simple
glielo scarica addosso.** Per un sistema mixed-criticality e' esattamente la proprieta'
che conta, perche' i collector cadono davvero e non e' accettabile che il guasto di un
sistema di monitoraggio si propaghi a un task con scadenze rigide.

C'e' pero' una conseguenza da dichiarare con onesta': i numeri che misuriamo sulle celle
Simple **non dicono "quanto costa esportare"**, dicono "quanto costa provare a esportare
verso un backend irraggiungibile". Sono due cose diverse, e la relazione deve chiamarle
col nome giusto.

Verrebbe da dire: allora accendiamo un collector. Ci abbiamo pensato e la conclusione e'
stata no. Con Simple e otto task di disturbo servirebbero **ottomila richieste HTTP al
secondo**; il collector finto che abbiamo e' un server Python a thread singolo che
riscrive un file a ogni richiesta, quindi diventerebbe lui il collo di bottiglia — e
siccome Simple aspetta la risposta *dentro* il percorso critico, staremmo misurando la
lentezza del nostro server invece del costo di OpenTelemetry. Una misura falsata in modo
piu' insidioso, perche' sembrerebbe legittima.

I blocchi 1 e 2 non sono toccati dalla questione: il primo fa otto connessioni per
esecuzione, il secondo non usa affatto la rete. Resta un limite dichiarato dello studio:
**non abbiamo un numero per il costo di un export che riesce.**

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
