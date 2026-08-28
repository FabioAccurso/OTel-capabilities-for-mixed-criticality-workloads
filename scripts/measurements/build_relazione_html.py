import base64, os, html
ROOT = "/home/benny/Scrivania/OTel-capabilities-for-mixed-criticality-workloads"
FIG = os.path.join(ROOT, "2-DoE", "figures")

def img(name):
    with open(os.path.join(FIG, name), "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()

# (n, slug, titolo, domanda-indice, file, [(label, html)])
S = [
(1,"all-or-nothing","La decisione di campionamento è per-trace",
 "Il sampler sa distinguere HI da LO?","01_all_or_nothing.png",[
 ("Cosa mostra","<p>Ogni punto è uno dei 150 run del blocco 2. In ascissa il sampler configurato, in ordinata quanti span quel run ha effettivamente esportato. La banda rosa copre l'intera regione fra 1 e 16 span.</p>"),
 ("Come leggerlo","<p>I punti si dispongono su <strong>due sole righe</strong>: 0 span oppure 17. La banda rosa è vuota in tutte e sei le colonne.</p>"),
 ("Perché è significativo","<p>È la verifica sperimentale dell'ipotesi centrale del progetto, e il grafico più importante dell'elaborato. Se <code>TraceIdRatioBasedSampler</code> sapesse distinguere fra task — cioè se potesse tenere gli span del task critico e scartare quelli best-effort — esisterebbero run con un numero di span <strong>intermedio</strong>. Non ce n'è nemmeno uno su 150.</p><p>Il motivo è nel codice: ogni thread nasce con <code>span_opts.parent = main_span-&gt;GetContext()</code>, quindi tutti gli span di un'esecuzione condividono lo stesso <code>trace_id</code>, e il sampler decide in funzione del solo <code>trace_id</code>. La decisione è presa <strong>una volta per esecuzione</strong>, non per span. Quando un run è campionato escono sempre esattamente 1 span HI e 4 LO.</p>"),
 ("Cosa non dice","<p>Non dice che il sampler sia rotto: dice che opera alla granularità sbagliata per un contesto mixed-criticality. La figura 2 completa il quadro.</p>")]),
(2,"sampling-fraction","Il sampler rispetta la probabilità richiesta",
 "E la probabilità è quella giusta?","02_sampling_fraction.png",[
 ("Cosa mostra","<p>Frazione di run che hanno esportato qualcosa, contro il ratio richiesto. Barre d'errore: intervallo di confidenza al 95 % di Wilson su n=25. La diagonale tratteggiata è il comportamento atteso se la probabilità fosse rispettata.</p>"),
 ("Come leggerlo","<p>Tutti i punti cadono sulla diagonale entro il proprio intervallo di confidenza: 0.16 a fronte di 0.1, 0.44 di 0.3, 0.64 di 0.5, 0.80 di 0.7, più i due estremi esatti.</p>"),
 ("Perché è significativo","<p>Va letto <strong>insieme alla figura 1</strong>, e insieme le due dicono una cosa che nessuna delle due direbbe da sola: il meccanismo <em>funziona correttamente</em> — la probabilità è quella richiesta — ma si applica all'<strong>intera esecuzione</strong>. Impostare <code>ratio = 0.1</code> non significa «conserva il 10 % degli span»: significa «scarta tutto, task critico compreso, con probabilità del 90 %».</p>"),
 ("Conseguenza operativa","<p>A ratio 0.1, in 21 run su 25 non esiste <strong>alcuna</strong> traccia del task critico. In un sistema mixed-criticality è il comportamento peggiore possibile, ed è la motivazione empirica del Task 6.</p>")]),
(3,"overhead","Il costo lo decide il processor, non il tracing",
 "Quanto costa il monitoraggio?","03_overhead_processor.png",[
 ("Cosa mostra","<p>Costo per iterazione del task critico, misurato come differenza di <code>budget</code> (= <code>run + slack</code>) rispetto alla cella di controllo senza tracing, allo stesso carico. Pannello destro: stessa cosa con la scala espansa.</p>"),
 ("Come leggerlo","<p><strong>Batch</strong> resta piatto a 12-14 µs a ogni livello di carico. <strong>Simple</strong> sta a ~300 µs: circa 23 volte tanto, il 3 % del periodo di 10 ms e il <strong>15 % del lavoro utile</strong> di 2000 µs.</p>"),
 ("Perché è significativo","<p>Sposta la conclusione dell'elaborato: non è la <em>quantità</em> di telemetria a determinare il costo, ma <strong>come</strong> viene consegnata. Lo stesso <code>trace_level=3</code>, con lo stesso numero di span, costa 13 µs o 300 a seconda del solo processor.</p>"),
 ("Cautela sulla barra a n_lo=4","<p>Il valore 1303 è segnalato in figura perché <strong>non va letto come un costo maggiore a quel carico</strong>: quella cella è bimodale (8 ripetizioni intorno a 8688 µs di budget, 7 intorno a 9665) e la mediana cade sul gruppo basso. La non-monotonia rispetto a <code>n_lo=8</code> è quindi apparente. Il costo di Simple è ~300 µs; il secondo modo, che vale altri ~980 µs per iterazione, resta non spiegato.</p>")]),
(4,"export","Perché Simple costa 23 volte tanto",
 "Da dove viene quel costo?","04_export_attempts.png",[
 ("Cosa mostra","<p>Numero di tentativi di export per run, in scala logaritmica, contato dalle righe che l'exporter Zipkin lascia su <code>stderr</code>.</p>"),
 ("Come leggerlo","<p>Il controllo sta a zero. <strong>Batch</strong> cresce da 8 a ~230 al crescere del carico. <strong>Simple</strong> arriva a <strong>25 500</strong>: due ordini di grandezza sopra.</p>"),
 ("Perché è significativo","<p>È il <strong>meccanismo</strong> dietro la figura 3, non una sua ripetizione. <code>SimpleSpanProcessor::OnEnd</code> chiama <code>Export()</code> in modo <strong>sincrono, nel thread che ha appena chiuso lo span</strong>, sotto uno spin-lock condiviso fra tutti i thread; <code>BatchSpanProcessor</code> accoda e delega a un thread proprio. Il task critico quindi, con Simple, paga di persona una connessione HTTP per ogni span che chiude, e si contende lo spin-lock con i nove thread applicativi.</p>"),
 ("Un dettaglio che rende il risultato conservativo","<p>Nessun collector era in ascolto: gli export falliscono immediatamente con <code>ECONNREFUSED</code> su localhost. È il caso <strong>più favorevole</strong> a Simple. Con un collector reale, che accetta la connessione e risponde, il divario sarebbe maggiore — i valori misurati sono un limite inferiore.</p>")]),
(5,"slack","Dove il margine va sotto zero",
 "Il monitoraggio fa violare gli SLO?","05_slack_distribution.png",[
 ("Cosa mostra","<p>Distribuzione cumulativa empirica dello <code>slack</code> — il margine residuo prima della deadline — su tutte le ~29 800 iterazioni di HI per ciascun braccio, al carico massimo (<code>n_lo = 8</code>). Il pannello destro ingrandisce la coda sinistra.</p>"),
 ("Come leggerlo","<p>Controllo e Batch (grigio tratteggiato e blu, sovrapposti) salgono verticalmente intorno a 8000 µs e <strong>non toccano mai lo zero</strong>: ogni iterazione chiude con almeno 65 µs di margine. Simple ha una coda che attraversa la linea rossa dello zero.</p>"),
 ("Perché è significativo","<p>È l'unica figura che mostra il <em>margine</em>, non solo il conteggio dei fallimenti. Un conteggio di 9 miss su 29 544 iterazioni (0.03 %) può sembrare trascurabile; la curva mostra che la distribuzione di Simple è <strong>strutturalmente diversa</strong>, con una coda che si estende fino a −3631 µs. Il task critico non «occasionalmente sfora»: ha un profilo di rischio qualitativamente diverso, con iterazioni che sforano di oltre un terzo del periodo.</p><p>Mostra anche il rovescio: la separazione fra Batch e Simple è netta e non c'è sovrapposizione nella coda, quindi il risultato non dipende da come si sceglie una soglia.</p>")]),
(6,"abort","Il processo non rallenta: muore",
 "La telemetria è sicura?","06_abort_rate.png",[
 ("Cosa mostra","<p>Percentuale di run terminati con SIGABRT nel braccio Simple, in funzione del numero di thread applicativi.</p>"),
 ("Come leggerlo","<p>Con un solo thread nessun crash (0/15). Da due thread in su la probabilità sale rapidamente: 11/15, 14/15, e a nove thread <strong>15/15</strong>. Batch e controllo: zero abort su 120 run.</p>"),
 ("Perché è significativo","<p>È il risultato più netto dell'intera campagna, e cambia la natura del problema. Le figure 3 e 5 misurano una <em>degradazione</em>; questa mostra che una configurazione di telemetria <strong>termina il processo real-time</strong>.</p>"),
 ("La causa, verificata nel codice","<p>Un'interazione a tre:</p><ol><li><code>__shutdown()</code> di rt-app termina i thread con <code>pthread_cancel</code> (<code>rt-app.cpp:933</code>);</li><li>in glibc la cancellazione è implementata lanciando un'eccezione di <em>forced unwind</em> nel thread bersaglio, per far girare i distruttori;</li><li><code>SimpleSpanProcessor::OnEnd</code> è dichiarato <strong><code>noexcept</code></strong> (<code>simple_processor.h:60</code>), e un unwind che attraversa una funzione <code>noexcept</code> chiama <code>std::terminate()</code>.</li></ol><p>La dipendenza dal numero di thread è esattamente ciò che il meccanismo prevede: con Simple ogni thread passa gran parte del suo tempo dentro <code>OnEnd</code> (l'export sincrono della figura 4), quindi la probabilità che il <code>cancel</code> lo colpisca lì cresce col numero di thread; con Batch <code>OnEnd</code> accoda e ritorna, e la finestra è minuscola.</p>"),
 ("Nota metodologica","<p>L'abort avviene <strong>dopo</strong> che tutti i log sono stati scritti, quindi i dati dei run abortiti sono validi (perdono le ultime 20 iterazioni su 2000). È anche il motivo per cui è un problema insidioso: nulla nei dati segnala che qualcosa è andato storto.</p>")]),
(7,"metric","Perché la metrica ovvia porta a una conclusione falsa",
 "Le misure sono valide?","07_metric_artifact.png",[
 ("Cosa mostra","<p>Blocco 1, quattro livelli di tracing. In alto l'anatomia di un'iterazione; in basso a sinistra la colonna <code>run</code> che rt-app riporta nativamente; in basso a destra la metrica corretta.</p>"),
 ("Da dove viene il «budget», e perché l'ordinata è quella","<p>Il task critico usa un timer su <strong>griglia assoluta</strong>, quindi fra un'attivazione e la successiva passano esattamente <strong>10 000 µs</strong>, sempre, a ogni livello. Quei 10 000 µs si dividono in tre parti:</p><ul><li><strong><code>run</code></strong> — il tempo del busy-loop, l'unica cosa che rt-app cronometra esplicitamente;</li><li><strong><code>slack</code></strong> — il margine residuo. <code>rt-app.cpp:761-763</code> lo calcola come <code>t_next − t_now</code> <strong>dopo</strong> che il lavoro dell'iterazione è finito;</li><li><strong>il resto</strong> — <code>10 000 − run − slack</code>: tempo realmente trascorso dentro l'iterazione che <strong>non compare in nessuna delle due colonne</strong> (creazione e chiusura degli span, logging, gestione eventi).</li></ul><p>Il <strong>budget</strong> è <code>run + slack</code>, cioè la parte di iterazione che rt-app <em>misura</em>. Il resto è la parte che gli sfugge — ed è esattamente lì che vive l'overhead di OpenTelemetry, perché gli span nascono e muoiono fuori dalla finestra cronometrata da <code>run</code>.</p><p>Ne segue la lettura dell'ordinata in basso a destra:</p><pre class=\"eq\">overhead in più = (10 000 − budget) − (10 000 − budget del livello 0)\n                =  resto(livello) − resto(livello 0)</pre><p>cioè <strong>di quanto cresce la parte invisibile</strong> rispetto alla configurazione senza tracing. Più la barra è alta, più l'iterazione ha speso tempo in cose che non sono il lavoro utile.</p><p class=\"corr\"><strong>Nota.</strong> Nella prima versione di questa figura l'ordinata era <code>budget − budget(livello 0)</code>, quindi <strong>negativa</strong>: un costo maggiore appariva come una barra verso il basso, in contraddizione con la figura 3, dove il costo è positivo. È stata corretta — ora entrambe usano la stessa convenzione, barra alta = più costoso.</p>"),
 ("I numeri","<div class=\"tbl-scroll\"><table><thead><tr><th>trace_level</th><th><code>run</code></th><th><code>slack</code></th><th>budget</th><th>periodo reale</th><th>il resto</th></tr></thead><tbody><tr><td>0</td><td>1984</td><td>8005</td><td>9991</td><td>10 000</td><td><strong>9</strong></td></tr><tr><td>1</td><td>1954</td><td>8036</td><td>9991</td><td>10 000</td><td><strong>9</strong></td></tr><tr><td>2</td><td>1984</td><td>8006</td><td>9991</td><td>10 000</td><td><strong>9</strong></td></tr><tr><td>3</td><td>1999</td><td>7979</td><td>9977</td><td>10 000</td><td><strong>23</strong></td></tr></tbody></table></div><p>La riga del livello 1 è la più istruttiva: <code>run</code> <strong>scende</strong> di 30 µs rispetto al livello 0 (1954 contro 1984), ma <code>slack</code> <strong>sale</strong> di 31 (8036 contro 8005). I due si compensano quasi esattamente e il budget resta 9991, identico. Se quei 30 µs fossero stati lavoro reale risparmiato, l'iterazione avrebbe finito prima e lo slack sarebbe cresciuto <em>restando</em> cresciuto: invece il tempo è semplicemente stato contato altrove.</p><p>Solo il livello 3 sposta davvero il budget, da 9991 a 9977: il resto passa da 9 a 23 µs, quindi il tracing a granularità massima aggiunge <strong>14 µs per iterazione</strong> di lavoro che non compare in nessuna colonna nativa.</p>"),
 ("Perché è significativo","<p>È una figura sulla <strong>validità delle misure</strong>, non sul sistema sotto test, e giustifica la variabile di risposta usata in tutte le altre. Un overhead non può rendere il codice più veloce: il risultato in basso a sinistra è un artefatto di <strong>layout del binario</strong> — ogni livello è un eseguibile diverso, e l'allineamento del codice del busy-loop cambia — e vale ~30 µs, cioè <strong>più del segnale da misurare</strong>.</p><p>Lo stesso problema affligge la colonna <code>period</code> (<code>end − start</code> della stessa riga), che al livello 3 <em>si accorcia</em> di 15-24 µs proprio dove l'overhead cresce, per la stessa ragione.</p>"),
 ("Implicazione pratica","<p>Chi analizzasse questo DoE con le colonne native di rt-app concluderebbe che la strumentazione OTel <strong>migliora</strong> le prestazioni.</p>")]),
(8,"anomalous","L'ipotesi «è un calo di frequenza» è falsificata",
 "Il regime anomalo inquina i risultati?","08_anomalous_regime.png",[
 ("Cosa mostra","<p>Ogni punto è un run: in ascissa la frequenza effettiva misurata durante quel run tramite i contatori <code>APERF</code>/<code>MPERF</code>, in ordinata la durata mediana dell'iterazione. I due rombi rossi sono i run in regime anomalo; i rombi vuoti arancioni segnano dove sarebbero caduti <em>se</em> la causa fosse stata la frequenza.</p>"),
 ("Come leggerlo","<p>I due run anomali impiegano 2 e 3.3 volte il tempo normale per iterazione, ma stanno a <strong>2286 MHz</strong>, in mezzo a tutti gli altri. La banda arancione a ~700 MHz, dove l'ipotesi li collocherebbe, è vuota.</p>"),
 ("Perché è significativo","<p>Durante tutta la campagna era comparso un regime anomalo in cui il busy-loop rallenta di un fattore 2-3.7, in circa l'1.2 % dei run. L'ipotesi naturale era un calo di frequenza (il fattore 3.67 corrisponde esattamente a 2296/626 MHz) e non era verificabile, perché <code>mhz_med</code> viene letto <strong>dopo</strong> il run. La colonna <code>aperf_mhz</code> è stata aggiunta apposta, con le letture fuori dalla finestra di misura per non perturbare l'esperimento, e ha risposto alla prima occasione utile: <strong>il lavoro per iterazione cresce, i MHz no.</strong></p>"),
 ("Un secondo fatto, altrettanto rilevante","<p>I due run anomali cadono in celle diverse, e <strong>uno dei due è una cella di controllo senza alcun tracing</strong>. Il fenomeno quindi <strong>non dipende da OpenTelemetry</strong> e non inquina i confronti fra bracci: colpisce tutte le configurazioni allo stesso modo.</p>"),
 ("Cosa resta aperto","<p>Ipotesi residue: contesa SMT sul sibling <strong>cpu3</strong> — che sta dentro il cpuset isolato ma non è controllato, e su cui può finire il worker del <code>BatchSpanProcessor</code> — oppure pressione su cache/memoria. Si distinguono con i contatori IPC di <code>perf stat</code>: se il lavoro è lo stesso e i cicli aumentano, l'IPC crolla. <code>hwlatdetect</code> è già stato escluso (0 latenze su 435 s di campionamento) ed è comunque lo strumento sbagliato, perché rileva <em>buchi</em> temporali e non rallentamenti sostenuti.</p>")]),
]

nav = "\n".join(
  f'<a class="nav-card" href="#fig{n}"><span class="nav-n">{n:02d}</span>'
  f'<span class="nav-q">{html.escape(q)}</span><span class="nav-t">{html.escape(t)}</span></a>'
  for n, s, t, q, f, b in S)

secs = []
for n, slug, titolo, dom, fname, blocks in S:
    body = "\n".join(
        f'<div class="note"><h3>{html.escape(lab)}</h3>{txt}</div>' for lab, txt in blocks)
    secs.append(f"""
<section class="fig" id="fig{n}">
  <header class="fig-head">
    <div class="fig-eyebrow"><span class="fig-n">Figura {n:02d}</span><span class="fig-q">{html.escape(dom)}</span></div>
    <h2>{html.escape(titolo)}</h2>
    <p class="fig-file"><code>{fname}</code></p>
  </header>
  <figure class="plate"><img src="{img(fname)}" alt="{html.escape(titolo)}" loading="lazy"></figure>
  <div class="notes">{body}</div>
</section>""")

HTML = f"""<title>Telemetria sotto deadline</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&display=swap">
<style>
:root {{
  --ground:#fbfcfd; --surface:#eef2f6; --surface-2:#e4eaf1;
  --ink:#10171f; --ink-2:#31404f; --muted:#59636e; --line:#d5dde6;
  --accent:#1f6feb; --critical:#d1242f; --warn:#a97400; --plate:#ffffff;
  --shadow:0 1px 2px rgba(16,23,31,.06), 0 8px 24px rgba(16,23,31,.07);
  --display:"Archivo","Helvetica Neue",Arial,sans-serif;
  --body:"IBM Plex Sans","Segoe UI",system-ui,sans-serif;
  --mono:"IBM Plex Mono","SFMono-Regular",Consolas,monospace;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --ground:#0c1117; --surface:#151c24; --surface-2:#1c252f;
    --ink:#e3eaf2; --ink-2:#c2ced9; --muted:#8a96a3; --line:#26313d;
    --accent:#5aa2ff; --critical:#ff7b72; --warn:#d9a441; --plate:#f5f7f9;
    --shadow:0 1px 2px rgba(0,0,0,.5), 0 10px 30px rgba(0,0,0,.45);
  }}
}}
:root[data-theme="dark"] {{
  --ground:#0c1117; --surface:#151c24; --surface-2:#1c252f;
  --ink:#e3eaf2; --ink-2:#c2ced9; --muted:#8a96a3; --line:#26313d;
  --accent:#5aa2ff; --critical:#ff7b72; --warn:#d9a441; --plate:#f5f7f9;
  --shadow:0 1px 2px rgba(0,0,0,.5), 0 10px 30px rgba(0,0,0,.45);
}}
*{{box-sizing:border-box}}
body{{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:var(--body); font-size:16.5px; line-height:1.62;
  -webkit-font-smoothing:antialiased;
}}
.wrap{{max-width:1180px;margin:0 auto;padding:0 28px}}
.col{{max-width:68ch}}
a{{color:var(--accent)}}
:focus-visible{{outline:2px solid var(--accent);outline-offset:3px;border-radius:2px}}
code{{font-family:var(--mono);font-size:.86em;background:var(--surface);
  padding:.12em .38em;border-radius:3px;border:1px solid var(--line)}}

/* ---------- intestazione ---------- */
.masthead{{border-bottom:1px solid var(--line);background:var(--surface);}}
.masthead .wrap{{padding-top:52px;padding-bottom:40px}}
.kicker{{font-family:var(--mono);font-size:12px;letter-spacing:.14em;
  text-transform:uppercase;color:var(--muted);margin:0 0 18px}}
h1{{font-family:var(--display);font-weight:700;letter-spacing:-.022em;
  font-size:clamp(34px,5.4vw,58px);line-height:1.04;margin:0 0 18px;
  text-wrap:balance;max-width:20ch}}
.standfirst{{font-size:19px;line-height:1.55;color:var(--ink-2);margin:0;max-width:62ch}}
.meta{{display:flex;flex-wrap:wrap;gap:0;margin-top:34px;
  border-top:1px solid var(--line);padding-top:20px}}
.meta div{{padding-right:34px;margin-right:34px;border-right:1px solid var(--line)}}
.meta div:last-child{{border-right:0;margin-right:0;padding-right:0}}
.meta dt{{font-family:var(--mono);font-size:11px;letter-spacing:.11em;
  text-transform:uppercase;color:var(--muted);margin:0 0 5px}}
.meta dd{{margin:0;font-family:var(--display);font-weight:600;font-size:23px;
  font-variant-numeric:tabular-nums}}

/* ---------- indice ---------- */
.index{{padding:46px 0 8px}}
.index h2{{font-family:var(--mono);font-size:12px;letter-spacing:.14em;
  text-transform:uppercase;color:var(--muted);font-weight:500;margin:0 0 20px}}
.nav-grid{{display:grid;gap:1px;background:var(--line);border:1px solid var(--line);
  grid-template-columns:repeat(auto-fit,minmax(255px,1fr))}}
.nav-card{{background:var(--ground);padding:17px 19px 19px;text-decoration:none;
  color:inherit;display:flex;flex-direction:column;gap:5px;transition:background .15s}}
.nav-card:hover{{background:var(--surface)}}
.nav-n{{font-family:var(--mono);font-size:11px;color:var(--accent);letter-spacing:.08em}}
.nav-q{{font-size:13.5px;color:var(--muted);line-height:1.35}}
.nav-t{{font-family:var(--display);font-weight:600;font-size:16px;line-height:1.28;
  letter-spacing:-.01em}}

/* ---------- figure ---------- */
.fig{{padding:62px 0;border-top:1px solid var(--line)}}
.fig:first-of-type{{border-top:0}}
.fig-eyebrow{{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:12px}}
.fig-n{{font-family:var(--mono);font-size:11.5px;letter-spacing:.13em;text-transform:uppercase;
  color:var(--ground);background:var(--accent);padding:4px 9px;border-radius:2px}}
.fig-q{{font-family:var(--mono);font-size:12.5px;color:var(--muted);letter-spacing:.02em}}
.fig h2{{font-family:var(--display);font-weight:600;letter-spacing:-.018em;
  font-size:clamp(25px,3.1vw,35px);line-height:1.14;margin:0 0 8px;
  text-wrap:balance;max-width:24ch}}
.fig-file{{margin:0 0 30px;font-size:13px;color:var(--muted)}}
.fig-file code{{background:transparent;border:0;padding:0}}
.plate{{margin:0 0 38px;background:var(--plate);border:1px solid var(--line);
  border-radius:4px;box-shadow:var(--shadow);padding:14px;overflow-x:auto}}
.plate img{{display:block;width:100%;height:auto;min-width:620px}}
.notes{{display:grid;gap:26px;max-width:74ch}}
.note h3{{font-family:var(--mono);font-size:11.5px;letter-spacing:.12em;
  text-transform:uppercase;color:var(--muted);font-weight:600;margin:0 0 7px;
  padding-bottom:7px;border-bottom:1px solid var(--line)}}
.note p{{margin:0 0 11px}} .note p:last-child{{margin-bottom:0}}
.note ol,.note ul{{margin:0 0 11px;padding-left:1.25em}} .note li{{margin-bottom:6px}}
.note .tbl-scroll{{margin:4px 0 14px}}
pre.eq{{font-family:var(--mono);font-size:13px;line-height:1.6;background:var(--surface);
  border:1px solid var(--line);border-left:3px solid var(--accent);padding:12px 15px;
  margin:4px 0 12px;overflow-x:auto}}
p.corr{{background:var(--surface);border-left:3px solid var(--warn);padding:11px 15px;
  margin:14px 0 0;font-size:14.5px}}

/* ---------- chiusura ---------- */
.close{{background:var(--surface);border-top:1px solid var(--line);margin-top:20px}}
.close .wrap{{padding-top:54px;padding-bottom:64px}}
.close h2{{font-family:var(--display);font-weight:700;letter-spacing:-.02em;
  font-size:clamp(26px,3.4vw,36px);margin:0 0 26px;text-wrap:balance}}
.tbl-scroll{{overflow-x:auto;margin:0 0 30px;border:1px solid var(--line);background:var(--ground)}}
table{{border-collapse:collapse;width:100%;min-width:620px;font-size:15px}}
th,td{{text-align:left;padding:12px 16px;border-bottom:1px solid var(--line);vertical-align:top}}
thead th{{font-family:var(--mono);font-size:11px;letter-spacing:.11em;text-transform:uppercase;
  color:var(--muted);font-weight:600;background:var(--surface-2)}}
tbody tr:last-child td{{border-bottom:0}}
td:first-child{{font-family:var(--mono);color:var(--accent);white-space:nowrap;font-size:13px}}
.reco{{border-left:3px solid var(--accent);padding:2px 0 2px 20px;max-width:70ch}}
.reco p{{margin:0}}
.foot{{font-family:var(--mono);font-size:12px;color:var(--muted);
  border-top:1px solid var(--line);margin-top:38px;padding-top:20px;line-height:1.8}}
@media (max-width:640px){{
  body{{font-size:16px}} .wrap{{padding:0 18px}}
  .meta div{{padding-right:22px;margin-right:22px}}
  .fig{{padding:46px 0}}
}}
@media (prefers-reduced-motion:reduce){{*{{transition:none!important;animation:none!important}}}}
</style>

<header class="masthead"><div class="wrap">
  <p class="kicker">RTSIA · Progetto A5 · Analisi grafica del DoE</p>
  <h1>Telemetria sotto deadline</h1>
  <p class="standfirst">Otto grafici da una campagna di 485 run che misura cosa succede a un task
  real-time quando lo si strumenta con OpenTelemetry. Per ciascuno: cosa mostra, come si legge,
  e perché conta — comprese le due figure che servono a stabilire se le altre sei sono attendibili.</p>
  <div class="meta">
    <div><dt>Run totali</dt><dd>485</dd></div>
    <div><dt>Campagne</dt><dd>4</dd></div>
    <div><dt>Celle sperimentali</dt><dd>25</dd></div>
    <div><dt>Deadline perse</dt><dd>22</dd></div>
    <div><dt>Run abortiti</dt><dd>40</dd></div>
  </div>
</div></header>

<div class="wrap">
  <nav class="index">
    <h2>Le otto figure</h2>
    <div class="nav-grid">{nav}</div>
  </nav>
  {"".join(secs)}
</div>

<footer class="close"><div class="wrap">
  <h2>Cosa dicono le otto figure insieme</h2>
  <div class="tbl-scroll"><table>
    <thead><tr><th>Figure</th><th>Domanda</th><th>Risposta</th></tr></thead>
    <tbody>
      <tr><td>1, 2</td><td>OTel prioritizza i task critici?</td><td><strong>No.</strong> La decisione è per-trace: zero run parziali su 150</td></tr>
      <tr><td>3, 4</td><td>Quanto costa il monitoraggio?</td><td>13 µs per iterazione con Batch, ~300 con Simple; la causa è l'export sincrono</td></tr>
      <tr><td>5</td><td>Fa violare gli SLO temporali?</td><td>Solo con Simple, e con una coda fino a −3631 µs</td></tr>
      <tr><td>6</td><td>È sicuro?</td><td>Con Simple no: <strong>fino al 100 % dei run termina con SIGABRT</strong></td></tr>
      <tr><td>7</td><td>Le misure sono valide?</td><td>Solo con <code>run + slack</code>; le colonne native invertono il segno del risultato</td></tr>
      <tr><td>8</td><td>Il regime anomalo inquina i risultati?</td><td>No: è a frequenza nominale e compare anche <strong>senza</strong> tracing</td></tr>
    </tbody>
  </table></div>
  <div class="reco"><p>La raccomandazione che ne discende per un sistema mixed-criticality: usare
  <code>BatchSpanProcessor</code> — 13 µs, zero deadline perse, zero crash — <strong>non</strong> affidarsi
  al sampler per proteggere i task critici, e, se serve una prioritizzazione reale, un sampler che
  decida sul nome dello span anziché sul <code>trace_id</code>.</p></div>
  <p class="foot">Figure generate da <code>scripts/measurements/plot_doe.py</code> su <code>2-DoE/results.csv</code>.<br>
  Piattaforma: AMD Ryzen 7 3700U, kernel PREEMPT-RT 6.12.79-rt17, CPU isolate e frequenza fissata a 2295 MHz.<br>
  I valori assoluti sono legati a questa piattaforma; i confronti fra celle no.</p>
</div></footer>
"""
out = "/tmp/claude-1000/-home-benny-Scrivania-OTel-capabilities-for-mixed-criticality-workloads/7d936b1e-f6a7-47aa-a9cf-a14e6b8a3d14/scratchpad/art/relazione.html"
open(out, "w").write(HTML)
print(f"scritto {out}  ({os.path.getsize(out)/1048576:.2f} MB)")
