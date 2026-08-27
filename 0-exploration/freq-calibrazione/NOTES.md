# Frequenza fissa e calibrazione deterministica

Prerequisito del DoE, nato dal finding del task 0.1 (`run` misurato ~4150 µs contro 2000
configurati) e dallo span `calibration` da 10,3 s del task 0.3.

## 1. Il kernel RT non ha alcun controllo di frequenza

```
$ grep -E 'CPU_FREQ|CPU_IDLE' /boot/config-6.12.79-rt17
# CONFIG_CPU_FREQ is not set
# CONFIG_CPU_IDLE is not set
```

`/sys/devices/system/cpu/cpu*/cpufreq` **non esiste**: niente governor, `cpupower` inutile.
La frequenza è lasciata all'hardware. Unico canale rimasto: gli MSR
(`CONFIG_X86_MSR=m`, modulo `msr` già caricato, `/dev/cpu/N/msr`).

Stato di partenza letto dagli MSR (i7-8565U, Whiskey Lake):

```
PLATFORM_INFO=0x0004043df1011400   MISC_ENABLE=0x0000000000850089   PM_ENABLE=0x0
turbo ratio limit (1c..4c) : [41, 41, 45, 46]     -> fino a 4,6 GHz
HWP (Speed Shift) enabled  : no                   -> interfaccia legacy IA32_PERF_CTL
EIST (SpeedStep) enabled   : yes                  -> PERF_CTL viene onorato
turbo disabled             : no
```

Frequenza efficace misurata **sotto carico** con APERF/MPERF: 2587–2652 MHz, cioè turbo
attivo e instabile.

## 2. Pinning via MSR — `scripts/utils_freq/cpu_freq.py`

`info` / `pin` / `reset`. Poiché HWP è disattivato, `pin` scrive `IA32_PERF_CTL`
(`0x199`, bit 15:8 = ratio) su ogni CPU e alza il bit 38 di `IA32_MISC_ENABLE`
(turbo disable). Backup in `/run/rtsia-freq-backup.json`.

Serve root; `sudo` non funziona senza TTY in questa sessione, si usa `pkexec`:

```
pkexec /usr/bin/python3 scripts/utils_freq/cpu_freq.py pin
pkexec /usr/bin/python3 scripts/utils_freq/cpu_freq.py reset
```

Risultato:

| | prima | dopo |
|---|---|---|
| turbo | attivo | disattivato |
| PERF_CTL ratio | 18 | 20 |
| freq. sotto carico | 2587–2652 MHz | 1794–1805 MHz |
| spread tra le 8 CPU | ~2,5% | **0,3%** |

Nota sulla decodifica: `PLATFORM_INFO[15:8]` legge 20, ma il core sotto carico si
assesta a ~1800 MHz, cioè ratio 18 (il valore di targa dell'8565U). Il ratio richiesto
(20) viene clampato dall'hardware al massimo non-turbo reale. Il numero assoluto stampato
da `info` può quindi essere sovrastimato di ~10%; la **stabilità**, che è ciò che serve,
è comunque verificata.

## 3. Frequenza fissa NON basta: la calibrazione resta lenta e rumorosa

Con la frequenza inchiodata, `pLoad` continuava a oscillare (100–136 ns, una volta 41) e
la calibrazione a costare 5–22 s. Due cause distinte, nessuna delle due è il DVFS:

**(a) Interferenza.** Firefox occupava ~90% di un core (`load average` 3,5). La
calibrazione gira in `main()` come normale `SCHED_OTHER`, quindi viene preemptata.
Nemmeno `chrt -f 90` risolve del tutto, perché il sibling SMT (cpu2 ↔ cpu6) ruba comunque
le unità di esecuzione del core fisico.

**(b) L'algoritmo, per costruzione.** `calibrate_cpu_cycles_1()` (`rt-app.cpp:451`):

```c
avg_per_loop = (avg_per_loop + nsec_per_loop) >> 1;      /* parte da 0 */
if ((abs(nsec_per_loop - avg_per_loop) * 50) < avg_per_loop) return avg_per_loop;
```

La media mobile parte da 0 e si avvicina al valore vero come `n·(1−2^−k)`. La condizione
di uscita richiede `50·2^−k < 1 − 2^−k`, cioè `2^k > 51`, quindi **k ≥ 6 iterazioni** —
e ogni iterazione è preceduta da `clock_nanosleep` di **1 secondo pieno**. Il pavimento è
quindi ~6 s su una macchina perfettamente quieta; poi c'è il metodo 2, e
`calibrate_cpu_cycles()` prende il minimo dei due.

Misurato: 13,40 s di wall time per un workload di 5 s.

## 4. La soluzione: saltare la calibrazione

`rt-app_parse_config.cpp:1238` — se `"calibration"` è un **intero** invece di `"CPU0"`,
rt-app lo usa come `ns_per_loop` e non calibra affatto.

Il valore giusto non si prende dalla calibrazione di rt-app (è proprio quella che non ci
fidiamo), ma si ricava a ciclo chiuso da ciò che rt-app esegue davvero.
`rt-app.cpp:580`:

```c
load_count = (exec * 1000) / p_load;
```

quindi con un `p_load` noto e il `run` misurato nel log vale
`p_load_vero = p_load_usato · run_misurato / run_configurato`.
È ciò che fa `scripts/utils_freq/tune_calib.sh`:

```
step 1: p_load=100 -> median run = 2772 us   (configured 2000)
        => true cost per loop = 100 * 2772 / 2000 = 139 ns
step 2: p_load=139 -> median run = 1991 us   (error -0.5%)
```

Identico sotto `SCHED_OTHER` e sotto `chrt -f 90` (139 ns, 1991 µs in entrambi i casi).

## 5. Verifica finale

5 run con `"calibration": 139`, frequenza fissata:

| run | run mediano [µs] | wall [s] |
|---|---|---|
| 1 | 1991 | 5.01 |
| 2 | 1991 | 5.01 |
| 3 | 1991 | 5.01 |
| 4 | 1990 | 5.01 |
| 5 | 1990 | 5.01 |

Spread sul `run` misurato: **0,05%** (era il 35% sul `pLoad` calibrato).
Wall time: **5,01 s** contro 13,40 s, cioè zero tempo morto.
Confronto col punto di partenza del task 0.1: `run` 1990 µs contro 2000 configurati
(−0,5%), dove prima si misuravano ~4150 µs.

## Procedura da seguire prima di ogni sessione di DoE

```bash
pkexec /usr/bin/python3 scripts/utils_freq/cpu_freq.py pin      # frequenza fissa
pkexec /usr/bin/python3 scripts/utils_freq/cpu_freq.py info     # verifica
# ... eseguire i blocchi del DoE, con --calib 139 in gen_config.py ...
pkexec /usr/bin/python3 scripts/utils_freq/cpu_freq.py reset    # a fine sessione
```

Il valore 139 ns vale **per questa macchina con la frequenza fissata a ~1800 MHz**. Se si
cambia il ratio, o si esegue su un'altra macchina, va rimisurato con `tune_calib.sh`.

## Cosa resta aperto (task 0.4)

- L'SMT è ancora attivo: cpu2 condivide il core fisico con cpu6. Per il DoE conviene o
  spegnere i sibling, o assegnare HI e LO a core fisici distinti.
- Il `cmdline` attuale ha `nohz_full=1,4-6` ma **nessun `isolcpus`**, e quelle CPU non
  coincidono con le 2,3 che `run_doe.sh` vuole isolare: da riconciliare.
