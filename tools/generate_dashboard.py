#!/usr/bin/env python3
"""generate_dashboard.py — ledgers → docs/index.html (read-only analytics dashboard).

PORTED PATTERN (MLB): a static page regenerated after each run, deployed by Pages on
merge to main. IT ONLY READS FILES THAT ARE COMMITTED (ledgers/, builds/) — never the
SQLite store, because the Pages workflow regenerates it in CI where data/context.db
does not exist. Parsing goes through calib.read_rows — ONE ledger parser repo-wide, so
the dashboard can never drift from the measurement layer (the MLB parser-guard lesson,
solved structurally instead of by reconciliation checks... which exist anyway: --selftest).

USAGE
    tools/generate_dashboard.py              # write docs/index.html
    tools/generate_dashboard.py --selftest   # parser invariants + calib reconciliation
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from calib import read_rows  # noqa: E402  — the single ledger parser

REPO = Path(HERE).parent
DOCS = REPO / "docs"
LEDGER = REPO / "ledgers" / "results_log.md"


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def load():
    live, bt, tickets, _orphans = read_rows(LEDGER.read_text(encoding="utf-8"))
    builds = []
    for p in sorted((REPO / "builds").glob("*-W*.md")):
        head = p.read_text(encoding="utf-8").split("\n", 1)[0].lstrip("# ")
        builds.append({"file": p.name, "title": head})
    fades = []
    fp = REPO / "ledgers" / "fades.md"
    if fp.exists():
        for ln in fp.read_text(encoding="utf-8").split("\n"):
            m = re.match(r"^\|\s*([A-E]\d+)\s*\|", ln)
            if m:
                cells = [c.strip() for c in ln.strip("|").split("|")]
                fades.append({"id": cells[0], "name": cells[1][:40],
                              "status": cells[-1][:60]})
    rolls = []
    bp = REPO / "ledgers" / "bankroll.md"
    if bp.exists():
        for ln in bp.read_text(encoding="utf-8").split("\n"):
            c = [x.strip() for x in ln.strip("|").split("|")]
            if len(c) >= 8 and re.match(r"^\d+$", c[0] or ""):
                rolls.append(c)
    health = []
    hp = REPO / "ledgers" / "run_health.jsonl"
    if hp.exists():
        for ln in hp.read_text(encoding="utf-8").split("\n"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                health.append(json.loads(ln))
            except json.JSONDecodeError:
                continue          # one corrupt line must not blind the strip
    return live, bt, tickets, builds, fades, rolls, health


def latest_run_section():
    """Newest '## Run' block of the newest build file → (title, body_lines). Pure-ish."""
    files = sorted((REPO / "builds").glob("*-W*.md"))
    if not files:
        return None, []
    txt = files[-1].read_text(encoding="utf-8").split("\n")
    starts = [i for i, l in enumerate(txt) if l.startswith("## Run")]
    if not starts:
        return files[-1].name, []
    return txt[starts[-1]].lstrip("# ").strip(), txt[starts[-1] + 1:]


def health_strip(health):
    """Last run's gates + channels. This is the panel that would have caught run 6's
    silent Slack skip on day one instead of a day later."""
    if not health:
        return ("<p class='note'>no runs recorded yet — the next scheduled run writes "
                "the first line via tools/run_health.py</p>")
    r = health[-1]
    def dot(v):
        cls = {"ok": "ok", "SKIP": "warn", "FAILED": "bad"}.get(v, "na")
        return f"<span class='pill {cls}'>{esc(str(v))}</span>"
    st_ok = r.get("selftest_green")
    st = (f"<span class='pill {'ok' if st_ok else 'bad'}'>"
          f"{esc(r.get('selftest') or '?')}</span>")
    fold = esc((r.get("fold") or "—")[:8])
    return (
        f"<p class='note' style='margin:0 0 8px'>last run <b>{esc(r.get('run_type') or '?')}"
        f"</b> at {esc(r.get('at') or '?')} · verdict {esc(r.get('verdict') or '—')}</p>"
        f"<div class='strip'>selftest {st} · fold <code>{fold}</code> · email {dot(r.get('email'))}"
        f" · slack {dot(r.get('slack'))} · push {dot(r.get('push'))}"
        f" · credits <b>{esc(str(r.get('credits') or '—'))}</b></div>")


def health_timeline(health, limit=12):
    if not health:
        return "<p class='note'>none yet</p>"
    rows = []
    for r in reversed(health[-limit:]):
        rows.append(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td><code>{}</code></td>"
            "<td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                esc((r.get("at") or "")[:16]), esc(r.get("run_type") or "?"),
                esc(r.get("selftest") or "?"), esc((r.get("fold") or "—")[:8]),
                esc(str(r.get("email") or "—")), esc(str(r.get("slack") or "—")),
                esc(str(r.get("push") or "—")), esc(str(r.get("credits") or "—")),
                esc((r.get("verdict") or "")[:26])))
    return ("<table><thead><tr><th>when</th><th>type</th><th>selftest</th><th>fold</th>"
            "<th>email</th><th>slack</th><th>push</th><th>credits</th><th>verdict</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


def pipeline_panel(live, bt):
    """An empty ledger should read as EARLY, not BROKEN. Says what is pending and when
    it can possibly settle."""
    decided = sum(r["result"] in ("W", "L", "Push") for r in live)
    played = sum(1 for r in live if r["played"])
    staked = sum(1 for r in live if r.get("stake") is not None)
    first = "—"
    try:
        import sqlite3
        db = os.environ.get("NFL_DB", str(REPO / "data" / "context.db"))
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        row = con.execute("SELECT MIN(kickoff_utc) FROM games WHERE game_type='REG' "
                          "AND kickoff_utc > strftime('%Y-%m-%dT%H:%M:%SZ','now')"
                          ).fetchone()
        first = (row[0] or "—")[:10] if row else "—"
    except Exception:
        pass
    items = [("legs logged", len(live)), ("decided", decided), ("played", played),
             ("with a real stake", staked), ("backtest rows", len(bt))]
    cells = "".join(f"<div class='kpi'><b>{v}</b><span>{esc(k)}</span></div>"
                    for k, v in items)
    note = ("Calibration needs decided legs. nflverse carries no preseason games, so "
            f"nothing can settle before the first REG kickoff ({esc(first)}).")
    return f"<div class='kpis'>{cells}</div><p class='note'>{note}</p>"


def summarize(live, bt):
    dec = [r for r in live if r["result"] in ("W", "L", "Push")]
    w = sum(r["result"] == "W" for r in dec)
    l = sum(r["result"] == "L" for r in dec)
    clv = [r["clv"].replace("−", "-").strip() for r in live if r["clv"].strip() not in ("—", "-", "")]
    open_n = sum(1 for r in live if r["result"] is None)
    bt_dec = [r for r in bt if r["result"] in ("W", "L", "Push")]
    return {
        "live_rows": len(live), "decided": len(dec), "w": w, "l": l,
        "hit": (w / (w + l) * 100) if (w + l) else None,
        "clv_pos": sum(1 for c in clv if c.startswith("+")),
        "clv_neg": sum(1 for c in clv if c.startswith("-")),
        "clv_flat": sum(1 for c in clv if c.startswith("=")),
        "open": open_n,
        "bt": f"{sum(r['result']=='W' for r in bt_dec)}-"
              f"{sum(r['result']=='L' for r in bt_dec)}",
        "bt_detail": f"{len(bt_dec)}/{len(bt)} settled",
    }


def calib_bands(live):
    from collections import defaultdict
    b = defaultdict(lambda: [0, 0])
    for r in live:
        if r["played"] and not r["starred"] and r["truep"] is not None \
                and r["result"] in ("W", "L"):
            lo = int(r["truep"] // 5 * 5)
            b[lo][0] += 1
            b[lo][1] += r["result"] == "W"
    out = []
    for lo in sorted(b):
        n, w = b[lo]
        out.append({"band": f"{lo}-{lo+4}", "n": n, "hit": w / n * 100 if n else 0,
                    "mid": lo + 2.5})
    return out


def leg_table(rows, limit=25):
    tr = []
    for r in list(reversed(rows))[:limit]:
        res = r["result"] or "TBD"
        cls = {"W": "pos", "L": "neg", "Push": ""}.get(res, "muted")
        tr.append(f"<tr><td>{esc(r['week'])}</td><td>{esc(r['leg'][:52])}</td>"
                  f"<td>{esc(r['type'])}</td><td class='mono'>{esc(r['truep'] or '—')}"
                  f"</td><td class='mono'>{esc(r['clv'] or '—')}</td>"
                  f"<td class='{cls}'>{esc(res)}</td></tr>")
    return "\n".join(tr) or "<tr><td colspan=6 class='muted'>no rows yet</td></tr>"


HTML = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>NFL Parlay Builder — dashboard</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🏈</text></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@500;600&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
/* Night-game gridiron theme. Chart status pair #5ad46b/#c9432f is CVD-validated
   (deutan ΔE 19.5); bar direction doubles as the non-color encoding. Gold #e9a416
   is a deliberate lone-accent series (contrast vs surface passes). */
:root{--bg:#0b1108;--card:#141f0f;--panel:#0d1409;--border:#2b3d20;--fg:#e9eede;
--muted:#98a88a;--chalk:#e8e4d8;--gold:#e9a416;--leather:#a86b32;
--pos:#5ad46b;--neg:#ef6a55}
*{box-sizing:border-box;margin:0}
body{background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,'Segoe UI',Roboto,sans-serif;padding:20px}
.wrap{max-width:1080px;margin:0 auto}
.hero{position:relative;overflow:hidden;border:1px solid var(--border);border-radius:12px;
padding:20px 24px 16px;margin-bottom:16px;
background:repeating-linear-gradient(90deg,transparent 0 88px,rgba(232,228,216,.055) 88px 90px),
repeating-linear-gradient(90deg,rgba(255,255,255,.024) 0 45px,transparent 45px 90px),
linear-gradient(180deg,#17230e,#0f190b)}
.hero::after{content:"50";position:absolute;right:20px;bottom:-16px;font-family:'Oswald',sans-serif;
font-size:72px;font-weight:600;color:rgba(232,228,216,.06);letter-spacing:2px;pointer-events:none}
h1{font-family:'Oswald',-apple-system,sans-serif;font-weight:600;font-size:23px;
text-transform:uppercase;letter-spacing:1.5px;margin-bottom:3px}
h2{font-family:'Oswald',-apple-system,sans-serif;font-weight:500;font-size:13.5px;
text-transform:uppercase;letter-spacing:1px;color:var(--chalk);margin:0 0 10px;
border-left:3px solid var(--gold);padding-left:9px}
.sub{color:var(--muted);font-size:12px}
.badge{display:inline-block;border:1px solid rgba(233,164,22,.45);border-radius:12px;
padding:1px 10px;font-size:11px;margin-left:10px;font-family:-apple-system,'Segoe UI',sans-serif;
text-transform:none;letter-spacing:0;vertical-align:3px}
.fresh{color:var(--gold)} .stale{color:var(--leather)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:16px}
.tile{background:linear-gradient(180deg,var(--panel),#0a1007);border:1px solid var(--border);
border-top:2px solid var(--gold);border-radius:10px;padding:11px 14px 10px}
.tile .v{font-family:'Oswald',sans-serif;font-weight:600;font-size:25px;color:var(--gold);
letter-spacing:.5px;font-variant-numeric:tabular-nums}
.tile .k{color:var(--muted);font-size:10.5px;text-transform:uppercase;letter-spacing:1px;margin-top:2px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px 16px}
.chart{height:230px;position:relative}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{color:var(--muted);text-align:left;font-weight:600;font-size:11px;text-transform:uppercase;
letter-spacing:.7px;padding:5px 8px;border-bottom:1px solid var(--border)}
td{padding:5px 8px;border-bottom:1px solid rgba(43,61,32,.55)}
tr:hover td{background:rgba(233,164,22,.05)}
.mono{font-family:ui-monospace,monospace}.muted{color:var(--muted)}
.pos{color:var(--pos);font-weight:600}.neg{color:var(--neg);font-weight:600}
.note{color:var(--muted);font-size:11.5px;margin-top:8px}
@media(max-width:760px){.grid{grid-template-columns:1fr}.hero::after{display:none}}
/* ONE tile system. .kpi previously invented a second one — flex-with-min-width
   (tiles size to content, so they never line up in columns) plus hardcoded grey
   #1b1b20/#9ca3af that clashed with the gridiron palette. It now reuses .tiles'
   grid and .tile's visual language, so every tile on the page aligns. */
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));
 gap:10px;margin-bottom:10px}
.kpi{background:linear-gradient(180deg,var(--panel),#0a1007);
 border:1px solid var(--border);border-radius:10px;padding:10px 12px;text-align:center}
.kpi b{display:block;font-family:'Oswald',sans-serif;font-weight:600;font-size:22px;
 line-height:1.15;color:var(--gold)}
.kpi span{display:block;color:var(--muted);font-size:10.5px;text-transform:uppercase;
 letter-spacing:1px;margin-top:2px}
/* pills: theme tokens, not ad-hoc hexes; vertical-align keeps them on the text baseline */
.pill{display:inline-block;padding:1px 8px;border-radius:9px;font-size:11px;
 font-weight:700;vertical-align:baseline}
.pill.ok{background:rgba(90,212,107,.16);color:var(--pos)}
.pill.warn{background:rgba(233,164,22,.16);color:var(--gold)}
.pill.bad{background:rgba(239,106,85,.16);color:var(--neg)}
.pill.na{background:rgba(152,168,138,.14);color:var(--muted)}
.strip{font-size:13px;line-height:1.9;color:var(--chalk)}
.strip b{color:var(--fg)}
.strip code{color:var(--muted)}
/* board section heading. NOT '.sub' — that class already styles the header subtitle,
   and redefining it silently restyled the page header (bold/uppercase instead of small
   muted). Never reuse an existing class name for a new purpose. */
.bsub{font-size:12px;color:var(--chalk);font-weight:700;margin:12px 0 4px;
 text-transform:uppercase;letter-spacing:.6px}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.scroll table{min-width:100%;white-space:nowrap}
</style></head><body><div class="wrap">
<header class="hero"><h1>🏈 NFL Parlay Builder <span class="badge __FRESH_CLS__">__FRESH_TXT__</span></h1>
<div class="sub">read-only measurement dashboard · generated __UPDATED__ · doctrine: NO BET is a valid output; parlays are chalk×vig — the standalone is where measured edge lives</div></header>

<div class="tiles">
<div class="tile"><div class="v">__DECIDED__</div><div class="k">decided live legs</div></div>
<div class="tile"><div class="v">__RECORD__</div><div class="k">record __HIT__</div></div>
<div class="tile"><div class="v">__CLV__</div><div class="k">CLV +/=/−</div></div>
<div class="tile"><div class="v">__OPEN__</div><div class="k">open legs</div></div>
<div class="tile"><div class="v">__BT__</div><div class="k">pipeline validation (BT) · __BT_DETAIL__</div></div>
</div>

<div class="grid">
<div class="card"><h2>Run health — last scheduled run</h2>__HEALTH__</div>
<div class="card"><h2>Pipeline</h2>__PIPELINE__</div>
<div class="card"><h2>This week's board (newest run)</h2>__WEEKBOARD__</div>
<div class="card"><h2>Calibration (played legs vs TrueP band)</h2><div class="chart"><canvas id="cal"></canvas></div>
<div class="note">bars = actual hit%; line = perfect calibration. Bands need n≥20-30 before they mean anything.</div></div>
<div class="card"><h2>Streaks &amp; the $10 ladder</h2>__STREAKS__</div>
<div class="card"><h2>Correlation coverage (parlay floors depend on these)</h2>__CORR__</div>
<div class="card"><h2>Cumulative P/L (real stakes)</h2><div class="chart"><canvas id="pl"></canvas></div>
<p class="note">Only legs carrying a stake from ledgers/played.md. An assumed flat-1u curve is exactly the fake number that file replaces.</p></div>
<div class="card"><h2>Bankroll ladder ($10 rollover)</h2><div class="chart"><canvas id="br"></canvas></div></div>
<div class="card"><h2>Hit rate by edge bucket</h2>__EDGEBUCKETS__
<p class="note">The +2pp gate's own scoreboard: the ≥2pp buckets must out-hit the &lt;2pp ones over a real sample, or the gate is not earning its keep.</p></div>
<div class="card"><h2>Bet-type breakdown</h2>__TYPES__</div>
<div class="card"><h2>CLV vs results</h2>__CLVRES__</div>
<div class="card"><h2>CLV per leg (closing no-vig − bet no-vig)</h2><div class="chart"><canvas id="clv"></canvas></div>
<div class="note">the primary scoreboard at small samples. `=` dead-band ±0.5pp. Blank cells = capture holes (a measurement leak, not a shrug).</div></div>
</div>

<div class="card" style="margin-bottom:14px"><h2>Recent legs (live ledger, newest first)</h2>
<table><tr><th>Week</th><th>Leg</th><th>Type</th><th>TrueP</th><th>CLV</th><th>Result</th></tr>
__LEGS__</table></div>

<div class="grid">
<div class="card"><h2>Backtest / pipeline-validation rows (BT — never in live stats)</h2>
<table><tr><th>Week</th><th>Leg</th><th>Type</th><th>TrueP</th><th>CLV</th><th>Result</th></tr>
__BT_LEGS__</table></div>
<div class="card" style="margin-bottom:14px"><h2>Run timeline</h2><div class="scroll">__TIMELINE__</div></div>
<div class="card" style="margin-bottom:14px"><h2>Parlay tickets</h2>__TICKETS__</div>
<div class="card" style="margin-bottom:14px"><h2>Active fades &amp; their records</h2>__FADETABLE__</div>
<div class="card"><h2>Builds · Fades · Bankroll</h2>
<p class="note" style="margin:0 0 6px"><b>Builds:</b></p>__BUILDS__
<p class="note" style="margin:10px 0 6px"><b>Fade registry:</b> __FADES__</p>
<p class="note" style="margin:10px 0 6px"><b>$10 ladder:</b> __BANKROLL__</p>
</div>
</div>

<div class="note">Sources: ledgers/results_log.md · ledgers/fades.md · ledgers/bankroll.md · builds/*.md — parsed by the same code as tools/calib.py. If this page disagrees with calib.py, run tools/generate_dashboard.py --selftest.</div>
</div>
<script>
const CAL=__CAL_JSON__, CLVD=__CLV_JSON__, PLD=__PL_JSON__, BRD=__BR_JSON__;
const GRID='rgba(232,228,216,.07)', TICK='#98a88a';
if(typeof Chart==='undefined'){document.querySelectorAll('.chart').forEach(
 c=>c.innerHTML='<p class="muted" style="padding-top:80px;text-align:center">charts unavailable — Chart.js CDN unreachable</p>');}
else{
if(CAL.labels.length){new Chart(document.getElementById('cal'),{data:{labels:CAL.labels,
 datasets:[{type:'bar',label:'actual hit %',data:CAL.hit,backgroundColor:'rgba(233,164,22,.85)',borderRadius:4},
 {type:'line',label:'perfect calibration',data:CAL.mid,borderColor:'#e8e4d8',borderDash:[6,5],pointRadius:3,fill:false}]},
 options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{boxWidth:10,color:TICK}}},
 scales:{x:{grid:{color:GRID},ticks:{color:TICK}},y:{min:0,max:100,grid:{color:GRID},ticks:{color:TICK,callback:v=>v+'%'}}}}});}
else{document.getElementById('cal').closest('.chart').innerHTML='<p class="muted" style="padding-top:80px;text-align:center">no decided played legs yet</p>';}
if(CLVD.labels.length){new Chart(document.getElementById('clv'),{type:'bar',data:{labels:CLVD.labels,
 datasets:[{data:CLVD.vals,backgroundColor:CLVD.cols,borderRadius:4}]},
 options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},
 scales:{x:{grid:{color:GRID},ticks:{color:TICK,font:{size:9}}},y:{grid:{color:GRID},ticks:{color:TICK,callback:v=>v+'pp'}}}}});}
else{document.getElementById('clv').closest('.chart').innerHTML='<p class="muted" style="padding-top:80px;text-align:center">no CLV verdicts captured yet</p>';}
function line(id,d,label,col,empty){const el=document.getElementById(id);if(!el)return;
 if(d.labels.length){new Chart(el,{type:'line',data:{labels:d.labels,datasets:[{label:label,data:d.vals,
  borderColor:col,backgroundColor:col,tension:.25,pointRadius:2,fill:false}]},
  options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{boxWidth:10,color:TICK}}},
  scales:{x:{grid:{color:GRID},ticks:{color:TICK,font:{size:9}}},y:{grid:{color:GRID},ticks:{color:TICK}}}}});}
 else{el.closest('.chart').innerHTML='<p class="muted" style="padding-top:80px;text-align:center">'+empty+'</p>';}}
line('pl',PLD,'cumulative P/L','#e9a416','no staked, decided legs yet — log bets in ledgers/played.md');
line('br',BRD,'balance','#4ade80','no rolls logged yet');
}
</script></body></html>
"""


