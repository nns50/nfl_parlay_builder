#!/usr/bin/env python3
"""pulse.py — recent-window exposure governor (ported principle, NFL keys).

PRINCIPLE (the MLB system's best late idea, kept verbatim):
    recency governs EXPOSURE every build; the n≥20-30 evidence bar governs BELIEF.
    You stop leaning on a dimension the moment it runs cold, without overfitting the
    doctrine to noise. Mechanical, pre-registered rules — auditable, not vibes.

RULES (thresholds ported; window re-scoped to NFL cadence)
    Window: decided live legs from the LAST 3 DISTINCT WEEK LABELS in the ledger;
    if fewer than 15 rows, the last 25 decided legs. Dimensions: market family (from
    leg_id — no text parsing), fav/dog for h2h, each [adj:] tag, TrueP band.
      COOL          n≥5, hit ≤ claimed−15pp → halve its adjustments; barred from
                                              Tier 1 and parlay-anchor this build
      SUSPEND       n≥6, hit ≤ claimed−25pp → no new legs in this dimension
      MARKET-SHADE  ≥4 CLV verdicts and −'s ≥ +'s+2 → TrueP = market no-vig for the
                                              dimension until CLV recovers
      GLOBAL SHRINK recent Brier(TrueP) worse than market over n≥10 → halve everything
      RE-WARM       automatic — ≥3 of the dimension's last 5 decided legs won
    Bucket=BT rows never enter the window.

USAGE
    tools/pulse.py [path/to/results_log.md]
"""
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from calib import parse_adj_tags, read_rows  # noqa: E402
from legs import parse_leg_id  # noqa: E402

REPO = os.path.dirname(HERE)
LEDGER = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].endswith(".md") else \
    os.environ.get("NFL_LEDGER", os.path.join(REPO, "ledgers", "results_log.md"))

WINDOW_WEEKS = 3
MIN_ROWS = 15
FALLBACK_ROWS = 25
COOL_N, COOL_GAP = 5, 15.0
SUSP_N, SUSP_GAP = 6, 25.0
CLV_MIN = 4


def market_family(leg_id_str, price_hint=None):
    leg = parse_leg_id(leg_id_str)
    if not leg:
        return "other"
    m = leg["market"]
    if m == "h2h":
        return "ML"
    if m == "spreads":
        return "spread"
    if m == "totals":
        return "total"
    if m == "team_total":
        return "team-total"
    return m.replace("player_", "prop:")


def window_rows(rows):
    """Decided live rows from the last 3 distinct week labels (ledger weeks sort
    lexically: 2026-W01 < 2026-W02 < … < 2027-W01 — season rollover safe)."""
    dec = [r for r in rows if r["result"] in ("W", "L") and r["truep"] is not None
           and not r["starred"]]
    if not dec:
        return []
    weeks = sorted({r["week"] for r in dec})
    recent = [r for r in dec if r["week"] in weeks[-WINDOW_WEEKS:]]
    if len(recent) < MIN_ROWS:
        recent = dec[-FALLBACK_ROWS:]
    return recent


def clv_window_rows(rows):
    """Live rows carrying a CLV verdict, DECIDED OR NOT (2026-08-09).

    WHY SEPARATE FROM window_rows(): MARKET-SHADE is a pure CLV rule — it asks whether
    the market moved against a dimension, which is knowable at the CLOSE, weeks before
    any W/L exists. Gating it behind decided legs left the governor completely idle for
    the first ~3 weeks of a season (MIN_ROWS=15 decided), which is exactly when the
    adjustments are least proven and a bad one does the most damage. Hit-rate rules
    (COOL/SUSPEND/GLOBAL SHRINK) still require decisions — those genuinely need results.
    """
    have = [r for r in rows
            if r["truep"] is not None and not r["starred"]
            and (r["clv"] or "").replace("−", "-").strip()[:1] in ("+", "-", "=")]
    if not have:
        return []
    weeks = sorted({r["week"] for r in have})
    recent = [r for r in have if r["week"] in weeks[-WINDOW_WEEKS:]]
    return recent if len(recent) >= MIN_ROWS else have[-FALLBACK_ROWS:]


