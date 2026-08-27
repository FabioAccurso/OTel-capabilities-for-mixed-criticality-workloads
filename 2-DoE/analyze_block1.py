import glob, statistics as st, os
def per_run(path):
    rows=[]
    with open(path) as f:
        for i,l in enumerate(f):
            p=l.split()
            if len(p)<11 or not p[0].isdigit(): continue
            rows.append([int(x) for x in (p[2],p[3],p[7],p[10])])  # run, period, slack, wu_lat
    rows=rows[1:]                      # scarta il transitorio di avvio (task 0.5)
    run=[r[0] for r in rows]; per=[r[1] for r in rows]
    slack=[r[2] for r in rows]; wu=[r[3] for r in rows]
    return dict(n=len(rows), run_med=st.median(run), run_max=max(run),
                per_med=st.median(per), per_std=st.pstdev(per),
                miss=100*sum(1 for s in slack if s<0)/len(slack),
                wu_med=st.median(wu), wu_max=max(wu))
def q(v,p): 
    v=sorted(v); k=(len(v)-1)*p; f=int(k)
    return v[f] if f+1>=len(v) else v[f]+(v[f+1]-v[f])*(k-f)

print(f"{'liv':<4} {'run_med':>18} {'run_max':>14} {'per_std':>16} {'wu_med':>12} {'wu_max':>12} {'miss%':>7}")
print(f"{'':4} {'mediana [IQR]':>18} {'mediana':>14} {'mediana [IQR]':>16} {'med':>12} {'peggiore':>12}")
print("-"*90)
base={}
for t in (0,1,2,3):
    runs=[per_run(p) for p in sorted(glob.glob(f"2-DoE/block1/t{t}_*/run_*/rtapp-HI_task-0.log"))]
    g=lambda k:[r[k] for r in runs]
    rm=st.median(g('run_med')); ps=st.median(g('per_std'))
    if t==0: base=dict(rm=rm, ps=ps, rx=st.median(g('run_max')))
    print(f"{t:<4} {rm:8.0f} [{q(g('run_med'),.25):.0f}-{q(g('run_med'),.75):.0f}]"
          f" {st.median(g('run_max')):10.0f}    "
          f" {ps:6.1f} [{q(g('per_std'),.25):.1f}-{q(g('per_std'),.75):.1f}]"
          f" {st.median(g('wu_med')):11.0f} {max(g('wu_max')):11.0f}"
          f" {st.median(g('miss')):6.2f}")
print("-"*90)
print("delta rispetto al livello 0 (nessuna strumentazione):")
for t in (1,2,3):
    runs=[per_run(p) for p in sorted(glob.glob(f"2-DoE/block1/t{t}_*/run_*/rtapp-HI_task-0.log"))]
    g=lambda k:[r[k] for r in runs]
    print(f"  liv {t}: run_med {st.median(g('run_med'))-base['rm']:+6.0f} us "
          f"({100*(st.median(g('run_med'))-base['rm'])/base['rm']:+5.1f}%) | "
          f"run_max {st.median(g('run_max'))-base['rx']:+6.0f} us | "
          f"period_std {st.median(g('per_std'))-base['ps']:+6.1f} us "
          f"({100*(st.median(g('per_std'))-base['ps'])/base['ps']:+6.1f}%)")