def clv_chart(rows):
    labels, vals, cols = [], [], []
    for r in rows:
        c = (r["clv"] or "").replace("−", "-").strip()
        m = re.match(r"([+=\-])\s*(\d+)%cl", c)
        if not m or r["implp"] is None:
            continue
        diff = float(m.group(2)) - r["implp"]
        labels.append(r["leg"][:18])
        vals.append(round(diff, 1))
        cols.append("#5ad46b" if m.group(1) == "+" else
                    "#c9432f" if m.group(1) == "-" else "#7e8f70")
    return {"labels": labels, "vals": vals, "cols": cols}


def _dec(american):
    """American price → decimal. Shared by every P/L computation on this page."""
    try:
        a = float(str(american).replace("−", "-").replace("+", "").strip())
    except (TypeError, ValueError):
        return None
    if a == 0:
        return None
    return 1 + (a / 100.0 if a > 0 else 100.0 / -a)


def edge_buckets(live):
    """Hit rate by EDGE bucket — ported from the MLB dashboard. This is the panel that
    actually tests the +2pp gate: if the ≥2pp buckets do not out-hit the <2pp ones over a
    real sample, the gate is not earning its keep."""
    rows = [r for r in live if r["result"] in ("W", "L") and r["edge"] is not None]
    bins = [("< 0pp", -99, 0), ("0–2pp", 0, 2), ("2–4pp", 2, 4),
            ("4–6pp", 4, 6), ("6pp+", 6, 99)]
    out = []
    for label, lo, hi in bins:
        legs = [r for r in rows if lo <= r["edge"] < hi]
        w = sum(r["result"] == "W" for r in legs)
        out.append({"label": label, "n": len(legs),
                    "hit": round(w / len(legs) * 100) if legs else None, "w": w,
                    "l": len(legs) - w})
    return out


