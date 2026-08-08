#!/usr/bin/env python3
"""clv_backfill.py — retro-fill blank CLV cells from The Odds API HISTORICAL snapshots.

WHY THIS EXISTS (ported; deliberately deferred from M5 to ops)
    Live capture can only close games whose kickoff is still ahead of a run — a dropped
    lock run leaves holes, and blank CLV cells on decided legs bias the governor's own
    shade trigger. The /historical endpoint serves full-board snapshots at 5-minute
    grain. NFL kickoffs CLUSTER: one snapshot at a window's kickoff−2min closes every
    game in that window, so a whole missed Sunday is typically 2-3 snapshots.

COST + GATES (ported discipline)
    Historical calls bill 10 × markets × regions → h2h+spreads+totals @ us =
    30 credits PER SNAPSHOT TIMESTAMP. Plan mode (default) spends NOTHING and prints
    rows/snapshots/exact cost; --apply requires the rich tier (≥5000 reported) and
    respects --max-credits (default 150). Scope: h2h / spreads / totals (props are
    per-event on the historical API — hand-pull those). Verdicts carry a ' bf'
    provenance marker; in-game-timestamp snapshots are refused per game.

USAGE
    tools/clv_backfill.py <season> <week>                    # PLAN — no spend
    tools/clv_backfill.py <season> <week> --apply [--max-credits 90]
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from clv_capture import close_novig, edge_warning, verdict_from_close, _pct  # noqa: E402
from legs import COL, is_leg_row, parse_leg_id, set_cell, split_row  # noqa: E402

DB = os.environ.get("NFL_DB", os.path.join(REPO, "data", "context.db"))
LEDGER = os.environ.get("NFL_LEDGER", os.path.join(REPO, "ledgers", "results_log.md"))
ODDS = os.path.join(HERE, "odds_api.sh")
CONF = os.path.join(REPO, "config", "markets.conf")
SNAP_COST = 30              # 10cr × 3 markets × 1 region
RICH_FLOOR = 5000
BACKFILLABLE = ("h2h", "spreads", "totals")


def conf(key, default=None):
    with open(CONF, encoding="utf-8") as fh:
        for ln in fh:
            if ln.startswith(key + "="):
                return ln.strip().split("=", 1)[1]
    return default


def snapshot_ts(kickoff_iso, minutes_before=2):
    """kickoff − N minutes, ISO-Z. Pure."""
    ko = datetime.strptime(kickoff_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (ko - timedelta(minutes=minutes_before)).strftime("%Y-%m-%dT%H:%M:%SZ")


def plan_rows(lines, season, week, games):
    """[(line_idx, leg, kickoff)] for blank-CLV backfillable rows of the week. Pure."""
    out = []
    for i, ln in enumerate(lines):
        if not is_leg_row(ln):
            continue
        c = split_row(ln)
        leg = parse_leg_id(c[COL["leg_id"]])
        if not leg or leg["season"] != season or leg["week"] != week:
            continue
        if leg["market"] not in BACKFILLABLE:
            continue
        if c[COL["clv"]] not in ("—", "-", ""):
            continue
        g = games.get(leg["game_id"])
        if g and g["kickoff_utc"]:
            out.append((i, leg, g["kickoff_utc"]))
    return out


def quota_remaining():
    m = re.search(r"remaining:\s*([\d,]+)",
                  subprocess.run(["bash", ODDS, "quota"], capture_output=True,
                                 text=True, timeout=40).stdout)
    return int(m.group(1).replace(",", "")) if m else None


def fetch_snapshot(ts):
    sport = conf("SPORT_KEY_REG")
    path = (f"historical/sports/{sport}/odds?regions=us&markets=h2h,spreads,totals"
            f"&oddsFormat=american&dateFormat=iso&date={ts}")
    raw = subprocess.run(["bash", ODDS, "raw", path], capture_output=True,
                         text=True, timeout=90).stdout
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data.get("data") if isinstance(data, dict) else None


def main():
    args = sys.argv[1:]
    apply_mode = "--apply" in args
    maxcr = 150
    if "--max-credits" in args:
        maxcr = int(args[args.index("--max-credits") + 1])
    pos = [a for a in args if not a.startswith("--") and not a.isdigit() or a.isdigit()]
    nums = [a for a in args if re.fullmatch(r"\d+", a)]
    if len(nums) < 2:
        sys.exit("usage: clv_backfill.py <season> <week> [--apply] [--max-credits N]")
    season, week = int(nums[0]), int(nums[1])

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    games = {g["game_id"]: g for g in con.execute(
        "SELECT * FROM games WHERE season=? AND week=?", (season, week))}
    abbr_names = {r["team_abbr"]: r["team_name"] for r in
                  con.execute("SELECT team_abbr, team_name FROM teams")}

    with open(LEDGER, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    rows = plan_rows(lines, season, week, games)
    stamps = sorted({snapshot_ts(k) for _, _, k in rows})
    cost = len(stamps) * SNAP_COST

    print("=" * 70)
    print(f"  CLV BACKFILL — {season} W{week}  "
          f"({'APPLY' if apply_mode else 'PLAN — no spend'})")
    print("=" * 70)
    if not rows:
        print("  (no blank-CLV h2h/spreads/totals rows for this week — nothing to fill)")
        return
    print(f"  fillable rows: {len(rows)}   snapshot timestamps: {len(stamps)} "
          f"(windows cluster)   cost: {len(stamps)}×{SNAP_COST} = {cost} credits")
    for ts in stamps:
        n = sum(1 for _, _, k in rows if snapshot_ts(k) == ts)
        print(f"    {ts}  closes {n} leg(s)")
    if not apply_mode:
        print(f"  → apply: tools/clv_backfill.py {season} {week} --apply "
              f"[--max-credits {maxcr}]  (rich tier only)")
        return

    rem = quota_remaining()
    if rem is None or rem < RICH_FLOOR:
        sys.exit(f"⛔ REFUSING: API reports {rem} remaining (< {RICH_FLOOR} rich floor).")
    if cost > maxcr:
        sys.exit(f"⛔ REFUSING: plan cost {cost} > --max-credits {maxcr}.")

    filled = 0
    for ts in stamps:
        board = fetch_snapshot(ts)
        if not board:
            print(f"  ✗ snapshot {ts} failed — skipping its legs")
            continue
        for i, leg, kickoff in rows:
            if snapshot_ts(kickoff) != ts:
                continue
            g = games[leg["game_id"]]
            an, hn = abbr_names.get(g["away_team"]), abbr_names.get(g["home_team"])
            ev = next((e for e in board if e.get("away_team") == an
                       and e.get("home_team") == hn), None)
            if ev is None:
                print(f"  ⚠ {leg['game_id']}: not in the {ts} snapshot — MANUAL")
                continue
            got, err = close_novig(ev, leg["market"], leg["side"], leg["point"], abbr_names)
            if err:
                print(f"  ⚠ {leg['game_id']} {leg['market']}: {err}")
                continue
            nv, desc = got
            c = split_row(lines[i])
            verdict = verdict_from_close(nv * 100, _pct(c[COL["implp"]]))
            if verdict:
                lines[i] = set_cell(lines[i], COL["clv"], verdict + " bf")
                filled += 1
                print(f"  ✓ {leg['game_id']} {leg['market']} {leg['side']}: "
                      f"{desc} → {verdict} bf")
    if filled:
        with open(LEDGER, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        print(f"  ✓ wrote {filled} backfilled CLV verdict(s) (' bf' provenance marker)")
    print("=" * 70)


if __name__ == "__main__":
    main()
