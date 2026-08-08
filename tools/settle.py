#!/usr/bin/env python3
"""settle.py — settle open ledger legs from the CONTEXT STORE, by leg_id (no regex).

WHY THIS IS SIMPLER THAN THE MLB VERSION
    The MLB settle tool was 570 lines of leg-text regex forensics (surname resolution,
    doubleheader hints, team-nickname collisions — each a pinned burn). Here every row
    carries a structured leg_id (tools/legs.py), so settlement is a JOIN:
      game markets  → games scores (h2h by score; spreads by MARGIN — the ported
                      −1.5-wins-by-1-loses rule; totals/team totals with integer Pushes)
      player props  → player_week row for (season, week, gsis) vs the point
                      (anytime TD = rushing+receiving TDs ≥ 1; kicking points =
                      3·fg_made + pat_made; no stat row = DNP → MANUAL, books void)
      defense/longest → MANUAL by doctrine (press-box vs pbp mismatch)
    Games not Final propose nothing. Ported posture: READ-ONLY proposals by default;
    --apply writes ONLY the Result cell of matched rows.

USAGE
    tools/settle.py <season> <week>            # propose (read-only)
    tools/settle.py <season> <week> --apply    # write Result cells in place
"""
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from legs import (COL, MARKET_STAT, flag_verdict, is_leg_row, ou_verdict,  # noqa: E402
                  parse_leg_id, set_cell, split_row, spread_verdict)

DB = os.environ.get("NFL_DB", os.path.join(REPO, "data", "context.db"))
LEDGER = os.environ.get("NFL_LEDGER", os.path.join(REPO, "ledgers", "results_log.md"))


def settle_leg(leg, game, stat_row):
    """(verdict, why) for one parsed leg_id. verdict ∈ W/L/Push/MANUAL/None(not final).
    Pure over store rows — selftest-covered."""
    spec = MARKET_STAT.get(leg["market"])
    if spec is None:
        return "MANUAL", f"unknown market {leg['market']!r}"
    if spec[0] == "manual":
        return "MANUAL", spec[1]
    if game is None:
        return "MANUAL", "game not found in the store"
    if game["home_score"] is None:
        return None, "game not final yet"
    hs, as_ = game["home_score"], game["away_score"]
    home, away = game["home_team"], game["away_team"]

    if spec[0] == "game":
        side = leg["side"]
        if leg["market"] == "h2h":
            own = hs if side == home else as_ if side == away else None
            opp = as_ if side == home else hs if side == away else None
            if own is None:
                return "MANUAL", f"side {side!r} is neither {away} nor {home}"
            v = "W" if own > opp else ("L" if own < opp else "Push")
            return v, f"{side} {own}-{opp}"
        if leg["market"] == "spreads":
            own = hs if side == home else as_ if side == away else None
            opp = as_ if side == home else hs if side == away else None
            if own is None or leg["point"] is None:
                return "MANUAL", "unresolvable spread side/point"
            v = spread_verdict(own, opp, leg["point"])
            return v, f"{side} {own}-{opp} w/ {leg['point']:+g} → margin {own-opp:+d}"
        if leg["market"] == "totals":
            tot = hs + as_
            v = ou_verdict(leg["side"], leg["point"], tot)
            return v, f"total {tot} vs {leg['side']} {leg['point']:g}"
        if leg["market"] == "team_total":
            own = hs if leg["side"] == home else as_ if leg["side"] == away else None
            if own is None or leg["point"] is None:
                return "MANUAL", "unresolvable team-total side/point"
            # side names the team; direction rides in the label — Over by ledger
            # convention unless the point is stored negative (not used); we settle
            # Over here and callers writing Unders use side 'Under' + team in label?
            # NO — keep it structural: team_total side = team, and the O/U direction
            # is encoded by point sign convention being always Over? Too clever.
            return "MANUAL", "team_total needs O/U in side — use side=<TEAM>_Over/<TEAM>_Under"
    if spec[0] in ("stat", "stat_sum", "kicking_points", "stat_flag"):
        if stat_row is None:
            return "MANUAL", "no stat row (DNP) — books void; check by hand"
        if spec[0] == "stat":
            val = stat_row[spec[1]] or 0
        elif spec[0] == "stat_sum":
            val = sum(stat_row[c] or 0 for c in spec[1])
        elif spec[0] == "kicking_points":
            val = 3 * (stat_row["fg_made"] or 0) + (stat_row["pat_made"] or 0)
        else:  # stat_flag
            cnt = sum(stat_row[c] or 0 for c in spec[1])
            return (flag_verdict(leg["side"], cnt),
                    f"{stat_row['player_display_name']} TDs={cnt}")
        if leg["point"] is None:
            return "MANUAL", "no point on a counting prop"
        v = ou_verdict(leg["side"], leg["point"], val)
        return v, (f"{stat_row['player_display_name']} {val:g} vs "
                   f"{leg['side']} {leg['point']:g}")
    return "MANUAL", "unhandled spec"


