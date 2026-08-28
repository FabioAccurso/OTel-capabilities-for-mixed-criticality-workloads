#!/usr/bin/env python3
"""Genera i grafici del Task 5 come SVG, senza dipendenze esterne.

SVG e non PNG perche' e' vettoriale (si scala nella relazione senza sgranare) e
perche' su questa macchina matplotlib non e' installato.

Palette: quella di riferimento della skill dataviz, usata SENZA modifiche
(slot categorici 1-2 blu/arancio, rampa sequenziale blu, status critical).
Ogni SVG e' autonomo: porta il proprio <style> con i valori chiari e la
variante scura, con selettori prefissati dall'id per non collidere quando piu'
grafici finiscono nella stessa pagina HTML.

Uso:  python3 2-DoE/make_plots.py     ->  2-DoE/plots/*.svg
"""
import csv, math, os, statistics as st, collections

OUT = "2-DoE/plots"
ROWS = list(csv.DictReader(open("2-DoE/results.csv")))
F = lambda r, k: float(r[k]) if r[k] not in ("", None) else None
I = lambda r, k: int(float(r[k])) if r[k] not in ("", None) else None

# ---------------------------------------------------------------- palette
LIGHT = dict(surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e", ink3="#7b7a75",
             grid="#e6e5e1", axis="#c9c8c3",
             s1="#2a78d6", s2="#eb6834", crit="#d03b3b",
             q1="#86b6ef", q2="#5598e7", q3="#2a78d6", q4="#1c5cab")
DARK = dict(surface="#1a1a19", ink="#ffffff", ink2="#c3c2b7", ink3="#94938b",
            grid="#33332f", axis="#4a4a45",
            s1="#3987e5", s2="#d95926", crit="#d03b3b",
            q1="#184f95", q2="#256abf", q3="#3987e5", q4="#86b6ef")

FONT = "system-ui,-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif"


def style_block(cid):
    def vars_(d):
        return "".join(f"--{k}:{v};" for k, v in d.items())
    return f"""<style>
#{cid}{{{vars_(LIGHT)}font-family:{FONT}}}
@media (prefers-color-scheme:dark){{
  :root:not([data-theme="light"]) #{cid}{{{vars_(DARK)}}}
}}
:root[data-theme="dark"] #{cid}{{{vars_(DARK)}}}
#{cid} .bg{{fill:var(--surface)}}
#{cid} .grid{{stroke:var(--grid);stroke-width:1}}
#{cid} .axis{{stroke:var(--axis);stroke-width:1}}
#{cid} .t{{fill:var(--ink);font-size:13px}}
#{cid} .t2{{fill:var(--ink2);font-size:12px}}
#{cid} .t3{{fill:var(--ink3);font-size:11px}}
#{cid} .ttl{{fill:var(--ink);font-size:15px;font-weight:600}}
#{cid} .sub{{fill:var(--ink2);font-size:12px}}
#{cid} .val{{fill:var(--ink);font-size:12px;font-weight:600}}
</style>"""


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def bar_top_rounded(x, y, w, h, r=4):
    """Barra ancorata alla baseline con i soli angoli superiori arrotondati."""
    r = min(r, w / 2, h) if h > 0 else 0
    if h <= 0:
        return ""
    return (f'M{x:.1f},{y+h:.1f} V{y+r:.1f} Q{x:.1f},{y:.1f} {x+r:.1f},{y:.1f} '
            f'H{x+w-r:.1f} Q{x+w:.1f},{y:.1f} {x+w:.1f},{y+r:.1f} V{y+h:.1f} Z')


def svg_open(cid, w, h, title, subtitle):
    s = [f'<svg id="{cid}" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
         f'width="100%" role="img" aria-label="{esc(title)}">']
    s.append(style_block(cid))
    s.append(f'<rect class="bg" x="0" y="0" width="{w}" height="{h}"/>')
    s.append(f'<text class="ttl" x="16" y="26">{esc(title)}</text>')
    if subtitle:
        s.append(f'<text class="sub" x="16" y="45">{esc(subtitle)}</text>')
    return s


def write(cid, parts):
    parts.append("</svg>")
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, f"{cid}.svg")
    with open(p, "w") as f:
        f.write("\n".join(parts))
    print(f"  {p}")
    return "\n".join(parts)


