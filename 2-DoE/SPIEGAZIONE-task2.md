# Task 2 spiegato in parole semplici

## Cosa doveva fare

Scrivere le configurazioni definitive degli esperimenti: i "compiti" che rt-app dovrà
eseguire in ogni cella della campagna. E soprattutto applicare la correzione che era
emersa dal task 0.5, dove avevamo scoperto che la metrica principale del progetto sarebbe
stata sempre zero.

## La correzione

Il problema era una parola sola nel file di configurazione.

Prima, ogni task diceva: *"calcola per 2 millisecondi, poi dormi per 8"*. È la parola
`sleep`. Sembra ragionevole, ma ha un difetto: non c'è nessun appuntamento. Se il calcolo
dura di più del previsto, il giro dopo semplicemente comincia più tardi, e nessuno se ne
accorge. Non essendoci una scadenza, non c'è modo di mancarla — e infatti rt-app lasciava
a zero tutte le colonne che riguardano le scadenze.

Adesso ogni task dice: *"calcola per 2 millisecondi, poi risvegliati 10 millisecondi dopo
l'inizio di questo giro"*. È la parola `timer`. Ora l'appuntamento c'è, è fissato in
anticipo, e se lo si manca rt-app lo scrive.

Il dettaglio da non sbagliare, e che ho verificato leggendo il sorgente, è che il numero
che si scrive è il **periodo intero**, non il tempo di attesa. Con `sleep` si scriveva 8
(dormi 8 ms dopo aver calcolato per 2); con `timer` si scrive 10 (il ciclo completo dura
10 ms). Sono la stessa cosa solo se il calcolo dura esattamente quanto previsto.

Ho lasciato la possibilità di tornare al vecchio comportamento con un'opzione
(`--pacing sleep`), che serve solo a poter rifare il confronto del task 0.5 e stampa un
avviso perché non venga usata per sbaglio in un esperimento vero.

## Le quattro configurazioni

La campagna userà quattro taskset, che differiscono solo per quanti task di disturbo
girano accanto a quello critico:

| | task critico | disturbo |
|---|---|---|
| `cfg_n0` | 20% di una CPU | nessuno |
| `cfg_n1` | 20% di una CPU | 1 thread, chiede il 50% di un'altra CPU |
| `cfg_n4` | 20% di una CPU | 4 thread, chiedono il **200%** |
| `cfg_n8` | 20% di una CPU | 8 thread, chiedono il **400%** |

Chiedere il 400% di una CPU che può darne il 100% è ovviamente impossibile: è
esattamente il punto. Quei task servono a mettere il sistema sotto pressione e a vedere se
il task critico regge.

## La verifica

Le ho eseguite tutte e quattro. Il risultato:

**Il task critico non manca mai una scadenza.** Nemmeno con otto thread che si azzuffano
sulla CPU accanto. Zero su circa duemila giri, in tutte e quattro le configurazioni. E
continua a fare esattamente il lavoro che gli chiediamo — 1979 microsecondi contro i 2000
richiesti, l'1% di scarto, identico a qualunque livello di carico.

**I task di disturbo mancano più della metà delle scadenze** appena diventano
sovraccarichi. È il quadro tipico di un sistema mixed-criticality, ed è precisamente
quello che il progetto deve saper misurare.

Questo è anche il collaudo finale del lavoro fatto nei task precedenti: la frequenza fissa,
l'isolamento delle CPU e i core gemelli tenuti liberi stanno reggendo tutti insieme.

## Due cose da sapere prima di leggere i risultati della campagna

**La percentuale di scadenze mancate dai task di disturbo non cresce col carico.** Passando
da 4 a 8 thread di disturbo — cioè raddoppiando la pressione — la percentuale resta ferma
al 53%. Non è un errore: quando un task sfora, rt-app gli sposta avanti l'appuntamento
successivo invece di accumulare il ritardo, quindi la percentuale si assesta invece di
salire verso il 100%. Quello che cresce davvero è il ritardo del risveglio, che passa da 7
millisecondi a 19. In fase di analisi bisognerà guardare quello, non la percentuale.

**Un singolo esperimento non è rappresentativo.** Nella prima tornata un run sembrava
anomalo, con jitter quattro volte più alto degli altri. Ho pensato dipendesse dal carico,
e mi sbagliavo: ripetendo, la stessa anomalia è comparsa anche negli esperimenti **senza
alcun disturbo**. Su dieci run, quattro hanno mostrato un jitter elevato, in modo
apparentemente casuale.

Non ho trovato la causa: la CPU è isolata, la frequenza è fissa, il core gemello è vuoto.
Resta qualcosa di condiviso più in profondità nel processore, che si manifesta a
intermittenza.

La conseguenza però è chiara e utile: le 15-25 ripetizioni per cella previste dalla
campagna **non sono una formalità statistica, servono davvero**. E in fase di analisi i
confronti andranno fatti fra mediane di molte ripetizioni, mai fra due run singoli — che
è poi esattamente ciò che la traccia dell'elaborato chiedeva quando parlava di 10-30
ripetizioni per misura.
