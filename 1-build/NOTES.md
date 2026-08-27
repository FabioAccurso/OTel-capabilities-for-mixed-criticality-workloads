# Task 1 — build completa, da albero pulito

Data: 2026-08-27. Ubuntu 24.04, gcc/g++ 13.3.0, cmake 3.28.3, autoconf 2.71.

## 1. Prerequisiti apt: tutti presenti

| pacchetto | versione |
|---|---|
| autoconf | 2.71-3 |
| autoconf-archive | 20220903-3 |
| automake | 1:1.16.5-1.3ubuntu1 |
| libtool | 2.4.7-7build1 |
| libcurl4-openssl-dev | 8.5.0-2ubuntu10.13 |
| libnuma-dev | 2.0.18-1ubuntu0.24.04.1 |
| **libjson-c-dev** | 0.17-1build1 |
| cpuset | 1.6.2-1 |
| cmake | 3.28.3-1build7 |

`configure` verifica esplicitamente le tre librerie e le trova tutte:

```
checking for pthread_create in -lpthread... yes
checking for numa_available in -lnuma... yes
checking for json_object_from_file in -ljson-c... yes
```

## 2. `otel-installdir/` era già costruito

12 MB, 16 archivi statici. Le **sette** librerie che `src/Makefile.am` richiede al linker
esistono tutte:

```
libopentelemetry_exporter_zipkin_trace.a          408K
libopentelemetry_exporter_ostream_span.a           88K
libopentelemetry_exporter_ostream_span_builder.a  8,0K
libopentelemetry_http_client_curl.a               388K
libopentelemetry_trace.a                          1,8M
libopentelemetry_resources.a                      156K
libopentelemetry_common.a                         112K
```

Non è stato necessario ricostruirlo (era stato fatto nel task 0.2, opentelemetry-cpp
v1.28.0 con `WITH_ZIPKIN=ON`). `otel-src/` e `otel-installdir/` sono in `.gitignore`
perché rigenerabili e pesanti (~240 MB il sorgente).

`src/Makefile.am` li trova tramite percorso relativo:

```make
AM_CPPFLAGS = -I$(srcdir)/../libdl/ -I$(top_srcdir)/../otel-installdir/include/
AM_CXXFLAGS = -std=c++17
rt_app_LDADD = ... -L$(top_srcdir)/../otel-installdir/lib ...
```

Siccome `$(top_srcdir)` è `rt-app/`, `../otel-installdir` è la cartella nella radice del
progetto: la struttura di cartelle attuale è un requisito, non una convenienza.

## 3. La build

Partendo da albero pulito (`make distclean`), la catena canonica funziona **senza nessun
override**:

```
./autogen.sh && ./configure && make
```

Questo chiude il workaround del task 0.1, dove serviva
`make rt_app_LDADD="../libdl/libdl.a -lpthread"` perché le librerie OTel non erano ancora
state costruite.

Tre osservazioni.

**`autogen.sh` stampa cinque `fatal: Nessun nome trovato`** ma esce 0. È
`configure.ac:1`:

```m4
AC_INIT([rt-app], [m4_esyscmd_s([git describe --tags HEAD])], [...])
```

`git describe --tags` fallisce perché il repository non ha tag, quindi
`PACKAGE_VERSION` resta la stringa vuota. Non impatta la build né l'esecuzione: cambia
solo la versione dichiarata dal pacchetto. Si risolverebbe con un `git tag`.

**Cinque warning in compilazione**, tutti identici e innocui — uno per unità di
compilazione:

```
./../libdl/dl_syscalls.h:20: warning: "_GNU_SOURCE" redefined
```

`_GNU_SOURCE` è già definito da `config.h` generato da autoconf, e `dl_syscalls.h` lo
ridefinisce. Nessun errore.

**Il binario di default non contiene OTel.** Senza macro, `RTAPP_TRACE_LEVEL` vale 0 e
l'include è protetto da `#if (RTAPP_TRACE_LEVEL > 0)` (`rt-app_types.h:60`, fix del
task 0.1): il binario risulta di 340 KB con **zero** simboli `opentelemetry`. Gli archivi
statici sono passati al linker ma, non essendoci simboli da risolvere, non vengono
incorporati.

## 4. Matrice delle macro: tutte le combinazioni del DoE compilano

`run_doe.sh:70` ricostruisce rt-app per ogni cella con

```
make CPPFLAGS="-DRTAPP_TRACE_LEVEL=$trace -DRTAPP_PROCESSOR_TYPE=$proc \
               -DRTAPP_SAMPLER_TYPE=$samp -DRTAPP_SAMPLER_RATIO=$ratio"
```

