#!/usr/bin/env python3
"""validate_settle.py — prove settle.py settles REAL games correctly.

WHY THIS EXISTS (2026-08-09)
    Settlement is the half of the ledger loop that money depends on, and until this
    tool it had never run against real completed games with real logged legs — the
    live ledger's 83 rows are all future REG W1, so nothing had ever settled.

METHOD (the part that makes it worth anything)
    Every EXPECTED verdict below is HAND-COMPUTED from the published 2025 W18 final
    score / boxscore line and written as a literal. Nothing here imports settle.py's
    verdict helpers, so a disagreement means one of the two is WRONG — this is not a
    self-consistency check. Cases deliberately cover the classes most likely to be
    mis-settled: spreads by MARGIN (a -2.5 favourite that wins by 2 LOSES), integer
    pushes on spreads/totals/team-totals/props, AWAY-team margins, the kicking-points
    formula (3*FG + PAT), anytime-TD as a flag, and the MANUAL classes (defensive and
    longest-play props by doctrine, DNP because books void).

    Runs against a TEMP ledger via NFL_LEDGER — the live ledger is never touched.
    Skips (exit 0) when the store lacks 2025 W18, so a pre-sync environment does not
    fail the suite.

USAGE
    tools/validate_settle.py           # human-readable table
    tools/validate_settle.py --quiet   # summary line only (selftest mode)
"""
import os
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DB = os.environ.get("NFL_DB", os.path.join(REPO, "data", "context.db"))

# (case_id, leg_id, label, EXPECTED verdict — hand-computed, why)
#   2025_18_NO_ATL   NO 17 @ ATL 19   home margin +2   total 36
#   2025_18_DET_CHI  DET 19 @ CHI 16  AWAY DET won by 3, total 35
#   2025_18_GB_MIN   GB 3 @ MIN 16    total 19
#   2025_18_LAC_DEN  LAC 3 @ DEN 19   total 22
#   2025_18_MIA_NE   MIA 10 @ NE 38   total 48
#   2025_18_BAL_PIT  BAL 24 @ PIT 26  total 50
#   Ham 00-0032918 rushTD 1 · Allen 00-0030279 0TD/7rec/36yds
#   Henry 00-0033090 56.0 yds · Boswell 00-0031136 fg2+pat2 = 8 pts
CASES = [
    ("h2h-win", "2025-W18:2025_18_NO_ATL:h2h:ATL::", "ATL ML", "W", "ATL won 19-17"),
    ("h2h-loss", "2025-W18:2025_18_NO_ATL:h2h:NO::", "NO ML", "L", "NO lost 17-19"),
    ("sp-fav-cover", "2025-W18:2025_18_NO_ATL:spreads:ATL:-1.5:", "ATL -1.5", "W",
     "won by 2 > 1.5"),
    ("sp-fav-push", "2025-W18:2025_18_NO_ATL:spreads:ATL:-2:", "ATL -2", "Push",
     "won by exactly 2"),
    ("sp-fav-fail", "2025-W18:2025_18_NO_ATL:spreads:ATL:-2.5:", "ATL -2.5", "L",
     "won by 2 < 2.5 — favourite wins but does NOT cover"),
    ("sp-dog-cover", "2025-W18:2025_18_NO_ATL:spreads:NO:+2.5:", "NO +2.5", "W",
     "lost by 2 < 2.5"),
    ("sp-dog-fail", "2025-W18:2025_18_NO_ATL:spreads:NO:+1.5:", "NO +1.5", "L",
     "lost by 2 > 1.5"),
    ("sp-away-push", "2025-W18:2025_18_DET_CHI:spreads:DET:-3:", "DET -3", "Push",
     "AWAY favourite won by exactly 3"),
    ("sp-away-cover", "2025-W18:2025_18_DET_CHI:spreads:DET:-2.5:", "DET -2.5", "W",
     "away won by 3 > 2.5"),
    ("tot-over-win", "2025-W18:2025_18_NO_ATL:totals:Over:35.5:", "Over 35.5", "W",
     "36 > 35.5"),
    ("tot-over-push", "2025-W18:2025_18_NO_ATL:totals:Over:36:", "Over 36", "Push",
     "36 = 36"),
    ("tot-under-win", "2025-W18:2025_18_NO_ATL:totals:Under:36.5:", "Under 36.5", "W",
     "36 < 36.5"),
    ("tot-under-push", "2025-W18:2025_18_GB_MIN:totals:Under:19:", "Under 19", "Push",
     "19 = 19"),
    ("tot-over-loss", "2025-W18:2025_18_LAC_DEN:totals:Over:22.5:", "Over 22.5", "L",
     "22 < 22.5"),
    ("tt-over-win", "2025-W18:2025_18_NO_ATL:team_total:ATL_Over:17.5:", "ATL TT o17.5",
     "W", "ATL 19 > 17.5"),
    ("tt-over-push", "2025-W18:2025_18_NO_ATL:team_total:ATL_Over:19:", "ATL TT o19",
     "Push", "ATL 19 = 19"),
    ("tt-under-win", "2025-W18:2025_18_NO_ATL:team_total:NO_Under:20.5:", "NO TT u20.5",
     "W", "NO 17 < 20.5"),
    ("tt-over-loss", "2025-W18:2025_18_GB_MIN:team_total:GB_Over:6.5:", "GB TT o6.5",
     "L", "GB 3 < 6.5"),
    ("atd-hit", "2025-W18:2025_18_GB_MIN:player_anytime_td:Yes::00-0032918", "Ham ATD",
     "W", "1 rushing TD"),
    ("atd-miss", "2025-W18:2025_18_LAC_DEN:player_anytime_td:Yes::00-0030279",
     "Allen ATD", "L", "0 TDs"),
    ("kick-over", "2025-W18:2025_18_BAL_PIT:player_kicking_points:Over:7.5:00-0031136",
     "Boswell KP o7.5", "W", "3*2+2 = 8 > 7.5"),
    ("kick-under", "2025-W18:2025_18_BAL_PIT:player_kicking_points:Under:7.5:00-0031136",
     "Boswell KP u7.5", "L", "8 > 7.5"),
    ("kick-push", "2025-W18:2025_18_BAL_PIT:player_kicking_points:Over:8:00-0031136",
     "Boswell KP o8", "Push", "8 = 8"),
    ("rec-over", "2025-W18:2025_18_LAC_DEN:player_receptions:Over:6.5:00-0030279",
     "Allen rec o6.5", "W", "7 > 6.5"),
    ("recyd-under",
     "2025-W18:2025_18_LAC_DEN:player_reception_yds:Under:40.5:00-0030279",
     "Allen recyd u40.5", "W", "36.0 < 40.5"),
    ("recyd-push", "2025-W18:2025_18_MIA_NE:player_reception_yds:Over:56:00-0033090",
     "Henry recyd o56", "Push", "56.0 = 56"),
    ("man-sacks", "2025-W18:2025_18_BAL_PIT:player_sacks:Over:0.5:00-0031136",
     "sacks prop", "MANUAL", "defensive props settle MANUAL"),
    ("man-long", "2025-W18:2025_18_MIA_NE:player_rush_longest:Over:12.5:00-0033090",
     "longest rush", "MANUAL", "longest-play props settle MANUAL"),
    ("man-dnp", "2025-W18:2025_18_MIA_NE:player_anytime_td:Yes::00-0019596",
     "DNP player ATD", "MANUAL", "no stat row — books void"),
]

