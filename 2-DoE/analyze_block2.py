#!/usr/bin/env python3
"""Analisi del blocco 2: campionamento e costo dell'export sul task critico.

Sfrutta un esperimento naturale: dentro le celle a ratio, stesso binario e stessa
config, i run campionati e quelli scartati differiscono SOLO per la decisione del
sampler. Confrontarli isola il costo dell'export da quello dell'instrumentazione.
"""
import glob, os, re, math, statistics as st

SPAN_FULL = 17          # 2 + 5 thread * 3, verificato sul campo

def run_complete(rd):
    """test.sh gzippa i log LO come ultimo passo -> marcatore di run concluso."""
    return bool(glob.glob(os.path.join(rd, "*LO_noise*.log.gz")))

def n_spans(rd):
    with open(os.path.join(rd, "stdout.log"), errors="ignore") as f:
        return sum(1 for l in f if l.startswith("  name"))

def hi_metrics(rd):
    rows = []
    with open(os.path.join(rd, "rtapp-HI_task-0.log")) as f:
        for l in f:
            p = l.split()
            if len(p) < 11 or not p[0].isdigit():
                continue
            rows.append((int(p[2]), int(p[3]), int(p[7]), int(p[10])))
    rows = rows[1:]                      # transitorio di avvio (task 0.5)
    run, per, slack, wu = zip(*rows)
    return dict(n=len(rows), run_med=st.median(run), per_std=st.pstdev(per),
                slack_med=st.median(slack), miss=100*sum(1 for s in slack if s < 0)/len(slack),
                wu_med=st.median(wu), wu_max=max(wu))

def wilson(k, n, z=1.96):
    if n == 0: return (0.0, 0.0)
    p = k/n; d = 1 + z*z/n
    c = (p + z*z/(2*n))/d
    h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))/d
    return (100*max(0, c-h), 100*min(1, c+h))

cells = {}
for d in sorted(glob.glob("2-DoE/block2/t2_*")):
    m = re.search(r"_s(\d)_r([\d.]+)_", d)
    runs = [rd for rd in sorted(glob.glob(os.path.join(d, "run_*"))) if run_complete(rd)]
    cells[d] = dict(samp=m.group(1), ratio=float(m.group(2)),
                    data=[(n_spans(rd), hi_metrics(rd)) for rd in runs])

# ---------- 1. campionamento ----------
print("=" * 78)
print("1. CAMPIONAMENTO -- il sampler separa mai HI da LO?")
print("=" * 78)
print(f"{'cella':<12} {'n':>4} {'campionati':>11} {'osservato':>10} {'IC 95% (Wilson)':>18} {'intermedi':>10}")
print("-" * 78)
tot_int = tot_n = 0
for d, c in sorted(cells.items(), key=lambda x: (x[1]['samp'] != '2', x[1]['ratio'])):
    counts = [n for n, _ in c["data"]]
    n = len(counts); k = sum(1 for x in counts if x == SPAN_FULL)
    inter = sum(1 for x in counts if x not in (0, SPAN_FULL))
    tot_int += inter; tot_n += n
    lab = {"2": "AlwaysOff", "0": "AlwaysOn"}.get(c["samp"], f"ratio {c['ratio']}")
    lo, hi = wilson(k, n)
    print(f"{lab:<12} {n:>4} {k:>11} {100*k/n:>9.1f}% {f'[{lo:.1f}, {hi:.1f}]':>18} {inter:>10}")
print("-" * 78)
print(f"TOTALE: {tot_n} run completi, valori intermedi = {tot_int}")
print("(un valore intermedio, cioe' diverso da 0 e da 17, sarebbe l'unica prova che il")
print(" sampler puo' dare destini diversi a HI e ai LO)")

# ---------- 2. costo dell'export ----------
print()
print("=" * 78)
print("2. ESPERIMENTO NATURALE -- costo dell'EXPORT sul task critico")
print("=" * 78)
print("Solo celle a ratio: stesso binario, stessa config, cambia solo l'esito del")
print("sorteggio. Mediane fra ripetizioni, prima riga di ogni log scartata.")
print()
camp, scar = [], []
for d, c in cells.items():
    if c["samp"] != "1":
        continue
    for n, m in c["data"]:
        (camp if n == SPAN_FULL else scar).append(m)
print(f"{'gruppo':<24} {'run':>4} {'run_med':>9} {'per_std':>9} {'slack_med':>10} {'wu_med':>8} {'wu_max':>8} {'miss%':>7}")
print("-" * 78)
for lab, g in (("campionati (17 span)", camp), ("scartati (0 span)", scar)):
    if not g: continue
    med = lambda k: st.median([x[k] for x in g])
    print(f"{lab:<24} {len(g):>4} {med('run_med'):>9.0f} {med('per_std'):>9.1f} "
          f"{med('slack_med'):>10.0f} {med('wu_med'):>8.0f} {max(x['wu_max'] for x in g):>8.0f} "
          f"{med('miss'):>7.2f}")
if camp and scar:
    dp = st.median([x['per_std'] for x in camp]) - st.median([x['per_std'] for x in scar])
    ds = st.median([x['slack_med'] for x in camp]) - st.median([x['slack_med'] for x in scar])
    print("-" * 78)
    print(f"delta campionati - scartati:  period_std {dp:+.1f} us   slack {ds:+.0f} us")

# ---------- 3. HI sotto carico ----------
print()
print("=" * 78)
print("3. IL TASK CRITICO SOTTO CARICO (n_lo=4, tutte le celle)")
print("=" * 78)
allm = [m for c in cells.values() for _, m in c["data"]]
print(f"run analizzati: {len(allm)}   giri totali: {sum(x['n'] for x in allm)}")
print(f"deadline miss: max su tutte le celle = {max(x['miss'] for x in allm):.3f}%")
print(f"slack mediano: {st.median([x['slack_med'] for x in allm]):.0f} us   "
      f"minimo osservato: {min(x['slack_med'] for x in allm):.0f} us")
print(f"wu_latency peggiore: {max(x['wu_max'] for x in allm)} us")