def type_breakdown(live):
    """Record by bet type (calib.py §2 rendered). Shows WHICH markets earn."""
    agg = {}
    for r in live:
        if r["result"] not in ("W", "L", "Push"):
            continue
        a = agg.setdefault(r["type"] or "?", {"w": 0, "l": 0, "p": 0})
        a["w" if r["result"] == "W" else "l" if r["result"] == "L" else "p"] += 1
    out = []
    for t, a in sorted(agg.items(), key=lambda kv: -(kv[1]["w"] + kv[1]["l"])):
        d = a["w"] + a["l"]
        out.append({"type": t, "w": a["w"], "l": a["l"], "p": a["p"],
                    "hit": round(a["w"] / d * 100) if d else None})
    return out


def pl_curve(live):
    """Cumulative REAL-STAKE P/L. Only legs carrying a stake count — an assumed flat
    1u curve is the fake number ledgers/played.md exists to replace."""
    rows = [r for r in live if r["played"] and r["stake"] is not None
            and r["result"] in ("W", "L", "Push")]
    rows.sort(key=lambda r: (r["week"], r["leg_id"]))
    labels, vals, run = [], [], 0.0
    for r in rows:
        d = _dec(r["price"])
        if d is None:
            continue
        run += (r["stake"] * (d - 1) if r["result"] == "W"
                else -r["stake"] if r["result"] == "L" else 0.0)
        labels.append(r["week"])
        vals.append(round(run, 2))
    return {"labels": labels, "vals": vals}


