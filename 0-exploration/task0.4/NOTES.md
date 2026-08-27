# Task 0.4 — isolamento delle CPU: cosa fa il kernel, cosa aggiunge lo script

Data: 2026-08-27. Kernel `6.12.79-rt17` (PREEMPT_RT), i7-8565U, 4 core / 8 thread.
Frequenza pinnata a 1800 MHz effettivi prima di ogni misura (turbo off, vedi
`0-exploration/freq-calibrazione/`).

## 0. Stato di partenza: la cmdline era già stata cambiata

All'inizio del task la macchina era stata riavviata con la riga GRUB proposta:

```
isolcpus=domain,managed_irq,2,3,6,7 nohz_full=2,3,6,7 irqaffinity=0,1,4,5
```

```
/sys/devices/system/cpu/isolated   -> 2-3,6-7
/sys/devices/system/cpu/nohz_full  -> 2-3,6-7
tutti i 32 /proc/irq/*/smp_affinity_list -> 0-1,4-5
```

Quindi il task si è diviso in due metà: (1) verificare che l'isolamento **del kernel**
funzioni, (2) capire cosa aggiunge davvero `isolate_cpus.sh` sopra di esso.

Topologia SMT (necessaria per leggere tutto il resto):

| core fisico | logiche |
|---|---|
| 0 | 0, 4 |
| 1 | 1, 5 |
| 2 | **2**, 6 |
| 3 | **3**, 7 |

## 1. `isolcpus` ha effetto reale

**Test A** — 8 spinner senza `taskset`, su una macchina con 8 CPU logiche:

```
cpu0: 1   cpu1: 4   cpu4: 1   cpu5: 2      <- 8 thread ammassati su 4 CPU
cpu2: 0   cpu3: 0   cpu6: 0   cpu7: 0      <- mai toccate
```

Lo scheduler ha preferito sovraccaricare 2× quattro CPU piuttosto che usare le quattro
libere: è esattamente ciò che `isolcpus=domain` chiede (le CPU escono dai domini di
load balancing).

**Test B/C** — `taskset -c 2` e `taskset -c 3` funzionano regolarmente (`psr` = 2 e 3).
`isolcpus` non *vieta* quelle CPU, le rende solo non-elette d'ufficio: chi le vuole deve
chiederle esplicitamente, ed è esattamente ciò che fa rt-app con `"cpus": [2]`.

## 2. `nohz_full` ha effetto reale

**Test D** — interrupt del timer locale (riga `LOC` di `/proc/interrupts`) durante 5 s di
carico pinnato:

| CPU | tick in 5 s | Hz |
|---|---|---|
| cpu0 | 4283 | 856 |
| cpu1 | 5000 | 1000 |
| **cpu2** | **5** | **1** |
| **cpu3** | **5** | **1** |
| **cpu6** | **5** | **1** |

`CONFIG_HZ=1000` → 1000 Hz sulle housekeeping, **1 Hz** sulle isolate. Fattore 1000.
Totali dall'avvio (≈5 min): cpu0 371623, cpu1 166489 · cpu2 295, cpu3 296, cpu6 289, cpu7 279.

## 3. Cosa aggiunge `isolate_cpus.sh` (cset shield)

Contrariamente a quanto temevo, `cset` **funziona** su questo sistema pur essendo
`/sys/fs/cgroup` montato come cgroup v2 puro: `cset` si monta da solo una gerarchia
cgroup v1 privata.

```
none on /cpusets type cgroup (rw,relatime,cpuset,noprefix,release_agent=...)
```

Output di `cset shield --cpu=2,3 --kthread=on`:

```
cset: moving 489 tasks from root into system cpuset...
cset: kthread shield activated, moving 15 tasks into system cpuset...
cset: **> 13 tasks are not movable, impossible to move
cset: "system" cpuset of CPUSPEC(0-1,4-7) with 491 tasks running
cset: "user"   cpuset of CPUSPEC(2-3)     with 0 tasks running
```

Verifiche fatte:

- **Confinamento reale**: `cset shield --exec -- bash -c 'taskset -cp $$'` →
  `affinity: 2,3`, `psr: 2`. Lo shield funziona.
- **I 13 "not movable"** sono kthread per-CPU legati a cpu2/cpu3 (`cpuhp/2`, `irq_work/2`, …):
  non sono spostabili per costruzione, e non sono un problema perché si svegliano solo
  per eventi che riguardano quella CPU.
