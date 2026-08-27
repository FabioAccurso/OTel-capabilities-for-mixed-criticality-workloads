# Task 1 spiegato in parole semplici

## Cosa doveva verificare

I task esplorativi 0.x avevano compilato rt-app un po' alla volta, con qualche
aggiustamento a mano quando serviva. Il Task 1 fa la domanda seria: **partendo da zero, la
build funziona da sola?** Perché al momento di consegnare, chi legge deve poter scaricare
il progetto e compilarlo con tre comandi, senza trucchi.

## Il risultato

Sì. Ho cancellato tutto quello che la build precedente aveva prodotto e ho rifatto la
catena canonica:

```
./autogen.sh && ./configure && make
```

Funziona senza nessun aggiustamento. Questo chiude una pendenza del task 0.1, dove avevo
dovuto forzare a mano le opzioni del linker perché le librerie di OpenTelemetry non
esistevano ancora. Adesso ci sono, e il file di build scritto dal docente le trova da solo.

Tutti i pacchetti di sistema richiesti erano già installati, incluso `libjson-c-dev` che è
quello senza cui `configure` si ferma.

## Tre cose che vale la pena sapere

**Il progetto dichiara una versione vuota.** Durante `autogen.sh` compaiono cinque righe
`fatal: Nessun nome trovato`. Sembrano gravi, non lo sono: il file di configurazione prova
a ricavare il numero di versione dai tag di git, e questo repository non ne ha. La build
prosegue e funziona; l'unica conseguenza è che il pacchetto si dichiara "senza versione".
Si risolverebbe con un `git tag`, se vi interessa.

**Ci sono cinque warning in compilazione, tutti uguali e innocui.** Una costante viene
definita due volte, una dal sistema di build e una da un header. Il compilatore lo segnala
una volta per file sorgente. Nessun errore.

**Il binario "normale" non contiene OpenTelemetry.** Senza attivare esplicitamente il
tracing, rt-app pesa 340 KB e non ha dentro una riga di OTel — le librerie vengono passate
al linker ma, non essendoci niente da collegare, restano fuori. È una cosa buona: la
misura "senza strumentazione" del DoE è davvero senza strumentazione, non è la stessa cosa
con un interruttore spento.

## La verifica che conta

Il DoE non compila rt-app una volta: lo ricompila **tredici volte**, una per ogni
combinazione di opzioni da confrontare. Se una di quelle combinazioni non compilasse, ce
ne accorgeremmo a metà di una campagna da due ore. Quindi le ho provate tutte in anticipo.

Compilano tutte. E si scopre una cosa utile per pianificare:

| | senza tracing | con tracing |
|---|---|---|
| dimensione del binario | 340 KB | **5,2 MB** |
| tempo di compilazione | 5 secondi | **38 secondi** |

Quindici volte più grande, sette volte più lento da compilare. Il motivo è che tutto
OpenTelemetry viene incorporato staticamente dentro l'eseguibile.

## Ma compilare non basta

Un binario può compilare benissimo e ignorare completamente le opzioni che gli hai
passato. È letteralmente il problema che avevamo già trovato nel task 0.3, dove una
funzione di OTel ignorava tre macro su quattro.

Quindi ho fatto una controprova: stesso identico taskset, eseguito con due binari che
differiscono **solo** per il tipo di campionatore, senza nessun collector in ascolto.

- con il campionatore **spento**: zero tentativi di invio.
- con il campionatore **acceso**: un tentativo, che fallisce con
  `Zipkin Exporter: Connection failed` perché il collector non c'è.

Perfetto: quando nessuno span viene campionato non c'è niente da esportare e l'exporter
non prova nemmeno a connettersi. Le macro cambiano davvero il comportamento a runtime, non
solo il codice compilato.

## Quanto costerà la campagna

Con i tempi misurati qui e le dimensioni dei log misurate nel task 0.5, ora si può fare un
preventivo del Task 4:

- **410 esecuzioni** in totale, divise in tre blocchi da lanciare separatamente.
- **circa due ore e mezza** di macchina, di cui sette minuti solo di compilazioni.
- **circa 1,5 gigabyte** di log, più gli span del blocco 2 che non sono ancora stimabili.

Non è un dettaglio organizzativo: sapere che sono due ore e mezza significa che la
macchina va lasciata ferma, senza browser aperti — e il task 0.4 ha mostrato quanto quello
conti.

## Cosa manca prima di poter lanciare il DoE

Una cosa banale e una vera.

Quella banale: i tre percorsi in cima a `run_doe.sh` puntano a una cartella che su questa
macchina non esiste (`~/rtsia-project/project/...`). Vanno corretti, ed è esplicitamente
parte del Task 4.

Quella vera: il blocco 2 del DoE ha bisogno dell'exporter che stampa a video, cioè del
**Task 3**. E lì c'è già in agenda la correzione trovata nel task 0.3, ovvero che quella
funzione ignora tre delle quattro macro — senza sistemarla, il blocco 2 conterebbe sempre
lo stesso numero di span a qualunque livello di campionamento, e sarebbe tempo buttato.

Ho lasciato l'albero con la build normale, quella che ottiene chiunque faccia `make` su
un clone pulito.