# bankroll row: | Attempt | Week | Roll | Bal before | Bet | TrueP | Result | Bal after | Note |
BR = {"attempt": 0, "week": 1, "roll": 2, "before": 3, "bet": 4, "truep": 5,
      "result": 6, "after": 7}


def bankroll_curve(rolls):
    """The $10 rollover ladder as a curve. Reads the Balance-after COLUMN explicitly —
    scanning for 'the last number in the row' would happily pick up a stray figure in
    the Note cell."""
    labels, vals = [], []
    for c in rolls:
        if len(c) <= BR["after"]:
            continue
        m = re.search(r"(\d+(?:\.\d+)?)", (c[BR["after"]] or "").replace("$", ""))
        if m:
            labels.append(f"A{c[BR['attempt']]}·R{c[BR['roll']]}")
            vals.append(float(m.group(1)))
    return {"labels": labels, "vals": vals}


def streaks(live):
    """Current / longest runs over DECIDED legs, oldest→newest. Push breaks nothing —
    it is not a loss, so it is skipped rather than ending a run.
    → {'current': signed int, 'best_w': int, 'best_l': int, 'last': 'W'|'L'|None}"""
    chron = [r for r in live if r["result"] in ("W", "L")]
    chron.sort(key=lambda r: (r["week"], r["leg_id"]))
    if not chron:
        return {"current": 0, "best_w": 0, "best_l": 0, "last": None}
    last = chron[-1]["result"]
    cur = 0
    for r in reversed(chron):
        if r["result"] != last:
            break
        cur += 1
    best_w = best_l = rw = rl = 0
    for r in chron:
        rw = rw + 1 if r["result"] == "W" else 0
        rl = rl + 1 if r["result"] == "L" else 0
        best_w, best_l = max(best_w, rw), max(best_l, rl)
    return {"current": cur if last == "W" else -cur,
            "best_w": best_w, "best_l": best_l, "last": last}


