#!/usr/bin/env python3
"""Analisi del blocco 3: carico di fondo x configurazione della pipeline di telemetria.

Lezioni incorporate dalle analisi precedenti:
 - la prima riga di ogni log e' un transitorio di avvio (task 0.5) -> scartata;
 - i deadline miss vanno SOMMATI fra ripetizioni, mai mediati: sono eventi rari e la
   mediana fra run li azzera (blocco 3, cella Simple n_lo=4);
 - il jitter va separato in "corpo" e "code": pochi giri con periodo dimezzato dopo uno
   sforo gonfiano la deviazione standard senza vera irregolarita' diffusa;
 - le celle di controllo sono BIMODALI a carico basso -> la mediana cade nel vuoto fra
   le due mode e non e' una statistica di sintesi valida: si riportano le due mode.
"""
import glob, os, statistics as st

CELLS = (("t0 (controllo)", "t0_p0_s0_r0.0"),
         ("t3 Batch",       "t3_p0_s0_r0.0"),
         ("t3 Simple",      "t3_p1_s0_r0.0"))

def load(rd):
    run=[]; per=[]; slack=[]; wu=[]
    with open(os.path.join(rd, "rtapp-HI_task-0.log")) as f:
        for l in f:
            p = l.split()
            if len(p) < 11 or not p[0].isdigit():
                continue
            run.append(int(p[2])); per.append(int(p[3]))
            slack.append(int(p[7])); wu.append(int(p[10]))
    return run[1:], per[1:], slack[1:], wu[1:]     # scarta il transitorio

def cell(pat, n_lo):
    out=[]
    for rd in sorted(glob.glob(f"2-DoE/block3/{pat}_n{n_lo}/run_*")):
        if os.path.exists(os.path.join(rd, "rtapp-HI_task-0.log")):
            out.append(load(rd))
    return out

def failed_conn(pat, n_lo):
    f = f"2-DoE/block3/{pat}_n{n_lo}/run_01/stderr.log"
    if not os.path.exists(f): return 0
    with open(f, errors="ignore") as fh:
        return sum(1 for l in fh if "Connection failed" in l)

print("="*94)
print("1. COSTO SUL TASK CRITICO  (slack mediano; mediana fra le 15 ripetizioni)")
print("="*94)
print(f"{'n_lo':>5} {'cella':<16} {'slack':>7} {'vs controllo':>13} {'run_med':>8} {'wu_med':>7} {'wu_max':>7} {'conn.fallite/run':>17}")
print("-"*94)
for n_lo in (0,1,4,8):
    base=None
    for lab,pat in CELLS:
        g = cell(pat, n_lo)
        if not g: continue
        sl = st.median([st.median(x[2]) for x in g])
        rm = st.median([st.median(x[0]) for x in g])
        wm = st.median([st.median(x[3]) for x in g])
        wx = max(max(x[3]) for x in g)
        if base is None: base, d = sl, "—"
        else: d = f"{sl-base:+.0f} us"
        print(f"{n_lo:>5} {lab:<16} {sl:>7.0f} {d:>13} {rm:>8.0f} {wm:>7.0f} {wx:>7.0f} {failed_conn(pat,n_lo):>17}")
    print()

print("="*94)
print("2. DEADLINE MISS  (SOMMATI su tutte le ripetizioni -- mai mediati)")
print("="*94)
print(f"{'n_lo':>5} {'cella':<16} {'giri tot':>9} {'miss':>6} {'miss%':>8} {'run con miss':>13} {'sforo peggiore':>16}")
print("-"*94)
tot_miss=0
for n_lo in (0,1,4,8):
    for lab,pat in CELLS:
        g = cell(pat, n_lo)
        if not g: continue
        giri = sum(len(x[2]) for x in g)
        miss = sum(sum(1 for s in x[2] if s<0) for x in g)
        rwm  = sum(1 for x in g if any(s<0 for s in x[2]))
        worst= min(min(x[2]) for x in g)
        tot_miss += miss
        flag = "  <<<" if miss else ""
        print(f"{n_lo:>5} {lab:<16} {giri:>9} {miss:>6} {100*miss/giri:>7.3f}% {rwm:>9}/{len(g):<3} "
              f"{worst if worst<0 else 0:>13} us{flag}")
    print()
print(f"TOTALE deadline miss nel blocco 3: {tot_miss}")

print()
print("="*94)
print("3. JITTER: corpo della distribuzione contro code")
print("="*94)
print("Il per_std e' gonfiato da pochi giri con periodo dimezzato (il timer che si")
print("riaggancia dopo uno sforo). Si riporta anche l'IQR, insensibile a quelle code.")
print()
print(f"{'n_lo':>5} {'cella':<16} {'per_std':>9} {'IQR':>7} {'per_med':>8} {'giri<5000us':>12}")
print("-"*94)
for n_lo in (0,1,4,8):
    for lab,pat in CELLS:
        g = cell(pat, n_lo)
        if not g: continue
        sd  = st.median([st.pstdev(x[1]) for x in g])
        pm  = st.median([st.median(x[1]) for x in g])
        iqr = st.median([(lambda v: sorted(v)[int(.75*len(v))]-sorted(v)[int(.25*len(v))])(x[1]) for x in g])
        tiny= sum(sum(1 for p in x[1] if p<5000) for x in g)
        print(f"{n_lo:>5} {lab:<16} {sd:>9.1f} {iqr:>7.0f} {pm:>8.0f} {tiny:>12}")
    print()

print("="*94)
print("4. L'ANOMALIA DEL BLOCCO 2, RISOLTA: jitter a trace_level=0 (nessun exporter)")
print("="*94)
for n_lo in (0,1,4,8):
    g = cell("t0_p0_s0_r0.0", n_lo)
    if not g: continue
    v = sorted(st.pstdev(x[1]) for x in g)
    lo = sum(1 for x in v if x < 6)
    print(f"  n_lo={n_lo}: mediana {st.median(v):5.1f} us   modo basso(<6us) {lo:2d}/{len(v)}   "
          f"min {v[0]:4.1f}  max {v[-1]:5.1f}")
print()
print("  Nessun exporter e' linkato in queste celle (RTAPP_TRACE_LEVEL=0, verificato")
print("  al Task 1: zero simboli otel nel binario) -> l'effetto e' del CARICO, non di Zipkin.")