Ho verificato in anticipo le combinazioni che i tre blocchi useranno:

| TRACE | PROC | SAMP | RATIO | esito | tempo | binario | simboli otel |
|---|---|---|---|---|---|---|---|
| 0 | 0 | 0 | 1.0 | OK | **5 s** | **340 K** | **0** |
| 1 | 0 | 0 | 1.0 | OK | 37 s | 5,1 M | 1232 |
| 2 | 0 | 0 | 1.0 | OK | 37 s | 5,2 M | 1234 |
| 3 | 0 | 0 | 1.0 | OK | 38 s | 5,3 M | 1234 |
| 3 | 1 | 1 | 0.1 | OK | 38 s | 5,3 M | 1257 |
| 1 | 1 | 2 | 1.0 | OK | 37 s | 5,2 M | 1252 |

Attivare il tracing costa **15× di binario** (340 K → 5,2 M) e **7,5× di tempo di
compilazione** (5 s → 38 s), perché tutto opentelemetry-cpp viene linkato staticamente.

## 5. Verifica funzionale: le macro hanno effetto a runtime

Non basta che compili. Ho eseguito lo stesso taskset (3 s, un thread) con due binari che
differiscono **solo** per il sampler, senza nessun collector Zipkin in ascolto:

| binario | tentativi di export |
|---|---|
| `TRACE=1 PROC=1 SAMP=2` (AlwaysOff) | **0** |
| `TRACE=1 PROC=0 SAMP=0` (AlwaysOn) | **1** |

```
[Error] ... zipkin_exporter.cc:111 ZIPKIN EXPORTER] Zipkin Exporter: Connection failed
```

Con AlwaysOff nessuno span viene campionato, quindi non c'è niente da esportare e
l'exporter non tenta nemmeno la connessione. Con AlwaysOn tenta e fallisce, perché il
collector non c'è. La macro `RTAPP_SAMPLER_TYPE` cambia davvero il comportamento — non è
solo codice morto compilato via.

Entrambi i binari eseguono correttamente e producono il log per-thread (299 righe in 3 s).

## 6. Costo previsto del DoE (dati misurati qui + task 0.5)

Dalle definizioni dei blocchi (`run_doe.sh:98-133`):

| blocco | celle | rip. | run | binari distinti |
|---|---|---|---|---|
| block1 | 4 | 20 | 80 | 4 |
| block2 | 6 | 25 | 150 | 6 |
| block3 | 12 | 15 | 180 | 3 (in cache fra gli `n_lo`) |
| **totale** | **22** | | **410** | **13** |

- **Tempo**: 410 run × 20 s = 8200 s ≈ **2 h 17 min** di sola esecuzione, più ~7 min di
  compilazioni (13 binari, di cui 11 tracciati a 38 s). Con l'overhead di `test.sh`,
  **circa 2 ore e mezza** in totale, da fare in tre sessioni separate (i blocchi vanno
  lanciati uno alla volta).
- **Disco**: dal task 0.5, un run da 20 s con `n_lo=4` pesa 5,0 MB e con solo HI ~250 KB.
  Stima: block1 ~20 MB, block2 ~750 MB, block3 ~740 MB → **~1,5 GB**, a cui va aggiunto
  lo `stdout.log` degli span del blocco 2 (exporter ostream), non stimabile finché il
  Task 3 non è fatto. Da prevedere una compressione.

## 7. Cosa resta aperto (Task 4)

- **I percorsi in cima a `run_doe.sh` sono sbagliati per questa macchina**:
  `RTAPP_SRC_DIR`, `BIN_CACHE` e `DOE_ROOT` puntano a `$HOME/rtsia-project/project/...`,
  che non esiste. Sono override-abili da ambiente (`${VAR:-default}`) ma vanno editati.
- `bin/` esiste ma è **di proprietà di root** ed è vuota. Il DoE gira da root (serve
  `SCHED_FIFO` 90), quindi non blocca nulla, ma le cartelle prodotte vanno poi
  `chown`-ate.
- `2-DoE/data_table.csv` contiene solo l'intestazione: è corretto, è un file di **output**
  che `run_doe.sh:88` riempie una riga per run, non una matrice di progetto da preparare.
- Il blocco 2 richiede l'exporter ostream, cioè il **Task 3**, e con esso la correzione
  già annotata: `InitTracer()` ignora `RTAPP_SAMPLER_TYPE`/`_RATIO`/`RTAPP_PROCESSOR_TYPE`
  (finding del task 0.3).

L'albero è stato lasciato con la build di default (`RTAPP_TRACE_LEVEL=0`, 340 KB), cioè
quello che produce un `make` su un clone pulito.