def ladder_state(rolls):
    """The $10 ladder's live state. NOT decorative: doctrine says 4 CONSECUTIVE WINS →
    STOP & WITHDRAW, and any loss restarts at $10. That rule currently depends on a human
    remembering, so compute it and let the UI shout."""
    st = {"attempt": None, "wins": 0, "balance": 10.0, "stop": False, "rolls": len(rolls)}
    if not rolls:
        return st
    cur_attempt = rolls[-1][BR["attempt"]]
    st["attempt"] = cur_attempt
    for c in rolls:
        if len(c) <= BR["after"] or c[BR["attempt"]] != cur_attempt:
            continue
        res = (c[BR["result"]] or "").upper()
        m = re.search(r"(\d+(?:\.\d+)?)", (c[BR["after"]] or "").replace("$", ""))
        if m:
            st["balance"] = float(m.group(1))
        if res.startswith("W"):
            st["wins"] += 1
        elif res.startswith("L"):
            st["wins"] = 0            # a loss ends the attempt; next roll restarts at $10
    st["stop"] = st["wins"] >= 4
    return st


def streak_panel(live, rolls):
    s, ld = streaks(live), ladder_state(rolls)
    if s["last"] is None:
        legs = "<p class='note'>no decided legs yet — streaks begin at Week 1</p>"
    else:
        cur = s["current"]
        cls = "ok" if cur > 0 else "bad"
        legs = (f"<div class='strip'>current <span class='pill {cls}'>"
                f"{'W' if cur > 0 else 'L'}{abs(cur)}</span>"
                f" · longest win run <b>{s['best_w']}</b>"
                f" · longest losing run <b>{s['best_l']}</b></div>")
    bar = (f"<div class='strip'>ladder attempt <b>{esc(str(ld['attempt'] or '—'))}</b>"
           f" · consecutive wins <span class='pill "
           f"{'ok' if ld['wins'] else 'na'}'>{ld['wins']}/4</span>"
           f" · balance <b>${ld['balance']:.2f}</b></div>")
    if ld["stop"]:
        bar += ("<p class='note' style='color:#4ade80;font-weight:700'>"
                "★ 4 CONSECUTIVE WINS — doctrine says STOP &amp; WITHDRAW; "
                "the next roll restarts at $10.</p>")
    return legs + bar


