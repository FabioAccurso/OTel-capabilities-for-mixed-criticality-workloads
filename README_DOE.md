# DoE kit — rt-app / OpenTelemetry mixed-criticality assessment

Estrai questo tar dentro `project/` (accanto a `rt-app/` e `otel-installdir/`).

## Prerequisiti
- `rt-app` compilabile (vedi guida precedente): binario in `rt-app/src/rt-app`
- `sudo apt install cpuset` (per `cset shield`)
- Python 3 (nessuna dipendenza esterna: solo stdlib)

## Passi

1. Modifica le tre variabili in cima a `scripts/measurements/run_doe.sh`
   (`RTAPP_SRC_DIR`, `BIN_CACHE`, `DOE_ROOT`) se i tuoi path sono diversi.

2. Isola le CPU (una volta per sessione, richiede sudo):
   ```
   sudo scripts/utils_isolation/isolate_cpus.sh 2,3
   ```

3. Blocco 1 — overhead puro dell'istrumentazione:
   ```
   scripts/measurements/run_doe.sh block1
   ```

4. Blocco 2 — granularità del sampling (richiede di passare temporaneamente
   a InitTracer() invece di InitTracerZipkin() in main(), per poter contare
   gli span esportati da stdout.log):
   ```
   scripts/measurements/run_doe.sh block2
   ```

5. Blocco 3 — contesa del processor/exporter sotto carico crescente:
   ```
   scripts/measurements/run_doe.sh block3
   ```

6. Analisi (una volta finiti i blocchi che ti interessano):
   ```
   python3 scripts/measurements/analyze_doe.py \
       --data-table 2-DoE/data_table.csv --out 2-DoE/results.csv
   ```

7. Rimuovi lo shield quando hai finito:
   ```
   sudo scripts/utils_isolation/reset_isolation.sh
   ```

`2-DoE/results.csv` avrà una riga per run con tutti i fattori (trace_level,
processor_type, sampler_type, sampler_ratio, n_lo) e le variabili di
risposta (deadline_miss_ratio, max_duration_us, period_jitter_std_us,
hi_spans_exported, lo_spans_exported) pronte per pandas/R.
