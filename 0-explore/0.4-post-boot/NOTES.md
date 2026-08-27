# Task 0.4 — rimisurazione DOPO i parametri di boot (2026-08-27)

Rifacimento della batteria del task 0.4 con la cmdline GRUB modificata, per misurare
quanto valgono davvero i parametri di boot. **Non e' un task nuovo**: il task 0.4 resta
`[x]`, questa cartella affianca `0-explore/0.4/` come secondo punto di misura.

## Stato della piattaforma

```
BOOT_IMAGE=/boot/vmlinuz-6.12.79-rt17 ... quiet splash
    isolcpus=managed_irq,domain,2,3  nohz_full=2,3  rcu_nocbs=2,3
```

| verifica | atteso | ottenuto |
|---|---|---|
| `/sys/devices/system/cpu/nohz_full` | 2-3 | **2-3** |
| `/sys/devices/system/cpu/isolated` | 2-3 | **2-3** |
| `/sys/devices/virtual/workqueue/cpumask` | f3 | **f3** (= 0,1,4,5,6,7) |
| `/proc/irq/54/smp_affinity_list` | != 2 | **2** — vedi sotto |

Frequenza: `pin_cpu_freq.sh fix 0` applicato, `CpbDis=1`, tutti i core P0.

## Correzione: `managed_irq` non sposta l'IRQ, gli toglie il lavoro

La checklist in `CLAUDE.md` si aspettava che `/proc/irq/54/smp_affinity_list` smettesse di
valere 2. **L'attesa era sbagliata.** Gli IRQ managed restano affini alla loro CPU:

```
irq 54 (nvme0q3)  smp_affinity_list: 2   effective: 2   ->  0 interrupt dal boot
irq 55 (nvme0q4)  smp_affinity_list: 3   effective: 3   ->  0 interrupt dal boot
```

`isolcpus=managed_irq` agisce sul lato *submit*: blk-mq evita di usare da CPU housekeeping
le code hardware il cui IRQ punta a una CPU isolata, e nessun processo sulle CPU isolate fa
I/O. La coda quindi esiste ma non spara mai. **La verifica giusta e' il contatore in
`/proc/interrupts`, non l'affinity.**

### Quello che i parametri di boot NON coprono

`managed_irq` vale solo per gli IRQ managed. Gli IRQ di device ordinari continuano a
finire su 2,3 finche' `isolate_cpus.sh` non ne riscrive `smp_affinity` a runtime:

| IRQ | CPU2 | CPU3 |
|---|---|---|
| 39 `xhci_hcd` | 10394 | 0 |
| 67 `amdgpu` | 0 | 141811 |
| 1 `i8042` | 0 | 1422 |
| 66 `snd_hda_intel` | 578 | 0 |

(conteggi cumulativi a 13 min di uptime, prima dello shield)

**Conclusione: i parametri di boot non sostituiscono `isolate_cpus.sh`, lo completano.**

## `nohz_full`: quanto serve davvero su questo workload

`CLAUDE.md` diceva di misurarlo e non assumerlo, perche' il thread di rt-app dorme 8 ms su
10 e `nohz_full` ferma il tick solo con **un solo task runnable**. Misurato: delta di `LOC`
(local timer interrupts) su tutte le CPU durante un run di 5 s dentro lo shield.

```
CPU0   5774
CPU1    690
CPU2    106   <- isolata, ci gira rt-app
CPU3      2   <- isolata, vuota
CPU4   1017
CPU5    884
CPU6   1216
CPU7    623

tick pieno a CONFIG_HZ=1000 su 5 s = 5000
```

**Serve, e molto**: 106 tick invece di 5000, cioe' il tick periodico e' spento ~98 % del
tempo anche con il task che si sveglia 497 volte. Le CPU housekeeping stanno a 623-1216
(gia' sotto 5000 grazie a `NO_HZ_IDLE`), CPU0 a 5774. Nello stesso run `CAL` (function
call IPI) = 1 e `IWI` = 6 su CPU2: le CPU isolate sono praticamente mute.

## Risultati: 12 run, 3 ripetizioni x 4 condizioni

Stessa metodologia del task 0.4: `bin/rt-app_T0` (nessun tracing), `cfg.json` invariato
(`"calibration": 29`, 1 thread `SCHED_OTHER` run 2000 / sleep 8000, 5 s, 500 loop
teorici), `jitter = period max - period p50`. **Ordine alternato out/in** dentro ogni
ripetizione, per spalmare la deriva termica sui due bracci. Dati grezzi in `results.txt`,
log in `logs/`, MHz e Tctl per ogni run in `metadata.txt`.

| scenario | loop | run_med | run_max | per_p50 | per_p99 | per_max | jitter |
|---|---|---|---|---|---|---|---|
| idle, FUORI | 492-493 | 2017-2018 | 3270-3339 | 10090-10092 | 10876-10951 | 11362-11427 | 1271-1337 |
| idle, DENTRO | **497** | 1984-1985 | 2016-2020 | 10052-10054 | 10086-10089 | 10099-10117 | **47-63** |
| rumore, FUORI | 397-406 | 2662-2669 | 8639-12010 | 11997 | 15997-16980 | 20103-24045 | 8106-12048 |
| rumore, DENTRO | **497** | 1983 | 2025-2040 | 10051 | 10075-10077 | 10085-10116 | **34-65** |

### Confronto con la baseline pre-boot (solo il braccio DENTRO)