def team_total_verdict(leg, game):
    """team_total with side '<TEAM>_Over'/'<TEAM>_Under'."""
    if game is None or game["home_score"] is None:
        return (None, "game not final yet") if game else ("MANUAL", "game not found")
    team, _, direction = leg["side"].partition("_")
    own = (game["home_score"] if team == game["home_team"]
           else game["away_score"] if team == game["away_team"] else None)
    if own is None or leg["point"] is None or direction not in ("Over", "Under"):
        return "MANUAL", "team_total side must be <TEAM>_Over or <TEAM>_Under"
    v = ou_verdict(direction, leg["point"], own)
    return v, f"{team} scored {own} vs {direction} {leg['point']:g}"


def main():
    args = sys.argv[1:]
    apply_mode = "--apply" in args
    pos = [a for a in args if not a.startswith("--")]
    if len(pos) < 2:
        sys.exit("usage: settle.py <season> <week> [--apply]")
    season, week = int(pos[0]), int(pos[1])

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    games = {g["game_id"]: g for g in con.execute(
        "SELECT * FROM games WHERE season=? AND week=?", (season, week))}
    stats = {}
    for r in con.execute("SELECT * FROM player_week WHERE season=? AND week=?",
                         (season, week)):
        stats[r["player_id"]] = r

    with open(LEDGER, encoding="utf-8") as fh:
        lines = fh.read().split("\n")

    proposals = []   # (line_idx, leg_id, verdict, why)
    for i, ln in enumerate(lines):
        if not is_leg_row(ln):
            continue
        c = split_row(ln)
        leg = parse_leg_id(c[COL["leg_id"]])
        if leg["season"] != season or leg["week"] != week:
            continue
        if "tbd" not in c[COL["result"]].lower():
            continue
        game = games.get(leg["game_id"])
        if leg["market"] == "team_total" and "_" in leg["side"]:
            verdict, why = team_total_verdict(leg, game)
        else:
            verdict, why = settle_leg(leg, game, stats.get(leg["gsis_id"]))
        if verdict is None:
            proposals.append((i, c[COL["leg_id"]], "—", why))
        else:
            proposals.append((i, c[COL["leg_id"]], verdict, why))

    print("=" * 70)
    print(f"  SETTLE — {season} W{week}  "
          f"({'APPLY' if apply_mode else 'read-only proposals'})")
    print("=" * 70)
    if not proposals:
        print("  (no TBD rows for this week)")
        return
    applied = 0
    for i, lid, verdict, why in proposals:
        tag = {"W": "✅ W", "L": "❌ L", "Push": "➖ Push"}.get(verdict, f"⚠ {verdict}")
        print(f"  {tag:<8} {lid:<58}  {why}")
        if apply_mode and verdict in ("W", "L", "Push"):
            lines[i] = set_cell(lines[i], COL["result"], f"**{verdict}** ({why})")
            applied += 1
    if apply_mode:
        with open(LEDGER, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        print(f"  ✓ wrote {applied} Result cell(s) into {os.path.basename(LEDGER)}")
    else:
        print("  → re-run with --apply to write Result cells "
              "(MANUAL/not-final rows are never auto-written)")
    print("=" * 70)


if __name__ == "__main__":
    main()