- **I 189 task rimasti nel cpuset root** sono **tutti** kthread (verificato: nessuno ha
  `/proc/PID/exe`), e la maggioranza ha già affinity `0,1,4,5` perché il kernel onora
  `isolcpus` per i kthread non vincolati.

**Conclusione**: con `isolcpus` già sulla cmdline, `cset shield` è in gran parte
ridondante per *tenere fuori* i processi. Il valore che aggiunge è un altro: dà
all'esperimento un cpuset esplicito (`cset shield --exec`), sposta i kthread spostabili,
e serve come rete di sicurezza sulle macchine dove non si può toccare GRUB.

**`reset_isolation.sh`** funziona (`cset shield --reset`, 490 task riportati in root,
set `/user` e `/system` cancellati). Due asimmetrie da sapere: lascia `/cpusets` montato
(innocuo) e **non ripristina le affinity degli IRQ** che `isolate_cpus.sh` ha cambiato.

## 4. Due bug trovati in `isolate_cpus.sh` (corretti)

### 4.1 `nproc` dentro lo shield

```bash
ALL_CPUS=$(nproc)
NON_ISO=$(seq -s',' 0 $((ALL_CPUS-1)) | ... )
```

Questa riga gira **dopo** `cset shield`, che ha già spostato la shell dello script nel
cpuset `system`. Quindi `nproc` non ritorna 8 ma la dimensione della maschera di affinity:

```
nproc normale                  : 8
nproc con affinity 0,1,4,5,6,7 : 6      <- quello che vede lo script
seq 0..5 meno {2,3}            = 0,1,4,5
```

Lo script enumera **indici** `0..nproc-1`, non gli **id** reali delle CPU non isolate
(`0,1,4,5,6,7`). Qui il bug si annullava da solo, ma è fragile: cambia il set isolato e
produce id sbagliati. Corretto leggendo `/sys/devices/system/cpu/present`, che non
dipende dall'affinity.

### 4.2 Gli IRQ finivano sui fratelli SMT

Una volta corretto il punto 4.1, lo script con `ISO_CPUS=2,3` chiedeva onestamente
`0,1,4,5,6,7` — e il kernel **accettava**, portando gli IRQ su cpu6 e cpu7, cioè sui
fratelli SMT delle CPU real-time:

```
[isolate] IRQ affinity requested: 0,1,4,5,6,7 | actually set: 0-1,4-7
```

Un interrupt preso su cpu6 ruba il core fisico a cpu2 esattamente come se fosse preso su
cpu2. Corretto escludendo dagli IRQ l'unione fra CPU isolate e loro fratelli SMT.

Aggiunti anche: un **WARNING** quando si isola una CPU senza il suo fratello, e la stampa
di *quello che il kernel ha davvero accettato* (con `isolcpus=managed_irq` alcune scritture
vengono silenziosamente troncate, e lo script le ingoiava con `2>/dev/null || true`).

Dopo la correzione:

```
$ isolate_cpus.sh 2,3
[isolate] WARNING: cpu6 is the SMT sibling of isolated cpu2 but is NOT isolated.
[isolate] WARNING: cpu7 is the SMT sibling of isolated cpu3 but is NOT isolated.
[isolate] IRQ affinity requested: 0,1,4,5 | actually set: 0-1,4-5

$ isolate_cpus.sh 2,3,6,7
[isolate] IRQ affinity requested: 0,1,4,5 | actually set: 0-1,4-5
   shield: "user" cpuset of CPUSPEC(2-3,6-7)
```

## 5. Il finding principale: l'SMT cambia il *lavoro* di rt-app, non solo la latenza

Micro-benchmark `evidence/jitter.c` (2000 ripetizioni di una quantità fissa di lavoro,
proxy di WCET: conta il massimo, non la media).

### 5.1 L'isolamento protegge la coda

Con 8 processi di disturbo senza affinity (finiscono tutti su 0,1,4,5):

| CPU | min | mediana | p99 | **MAX** | max/med |
|---|---|---|---|---|---|
| cpu0 (housekeeping) | 1362 | 1587 | 10269 | **20571 µs** | **12,96×** |
| cpu0 (ripetizione)  | 1308 | 1589 | 8590  | **11864 µs** | 7,47× |
| cpu0 (ripetizione)  | 1066 | 1586 | 7624  | **12690 µs** | 8,00× |
| **cpu2 (isolata)**  | 2106 | 2171,8 | 2205 | **2222 µs** | **1,02×** |
| **cpu2 (ripetizione)** | 2105 | 2171,8 | 2202 | 2231 µs | 1,03× |
| **cpu2 (ripetizione)** | 2105 | 2171,9 | 2202 | 2215 µs | 1,02× |

