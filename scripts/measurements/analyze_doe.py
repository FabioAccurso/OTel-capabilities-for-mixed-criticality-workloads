#!/usr/bin/env python3
"""
Estrae le variabili di risposta da ogni run del DoE e le unisce ai livelli dei
fattori letti da data_table.csv, producendo 2-DoE/results.csv (una riga per run).

Colonne del log di rt-app (rt-app_utils.cpp:151), separate da spazi:
  ind  perf  duration  period  start_time  end_time  rel_start_time  slack
  c_duration  c_period  wu_latency
Tutti i tempi in microsecondi. slack < 0 = la scadenza e' stata mancata.

CORREZIONI RISPETTO ALLA VERSIONE ORIGINALE (tutte pagate con errori veri durante
la campagna; il dettaglio sta in CLAUDE.md, Task 5):

 1. La PRIMA RIGA di ogni log e' un transitorio di avvio: t_next viene inizializzato
    a *t_first (rt-app.cpp:737), quindi il primo slack e' privo di senso e vale da
    solo 1 deadline miss su ~2000 in OGNI cella. Scartata.

 2. count_exported_spans() contava la SOTTOSTRINGA del nome in tutto il file. Lo span
    del thread porta il nome due volte (campo `name` e attributo `config.name`) ->
    fattore 2 esatto; e i discendenti (thread_loop, phase, phase_loop) non portano il
    nome della task e non venivano contati affatto. Ora si contano le righe
    `^  name<spazi>: X`, distinguendo il nome esatto, e si riporta anche il totale.

 3. Si emette il NUMERO di miss oltre al rapporto: i miss vanno SOMMATI fra
    ripetizioni, mai mediati (blocco 3: 6 miss su 5 run di 15 -> mediana 0,00%).

 4. Si emette l'IQR del periodo oltre alla deviazione standard: dove divergono di due
    ordini di grandezza il fenomeno e' fatto di incidenti isolati (riaggancio del
    timer `relative`, rt-app.cpp:752-756) e non di degrado diffuso.

 5. max_duration_us / mean_duration_us derivano da `duration` (la colonna `run`), che
    al livello 3 *scende* per un effetto microarchitetturale non spiegato (blocco 1).
    Restano nel CSV per continuita' ma sono marcate come NON USARE per confrontare
    livelli di tracing: per quello servono slack, period_jitter e wu_latency.

 6. I log LO_noise sono gzippati (decisione del 2026-08-28): letti con gzip.open.

Uso:
  ./analyze_doe.py --data-table 2-DoE/data_table.csv --out 2-DoE/results.csv
"""
import argparse
import csv
import glob
import gzip
import os
import re
import statistics as st

# Riga di uno span nell'esportatore ostream: due spazi, "name", spazi, ":", valore.
# Gli attributi usano invece un TAB iniziale (config.name, service.name) e non matchano.
SPAN_NAME_RE = re.compile(r"^  name\s*:\s*(\S+)\s*$")


def open_maybe_gz(path):
    return gzip.open(path, "rt", errors="ignore") if path.endswith(".gz") \
        else open(path, errors="ignore")


def find_log(run_dir, needle):
    """Log di un thread. HI_task resta in chiaro, LO_noise e' gzippato."""
    pats = [f"*{needle}*.log", f"*{needle}*.log.gz"]
    out = []
    for p in pats:
        out += glob.glob(os.path.join(run_dir, p))
    return sorted(out)


def parse_log(path):
    """Righe di timing, SENZA la prima (transitorio di avvio)."""
    rows = []
    with open_maybe_gz(path) as f:
        for line in f:
            parts = line.split()
            if len(parts) < 11 or not parts[0].isdigit():
                continue                      # intestazione o riga di commento
            rows.append(dict(duration=int(parts[2]), period=int(parts[3]),
                             slack=int(parts[7]), wu_latency=int(parts[10])))
    return rows[1:]


def quantile(v, q):
    v = sorted(v)
    if not v:
        return 0.0
    k = (len(v) - 1) * q
    f = int(k)
    return float(v[f]) if f + 1 >= len(v) else v[f] + (v[f + 1] - v[f]) * (k - f)


