# Frequenza e calibrazione, spiegate con parole semplici

## Da dove nasce il problema

Fin dal task 0.1 c'era un numero che non tornava: chiedevamo a rt-app di lavorare per
2000 microsecondi e ne misuravamo 4150. Nel task 0.3 ne è saltato fuori un altro: la fase
di calibrazione iniziale durava 10 secondi, il doppio dell'esperimento vero.

Entrambi hanno la stessa radice: **il processore non va sempre alla stessa velocità**. I
portatili moderni alzano e abbassano la frequenza in continuazione — vanno in turbo quando
c'è da spingere, rallentano quando scaldano o quando non serve. Per l'uso normale è
un'ottima idea. Per misurare un tempo di esecuzione nel caso peggiore è un disastro: stai
misurando col metro di gomma.

## Prima sorpresa: il tuo kernel non ha la manopola

La ricetta standard sarebbe mettere il "governor" della CPU su `performance`. Solo che il
tuo kernel real-time è stato compilato **senza** il sottosistema che gestisce la frequenza:

```
# CONFIG_CPU_FREQ is not set
```

Non è un errore, è una scelta comune in ambito real-time: quel sottosistema introduce
latenze. Il risultato però è che la cartella `/sys/.../cpufreq` non esiste proprio, non c'è
nessun governor da impostare, e `cpupower` non serve a niente.

L'unica strada rimasta è parlare **direttamente al processore**, scrivendo nei suoi
registri interni (si chiamano MSR, Model Specific Registers). È come togliere il cruscotto
e collegarsi ai fili. Per fortuna il kernel espone questa possibilità
(`/dev/cpu/N/msr`) ed è già attiva.

Ho scritto `scripts/utils_freq/cpu_freq.py` che fa tre cose: `info` legge lo stato,
`pin` blocca la frequenza e spegne il turbo, `reset` rimette tutto com'era.

## Cosa è successo quando l'ho lanciato

Prima, misurando la frequenza reale mentre il core lavorava: tra 2587 e 2652 MHz, con il
turbo che spingeva ben oltre i 2000 nominali. Dopo: **tra 1794 e 1802 MHz su tutti gli otto
core**. Lo scarto tra una CPU e l'altra è passato dal 2,5% allo 0,3%. Il metro non è più di
gomma.

Una nota onesta: il processore dichiara una frequenza base di 2000 MHz nei suoi registri,
ma sotto carico si assesta a 1800, che è il valore di targa dell'i7-8565U. Chiediamo 2000,
l'hardware clampa a 1800. Il numero assoluto stampato può quindi essere un po' ottimista;
quello che ci interessa — che sia *sempre lo stesso* — è verificato.

## Seconda sorpresa: non bastava

Rimisurata la calibrazione a frequenza fissa, continuava a impiegare dai 5 ai 22 secondi e
a restituire numeri diversi ogni volta. Quindi il DVFS non era l'unico colpevole. Ne sono
emersi altri due.

**Firefox.** Stava usando circa il 90% di un core. La calibrazione di rt-app gira come un
normalissimo processo, quindi veniva interrotta di continuo, e ogni interruzione allunga il
tempo che sta cercando di misurare. Quando l'hai chiuso, i numeri sono cambiati — ma non si
sono ancora stabilizzati, perché c'è dell'altro.

**L'hyper-threading.** Il tuo processore ha 4 core fisici che il sistema mostra come 8. La
CPU 2 e la CPU 6 sono lo stesso pezzo di silicio. Se qualcosa gira sulla 6, la 2 rallenta,
e nemmeno dare priorità real-time serve: la priorità ti protegge dall'essere interrotto,
non dal vicino che consuma il tuo stesso motore.

**L'algoritmo stesso.** Questa è la scoperta più interessante. Guardando il codice di
`calibrate_cpu_cycles_1()` si vede che tiene una media che parte da zero e si avvicina al
valore vero dimezzando l'errore a ogni giro, e si ferma quando l'ultima misura cade entro
il 2% della media. Facendo i conti, quella condizione non può essere soddisfatta prima del
**sesto giro** — e ogni giro comincia con un `sleep` di **un secondo pieno**. Quindi la
calibrazione di rt-app non può durare meno di sei secondi, nemmeno su una macchina
perfettamente silenziosa. Non è un problema del tuo PC: è come è scritta.

## La soluzione: non calibrare affatto

Leggendo il parser della configurazione ho trovato che se al campo `"calibration"` dai un
**numero** invece della stringa `"CPU0"`, rt-app lo prende per buono e salta tutta la
procedura.

Restava da capire quale numero. Non potevamo chiederlo alla calibrazione — è proprio quella
di cui non ci fidiamo. Così l'ho ricavato al contrario, dai fatti. rt-app trasforma "lavora
per 2000 µs" in "esegui N giri di un ciclo", dove N si ottiene dividendo 2000 µs per il
costo di un giro. Se allora gli diamo un costo *sbagliato ma noto* e guardiamo quanto è
durata davvero la fase, il costo vero si ricava con una proporzione.

Detto e fatto: con costo dichiarato 100 ns la fase durava 2772 µs invece di 2000, quindi il
costo vero è 100 × 2772 / 2000 = **139 ns**. Riprovato con 139: la fase dura 1991 µs, cioè
lo 0,5% sotto il bersaglio. Stesso identico risultato con priorità real-time.

## Il risultato

Cinque esecuzioni di fila con il valore fissato:

| | prima | adesso |
|---|---|---|
| durata misurata della fase | ~4150 µs (chiesti 2000) | 1990–1991 µs |
| variabilità tra run | 35% | **0,05%** |
| tempo totale per 5 s di lavoro | 13,4 s | **5,01 s** |

Il tempo morto è sparito e, cosa più importante, `"run": 2000` adesso significa la stessa
identica quantità di lavoro in ogni cella del DoE. Senza questo, avresti confrontato
configurazioni di OpenTelemetry facendo eseguire loro carichi diversi — e qualunque
differenza nei risultati sarebbe stata inattribuibile.

## Come si usa, in pratica

Prima di ogni sessione di misure:

```
pkexec /usr/bin/python3 scripts/utils_freq/cpu_freq.py pin
```

e alla fine, per restituire il turbo al portatile:

```
pkexec /usr/bin/python3 scripts/utils_freq/cpu_freq.py reset
```

Le configurazioni del DoE vanno generate con `--calib 139`. Se un giorno cambi macchina o
cambi la frequenza fissata, quel numero si rimisura in un minuto con `tune_calib.sh`.

## Cosa resta da fare

L'hyper-threading è ancora acceso e le CPU non sono ancora isolate dal resto del sistema.
Sono esattamente gli argomenti del task 0.4, e adesso hanno una base solida su cui
appoggiarsi: con la frequenza ferma e la calibrazione tolta di mezzo, qualunque variazione
residua che misureremo sarà davvero interferenza, e non il processore che cambia marcia.
