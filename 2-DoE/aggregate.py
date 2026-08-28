#!/usr/bin/env python3
"""Aggrega results.csv nelle tabelle di sintesi del Task 5.

Regole di aggregazione, ciascuna imparata da un errore vero durante la campagna:
  - i DEADLINE MISS si SOMMANO fra ripetizioni (mediarli li azzera);
  - le altre grandezze si aggregano per MEDIANA fra ripetizioni (mai run singoli);
  - il jitter si riporta con std E IQR (quando divergono, sono incidenti isolati);
  - i conteggi di span del blocco 2 sono BINARI per run -> proporzione di Wilson;
  - le celle di controllo a carico basso sono BIMODALI: si riportano le due mode.
"""
import csv, math, statistics as st, collections

ROWS = list(csv.DictReader(open("2-DoE/results.csv")))
F = lambda r, k: float(r[k]) if r[k] not in ("", None) else None
I = lambda r, k: int(float(r[k])) if r[k] not in ("", None) else None

def med(rs, k):
    v = [F(r, k) for r in rs if F(r, k) is not None]
    return st.median(v) if v else None

def wilson(k, n, z=1.96):
    if not n: return (0.0, 0.0)
    p = k / n; d = 1 + z*z/n
    c = (p + z*z/(2*n)) / d
    h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / d
    return (100*max(0, c-h), 100*min(1, c+h))

def cells(block, keyf):
    g = collections.defaultdict(list)
    for r in ROWS:
        if r["block"] == block:
            g[keyf(r)].append(r)
    return g

# ---------------------------------------------------------------- BLOCCO 1
print("="*88)
print("BLOCCO 1 — costo dell'instrumentazione (HI da solo, Batch, AlwaysOn, Zipkin)")
print("="*88)
print(f"{'trace_level':>12} {'run':>4} {'slack':>7} {'costo/giro':>11} {'jitter std':>11} {'IQR':>6} "
      f"{'wu med':>7} {'wu max':>7} {'miss':>5}")
print("-"*88)
b1 = cells("block1", lambda r: int(r["trace_level"]))
base = None
for lvl in sorted(b1):
    rs = b1[lvl]
    sl = med(rs, "hi_slack_median_us")
    if base is None: base, d = sl, "—"
    else: d = f"{sl-base:+.0f} us"
    miss = sum(I(r, "hi_deadline_miss_count") for r in rs)
    print(f"{lvl:>12} {len(rs):>4} {sl:>7.0f} {d:>11} {med(rs,'hi_period_jitter_std_us'):>11.1f} "
          f"{med(rs,'hi_period_iqr_us'):>6.0f} {med(rs,'hi_wu_latency_median_us'):>7.0f} "
          f"{max(F(r,'hi_wu_latency_max_us') for r in rs):>7.0f} {miss:>5}")

# ---------------------------------------------------------------- BLOCCO 2
print()
print("="*88)
print("BLOCCO 2 — campionamento (trace_level 2, ostream, 1 HI + 4 LO)")
print("="*88)
print(f"{'cella':>12} {'run':>4} {'campionati':>11} {'osservato':>10} {'IC 95%':>16} {'nominale':>9} {'intermedi':>10}")
print("-"*88)
b2 = cells("block2", lambda r: (int(r["sampler_type"]), float(r["sampler_ratio"])))
tot_int = 0
for (samp, ratio) in sorted(b2, key=lambda k: (k[0] != 2, k[1])):
    rs = b2[(samp, ratio)]
    cnt = [I(r, "spans_exported_total") for r in rs]
    n = len(cnt); k = sum(1 for c in cnt if c == 17)
    inter = sum(1 for c in cnt if c not in (0, 17)); tot_int += inter
    lab = {2: "AlwaysOff", 0: "AlwaysOn"}.get(samp, f"ratio {ratio}")
    nom = {2: "0%", 0: "100%"}.get(samp, f"{ratio*100:.0f}%")
    lo, hi = wilson(k, n)
    print(f"{lab:>12} {n:>4} {k:>11} {100*k/n:>9.1f}% {f'[{lo:.1f}, {hi:.1f}]':>16} {nom:>9} {inter:>10}")
