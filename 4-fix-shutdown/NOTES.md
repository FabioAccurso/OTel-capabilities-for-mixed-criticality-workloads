# Due bug di memoria in rt-app (C++), trovati e corretti il 2026-08-28

Documento tecnico. La versione discorsiva e' in `SPIEGAZIONE.md`.

Il codice C++ di rt-app non e' del docente: e' una traduzione fatta da un gruppo
dell'anno scorso, girata come materiale utile ma **senza garanzia di correttezza**.
Questi due difetti sono da segnalare.

---

## 1. Come sono emersi

Il **blocco 2 del DoE** si e' interrotto al run 12 su 25 della prima cella
(`t2_p0_s2_r0.0_n4`, AlwaysOff, `n_lo=4`) il 2026-08-28 alle 11:05:51:

```
scripts/measurements/test.sh: riga 36: 3757 Errore di segmentazione
    sudo cset shield --exec -- "$BIN" "$DIR/config.json"
=== [driver] run_doe.sh exit=139 ===
```

`exit 139 = 128 + 11` -> **SIGSEGV**.

Il crash e' **in chiusura, non durante la misura**. Prove:

- `evidence/crash_block2_run12_stderr.log` arriva fino a `[2] Exiting.` e
  `[3] Exiting.`: il workload da 20 s era finito e i thread stavano terminando;
- i log `LO_noise` del run 12 sono rimasti **in chiaro** invece che gzippati, perche'
  `test.sh` si e' interrotto prima di arrivare al passo di compressione;
- `rtapp-HI_task-0.log` e' 245760 byte = 240 KiB esatti, un multiplo tondo di 4096:
  e' il buffer di stdio mai svuotato di un processo morto. I run sani sono 247752 byte.

I run 1-11 della cella sono integri e completi.

### 1.1 La caccia statistica e' fallita, ed e' un dato

Prima di leggere il codice ho provato a riprodurre il crash a forza bruta. Tre tentativi:

| condizioni | crash |
|---|---|
| 20 run, root, **fuori** dallo shield, durata 5 s | 0/20 (ma invalido, vedi sotto) |
| 20 run, root, **dentro** lo shield, config reale 20 s, binario col bug | **0/20** |
| 20 run, root, dentro lo shield, config reale 20 s, binario corretto | 0/20 |

Il primo tentativo era **invalido**: senza root `pthread_setschedparam` non puo'
assegnare `SCHED_FIFO` 90 e rt-app muore sul percorso di errore
(`pthread_setschedparam: Operation not permitted`). Quei fallimenti non c'entravano
con lo shutdown.

Gli altri due sono validi e dicono che **il crash e' raro**: sommando al DoE siamo a
**1 crash su 32 esecuzioni reali**. Con un tasso di 1/12 la probabilita' di vedere
zero crash in 20 run e' del 17%, quindi il risultato non contraddice l'osservazione,
ma **non basta a dimostrare che il fix serva**. Da qui il passaggio ad AddressSanitizer.

### 1.2 AddressSanitizer

Build con `CXXFLAGS="-g -O1 -fsanitize=address -fno-omit-frame-pointer"` e
`LDFLAGS="-fsanitize=address"`, config `n_lo=4` da 3 s.

Due accorgimenti necessari per farla girare:
- `"lock_pages": false` in `global` — ASan riserva la shadow memory e `mlockall()`
  la fa esplodere. Attenzione: il parser vuole un **booleano JSON**, non `0`
  (`[rt-app] <crit> Invalid type for key lock_pages`);
- tutti i task a `SCHED_OTHER`, cosi' gira senza root.

---

## 2. Bug A — heap-buffer-overflow in `set_thread_affinity()`

**Deterministico**, si manifesta a ogni esecuzione. Log completo in
`evidence/asan_bug_cpuset.log`.

```
ERROR: AddressSanitizer: heap-buffer-overflow
READ of size 128 at 0x502000008058 thread T6
    #3 set_thread_affinity  rt-app.cpp:1104
    #4 thread_body          rt-app.cpp:1609
0x502000008058 is located 0 bytes after 8-byte region [0x502000008050,0x502000008058)
allocated by thread T6 here:
    #1 set_thread_affinity  rt-app.cpp:1085
```

Codice incriminato (allocazione a 1083-1087, uso a 1104):