La CPU isolata ripete `2171,8 µs` di mediana **a macchina scarica e sotto carico pieno**,
con 0,1 µs di differenza fra run. Su cpu0 il massimo arriva a 13 volte la mediana.

### 5.2 La scoperta inattesa: il fratello SMT rende la CPU più *veloce*

| condizione | mediana su cpu2 |
|---|---|
| fratello cpu6 **vuoto** | 2171,9 µs |
| fratello cpu6 **occupato** | 1554,5 µs (**−28%**) |

Controintuitivo: la contesa SMT dovrebbe rallentare. Ho escluso la frequenza misurando
APERF/MPERF (`evidence/freqprobe.py`) nelle due condizioni:

```
A. cpu6 vuoto     -> cpu2 = 1799,9 MHz
B. cpu6 occupato  -> cpu2 = 1800,0 MHz
C. tutte cariche  -> cpu2 = 1800,1 MHz
```

Frequenza identica. Ho quindi confrontato due kernel di calcolo diversi:

| loop | cpu6 vuoto | cpu6 occupato | differenza |
|---|---|---|---|
| interi (`r*1103515245+12345`) | 167,1 µs | 167,6 µs | **+0,3%** |
| `ldexp` annidati (= `waste_cpu_cycles` di rt-app) | 2038,3 µs | 1310,7 µs | **−36%** |

**L'effetto è specifico della FPU** (compatibile con il power-gating delle unità
floating-point: il fratello occupato tiene il core "sveglio"). Non è un artefatto del mio
benchmark: `evidence/jitter_rtapp.c` è la copia fedele del corpo di `waste_cpu_cycles()`.

### 5.3 Impatto misurato su rt-app vero

`HI_task` SCHED_FIFO 90 su cpu2, `"calibration": 139`, `"run": 2000` µs:

| condizione | run misurato | scarto dal configurato |
|---|---|---|
| **cpu6 vuoto** (setup attuale) | **1982,0 µs** (max 2029) | **−0,9%** |
| cpu6 occupato | 1302,3 µs (max 1366) | **−35%** |

Log grezzi in `evidence/A_sibling_idle.log` e `evidence/B_sibling_busy.log`.

**Conseguenza per il progetto**: l'unità di lavoro di rt-app non è costante, dipende da
cosa fa il fratello SMT. Se avessimo isolato solo `2,3` lasciando 6 e 7 al sistema
operativo, ogni fase `run` avrebbe eseguito fra il 65% e il 100% del lavoro richiesto a
seconda di cosa il kernel piazzava su cpu6 in quel momento — un errore del 35% invisibile
nei log, che avrebbe reso incomparabili le celle del DoE.

Con l'isolamento a `2,3,6,7` il valore `CALIB_NS=139` risulta **corretto**
(1982 µs contro 2000 configurati) e **non va rimisurato**.

## 6. Procedura operativa che ne esce

```
# una volta sola (già fatto): riga GRUB + reboot
isolcpus=domain,managed_irq,2,3,6,7 nohz_full=2,3,6,7 irqaffinity=0,1,4,5

# a ogni riavvio, prima di misurare
pkexec /usr/bin/python3 <path>/scripts/utils_freq/cpu_freq.py pin

# opzionale, prima di una campagna (rete di sicurezza sopra isolcpus)
sudo scripts/utils_isolation/isolate_cpus.sh 2,3,6,7     # <- NON 2,3
sudo cset shield --exec -- <comando>
sudo scripts/utils_isolation/reset_isolation.sh
```

## 7. Cosa resta aperto

- `reset_isolation.sh` non ripristina le affinity IRQ. Innocuo oggi perché lo script
  scrive lo stesso valore che `irqaffinity=` ha già impostato al boot, ma è un'asimmetria.
- `run_doe.sh` non invoca `isolate_cpus.sh`: l'isolamento resta un passo manuale.
  Da decidere al Task 4 se cablarlo.
- L'effetto FPU/SMT del §5.2 andrebbe citato nella relazione come limite metodologico
  di rt-app: `waste_cpu_cycles()` non è un'unità di lavoro invariante.