print("-"*88)
print(f"  valori intermedi su {sum(len(v) for v in b2.values())} run: {tot_int}")
print("  (un valore diverso da 0 e da 17 sarebbe l'unica prova che il sampler")
print("   sa dare destini diversi a HI e ai LO)")

# ---------------------------------------------------------------- BLOCCO 3
print()
print("="*88)
print("BLOCCO 3 — pipeline sotto carico (trace_level 3, Zipkin senza collector)")
print("="*88)
NAMES = {(0,0): "t0 controllo", (3,0): "t3 Batch", (3,1): "t3 Simple"}
b3 = cells("block3", lambda r: (int(r["n_lo"]), int(r["trace_level"]), int(r["processor_type"])))
print(f"{'n_lo':>5} {'cella':<14} {'slack':>7} {'costo/giro':>11} {'std':>8} {'IQR':>7} "
      f"{'MISS':>5} {'run':>6} {'sforo pegg.':>12}")
print("-"*88)
tot_miss = 0
for n_lo in (0, 1, 4, 8):
    b = None
    for tl, pt in ((0,0), (3,0), (3,1)):
        rs = b3.get((n_lo, tl, pt))
        if not rs: continue
        sl = med(rs, "hi_slack_median_us")
        if b is None: b, d = sl, "—"
        else: d = f"{sl-b:+.0f} us"
        miss = sum(I(r, "hi_deadline_miss_count") for r in rs); tot_miss += miss
        rwm = sum(1 for r in rs if I(r, "hi_deadline_miss_count"))
        worst = min(F(r, "hi_slack_min_us") for r in rs)
        flag = " <<<" if miss else ""
        print(f"{n_lo:>5} {NAMES[(tl,pt)]:<14} {sl:>7.0f} {d:>11} {med(rs,'hi_period_jitter_std_us'):>8.1f} "
              f"{med(rs,'hi_period_iqr_us'):>7.0f} {miss:>5} {rwm:>3}/{len(rs):<2} "
              f"{worst:>11.0f}{flag}")
    print()
print(f"TOTALE deadline miss nel blocco 3: {tot_miss}")

# ------------------------------------------------- LO sotto carico (blocco 3)
print()
print("="*88)
print("BLOCCO 3 — degrado dei task LO (il miss% satura, si usano wu_lat e periodo)")
print("="*88)
print(f"{'n_lo':>5} {'cella':<14} {'LO miss%':>9} {'LO periodo med':>15} {'LO wu med':>10} {'LO wu p99':>10}")
print("-"*88)
for n_lo in (1, 4, 8):
    for tl, pt in ((0,0), (3,1)):
        rs = b3.get((n_lo, tl, pt))
        if not rs or med(rs, "lo_n_iters") is None: continue
        print(f"{n_lo:>5} {NAMES[(tl,pt)]:<14} {100*med(rs,'lo_deadline_miss_ratio'):>8.1f}% "
              f"{med(rs,'lo_period_median_us'):>15.0f} {med(rs,'lo_wu_latency_median_us'):>10.0f} "
              f"{med(rs,'lo_wu_latency_p99_us'):>10.0f}")
    print()

# ------------------------------------------------- bimodalita' del controllo
print("="*88)
print("CELLE DI CONTROLLO — bimodalita' del jitter (NON riassumibili con la mediana)")
print("="*88)
for n_lo in (0, 1, 4, 8):
    rs = b3.get((n_lo, 0, 0))
    if not rs: continue
    v = sorted(F(r, "hi_period_jitter_std_us") for r in rs)
    lo = [x for x in v if x < 6]
    print(f"  n_lo={n_lo}: {len(lo):2d}/{len(v)} run nel modo basso "
          f"(mediana {st.median(lo):4.1f})" if lo else f"  n_lo={n_lo}: 0/{len(v)} nel modo basso", end="")
    hi = [x for x in v if x >= 6]
    print(f"   {len(hi):2d} nel modo alto (mediana {st.median(hi):5.1f})" if hi else "   nessuno nel modo alto")