def dim_names(r):
    names = [f"family:{market_family(r['leg_id'])}"]
    b = int(r["truep"] // 5 * 5)
    names.append(f"band:{b}-{b+4}")
    for tag in (parse_adj_tags(r["leg"]) or []):
        names.append(f"adj:{tag}")
    return names


def actions_for(recent, clv_recent=None):
    dims = defaultdict(lambda: {"n": 0, "w": 0, "tp": 0.0, "clv+": 0, "clv-": 0,
                                "last": []})
    bm = bk = scored = 0.0
    for r in recent:
        y = 1.0 if r["result"] == "W" else 0.0
        if r["implp"] is not None:
            bm += (r["truep"] / 100 - y) ** 2
            bk += (r["implp"] / 100 - y) ** 2
            scored += 1
        for d in dim_names(r):
            e = dims[d]
            e["n"] += 1
            e["w"] += int(y)
            e["tp"] += r["truep"]
            e["last"].append(y)
    # CLV counts come from their OWN window so the shade can fire pre-results. Rows in
    # both windows are counted once here, not twice.
    for r in (clv_recent if clv_recent is not None else recent):
        clv = (r["clv"] or "").replace("−", "-").strip()
        if not clv[:1] in ("+", "-"):
            continue
        for d in dim_names(r):
            dims[d]["clv+" if clv.startswith("+") else "clv-"] += 1
    acts = []
    for d, e in sorted(dims.items()):
        n, w = e["n"], e["w"]
        # A dimension can now exist on CLV alone (no decided legs yet) — hit-rate rules
        # must not divide by zero; they simply do not apply until results arrive.
        hit = (w / n * 100) if n else 0.0
        claimed = (e["tp"] / n) if n else 0.0
        rewarmed = len(e["last"]) >= 5 and sum(e["last"][-5:]) >= 3
        if n >= SUSP_N and hit <= claimed - SUSP_GAP and not rewarmed:
            acts.append(("⛔ SUSPEND", d, f"{w}-{n-w} ({hit:.0f}%) vs claimed "
                                         f"{claimed:.0f}% — no new legs this build"))
        elif n >= COOL_N and hit <= claimed - COOL_GAP and not rewarmed:
            acts.append(("🧊 COOL", d, f"{w}-{n-w} ({hit:.0f}%) vs claimed {claimed:.0f}% "
                                       f"— halve adjustments; barred from Tier 1/anchor"))
        if e["clv+"] + e["clv-"] >= CLV_MIN and e["clv-"] - e["clv+"] >= 2:
            acts.append(("📉 MARKET-SHADE", d,
                         f"CLV {e['clv+']}+/{e['clv-']}− — TrueP = market no-vig for "
                         f"this dimension until CLV recovers"))
    if scored >= 10 and bm > bk:
        acts.append(("🌐 GLOBAL SHRINK", "ALL adjustments",
                     f"recent Brier(TrueP) {bm/scored:.4f} worse than market "
                     f"{bk/scored:.4f} (n={scored:.0f}) — halve everything this build"))
    return dims, acts


def main():
    with open(LEDGER, encoding="utf-8") as fh:
        live, _bt, _tickets, _orphans = read_rows(fh.read())
    recent = window_rows(live)
    clv_recent = clv_window_rows(live)
    dims, acts = actions_for(recent, clv_recent)
    print("═" * 72)
    print(f"  PULSE — recent-window exposure governor ({len(recent)} decided legs, "
          f"{len(clv_recent)} CLV-bearing legs in window)")
    print("═" * 72)
    shown = 0
    for d, e in sorted(dims.items(), key=lambda kv: -kv[1]["n"]):
        clvn = e["clv+"] + e["clv-"]
        if e["n"] < 3 and clvn < CLV_MIN:
            continue
        if e["n"]:
            print(f"  {d:<28} {e['w']}-{e['n']-e['w']:<3} hit {e['w']/e['n']*100:>3.0f}% "
                  f"vs claimed {e['tp']/e['n']:>3.0f}%   CLV {e['clv+']}+/{e['clv-']}−")
        else:
            print(f"  {d:<28} {'—':<7} (no decided legs yet)        "
                  f"   CLV {e['clv+']}+/{e['clv-']}−")
        shown += 1
    if not shown:
        print("  (window too thin — no dimension has 3 decided legs or "
              f"{CLV_MIN} CLV verdicts; governor idles)")
    print("─" * 72)
    if acts:
        print("  ACTIONS (mechanical — the build MUST apply these; the registry itself")
        print("  still only changes at the n≥20-30 evidence bar):")
        for sev, d, msg in acts:
            print(f"  {sev}  {d} — {msg}")
    else:
        print("  ✓ no dimension breaches the thresholds — build normally.")
    print("═" * 72)


if __name__ == "__main__":
    main()