def nice_ticks(vmax, n=5):
    if vmax <= 0:
        return [0]
    raw = vmax / n
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            step = m * mag
            break
    ticks = []
    v = 0
    while v <= vmax * 1.0001:
        ticks.append(v)
        v += step
    if ticks[-1] < vmax:
        ticks.append(ticks[-1] + step)
    return ticks


# =============================================================== grafico 1
def plot1():
    cid = "fig1-overhead-per-livello"
    W, H = 720, 380
    L, R, T, B = 78, 24, 78, 74
    b1 = collections.defaultdict(list)
    for r in ROWS:
        if r["block"] == "block1":
            b1[int(r["trace_level"])].append(r)
    base = st.median([F(r, "hi_slack_median_us") for r in b1[0]])
    vals = []
    for lvl in sorted(b1):
        sl = st.median([F(r, "hi_slack_median_us") for r in b1[lvl]])
        vals.append((lvl, base - sl))
    labels = {0: "0\nnessuno", 1: "1\nmain+thread", 2: "2\n+phase", 3: "3\n+phase_loop"}
    quart = ["q1", "q2", "q3", "q4"]

    vmax = max(v for _, v in vals)
    ticks = nice_ticks(vmax)
    top = ticks[-1]
    ph, pw = H - T - B, W - L - R
    y = lambda v: T + ph - (v / top) * ph

    s = svg_open(cid, W, H,
                 "Costo dell'instrumentazione, per giro del task critico",
                 "Blocco 1 — HI da solo, BatchSpanProcessor, AlwaysOn. Mediana su 20 ripetizioni, misurato sullo slack.")
    for t in ticks:
        s.append(f'<line class="grid" x1="{L}" y1="{y(t):.1f}" x2="{W-R}" y2="{y(t):.1f}"/>')
        s.append(f'<text class="t3" x="{L-10}" y="{y(t)+4:.1f}" text-anchor="end">{t:.0f}</text>')
    s.append(f'<text class="t3" x="16" y="{T-14}">µs per giro</text>')
    s.append(f'<line class="axis" x1="{L}" y1="{T+ph}" x2="{W-R}" y2="{T+ph}"/>')

    n = len(vals)
    slot = pw / n
    bw = min(88, slot - 26)          # >=2px di superficie fra barre adiacenti
    for i, (lvl, v) in enumerate(vals):
        cx = L + slot * (i + .5)
        x0 = cx - bw / 2
        h = (v / top) * ph
        s.append(f'<path d="{bar_top_rounded(x0, y(v), bw, h)}" fill="var(--{quart[i]})"/>')
        s.append(f'<text class="val" x="{cx:.1f}" y="{y(v)-9:.1f}" text-anchor="middle">'
                 f'{"—" if v == 0 else f"+{v:.0f} µs"}</text>')
        for j, ln in enumerate(labels[lvl].split("\n")):
            cls = "t" if j == 0 else "t3"
            s.append(f'<text class="{cls}" x="{cx:.1f}" y="{T+ph+22+j*16:.1f}" '
                     f'text-anchor="middle">{esc(ln)}</text>')
    s.append(f'<text class="t3" x="{W/2}" y="{H-12}" text-anchor="middle">'
             f'RTAPP_TRACE_LEVEL — 0 deadline miss a ogni livello, su ~160000 giri</text>')
    return write(cid, s)