def clv_vs_result(live):
    """Does a positive close predict a win? The CLV thesis, testable once results land."""
    cells = {"+": [0, 0], "=": [0, 0], "-": [0, 0]}
    for r in live:
        if r["result"] not in ("W", "L"):
            continue
        # clv_capture writes a UNICODE minus (U+2212) for negative verdicts; calib.py
        # normalises it and so must this, or every negative-CLV leg silently vanishes
        # from the panel. Caught by selftest before it ever rendered a wrong number.
        m = re.match(r"([+=\-])", (r["clv"] or "").replace("−", "-").strip())
        if not m:
            continue
        cells[m.group(1)][0 if r["result"] == "W" else 1] += 1
    out = []
    for k, name in (("+", "beat the close"), ("=", "flat"), ("-", "lost to the close")):
        w, l = cells[k]
        out.append({"k": k, "name": name, "w": w, "l": l,
                    "hit": round(w / (w + l) * 100) if (w + l) else None})
    return out


def _table(headers, rows, empty):
    if not rows:
        return f"<p class='note'>{esc(empty)}</p>"
    h = "".join(f"<th>{esc(x)}</th>" for x in headers)
    b = "".join("<tr>" + "".join(f"<td>{esc(str(c))}</td>" for c in r) + "</tr>"
                for r in rows)
    return (f"<div class='scroll'><table><thead><tr>{h}</tr></thead>"
            f"<tbody>{b}</tbody></table></div>")


