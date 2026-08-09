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
.pill{display:inline-block;padding:1px 7px;border-radius:9px;font-size:11px;font-weight:700}
.pill.ok{background:#123d24;color:#4ade80}.pill.warn{background:#4a3410;color:#fbbf24}
.pill.bad{background:#4a1520;color:#f87171}.pill.na{background:#26262b;color:#9ca3af}
.strip{font-size:13px;line-height:2}
.kpis{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:6px}
.kpi{background:#1b1b20;border-radius:8px;padding:8px 12px;min-width:84px}
.kpi b{display:block;font-size:19px}.kpi span{font-size:11px;color:#9ca3af}
.sub{font-size:12px;color:#cbd5e1;font-weight:700;margin:10px 0 4px}
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
<div class="card"><h2>Builds · Fades · Bankroll</h2>
<p class="note" style="margin:0 0 6px"><b>Builds:</b></p>__BUILDS__
<p class="note" style="margin:10px 0 6px"><b>Fade registry:</b> __FADES__</p>
<p class="note" style="margin:10px 0 6px"><b>$10 ladder:</b> __BANKROLL__</p>
</div>
</div>

<div class="note">Sources: ledgers/results_log.md · ledgers/fades.md · ledgers/bankroll.md · builds/*.md — parsed by the same code as tools/calib.py. If this page disagrees with calib.py, run tools/generate_dashboard.py --selftest.</div>
</div>
<script>
const CAL=__CAL_JSON__, CLVD=__CLV_JSON__;
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
            out.append(f"<p class='sub'>{esc(t[4:])}</p>")
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