# =============================================================== grafico 2
def plot2():
    cid = "fig2-campionamento-binario"
    W, H = 720, 400
    L, R, T, B = 78, 24, 82, 82
    g = collections.defaultdict(list)
    for r in ROWS:
        if r["block"] == "block2":
            g[(int(r["sampler_type"]), float(r["sampler_ratio"]))].append(I(r, "spans_exported_total"))
    order = sorted(g, key=lambda k: (k[0] != 2, k[1]))
    names = {2: "AlwaysOff", 0: "AlwaysOn"}

    top = 20
    ph, pw = H - T - B, W - L - R
    y = lambda v: T + ph - (v / top) * ph
    s = svg_open(cid, W, H,
                 "Span esportati per esecuzione: sempre 17 oppure 0, mai una via di mezzo",
                 "Blocco 2 — un punto per esecuzione, 25 per cella.")
    for t in (0, 5, 10, 15, 17, 20):
        dash = ' stroke-dasharray="3 3"' if t == 17 else ""
        s.append(f'<line class="grid" x1="{L}" y1="{y(t):.1f}" x2="{W-R}" y2="{y(t):.1f}"{dash}/>')
        s.append(f'<text class="t3" x="{L-10}" y="{y(t)+4:.1f}" text-anchor="end">{t}</text>')
    s.append(f'<text class="t3" x="16" y="{T-14}">span esportati</text>')
    s.append(f'<text class="t3" x="{W-R-4}" y="{y(17)-8:.1f}" text-anchor="end">'
             f'esecuzione campionata = 17 span (2 + 5 thread × 3)</text>')
    s.append(f'<line class="axis" x1="{L}" y1="{T+ph}" x2="{W-R}" y2="{T+ph}"/>')

    slot = pw / len(order)
    for i, k in enumerate(order):
        cx = L + slot * (i + .5)
        cnt = g[k]
        n = len(cnt); k17 = sum(1 for c in cnt if c == 17)
        # punti sparpagliati in orizzontale, deterministico
        for j, c in enumerate(cnt):
            same = [jj for jj, cc in enumerate(cnt) if cc == c]
            pos = same.index(j); m = len(same)
            dx = (pos - (m - 1) / 2) * min(6.0, 64.0 / max(m, 1))
            s.append(f'<circle cx="{cx+dx:.1f}" cy="{y(c):.1f}" r="4.5" fill="var(--s1)" '
                     f'fill-opacity="0.75" stroke="var(--surface)" stroke-width="1.5"/>')
        lab = names.get(k[0], f"ratio {k[1]:g}")
        s.append(f'<text class="t" x="{cx:.1f}" y="{T+ph+24:.1f}" text-anchor="middle">{esc(lab)}</text>')
        s.append(f'<text class="t3" x="{cx:.1f}" y="{T+ph+41:.1f}" text-anchor="middle">'
                 f'{k17}/{n} campionati</text>')
    s.append(f'<text class="t3" x="{W/2}" y="{H-12}" text-anchor="middle">'
             f'150 esecuzioni, 0 valori intermedi: il sampler decide sul trace_id, condiviso da tutti i thread</text>')
    return write(cid, s)


# =============================================================== grafico 3
def plot3():
    cid = "fig3-batch-vs-simple-costo"
    W, H = 720, 400
    L, R, T, B = 78, 24, 82, 86
    g = collections.defaultdict(list)
    for r in ROWS:
        if r["block"] == "block3":
            g[(int(r["n_lo"]), int(r["trace_level"]), int(r["processor_type"]))].append(r)
    loads = (0, 1, 4, 8)
    data = []
    for n in loads:
        base = st.median([F(r, "hi_slack_median_us") for r in g[(n, 0, 0)]])
        bt = base - st.median([F(r, "hi_slack_median_us") for r in g[(n, 3, 0)]])
        si = base - st.median([F(r, "hi_slack_median_us") for r in g[(n, 3, 1)]])
        data.append((n, bt, si))

    top = 450
    ph, pw = H - T - B, W - L - R
    y = lambda v: T + ph - (v / top) * ph
    s = svg_open(cid, W, H,
                 "Costo per giro sul task critico: Batch contro Simple",
                 "Blocco 3 — trace_level 3, Zipkin senza collector. Mediana su 15 ripetizioni.")
    for t in nice_ticks(top, 5):
        s.append(f'<line class="grid" x1="{L}" y1="{y(t):.1f}" x2="{W-R}" y2="{y(t):.1f}"/>')
        s.append(f'<text class="t3" x="{L-10}" y="{y(t)+4:.1f}" text-anchor="end">{t:.0f}</text>')
    s.append(f'<text class="t3" x="16" y="{T-14}">µs per giro</text>')
    s.append(f'<line class="axis" x1="{L}" y1="{T+ph}" x2="{W-R}" y2="{T+ph}"/>')

    slot = pw / len(loads)
    bw = 46
    for i, (n, bt, si) in enumerate(data):
        cx = L + slot * (i + .5)
        for j, (v, col, nm) in enumerate(((bt, "s1", "Batch"), (si, "s2", "Simple"))):
            x0 = cx - bw - 1 + j * (bw + 2)      # 2px di superficie fra le due barre
            h = (v / top) * ph
            s.append(f'<path d="{bar_top_rounded(x0, y(v), bw, h)}" fill="var(--{col})"/>')
            s.append(f'<text class="val" x="{x0+bw/2:.1f}" y="{y(v)-9:.1f}" '
                     f'text-anchor="middle">{v:.0f}</text>')
        s.append(f'<text class="t" x="{cx:.1f}" y="{T+ph+24:.1f}" text-anchor="middle">{n}</text>')
    s.append(f'<text class="t2" x="{W/2}" y="{T+ph+46:.1f}" text-anchor="middle">'
             f'task best-effort di disturbo (n_lo)</text>')
    # legenda
    lx = L + 6
    for col, nm in (("s1", "BatchSpanProcessor"), ("s2", "SimpleSpanProcessor")):
        s.append(f'<rect x="{lx}" y="{T-30}" width="11" height="11" rx="2" fill="var(--{col})"/>')
        s.append(f'<text class="t2" x="{lx+16}" y="{T-20}">{esc(nm)}</text>')
        lx += 150
    s.append(f'<text class="t3" x="{W/2}" y="{H-12}" text-anchor="middle">'
             f'Il costo del Batch non cresce col carico: spedisce ogni 5 s a prescindere dal volume</text>')
    return write(cid, s)