**Solo le righe "DENTRO" sono confrontabili.** Le `NOTES.md` del task 0.4 non registrano
cosa girasse sul desktop durante la campagna precedente, e i bracci "FUORI" ne dipendono
completamente: il miglioramento apparente di `idle, FUORI` (run_med 2245-2324 -> 2017-2018)
e' con ogni probabilita' solo una macchina piu' scarica oggi, non merito dei parametri di
boot. Dentro lo shield il confronto regge, ed e' proprio la riga "rumore, DENTRO" ~
"idle, DENTRO" (in entrambe le campagne) a dimostrarlo.

| metrica, idle DENTRO | pre-boot | post-boot | |
|---|---|---|---|
| loop completati /500 | 495 | **497** | +2, identico in tutte e 6 le ripetizioni |
| run_med (us) | 2012-2013 | 1984-1985 | -28 us |
| run_max (us) | 2057-2183 | **2016-2020** | code sparite, insiemi disgiunti |
| period p50 (us) | 10081-10082 | 10052-10054 | -29 us |
| period p99 (us) | 10115-10122 | **10086-10089** | -30 us, insiemi disgiunti |
| period max (us) | 10133-10261 | **10099-10117** | insiemi disgiunti |
| jitter (us) | 51-180 | 47-63 | mediana 166 -> 49 |

Tre letture:

1. **Il guadagno c'e' ma e' piccolo in valore assoluto: ~30 us su p99 e ~150 us sul
   `run` peggiore.** Con n=3 il jitter da solo non separa (i due insiemi {51,166,180} e
   {47,49,63} si sovrappongono in un punto), ma `run_max`, `period p99` e `period max`
   danno insiemi **completamente disgiunti**, e i loop completati sono 495 in tutte e 6 le
   ripetizioni pre-boot contro 497 in tutte e 6 le post-boot. La direzione e' univoca.
2. **Il jitter e' molto piu' riproducibile.** Pre-boot 51-180 us significa che una
   ripetizione su tre pescava una coda 3.5x le altre; post-boot il range e' 47-63. Per una
   campagna con 10-30 ripetizioni per punto (Task 4) questo conta piu' del guadagno medio:
   riduce la varianza dello stimatore, quindi servono meno ripetizioni per la stessa
   potenza statistica.
3. **`run_med` scende sotto i 2000 us nominali** (1984 invece di 2012). Non e' un errore:
   `"calibration": 29` e' una costante fissa, e i 2012 us pre-boot contenevano ~28 us di
   interferenza residua che ora non c'e' piu'. Il costo per iterazione "pulito" e' quindi
   ~28.8 ns, non 29. Da riconsiderare nel Task 2: o si accetta un -0.8 % sistematico sul
   lavoro nominale, o si ritara la costante.

### Deriva termica e frequenza

Nessun throttling STAPM su questa campagna: MHz medio 2275-2296 in tutti e 12 i run,
inchiodato a **2296 MHz** durante tutta la fase con rumore, con Tctl salito da 56.5 a
60.6 C. Idle: Tctl 51.4 -> 51.8 C, deriva trascurabile.

**Attenzione**: la campagna dura ~3 minuti. Il Task 4, con 10-30 ripetizioni per punto,
durera' molto di piu' e puo' benissimo trovare il limite dei 15 W. `run_doe.sh` deve
continuare a registrare MHz e Tctl per run, e se P0 non regge la contromisura resta
`pin_cpu_freq.sh fix 1` (1700 MHz stabili).

## Cosa resta aperto per i Task 4-6

Tutto misurato qui e' con **`SCHED_OTHER` a 10 ms**. I kthread RT per-CPU
(`ktimers/N`, `ksoftirqd/N`, `rcuc/N`) girano a priorita' FIFO e a questo livello non si
vedono, ma con task HI in `SCHED_FIFO` i ~100 us di coda residua pesano molto di piu'.
Da riverificare li'.

## Struttura della cartella

```
results.txt    tabella riassuntiva delle 12 misure (input dell'analisi)
logs/          i 12 log di timing di rt-app, uno per run (<scenario>_<rip>.log)
runs/          una cartella per run con stdout/stderr; il log di timing NON e'
               duplicato qui, sta in logs/
metadata.txt   per ogni run: timestamp, Tctl pre/post, MHz per core pre/post, perf
```

rt-app scrive sempre `<log_basename>-<task>-<idx>.log` nella cwd e lo **sovrascrive** senza
avvisare: per questo ogni ripetizione gira in una cartella propria. Vale anche per
`run_doe.sh` (Task 4).

## Trappola operativa trovata durante questa campagna

`cset` **monta la gerarchia cgroup v1 in `/cpusets` a ogni invocazione**, anche per un
semplice `cset shield` di sola lettura. Quindi verificare lo stato *dopo*
`reset_isolation.sh` rimonta `/cpusets` e risottrae il controller `cpuset` a cgroup v2,
facendo sembrare che il reset non abbia funzionato. L'`umount` dello script e' corretto:
va solo eseguito per ultimo.

Controllo giusto a fine sessione, senza invocare `cset`:

```bash
mountpoint -q /cpusets && echo "ancora montato" || echo pulito
cat /sys/fs/cgroup/cgroup.controllers   # deve tornare a contenere 'cpuset'
```

Nota: i "non ripristinabili: 11" del reset sono gli IRQ managed NVMe che rifiutano la
scrittura con EPERM — atteso, non un errore.