```c
cpu_count = CPU_COUNT(&cpuset);                             /* 4 */
data->def_cpu_data.cpusetsize = CPU_ALLOC_SIZE(cpu_count);  /* 8 byte */
data->def_cpu_data.cpuset     = CPU_ALLOC(cpu_count);       /* 8 byte */
...
if (!CPU_EQUAL(actual_cpu_data->cpuset, data->curr_cpu_data->cpuset))  /* legge 128 byte */
```

Due errori sovrapposti:

1. **`CPU_COUNT()` e' l'input sbagliato per dimensionare il set.** Restituisce il
   numero di CPU *accese* nella maschera, non l'id piu' alto che la maschera deve
   rappresentare. Con lo shield su 2,3,6,7 ritorna 4, cioe' `CPU_ALLOC(4)` dimensiona
   per gli id 0..3 mentre la maschera contiene 6 e 7. Su questa macchina non fa danno
   perche' `CPU_ALLOC_SIZE(4)` arrotonda a 8 byte = 64 bit, ma su una macchina con
   piu' di 64 CPU e maschera sparsa **troncherebbe la maschera**.
2. **Macro a dimensione fissa su un set allocato dinamicamente.** `CPU_EQUAL(a,b)`
   confronta incondizionatamente `sizeof(cpu_set_t)` = 128 byte. Su un blocco da 8
   byte sono **120 byte letti oltre la fine**. La variante corretta per i set
   dinamici e' `CPU_EQUAL_S(setsize, a, b)`.

Il resto del file usa gia' le forme `_S` (`rt-app.cpp:1006`,
`CPU_COUNT_S(cpu_data->cpusetsize, ...)`): la riga 1104 e' rimasta indietro. I cpuset
che arrivano dalla config sono invece allocati correttamente a `sizeof(cpu_set_t)`
(`rt-app_parse_config.cpp:765`).

### 2.1 Fix

Allineato il cpuset di default alla stessa convenzione della config: un `cpu_set_t`
intero. Cosi' tutti i cpuset del programma sono da 128 byte e `CPU_EQUAL` torna
legittima, senza inseguire le varianti `_S` in tutto il file.

### 2.2 Le misure gia' raccolte NON sono compromesse

Domanda legittima: se `CPU_EQUAL` confrontava byte spazzatura, poteva rispondere
"diverso" a ogni giro e far chiamare `pthread_setaffinity_np()` nel percorso critico,
falsando l'overhead misurato nel blocco 1.

Verificato con `strace -c -e trace=sched_setaffinity`, stessa config, 5 thread:

```
PRIMA_del_fix: sched_setaffinity = 5
DOPO_il_fix:   sched_setaffinity = 5
```

**Cinque chiamate in entrambi i casi, una per thread all'avvio.** Il motivo e' che
nel caso comune `actual_cpu_data` e `data->curr_cpu_data` sono lo **stesso puntatore**,
quindi `memcmp(p, p, 128)` risponde "uguale" comunque, pur leggendo fuori bounds.
La lettura era UB reale ma non ha cambiato il comportamento osservabile.

**Conseguenza: il blocco 1 (80 run, 29 min) resta valido e non va rifatto.**

---

## 3. Bug B — heap-use-after-free nel teardown degli span

Log completo in `evidence/asan_bug_span.log`.

```
ERROR: AddressSanitizer: heap-use-after-free
READ of size 8 at 0x50300000a878 thread T6
  #0 std::_Sp_counted_base<...>::_M_release()          shared_ptr_base.h:337
  #1 std::__shared_count<...>::~__shared_count()       shared_ptr_base.h:1071
  #3 std::shared_ptr<Span>::~shared_ptr()              shared_ptr.h:175
  #4 nostd::shared_ptr<trace::Span>::shared_ptr_wrapper::~shared_ptr_wrapper()
```

`_M_release()` e' la funzione che decrementa il reference count di uno `shared_ptr`:
sta leggendo un control block gia' liberato.

Lo stesso teardown e' scritto in **due punti**:

| punto | riga | lock |
|---|---|---|
| `__shutdown()` (terminazione forzata) | 894 | `fork_mutex` |
| `thread_body()` (uscita naturale) | 1766 | **nessuno** |

Entrambi facevano:

```cpp
if (data->span) {
    if (data->span->IsRecording()) data->span->End();
    data->span.~shared_ptr();   // distruttore esplicito
    data->span = nullptr;       // assegnazione a un oggetto la cui vita e' finita
}
```

Due difetti sovrapposti:

1. **`~shared_ptr()` esplicito seguito da `= nullptr` e' UB anche senza concorrenza.**
   Il distruttore termina la vita dell'oggetto; l'assegnazione successiva chiama
   `operator=` su uno `shared_ptr` distrutto, che rilascia il control block una
   **seconda volta**. Assegnare `nullptr` e' gia' il teardown completo: rilascia il
   riferimento e lascia l'oggetto valido e vuoto.
2. **Race fra i due percorsi.** `__shutdown()` distrugge lo span di ogni thread sotto
   `fork_mutex` e poi fa `pthread_cancel()`; `thread_body()` fa la stessa cosa sullo
   stesso oggetto senza prendere alcun lock (verificato: nessun mutex fra le righe
   1700 e 1790). Il commento dell'autore — *"Only end it if it hasn't been ended by
   `__shutdown` yet"* — mostra che il problema era stato intuito, ma `IsRecording()`
   e' una lettura, non una primitiva di sincronizzazione.

### 3.1 Fix

- rimosso il `~shared_ptr()` esplicito in **entrambi** i punti;
- `thread_body()` prende `fork_mutex` attorno al teardown, lo stesso che usa
  `__shutdown()`.

Nessun rischio di deadlock: `__shutdown()` rilascia `fork_mutex` alla riga 910,
**prima** del ciclo di `pthread_join()` alla 934, quindi un thread che prende il
mutex mentre esce non blocca chi lo sta aspettando. E fra `lock` e `unlock` non ci
sono punti di cancellazione, quindi un `pthread_cancel()` non puo' lasciare il mutex
bloccato.

### 3.2 Verifica

Esperimento controllato: stesso binario, stesse macro
(`TRACE_LEVEL=2, PROCESSOR=0, SAMPLER=0 (AlwaysOn), EXPORTER=1`), fix del cpuset
presente in entrambe le varianti per isolare l'effetto di questo solo bug.

| variante | run con errore ASan | exit |
|---|---|---|
| con il bug degli span | **5 / 5** heap-use-after-free | 1 |
| con il fix | **0 / 5**, pulito | 0 |

I run corretti esportano 17 span, coerente con la formula del Task 3:
`2 (main + calibration) + 5 thread x 3 (thread + thread_loop + phase)`.

Nota: il bug si manifesta **anche con AlwaysOff**. Con quel sampler `IsRecording()`
e' falso e `End()` viene saltato, ma il distruttore esplicito e l'assegnazione
vengono eseguiti lo stesso. Ed e' infatti nella cella di controllo AlwaysOff che il
blocco 2 e' crashato.

---

## 4. Perche' il blocco 1 non era mai crashato

Il blocco 1 girava con `n_lo=0`: **un thread solo**. Il blocco 2 ne ha **cinque**.
La finestra di race si apre una volta per thread, quindi le occasioni per run passano
da 1 a 5. In 60 run strumentati del blocco 1 non si era mai manifestata.

Questo ha una ricaduta sul **blocco 3**, che non e' ancora stato lanciato: arriva a
`n_lo=8`, cioe' **9 thread**. Senza questi fix sarebbe stato molto probabilmente
ineseguibile fino in fondo.

---

## 5. Cosa e' stato toccato

Un solo file, `rt-app/src/rt-app.cpp`: **37 righe aggiunte, 13 rimosse**
(patch completa in `evidence/fix.patch`). Nessun cambiamento di interfaccia, nessuna
macro nuova, nessun file rimosso.

Binari di confronto, compilati con macro identiche
(`t2 p0 s2 r0.0 e1`):

```
evidence/rtapp_PRIMA_del_fix   e64c2aa320d680704a602ed4f7fa1b1e
evidence/rtapp_DOPO_il_fix     f84fc8257ace75dbd646bf926b8c5895
```

## 6. Ricadute operative

- **Cache dei binari da svuotare**: tutto cio' che sta in `bin/` e' compilato dal
  sorgente difettoso e va ricostruito.
- **Dati parziali del blocco 2 da buttare**: gli 11 run raccolti prima del crash
  vengono dal binario col bug. Vanno rimossi insieme alle loro righe in
  `data_table.csv` e `index.txt`.
- **Blocco 1: si tiene.** Vedi §2.2 — nessun cambiamento di comportamento osservabile,
  verificato con strace.
- **Materiale per il Task 6**: l'instrumentazione OTel di questo rt-app non costa solo
  jitter, ha anche due difetti di memoria, uno dei quali (il B) sta esattamente nel
  codice aggiunto per gestire gli span e si aggrava col numero di task monitorati.