# =============================================================== grafico 4
def plot4():
    cid = "fig4-deadline-miss"
    W, H = 720, 380
    L, R, T, B = 78, 24, 82, 92
    g = collections.defaultdict(list)
    for r in ROWS:
        if r["block"] == "block3":
            g[(int(r["n_lo"]), int(r["trace_level"]), int(r["processor_type"]))].append(r)
    loads = (0, 1, 4, 8)
    rows = []
    for n in loads:
        miss = {}
        for key, nm in (((n, 0, 0), "ctl"), ((n, 3, 0), "batch"), ((n, 3, 1), "simple")):
            miss[nm] = sum(I(r, "hi_deadline_miss_count") for r in g[key])
        worst = min(F(r, "hi_slack_min_us") for r in g[(n, 3, 1)])
        rows.append((n, miss, worst))

    top = 45
    ph, pw = H - T - B, W - L - R
    y = lambda v: T + ph - (v / top) * ph
    s = svg_open(cid, W, H,
                 "Scadenze mancate dal task critico: solo con il SimpleSpanProcessor",
                 "Blocco 3 — conteggi SOMMATI sulle 15 ripetizioni. Controllo e Batch: zero ovunque.")
    for t in (0, 10, 20, 30, 40):
        s.append(f'<line class="grid" x1="{L}" y1="{y(t):.1f}" x2="{W-R}" y2="{y(t):.1f}"/>')
        s.append(f'<text class="t3" x="{L-10}" y="{y(t)+4:.1f}" text-anchor="end">{t}</text>')
    s.append(f'<text class="t3" x="16" y="{T-14}">scadenze mancate</text>')
    s.append(f'<line class="axis" x1="{L}" y1="{T+ph}" x2="{W-R}" y2="{T+ph}"/>')

    slot = pw / len(loads)
    bw = 62
    for i, (n, miss, worst) in enumerate(rows):
        cx = L + slot * (i + .5)
        v = miss["simple"]
        if v:
            h = (v / top) * ph
            s.append(f'<path d="{bar_top_rounded(cx-bw/2, y(v), bw, h)}" fill="var(--crit)"/>')
            s.append(f'<text class="val" x="{cx:.1f}" y="{y(v)-9:.1f}" text-anchor="middle">{v}</text>')
            s.append(f'<text class="t3" x="{cx:.1f}" y="{T+ph+42:.1f}" text-anchor="middle">'
                     f'sforo max {abs(worst)/1000:.0f} ms</text>')
        else:
            s.append(f'<text class="t3" x="{cx:.1f}" y="{y(0)-10:.1f}" text-anchor="middle">0</text>')
        s.append(f'<text class="t" x="{cx:.1f}" y="{T+ph+24:.1f}" text-anchor="middle">{n}</text>')
    s.append(f'<text class="t2" x="{W/2}" y="{H-30}" text-anchor="middle">'
             f'task best-effort di disturbo (n_lo)</text>')
    s.append(f'<rect x="{L+6}" y="{T-30}" width="11" height="11" rx="2" fill="var(--crit)"/>')
    s.append(f'<text class="t2" x="{L+22}" y="{T-20}">SimpleSpanProcessor — violazione di scadenza</text>')
    s.append(f'<text class="t3" x="{W/2}" y="{H-12}" text-anchor="middle">'
             f'51 scadenze mancate in tutta la campagna di 410 esecuzioni, tutte in queste tre celle</text>')
    return write(cid, s)


