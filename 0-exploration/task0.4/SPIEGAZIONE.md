# Task 0.4 spiegato in parole semplici

## Il problema di partenza

Vogliamo misurare quanto costa il monitoraggio OpenTelemetry su un task real-time. Per
farlo dobbiamo poter dire frasi come "con il tracing attivo il task impiega 40 µs in più".
Ma questa frase ha senso solo se, *senza* tracing, il task impiega sempre lo stesso tempo.
Se il tempo di esecuzione balla da solo del 30% a seconda di cosa fa il resto del computer,
i 40 µs di OTel spariscono nel rumore e la campagna sperimentale non dimostra niente.

Isolare le CPU serve a questo: costruire un angolo di macchina dove il tempo è prevedibile.

## Due livelli di isolamento

C'è una cosa che ho capito facendo questo task: esistono **due** meccanismi diversi, e
si tende a confonderli.

Il primo è a livello di **kernel**, si attiva scrivendo parametri nella riga di avvio di
GRUB e richiede un riavvio. Dice al kernel: "queste CPU non esistono, per te". Il secondo
è a livello di **runtime**, lo fa lo script `isolate_cpus.sh` con il comando `cset`, e non
richiede riavvii. Dice al kernel: "sposta tutti i processi che ci sono adesso da un'altra
parte".

Il primo è molto più forte, perché vale anche per i processi che nasceranno dopo. Il
secondo fotografa la situazione in un istante.

Tu avevi già applicato il primo prima che iniziassi il task, quindi ho verificato entrambi.

## Il kernel fa il suo lavoro

Ho fatto la prova più semplice possibile: ho lanciato **8 processi** che consumano CPU al
100%, senza dire loro dove andare. La macchina ha 8 CPU logiche. Se non ci fosse
isolamento, il kernel ne metterebbe uno per CPU.

Invece li ha ammassati tutti su quattro CPU — cpu0, cpu1, cpu4, cpu5 — lasciando cpu2,
cpu3, cpu6 e cpu7 **completamente vuote**. Ha preferito far litigare due processi sulla
stessa CPU piuttosto che usare quelle isolate. È la dimostrazione che `isolcpus` funziona.

Poi ho verificato il secondo effetto, quello dell'orologio. Normalmente il kernel
interrompe ogni CPU 1000 volte al secondo per fare le sue faccende (contabilità, cambio
di processo, timer). Ogni interruzione è un piccolo furto di tempo al task real-time.
Contando le interruzioni durante 5 secondi di carico:

- cpu0: **4283** interruzioni
- cpu2 (isolata): **5** interruzioni

Da 1000 al secondo a 1 al secondo. Quel singolo tick residuo il kernel se lo tiene per
forza, ma è irrilevante.

## Quanto conta davvero, in numeri

Ho scritto un programmino che esegue 2000 volte la stessa identica quantità di calcolo e
cronometra ogni ripetizione. In un sistema real-time non interessa la media: interessa il
**caso peggiore**, perché è quello che fa sforare la scadenza.

Con la macchina disturbata da 8 processi in background:

- su **cpu0** (non isolata): la ripetizione più lenta ha impiegato **20,5 ms** contro una
  mediana di 1,6 ms. Tredici volte tanto.
- su **cpu2** (isolata): la ripetizione più lenta ha impiegato **2,222 ms** contro una
  mediana di 2,172 ms. Il 2% in più.

E ripetendo la misura tre volte su cpu2, la mediana è stata 2171,8 — 2171,8 — 2171,9 µs.
Un decimo di microsecondo di differenza fra un esperimento e l'altro. È il tipo di
stabilità che serve per poter dire "OTel costa 40 µs".

## La sorpresa

Poi è successa una cosa che non mi aspettavo, e che ha finito per essere il risultato più
importante del task.

Le CPU di questo processore sono 8 solo sulla carta: fisicamente i core sono 4, e ognuno
ospita due "CPU logiche" che si spartiscono lo stesso hardware. È l'hyper-threading. cpu2
e cpu6 sono lo stesso core fisico.

Mi aspettavo che, tenendo occupata cpu6, il lavoro su cpu2 rallentasse — due inquilini
nello stesso appartamento. Ho misurato l'opposto: **occupando cpu6, il calcolo su cpu2
diventava il 28% più veloce.**

Ho verificato che non fosse la frequenza, leggendo direttamente i contatori hardware del
processore: 1799,9 MHz con cpu6 vuota, 1800,0 MHz con cpu6 occupata. Identica.