def summarize(rows, prefix):
    if not rows:
        return {}
    per = [r["period"] for r in rows if r["period"] > 0]
    dur = [r["duration"] for r in rows]
    sl = [r["slack"] for r in rows]
    wu = [r["wu_latency"] for r in rows]
    miss = sum(1 for s in sl if s < 0)
    return {
        f"{prefix}n_iters": len(rows),
        f"{prefix}deadline_miss_count": miss,          # SOMMARE, non mediare
        f"{prefix}deadline_miss_ratio": round(miss / len(rows), 6),
        f"{prefix}slack_median_us": st.median(sl),
        f"{prefix}slack_min_us": min(sl),              # lo sforo peggiore
        f"{prefix}period_median_us": st.median(per) if per else "",
        f"{prefix}period_jitter_std_us": round(st.pstdev(per), 2) if len(per) > 1 else 0.0,
        f"{prefix}period_iqr_us": round(quantile(per, .75) - quantile(per, .25), 2) if per else "",
        f"{prefix}wu_latency_median_us": st.median(wu),
        f"{prefix}wu_latency_p99_us": round(quantile(wu, .99), 1),
        f"{prefix}wu_latency_max_us": max(wu),
        # derivate da `duration`: NON usare per confrontare livelli di tracing
        f"{prefix}max_duration_us": max(dur),
        f"{prefix}mean_duration_us": round(st.mean(dur), 1),
    }


def count_exported_spans(run_dir):
    """Conta gli span esportati su stdout (solo esportatore ostream, cioe' blocco 2).

    Corregge il bug segnalato: si contano le righe `  name : X`, non le occorrenze
    della sottostringa nel file. Restituisce il totale e la ripartizione per nome.
    """
    p = os.path.join(run_dir, "stdout.log")
    if not os.path.exists(p):
        return None, None, None
    names = []
    with open(p, errors="ignore") as f:
        for line in f:
            m = SPAN_NAME_RE.match(line)
            if m:
                names.append(m.group(1))
    if not names:
        return 0, 0, 0
    hi = sum(1 for n in names if n.startswith("HI_task"))
    lo = sum(1 for n in names if n.startswith("LO_noise"))
    return len(names), hi, lo


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-table", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.data_table) as f:
        input_rows = list(csv.DictReader(f))

    hi_fields = list(summarize([dict(duration=0, period=1, slack=0, wu_latency=0)] * 2, "hi_"))
    lo_fields = [f.replace("hi_", "lo_") for f in hi_fields]
    out_fields = (list(input_rows[0].keys()) + ["exporter"] + hi_fields + lo_fields +
                  ["spans_exported_total", "hi_spans_exported", "lo_spans_exported"])

    n_ok = n_missing = 0
    with open(args.out, "w", newline="") as out_f:
        w = csv.DictWriter(out_f, fieldnames=out_fields, extrasaction="ignore")
        w.writeheader()
        for row in input_rows:
            rd = row["run_dir"]
            merged = dict(row)
            # Solo il blocco 2 gira con RTAPP_EXPORTER_TYPE=1 (ostream); gli altri
            # usano Zipkin e quindi non stampano span su stdout.
            merged["exporter"] = "ostream" if row["block"] == "block2" else "zipkin"

            hi = find_log(rd, "HI_task")
            if hi:
                merged.update(summarize(parse_log(hi[0]), "hi_"))
                n_ok += 1
            else:
                n_missing += 1

            # LO: piu' istanze, si aggregano tutte le righe insieme.
            lo_rows = []
            for p in find_log(rd, "LO_noise"):
                lo_rows += parse_log(p)
            if lo_rows:
                merged.update(summarize(lo_rows, "lo_"))

            tot, h, l = count_exported_spans(rd)
            merged["spans_exported_total"] = "" if tot is None else tot
            merged["hi_spans_exported"] = "" if h is None else h
            merged["lo_spans_exported"] = "" if l is None else l

            w.writerow(merged)

    print(f"scritto {args.out}: {len(input_rows)} run "
          f"({n_ok} con log HI, {n_missing} senza)")


if __name__ == "__main__":
    main()