# "## Backtest" is REQUIRED: calib.py only ingests rows under a declared section, and
# rows outside one are silently skipped (calib's parser guard now flags that).
HEADER = ("# settle.py validation ledger (temp — never the live one)\n\n## Backtest\n\n"
          "| Week | Leg | leg_id | Type | Price | Book | TrueP | ImplP | Edge | Grade "
          "| Result | Played | CLV | Bucket |\n"
          "|------|-----|--------|------|-------|------|-------|-------|------|-------"
          "|--------|--------|-----|--------|\n")


def store_ready():
    """2025 W18 finals + that week's player stats must both be present."""
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        g = con.execute("SELECT COUNT(*) FROM games WHERE season=2025 AND week=18 "
                        "AND game_type='REG' AND home_score IS NOT NULL").fetchone()[0]
        p = con.execute("SELECT COUNT(*) FROM player_week WHERE season=2025 "
                        "AND week=18").fetchone()[0]
        return g >= 16 and p > 0
    except Exception:
        return False


def run():
    tmp = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    tmp.write(HEADER)
    for cid, leg_id, label, _exp, _why in CASES:
        tmp.write(f"| 2025-W18 | {label} [{cid}] | {leg_id} | BT | -110 | Validation "
                  f"| 50.0% | 50.0% | +0.0 | backtest | TBD | N |  | BT |\n")
    tmp.close()
    try:
        env = dict(os.environ, NFL_LEDGER=tmp.name)
        proc = subprocess.run([sys.executable, os.path.join(HERE, "settle.py"),
                               "2025", "18", "--apply"],
                              capture_output=True, text=True, env=env, cwd=REPO)
        if proc.returncode != 0:
            return None, f"settle.py exited {proc.returncode}: {proc.stderr[:200]}"
        got = {}
        for line in open(tmp.name, encoding="utf-8"):
            if not line.startswith("| 2025-W18"):
                continue
            c = [x.strip() for x in line.split("|")]
            cid = c[2][c[2].rfind("[") + 1:c[2].rfind("]")]
            res, leg_id = c[11], c[3]
            if res.startswith("**"):                 # written verdict: **W** (why)
                got[cid] = res[2:res.index("**", 2)]
            elif res.upper() == "TBD":               # MANUAL rows are never auto-written
                prop = [ln for ln in proc.stdout.splitlines() if leg_id in ln]
                got[cid] = "MANUAL" if prop and "MANUAL" in prop[0] else "TBD"
            else:
                got[cid] = res
        return got, None
    finally:
        os.unlink(tmp.name)


def main():
    quiet = "--quiet" in sys.argv
    if not store_ready():
        print("SKIP: store lacks 2025 W18 finals/player stats (sync first)")
        return 0
    got, err = run()
    if err:
        print(f"FAIL: {err}")
        return 1
    fails = [(cid, exp, got.get(cid, "<missing>"), why)
             for cid, _l, _lab, exp, why in CASES if got.get(cid) != exp]
    if not quiet:
        print(f"{'case':15} {'expected':9} {'settle.py':10} {'':2} why")
        print("-" * 78)
        for cid, _l, _lab, exp, why in CASES:
            a = got.get(cid, "<missing>")
            print(f"{cid:15} {exp:9} {a:10} {'OK' if a == exp else 'XX':2} {why}")
        print("-" * 78)
    print(f"settle validation: {len(CASES) - len(fails)}/{len(CASES)} correct "
          f"(real 2025 W18 finals)")
    for cid, exp, actual, why in fails:
        print(f"  ⛔ {cid}: expected {exp}, settle.py said {actual}  ({why})")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