def corr_coverage():
    """Which correlation pairs are MEASURED vs still guessed. rho drives the joint prob
    of every same-game stack, so a guessed row is an unpriced risk sitting inside the
    ticket floor — and the 2026-08-09 re-seed showed structural guesses running up to 2x
    off IN BOTH DIRECTIONS, including two SIGN errors."""
    fp = REPO / "config" / "corr_matrix.csv"
    if not fp.exists():
        return [], {"measured": 0, "structural": 0}
    rows, tally = [], {"measured": 0, "structural": 0}
    import csv as _csv
    for r in _csv.DictReader(fp.read_text(encoding="utf-8").splitlines()):
        basis = (r.get("basis") or "").strip()
        meas = basis.startswith("backtest")
        tally["measured" if meas else "structural"] += 1
        note = (r.get("note") or "")
        m = re.search(r"n=(\d+)", note)
        rows.append({"a": r["family_a"], "b": r["family_b"], "same": r["same_team"],
                     "rho": r["rho"], "meas": meas, "n": m.group(1) if m else "—",
                     "basis": basis})
    rows.sort(key=lambda x: (x["meas"], -abs(float(x["rho"]))), reverse=True)
    return rows, tally


def week_board(title, body):
    """The newest run section, rendered readable on a phone: keep tables + bold lines,
    drop the rest. The point is checking the board without digging through email."""
    if not title:
        return "<p class='note'>no build file yet</p>"
    out, tbl = [f"<p class='note' style='margin:0 0 8px'><b>{esc(title)}</b></p>"], []
    for ln in body[:220]:
        t = ln.rstrip()
        if t.startswith("## "):
            break                                  # next run section — stop
        if t.startswith("|"):
            tbl.append([c.strip() for c in t.strip("|").split("|")])
            continue
        if tbl:
            out.append(_tbl(tbl)); tbl = []
        if t.startswith("### "):
            out.append(f"<p class='bsub'>{esc(t[4:])}</p>")
        elif t.startswith("**") or t.startswith("- **"):
            out.append(f"<p class='note'>{esc(t.replace('**',''))[:220]}</p>")
    if tbl:
        out.append(_tbl(tbl))
    return "".join(out)


