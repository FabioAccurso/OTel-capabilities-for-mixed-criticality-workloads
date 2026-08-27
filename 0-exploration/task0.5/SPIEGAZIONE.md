# Task 0.5 spiegato in parole semplici

## Cosa volevamo capire

Nel Task 4 lanceremo centinaia di esperimenti in automatico. Prima di farlo conviene
lanciarne **uno solo, a mano**, e guardare con calma cosa produce: quali file nascono,
cosa c'è dentro, e soprattutto se i numeri che ne estrarremo hanno davvero senso. È
sgradevole scoprire che una misura era vuota dopo aver bruciato tre ore di esperimenti.

Ed è esattamente quello che è successo: guardando i file abbiamo trovato un problema che
avrebbe azzerato la variabile di risposta principale della campagna.

## Il taskset che abbiamo lanciato

`gen_config.py --n-lo 4` costruisce una situazione mixed-criticality in miniatura:

- **un task critico** (`HI_task`), priorità real-time massima, tutto per sé il core 2.
  Ogni 10 millisecondi si sveglia, calcola per 2 millisecondi, si riaddormenta. Usa il 20%
  della sua CPU: ha molto margine.
- **quattro task best-effort** (`LO_noise`), priorità normale, tutti insieme sul core 3.
  Ognuno vorrebbe calcolare per mezzo millisecondo ogni millisecondo, cioè usare metà
  CPU. Quattro che vogliono metà CPU ciascuno fanno il **200%** di una CPU sola. Sono
  sovraccarichi di proposito: servono a fare rumore.

Il tutto per 20 secondi.

## Cosa produce un run

Otto file, 5 megabyte:

```
config.json               la configurazione realmente eseguita, archiviata col run
stdout.log / stderr.log
rtapp-HI_task-0.log       1999 righe
rtapp-LO_noise-1.log      9844 righe
rtapp-LO_noise-2.log      9837 righe
rtapp-LO_noise-3.log      9847 righe
rtapp-LO_noise-4.log      9794 righe
```

Due cose da notare. Primo: c'è **un file per thread**, non per task — chiedere quattro
copie di `LO_noise` produce quattro log separati. Secondo: `test.sh` copia la
configurazione dentro la cartella del run. Sembra un dettaglio burocratico, ma quando
avrai duecento cartelle sarà l'unica cosa che ti dice con certezza quale configurazione ha
prodotto quali numeri.

E 5 MB per venti secondi: moltiplicato per le celle del DoE e le ripetizioni, si arriva a
qualche gigabyte. Meglio saperlo adesso.

Dentro ogni log c'è una riga per ogni giro del task, con undici colonne: quanto ha
calcolato davvero, ogni quanto si è svegliato, quando ha iniziato e finito, quanto margine
gli restava rispetto alla scadenza.

## I numeri dicono che il setup funziona

| | giri | calcolo | periodo | jitter |
|---|---|---|---|---|
| **HI_task** | 1998 | 1979 µs (ne chiedeva 2000) | 9987 µs (ne chiedeva 10000) | **10,3 µs** |
| LO_noise ×4 | ~9840 | 499 µs (ne chiedeva 500) | **2022 µs** (ne chiedeva 1000) | ~495 µs |

Il task critico si comporta benissimo: su venti secondi, il suo periodo non si è mai
allontanato più di 74 microsecondi dal valore nominale di 10 millisecondi.

I task di rumore invece hanno un periodo doppio del richiesto — 2022 microsecondi invece
di 1000. Non è un errore: è la conseguenza aritmetica del fatto che quattro thread
chiedono il 200% di una CPU che può darne il 100%. Ricevono metà di quello che vogliono,
quindi ci mettono il doppio. Il tempo di *calcolo* per giro resta giusto (499 µs): è la
*cadenza* a slittare.

E il rumore non tocca il task critico, perché sono su core fisici diversi con i gemelli
SMT isolati — è il lavoro del task 0.4 che paga i suoi dividendi.

## Il problema

