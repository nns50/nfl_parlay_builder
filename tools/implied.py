#!/usr/bin/env python3
"""implied.py — implied team totals from spread + game total (the NFL pricing primitive).

WHY THIS EXISTS (NFL_REQUIREMENTS §4.1)
    Every team-level and TD/yardage read anchors on the implied team total, derived from
    the two most liquid numbers on the board:
        home_implied = total/2 − spread_home/2      (spread_home negative when favored)
        away_implied = total/2 + spread_home/2
    This is a DERIVATION, not a model — it lives in one tool so the arithmetic is never
    done by hand (the devig.sh doctrine, applied to the other primitive).

USAGE
    tools/implied.py --spread -3.5 --total 44.5          # home favored by 3.5
    tools/implied.py --game 2026_01_BUF_HOU              # lines from the store
    tools/implied.py --week 2026 1                       # whole week's table
NOTE: spread is the HOME line (negative = home favored), matching nflverse spread_line
      sign convention is the opposite — schedules' spread_line is positive when the HOME
      team is favored. Store reads convert; CLI --spread expects the book convention
      (home -3.5 = home favored by 3.5).
"""
import argparse
import os
import sqlite3
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("NFL_DB", os.path.join(REPO, "data", "context.db"))


def implied_totals(spread_home, total):
    """(home_implied, away_implied). spread_home in book convention (negative = home
    favored). Pure — selftested."""
    home = total / 2.0 - spread_home / 2.0
    away = total - home
    return round(home, 2), round(away, 2)


def from_store_line(spread_line):
    """nflverse schedules stores spread_line as the amount the HOME team is favored by
    (positive = home favored) — flip to book convention."""
    return -spread_line if spread_line is not None else None


def print_game(away, home, spread_home, total, extra=""):
    hi, ai = implied_totals(spread_home, total)
    fav = home if spread_home < 0 else (away if spread_home > 0 else "PK")
    print(f"  {away:>3} @ {home:<3}  spread {spread_home:+g} (fav {fav}), total {total:g}"
          f"  →  implied {home} {hi:g} / {away} {ai:g}{extra}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spread", type=float, help="home spread, book convention (-3.5 = home fav)")
    ap.add_argument("--total", type=float)
    ap.add_argument("--game", help="game_id — read lines from the store")
    ap.add_argument("--week", nargs=2, metavar=("S", "W"), help="whole week from the store")
    a = ap.parse_args()

    if a.spread is not None and a.total is not None:
        hi, ai = implied_totals(a.spread, a.total)
        print(f"home implied {hi:g}   away implied {ai:g}   "
              f"(spread {a.spread:+g}, total {a.total:g})")
        return
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    if a.game:
        rows = con.execute("SELECT * FROM games WHERE game_id=?", (a.game,)).fetchall()
    elif a.week:
        rows = con.execute("SELECT * FROM games WHERE season=? AND week=? "
                           "ORDER BY kickoff_utc", (int(a.week[0]), int(a.week[1]))).fetchall()
    else:
        ap.error("need --spread/--total, --game, or --week")
    shown = 0
    for g in rows:
        sp, tt = from_store_line(g["spread_line"]), g["total_line"]
        if sp is None or tt is None:
            print(f"  {g['away_team']:>3} @ {g['home_team']:<3}  (no stored lines)")
            continue
        print_game(g["away_team"], g["home_team"], sp, tt)
        shown += 1
    if not shown and not rows:
        sys.exit("no games matched")


if __name__ == "__main__":
    main()