def _tbl(rows):
    rows = [r for r in rows if not all(set(c) <= set("-: ") for c in r)]
    if not rows:
        return ""
    head = "".join(f"<th>{esc(c)}</th>" for c in rows[0])
    body = "".join("<tr>" + "".join(f"<td>{esc(c)[:60]}</td>" for c in r) + "</tr>"
                   for r in rows[1:])
    return f"<div class='scroll'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def render():
    live, bt, tickets, builds, fades, rolls, health = load()
    s = summarize(live, bt)
    bands = calib_bands(live)
    weeks = sorted({r["week"] for r in live + bt})
    fresh_txt, fresh_cls = "● live", "fresh"
    html = (HTML
            .replace("__UPDATED__", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ"))
            .replace("__FRESH_TXT__", fresh_txt).replace("__FRESH_CLS__", fresh_cls)
            .replace("__DECIDED__", str(s["decided"]))
            .replace("__RECORD__", f"{s['w']}-{s['l']}")
            .replace("__HIT__", f"({s['hit']:.0f}%)" if s["hit"] is not None else "")
            .replace("__CLV__", f"{s['clv_pos']}/{s['clv_flat']}/{s['clv_neg']}")
            .replace("__OPEN__", str(s["open"]))
            .replace("__BT__", esc(s["bt"]))
            .replace("__BT_DETAIL__", esc(s["bt_detail"]))
            .replace("__CORR__", (lambda rc: (
                f"<div class='kpis'><div class='kpi'><b>{rc[1]['measured']}</b>"
                f"<span>measured</span></div><div class='kpi'><b>{rc[1]['structural']}"
                f"</b><span>still guessed</span></div></div>"
                + _table(["family A", "family B", "same team", "ρ", "basis", "n"],
                         [[r["a"], r["b"], r["same"], r["rho"],
                           "✓ measured" if r["meas"] else "guess", r["n"]]
                          for r in rc[0]],
                         "no matrix rows")
                + "<p class='note'>ρ drives the joint probability of every same-game "
                  "stack, so a guessed row is unpriced risk inside the ticket floor. "
                  "Re-measure with <code>tools/corr_backtest.py --seasons … --reseed"
                  "</code>.</p>"))(corr_coverage()))
            .replace("__STREAKS__", streak_panel(live, rolls))
            .replace("__EDGEBUCKETS__", _table(
                ["edge bucket", "n", "W-L", "hit %"],
                [[b["label"], b["n"], f"{b['w']}-{b['l']}",
                  f"{b['hit']}%" if b["hit"] is not None else "—"]
                 for b in edge_buckets(live)],
                "no decided legs yet — this panel tests whether the +2pp gate earns its keep"))
            .replace("__TYPES__", _table(
                ["bet type", "W", "L", "Push", "hit %"],
                [[t["type"], t["w"], t["l"], t["p"],
                  f"{t['hit']}%" if t["hit"] is not None else "—"]
                 for t in type_breakdown(live)],
                "no decided legs yet"))
            .replace("__CLVRES__", _table(
                ["closing line", "W", "L", "hit %"],
                [[c["name"], c["w"], c["l"],
                  f"{c['hit']}%" if c["hit"] is not None else "—"]
                 for c in clv_vs_result(live)],
                "needs decided legs WITH captured CLV — the thesis is that beating the "
                "close predicts winning"))
            .replace("__FADETABLE__", _table(
                ["id", "entry", "status"],
                [[f["id"], f["name"], f["status"]] for f in fades],
                "empty — fades must be EARNED by the NFL ledger; MLB entries do not port"))
            .replace("__TICKETS__", _table(
                ["week", "ticket", "stake", "return", "P/L", "result"],
                [[c[1][:10], c[2][:44], c[4], c[5], c[6], c[7]] for c in tickets
                 if len(c) >= 8],
                "no parlay tickets logged yet"))
            .replace("__PL_JSON__", json.dumps(pl_curve(live)))
            .replace("__BR_JSON__", json.dumps(bankroll_curve(rolls)))
            .replace("__HEALTH__", health_strip(health))
            .replace("__TIMELINE__", health_timeline(health))
            .replace("__PIPELINE__", pipeline_panel(live, bt))
            .replace("__WEEKBOARD__", week_board(*latest_run_section()))
            .replace("__LEGS__", leg_table(live))
            .replace("__BT_LEGS__", leg_table(bt))
            .replace("__BUILDS__", "".join(
                f"<p class='note' style='margin:2px 0'>{esc(b['file'])} — {esc(b['title'][:70])}</p>"
                for b in builds) or "<p class='note'>none yet</p>")
            .replace("__FADES__", f"{len(fades)} entries" if fades
                     else "empty (entries must be earned by the NFL ledger)")
            .replace("__BANKROLL__", f"{len(rolls)} rolls logged" if rolls
                     else "no rolls yet — starts with the first live week")
            .replace("__CAL_JSON__", json.dumps({
                "labels": [b["band"] for b in bands],
                "hit": [round(b["hit"]) for b in bands],
                "mid": [b["mid"] for b in bands]}))
            .replace("__CLV_JSON__", json.dumps(clv_chart(live + bt))))
    return html


def _calib_truth():
    """Run calib.py and read back ITS numbers. Ported from the MLB dashboard, where the
    lesson was that a dashboard which merely agrees with ITSELF can still disagree with
    the source of truth — and the page is what the owner actually looks at. calib.py is
    the authority; if these drift, the page is wrong."""
    import subprocess
    try:
        out = subprocess.run([sys.executable, str(REPO / "tools" / "calib.py")],
                             capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return {}
    t = {}
    m = re.search(r"live rows:\s*(\d+)", out)
    if m:
        t["live"] = int(m.group(1))
    m = re.search(r"BT validation rows:\s*(\d+)", out)
    if m:
        t["bt"] = int(m.group(1))
    m = re.search(r"legs\s+\d+\s+\d+-\d+.*?P/L\s+([+-][\d.]+)", out)
    if m:
        t["pl"] = float(m.group(1))
    if "PARSER GUARD" in out:
        t["orphans"] = True
    return t


def selftest():
    live, bt, tickets, builds, fades, rolls, health = load()
    checks = [
        ("ledger parses ≥2 live rows", len(live) >= 2),
        ("ledger parses ≥7 BT rows", len(bt) >= 7),
        ("BT never leaks into live", all(r["bucket"] != "BT" for r in live)),
        ("builds dir parses ≥1 file", len(builds) >= 1),
        ("render produces a page > 4KB with both canvases",
         len(render()) > 4096 and "id=\"cal\"" in render()),
        ("summary reconciles with raw rows",
         summarize(live, bt)["decided"]
         == sum(r["result"] in ("W", "L", "Push") for r in live)),
    ]
    # ── reconciliation with calib.py (the source of truth), ported from MLB ──
    truth = _calib_truth()
    if truth:
        checks.append(("live-row count reconciles with calib.py",
                       truth.get("live") == len(live)))
        checks.append(("BT-row count reconciles with calib.py",
                       truth.get("bt") == len(bt)))
        checks.append(("calib.py reports no orphaned rows", not truth.get("orphans")))
        if "pl" in truth:
            page_pl = pl_curve(live)["vals"]
            checks.append(("cumulative P/L reconciles with calib.py §3b",
                           abs((page_pl[-1] if page_pl else 0.0) - truth["pl"]) < 0.01))
    else:
        checks.append(("calib.py reachable for reconciliation", False))

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(f"  {'✓' if ok else '✗'} {n}")
    print(f"── dashboard self-test: {'ALL PASSED' if not bad else f'{len(bad)} FAILED'}")
    return 0 if not bad else 1


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(render(), encoding="utf-8")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    print(f"wrote {DOCS / 'index.html'}")


if __name__ == "__main__":
    main()