# =============================================================== grafico 5
def plot5():
    cid = "fig5-bimodalita-controllo"
    W, H = 720, 380
    L, R, T, B = 78, 24, 82, 86
    g = collections.defaultdict(list)
    for r in ROWS:
        if r["block"] == "block3" and int(r["trace_level"]) == 0:
            g[int(r["n_lo"])].append(F(r, "hi_period_jitter_std_us"))
    loads = (0, 1, 4, 8)
    top = 25
    ph, pw = H - T - B, W - L - R
    y = lambda v: T + ph - (min(v, top) / top) * ph
    s = svg_open(cid, W, H,
                 "Il jitter del task critico e' bimodale a carico basso, e il carico lo stabilizza",
                 "Blocco 3, celle senza tracing — un punto per esecuzione, 15 per carico.")
    for t in (0, 5, 6, 10, 15, 20, 25):
        if t == 6:
            s.append(f'<line class="grid" x1="{L}" y1="{y(t):.1f}" x2="{W-R}" y2="{y(t):.1f}" '
                     f'stroke-dasharray="4 4"/>')
            s.append(f'<text class="t3" x="{W-R-4}" y="{y(t)-6:.1f}" text-anchor="end">'
                     f'soglia fra le due mode</text>')
            continue
        s.append(f'<line class="grid" x1="{L}" y1="{y(t):.1f}" x2="{W-R}" y2="{y(t):.1f}"/>')
        s.append(f'<text class="t3" x="{L-10}" y="{y(t)+4:.1f}" text-anchor="end">{t}</text>')
    s.append(f'<text class="t3" x="16" y="{T-14}">jitter di periodo (µs)</text>')
    s.append(f'<line class="axis" x1="{L}" y1="{T+ph}" x2="{W-R}" y2="{T+ph}"/>')

    slot = pw / len(loads)
    for i, n in enumerate(loads):
        cx = L + slot * (i + .5)
        v = g[n]
        buckets = collections.defaultdict(list)
        for x in v:
            buckets[round(x)].append(x)
        for b, xs in buckets.items():
            for j, x in enumerate(xs):
                dx = (j - (len(xs) - 1) / 2) * 11
                s.append(f'<circle cx="{cx+dx:.1f}" cy="{y(x):.1f}" r="4.5" fill="var(--s1)" '
                         f'fill-opacity="0.8" stroke="var(--surface)" stroke-width="1.5"/>')
        lo = sum(1 for x in v if x < 6)
        s.append(f'<text class="t" x="{cx:.1f}" y="{T+ph+24:.1f}" text-anchor="middle">{n}</text>')
        s.append(f'<text class="t3" x="{cx:.1f}" y="{T+ph+41:.1f}" text-anchor="middle">'
                 f'{lo}/{len(v)} nel modo basso</text>')
    s.append(f'<text class="t2" x="{W/2}" y="{T+ph+62:.1f}" text-anchor="middle">'
             f'task best-effort di disturbo (n_lo)</text>')
    s.append(f'<text class="t3" x="{W/2}" y="{H-12}" text-anchor="middle">'
             f'La mediana di una distribuzione a due mode cade nel vuoto fra le due: qui non riassume nulla</text>')
    return write(cid, s)


if __name__ == "__main__":
    print("grafici generati:")
    for fn in (plot1, plot2, plot3, plot4, plot5):
        fn()