Poi ho guardato la colonna `slack` — il margine rispetto alla scadenza, cioè la colonna da
cui si capisce se un task ha mancato il suo appuntamento. Era **zero su tutte le 41321
righe** di tutti e cinque i file. Anche per i task di rumore, che sono sovraccarichi al
200% e dovrebbero mancare scadenze in continuazione.

Andando a leggere il codice sorgente di rt-app, il motivo è netto: quella colonna viene
scritta **solo** quando il task usa un evento di tipo `timer`. La configurazione generata
da `gen_config.py` invece usa `sleep`.

La differenza è sottile ma decisiva. `sleep` vuol dire "dopo aver finito di calcolare,
dormi 8 millisecondi". `timer` vuol dire "svegliati 10 millisecondi dopo l'inizio del giro
precedente". Nel primo caso non esiste nessun appuntamento fissato in anticipo, quindi non
c'è niente da mancare: se il calcolo dura di più, il giro successivo semplicemente
comincia dopo. Nel secondo caso c'è una scadenza vera, e rt-app può dirti di quanto l'hai
sforata.

Il punto è che lo script di analisi del progetto, `analyze_doe.py`, calcola così la
variabile principale della campagna:

```python
"deadline_miss_ratio": sum(1 for s in slacks if s < 0) / len(slacks),
```

Con le configurazioni attuali avrebbe restituito **0,000 in ogni singola cella del DoE**.
Avremmo confrontato dozzine di configurazioni di OpenTelemetry su una metrica che è
costantemente zero per costruzione, senza accorgercene.

## La controprova

Non volevo fermarmi alla lettura del codice, quindi ho riscritto la stessa identica
configurazione mettendo `timer` al posto di `sleep`, e l'ho rilanciata.

| | slack diversi da zero | scadenze mancate |
|---|---|---|
| con `sleep` — HI_task | 0 su 1998 | 0 |
| con `sleep` — LO_noise | 0 su 9843 | 0 |
| con `timer` — HI_task | **1998 su 1998** | 1 (0,1%) |
| con `timer` — LO_noise | **9873 su 9874** | **5316 (53,8%)** |

La metrica si accende, e dice esattamente quello che deve dire: il task critico rispetta
le scadenze, i task best-effort ne mancano più della metà. È il quadro tipico di un
sistema mixed-criticality, ed è precisamente ciò che il progetto deve saper misurare.

Sono venute fuori altre tre cose.

**L'unica scadenza mancata da HI_task è la prima riga del log.** È un artefatto di avvio:
rt-app fissa la prima scadenza prima ancora di aver eseguito il primo calcolo, quindi
quando la valuta è già passata. Scartando la prima riga, il task critico ha zero
scadenze mancate su 1997 giri. Va segnalato perché `analyze_doe.py` non la scarta, e
riporterebbe uno 0,05% di miss in ogni cella come rumore costante.

**Compare una misura che prima non esisteva**: la latenza di risveglio, cioè quanto
tardi il kernel sveglia il task rispetto all'istante richiesto. Sul nostro setup:
mediana 7 microsecondi, caso peggiore 23. È un numero eccellente, ed è la prova che kernel
real-time e isolamento delle CPU stanno facendo il loro lavoro.

**Il jitter migliora di tre volte.** Con `sleep` la deviazione standard del periodo era
10,3 µs, con `timer` è 3,3 µs. Il motivo è che con `sleep` ogni fluttuazione del tempo di
calcolo si trasferisce sul periodo, mentre con `timer` i risvegli sono ancorati a una
griglia fissa. Siccome il jitter è un'altra delle variabili di risposta del DoE, partire
da 3,3 µs di rumore di fondo invece che da 10,3 rende molto più facile far emergere
l'overhead di OpenTelemetry, che è proprio ciò che vogliamo misurare.

## In sintesi

Il run funziona, il setup regge, e adesso sappiamo esattamente che forma ha un
esperimento. Ma abbiamo anche scoperto che, così com'è, la campagna avrebbe prodotto due
metriche su sei costantemente nulle. La correzione è una riga di configurazione, e va
fatta nel Task 2 — non l'ho applicata qui perché scrivere le configurazioni definitive è
compito di quel task, e questo doveva solo guardare.
