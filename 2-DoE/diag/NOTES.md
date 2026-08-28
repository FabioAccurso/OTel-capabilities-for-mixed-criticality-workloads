# Campagna diagnostica — regime anomalo a ~3.5x

**Non fa parte del DoE.** Serve a testare una sola ipotesi: il regime a ~3.5x
osservato 1 volta nel blocco 1 e 2 volte nel blocco 2 e' causato da un calo
della **frequenza effettiva** della CPU del task critico?

## Metodo

Il fattore 3.67 osservato corrisponde a 2296/626 MHz. Per distinguere "la CPU
era lenta" da "il codice ha fatto piu' lavoro" serve la frequenza *effettiva*
durante il run, che nessuno script misurava: `mhz_med` legge `/proc/cpuinfo`
**dopo** il run, e riporta 2295 anche nei run anomali.

Aggiunta a `run_doe.sh` la colonna **`aperf_mhz`**, da contatori cumulativi
`APERF` (0xE8) / `MPERF` (0xE7):

```
f_media = (dAPERF / dMPERF) * f_TSC        f_TSC = 2300 MHz (constant_tsc)
```

**Le due letture cadono fuori dalla finestra di misura**, esattamente dove
`run_doe.sh` gia' legge `mhz_med` e `tctl`. E' una scelta obbligata: `rdmsr -p N`
forza un IPI verso la CPU N, quindi campionare *durante* il run inietterebbe
interruzioni nel task critico e renderebbe il blocco 3 non omogeneo rispetto ai
blocchi 1 e 2. I contatori sono cumulativi, quindi due letture bastano: il
regime anomalo dura run interi o centinaia di iterazioni consecutive, e
trascinerebbe la media in modo inequivocabile (626 contro 2296 MHz).

Validazione del metodo prima dell'uso: busy loop noto di 2 s su cpu2 ->
**2290 MHz** (rapporto 0.9957). Nei run normali `aperf_mhz` concorda con
`mhz_med` entro lo 0.3 %.

## Campagna

3 celle x 25 rip. da 20 s = **75 run**, condizioni **identiche** al blocco 2
(`trace_level=2`, Batch, exporter ostream, 1 HI su cpu2 + 4 LO su cpu6): le due
celle in cui il fenomeno era comparso (AlwaysOff, Ratio 0.3) piu' AlwaysOn come
controllo.

## Esito: il fenomeno NON si e' riprodotto

```
run anomali (run_med > 2500 us):   0 su 75
aperf_mhz:  n=75   media 2288.1   min 2286   max 2298
run_med per cella:  AlwaysOn 1983-1999   Ratio 0.3 1953-1969   AlwaysOff 1983-1999
```

**L'ipotesi frequenza resta quindi non verificata: non e' stata ne' confermata
ne' falsificata.** Senza un run anomalo da misurare, `aperf_mhz` non ha nulla su
cui pronunciarsi.

Il risultato non e' pero' in contraddizione col tasso osservato:

| | |
|---|---|
| tasso nei blocchi 1+2 | 3/230 = **1.3 %** |
| P(0 anomali in 75 run) a quel tasso | **0.37** |
| limite superiore 95 % del tasso, dato 0/75 | **4.0 %** |

Un'assenza in 75 run era attesa con probabilita' 37 %, quindi non sorprende e
**non e' evidenza che il fenomeno sia sparito**. Il limite superiore al 95 %
(4.0 %) e' compatibile con l'1.3 % misurato.

## Valore acquisito

1. La strumentazione **ora c'e'**: al prossimo run anomalo — nel blocco 3 o
   altrove — `aperf_mhz` rispondera' immediatamente, senza dover riprodurre
   nulla a comando;
2. e' stato escluso che il fenomeno sia *frequente* nelle condizioni del blocco
   2: il tasso e' sotto il 4 %;
3. il costo di tenerla e' nullo: due letture MSR fuori dalla finestra di misura,
   che non cambiano le condizioni sperimentali rispetto ai blocchi gia' fatti.

## Cosa resta da provare

`hwlatdetect` (pacchetto `rt-tests`, disponibile ma **non ancora installato**)
misura le finestre in cui la CPU sparisce senza che il kernel se ne accorga,
tipicamente per SMI del firmware. E' l'unica ipotesi rimasta che spieghi sia il
regime a 3.5x sia il deadline miss isolato del blocco 2, e non richiede di
aspettare che il fenomeno ricapiti. Va eseguito a sistema fermo, fuori da
qualunque campagna.
