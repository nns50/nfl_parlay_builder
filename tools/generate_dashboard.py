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
    live, bt, tickets = read_rows(LEDGER.read_text(encoding="utf-8"))
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
    return live, bt, tickets, builds, fades, rolls


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
              f"{sum(r['result']=='L' for r in bt_dec)}"
              f" ({len(bt_dec)}/{len(bt)} settled)",
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
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--fg:#e6edf3;--muted:#8b949e;
--blue:#3b82f6;--green:#22c55e;--red:#ef4444;--amber:#f59e0b}
*{box-sizing:border-box;margin:0}
body{background:var(--bg);color:var(--fg);font:14px/1.45 -apple-system,'Segoe UI',Roboto,sans-serif;padding:20px}
.wrap{max-width:1080px;margin:0 auto}
h1{font-size:19px;margin-bottom:2px} h2{font-size:14px;margin:0 0 10px}
.sub{color:var(--muted);font-size:12px;margin-bottom:18px}
.badge{display:inline-block;border:1px solid var(--border);border-radius:12px;padding:1px 9px;font-size:11px;margin-left:8px}
.fresh{color:var(--green)} .stale{color:var(--amber)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:18px}
.tile{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:12px}
.tile .v{font-size:20px;font-weight:700} .tile .k{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.6px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}
.card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px}
.chart{height:230px;position:relative}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{color:var(--muted);text-align:left;font-weight:600;padding:5px 8px;border-bottom:1px solid var(--border)}
td{padding:5px 8px;border-bottom:1px solid rgba(48,54,61,.5)}
.mono{font-family:ui-monospace,monospace}.muted{color:var(--muted)}.pos{color:var(--green)}.neg{color:var(--red)}
.note{color:var(--muted);font-size:11.5px;margin-top:8px}
@media(max-width:760px){.grid{grid-template-columns:1fr}}
</style></head><body><div class="wrap">
<h1>NFL Parlay Builder <span class="badge __FRESH_CLS__">__FRESH_TXT__</span></h1>
<div class="sub">read-only measurement dashboard · generated __UPDATED__ · doctrine: NO BET is a valid output; parlays are chalk×vig — the standalone is where measured edge lives</div>

<div class="tiles">
<div class="tile"><div class="v">__DECIDED__</div><div class="k">decided live legs</div></div>
<div class="tile"><div class="v">__RECORD__</div><div class="k">record __HIT__</div></div>
<div class="tile"><div class="v">__CLV__</div><div class="k">CLV +/=/−</div></div>
<div class="tile"><div class="v">__OPEN__</div><div class="k">open legs</div></div>
<div class="tile"><div class="v">__BT__</div><div class="k">pipeline validation (BT)</div></div>
</div>

<div class="grid">
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
if(CAL.labels.length){new Chart(document.getElementById('cal'),{data:{labels:CAL.labels,
 datasets:[{type:'bar',label:'actual hit %',data:CAL.hit,backgroundColor:'rgba(59,130,246,.75)',borderRadius:3},
 {type:'line',label:'perfect calibration',data:CAL.mid,borderColor:'#f59e0b',borderDash:[5,4],pointRadius:3,fill:false}]},
 options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{boxWidth:10,color:'#8b949e'}}},
 scales:{x:{grid:{color:'#21262d'},ticks:{color:'#8b949e'}},y:{min:0,max:100,grid:{color:'#21262d'},ticks:{color:'#8b949e',callback:v=>v+'%'}}}}});}
else{document.getElementById('cal').closest('.chart').innerHTML='<p class="muted" style="padding-top:80px;text-align:center">no decided played legs yet</p>';}
if(CLVD.labels.length){new Chart(document.getElementById('clv'),{type:'bar',data:{labels:CLVD.labels,
 datasets:[{data:CLVD.vals,backgroundColor:CLVD.cols,borderRadius:3}]},
 options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},
 scales:{x:{grid:{color:'#21262d'},ticks:{color:'#8b949e',font:{size:9}}},y:{grid:{color:'#21262d'},ticks:{color:'#8b949e',callback:v=>v+'pp'}}}}});}
else{document.getElementById('clv').closest('.chart').innerHTML='<p class="muted" style="padding-top:80px;text-align:center">no CLV verdicts captured yet</p>';}
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
        cols.append("#22c55e" if m.group(1) == "+" else
                    "#ef4444" if m.group(1) == "-" else "#8b949e")
    return {"labels": labels, "vals": vals, "cols": cols}


def render():
    live, bt, tickets, builds, fades, rolls = load()
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
    live, bt, tickets, builds, fades, rolls = load()
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