Allora ho provato con due tipi di calcolo diversi. Un ciclo di aritmetica **intera**: la
differenza è stata dello 0,3%, cioè niente. Un ciclo di aritmetica **in virgola mobile**:
36% di differenza. L'effetto riguarda solo le unità floating-point, e la spiegazione più
probabile è che quando il core non le usa il processore le mette a riposo per risparmiare
energia, e riaccenderle costa; se il core "gemello" lavora di continuo, restano accese.

## Perché questa sorpresa è un problema serio per il progetto

Perché rt-app, per simulare il carico di lavoro di un task real-time, usa proprio un
ciclo in virgola mobile — la funzione si chiama `waste_cpu_cycles()` ed è fatta di
chiamate `ldexp` annidate.

Ho quindi rifatto la prova su rt-app vero, chiedendogli una fase di lavoro da 2000 µs:

- con cpu6 vuota: rt-app ha eseguito **1982 µs** di lavoro. Perfetto, −0,9%.
- con cpu6 occupata: rt-app ha eseguito **1302 µs**. Il 35% in meno del richiesto.

E qui sta il punto. Nei log di rt-app **non appare nessun errore**. Non c'è nessuna
deadline mancata, nessun avviso. Semplicemente il task ha fatto un terzo di lavoro in
meno, e il file di log lo scrive come se fosse normale.

Se avessimo isolato solo cpu2 e cpu3, lasciando cpu6 e cpu7 al sistema operativo, ogni
singola cella del DoE avrebbe eseguito una quantità di lavoro diversa, a seconda di cosa
il kernel avesse deciso di far girare su cpu6 in quel preciso momento. Avremmo confrontato
configurazioni di OpenTelemetry attribuendo a OTel differenze che erano solo rumore
hardware.

Il fatto che tu abbia isolato **2,3,6,7** — cioè due core fisici interi, gemelli inclusi —
è ciò che rende le misure confrontabili. E ha un corollario pratico gradito: il valore
`CALIB_NS=139` trovato nella sessione precedente risulta ancora corretto, quindi non c'è
niente da rimisurare.

## Lo script del docente: funziona, ma aveva due difetti

`isolate_cpus.sh` fa il suo mestiere. L'ho verificato lanciando un processo "dentro lo
scudo" e controllando che fosse davvero confinato: lo era.

Però conteneva due errori che ho corretto.

**Il primo** è sottile e quasi divertente. Lo script, dopo aver creato lo scudo, chiede al
sistema quante CPU ci sono per calcolare quali *non* sono isolate. Ma nel frattempo lo
script stesso è stato spostato dentro lo scudo, quindi alla domanda "quante CPU ci sono?"
il sistema risponde contando solo quelle che lo script può usare — sei invece di otto.
Lo script finiva per ragionare su una lista di CPU sbagliata. Sulla nostra macchina
l'errore si annullava per coincidenza, ma sarebbe riemerso cambiando configurazione.

**Il secondo** è emerso proprio correggendo il primo, ed è più grave. Una volta che lo
script calcolava la lista giusta, spostava gli interrupt del sistema su cpu6 e cpu7 —
cioè proprio sui gemelli delle CPU real-time. Alla luce di quanto scoperto sopra, è
esattamente ciò che non si deve fare: un interrupt gestito su cpu6 disturba cpu2 come se
fosse gestito su cpu2.

Ho corretto entrambi e ho aggiunto un avviso esplicito: se chiami lo script isolando una
CPU ma non il suo gemello, adesso te lo dice.

```
$ isolate_cpus.sh 2,3
[isolate] WARNING: cpu6 is the SMT sibling of isolated cpu2 but is NOT isolated.
[isolate] WARNING: cpu7 is the SMT sibling of isolated cpu3 but is NOT isolated.
```

Da qui in avanti lo script va chiamato con **`2,3,6,7`**, non con `2,3`.

## In sintesi

L'isolamento funziona ed è verificato con numeri, non a fiducia. La CPU isolata ripete la
stessa misura a un decimo di microsecondo di distanza anche mentre il resto della macchina
è sotto carico pieno, mentre una CPU normale arriva a impiegare tredici volte il tempo
tipico. E abbiamo scoperto un limite metodologico di rt-app che vale la pena citare nella
relazione: il suo "lavoro" non è un'unità invariante, dipende dallo stato di risparmio
energetico delle unità floating-point del core.
