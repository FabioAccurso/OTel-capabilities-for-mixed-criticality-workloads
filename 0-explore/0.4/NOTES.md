# Task 0.4 — isolamento CPU: cosa fa `cset shield`, e funziona davvero?

## Cosa fa lo script (letto prima di eseguirlo)

`isolate_cpus.sh <cpu_list>` (default `2,3`) fa due cose:

1. `cset shield --cpu=2,3 --kthread=on` → crea due cpuset e ci sposta dentro i task:
   - `/user` = CPU 2,3 (lo *shield*, vuoto: ci si entra solo con `--exec`)
   - `/system` = CPU 0,1,4-7 (tutto il resto del sistema, ~825 task)
   `--kthread=on` estende lo spostamento anche ai kernel thread migrabili.
2. riscrive tutti i `/proc/irq/*/smp_affinity_list` con l'elenco delle CPU **non** isolate.

`reset_isolation.sh` faceva solo `cset shield --reset`.

## Sorpresa 1 — cgroup v2 non è un ostacolo

Il sistema monta **solo cgroup v2 unificato** (`/sys/fs/cgroup` è `cgroup2fs`,
`/sys/fs/cgroup/cpuset` non esiste), mentre `cset` 1.6 è uno strumento cgroup **v1**.
Previsione: fallimento. **Sbagliata**: `cset` monta per conto suo una gerarchia v1 in
`/cpusets` e funziona.

Il prezzo è però visibile: dopo lo shield il controller `cpuset` **sparisce** da
`/sys/fs/cgroup/cgroup.controllers` (il kernel lo rilega alla v1). Qualunque cosa usi
cpuset via cgroup v2 — `systemd AllowedCPUs=`, container — lo perde finché `/cpusets` resta
montato. `reset_isolation.sh` ora lo smonta e lo restituisce alla v2.

## Sorpresa 2 — tre bug nel calcolo delle CPU non isolate

Riga 26-27 dell'originale:

```bash
ALL_CPUS=$(nproc)
NON_ISO=$(seq -s',' 0 $((ALL_CPUS-1)) | tr ',' '\n' | grep -vFf <(echo "${ISO_CPUS}" | tr ',' '\n') | paste -sd, -)
```

Misurato dopo lo shield: **`NON_ISO = '0,1,4,5'`**, non `0,1,4,5,6,7`.

1. **`nproc` è affinity-aware.** A shield attivo la shell chiamante è già confinata nel
   cpuset `system`, quindi `nproc` torna **6** invece di 8 (`nproc --all` torna 8) e
   `seq 0 5` non arriva mai a 6,7. Gli IRQ finivano su 4 CPU invece di 6 — non rompe
   l'isolamento (2,3 restano escluse) ma concentra inutilmente il carico di interrupt.
2. **`grep -vFf` senza `-x` fa match di sottostringa.** Isolando la CPU `1` su una macchina
   con ≥10 CPU escluderebbe anche 10,11,…,19.
3. **La sintassi a intervallo rompe tutto in silenzio.** `cset` accetta `--cpu=2-3`, ma con
   `ISO_CPUS="2-3"` nessun pattern fa match e `NON_ISO` contiene **anche 2 e 3**: gli IRQ
   non vengono spostati per niente, senza alcun messaggio d'errore. È il caso pericoloso:
   il DoE girerebbe con un isolamento apparente.

Corretti tutti e tre (`nproc --all`, `grep -vxFf`, funzione `expand_cpus()` che normalizza
`0-2,5` → righe). Gli originali sono in `*.sh.orig`.

## Sorpresa 3 — `reset` non ripristinava gli IRQ

Dopo `reset_isolation.sh` le affinità IRQ restavano a `0-1,4-7`: modifica permanente fino
al reboot. Ora `isolate_cpus.sh` salva lo stato in `/var/tmp/rtapp-isolation/irq_affinity.bak`
(una sola volta, così un rilancio a shield attivo non sovrascrive il backup pulito) e
`reset_isolation.sh` lo rilegge. Verificato: `affinita' IRQ ripristinate: 28`.

## Cosa NON si riesce a isolare

Con lo shield attivo su 2,3 restano:

- **2 IRQ inamovibili**: `irq 54 → nvme0q3` su CPU 2 e `irq 55 → nvme0q4` su CPU 3. La
  scrittura fallisce con *Operazione non permessa*: sono IRQ **managed** (code per-CPU del
  driver NVMe), il kernel non ne consente la migrazione. In totale 11 scritture su 39
  vengono rifiutate. Si spostano solo con `isolcpus=` sulla cmdline al boot — che è
  esattamente ciò che il commento in testa allo script consiglia.
- **26 kernel thread per-CPU**, non migrabili per costruzione: `migration/2`, `ktimers/2`,
  `ksoftirqd/2`, `rcuc/2`, `irq_work/2`, `cpuhp/2`, `backlog_napi/2`, vari `kworker/2:*`
  (idem per la 3), più `irq/25-AMD-Vi` (handler threaded dell'IOMMU) su CPU 3.
  `cset` lo dice: `59 tasks are not movable, impossible to move`.

Quindi lo shield **non** è un isolamento totale. La domanda è se basta.

## Verifica sperimentale: sì, basta (per SCHED_OTHER a 10 ms)

3 ripetizioni per condizione, `"calibration": 29` fisso, frequenza fissata a P0 = 2300 MHz,
1 thread `SCHED_OTHER` `run 2000 us / sleep 8000 us` per 5 s (periodo nominale 10000 us,
500 loop teorici). "DENTRO" = `sudo cset shield --exec --`. Colonne in us,
`jitter` = `period max − period p50`. Dati completi in `results.txt`.

| scenario | loop | run medio | run max | period p50 | period p99 | period max | jitter |
|---|---|---|---|---|---|---|---|
| idle, FUORI | 479-483 | 2245-2324 | 3377-4495 | 10153-10171 | 11272-11916 | 11579-12589 | 1420-2418 |
| idle, DENTRO | **495** | **2012-2013** | 2057-2183 | 10081-10082 | 10115-10122 | 10133-10261 | **51-180** |
| rumore, FUORI | 342-362 | 3899-4230 | 11671-13347 | 13459-14567 | 20633-21225 | 21223-23977 | 7764-9892 |
| rumore, DENTRO | **495** | **2008-2011** | 2136-2188 | 10074-10074 | 10125-10208 | 10204-10260 | **130-186** |

("rumore" = 8 busy-loop lanciati dalla shell, che essendo nel cpuset `system` girano su
0-1,4-7 e non toccano le CPU isolate.)

Tre letture:

1. **L'isolamento funziona.** Dentro lo shield il jitter passa da 1420-2418 us a 51-180 us
   a macchina idle: **un fattore ~15**. I loop completati passano da 479-483 a 495 su 500
   teorici, e il `run` medio da +12/+16 % a **+0.6 %** rispetto ai 2000 us richiesti.
2. **Dentro lo shield il rumore è invisibile.** Le righe "idle, DENTRO" e "rumore, DENTRO"
   sono statisticamente identiche (jitter 51-180 vs 130-186 us), mentre fuori il carico
   distrugge la periodicità: periodo mediano 14085 us invece di 10000, un terzo dei loop
   persi, picchi a 24 ms. È la prova che il confine del cpuset regge.
3. **I kthread residui non si vedono a questo livello.** Nonostante i 26 kernel thread e i
   2 IRQ NVMe rimasti su 2,3, il periodo massimo dentro lo shield è 10260 us contro 10000
   nominali. Per `SCHED_OTHER` a 10 ms è rumore trascurabile. **Da riverificare ai Task 4-6
   con task HI in `SCHED_FIFO`**: lì i ~200 us di coda contano molto di più, e i kthread RT
   per-CPU (`ktimers/N`, `ksoftirqd/N`, `rcuc/N` girano a priorità FIFO) possono preemptare
   un task HI. Se succede, la contromisura è `isolcpus=2,3 nohz_full=2,3 rcu_nocbs=2,3`
   sulla cmdline GRUB + reboot.

## Uso operativo

```
sudo scripts/utils_isolation/isolate_cpus.sh 2,3      # oppure 2-3, ora equivalente
sudo cset shield --exec -- <comando>                  # lancia DENTRO lo shield
sudo scripts/utils_isolation/reset_isolation.sh       # ripristina anche gli IRQ
```

`cset shield` (senza argomenti) mostra lo stato; `cset set -l` elenca i cpuset.
Attenzione: `cset shield --status` **non esiste** (`error: no such option`).

Nota: i processi lanciati con `--exec` girano come **root**, quindi i log di rt-app
finiscono di proprietà di root. Da gestire in `run_doe.sh` (Task 4).
