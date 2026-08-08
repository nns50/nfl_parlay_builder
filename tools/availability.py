#!/usr/bin/env python3
"""availability.py — the injury/practice/inactives ladder (NFL_REQUIREMENTS §2).

WHY THIS EXISTS
    MLB had a binary lineup gate. NFL availability is a WEEK-LONG state machine:
    practice participation → Fri designation (Q/D/O) → T-90min inactives. The nflverse
    `injuries` dataset is dead for 2025+ (verified), so this layer runs on two sources:
      • ROSTER FLOOR (always available): weekly_rosters status — RES/PUP/NFI/SUS are
        hard OUTs; everyone else is roster-active with NO practice-report info.
      • ESPN ENRICHMENT (best-effort, undocumented, can vanish mid-week): the league
        injuries feed upgrades roster-active players to Q/D/O/IR designations with
        injury detail + return dates. Every ESPN-derived row carries source='espn';
        absence of ESPN degrades the board VISIBLY (a DEGRADED banner + roster-only
        states), never silently and never by inventing designations.

    p_plays haircuts (directional seeds per the resolved plan — each gets its own
    calibration dimension once the ledger runs): OUT/IR 0.0, DOUBTFUL 0.25,
    QUESTIONABLE 0.75, DAY-TO-DAY 0.85. QB listings are flagged loudest — a QB status
    reprices the whole game (the SP-scratch analog).

USAGE
    tools/availability.py sync [--season S --week W] [--no-espn]
    tools/availability.py team <ABBR>          # the team's availability board
    tools/availability.py gate [S W]           # per-game gate table for the week
    tools/availability.py player "<name>"
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DB = os.environ.get("NFL_DB", os.path.join(REPO, "data", "context.db"))
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"

DDL = """CREATE TABLE IF NOT EXISTS availability (
  season INT, week INT, gsis_id TEXT, name TEXT, position TEXT, team TEXT,
  designation TEXT, detail TEXT, ret_date TEXT, p_plays REAL,
  source TEXT, espn_status TEXT, updated_at TEXT,
  PRIMARY KEY (season, week, gsis_id))"""

# Roster statuses that are hard OUT regardless of ESPN (weekly_rosters.status)
ROSTER_OUT = {"RES", "PUP", "NON", "NFI", "SUS", "EXE", "RET"}


# ── pure ladder (selftest-covered) ────────────────────────────────────────────

def map_status(espn_status):
    """ESPN status string → canonical designation (None = not listed / cleared)."""
    s = (espn_status or "").strip().lower()
    if s in ("out",):
        return "OUT"
    if s in ("injured reserve", "ir"):
        return "IR"
    if s == "doubtful":
        return "DOUBTFUL"
    if s == "questionable":
        return "QUESTIONABLE"
    if s in ("day-to-day", "day to day"):
        return "DTD"
    return None          # 'Active' etc. — a news note, not a listing


def p_plays(designation, roster_status=None):
    """P(player suits up). Directional seeds (plan §7.3) — calibration-owned later.
    None = no availability signal at all (roster-active, no report source)."""
    if roster_status and roster_status.upper() in ROSTER_OUT:
        return 0.0
    d = (designation or "").upper()
    if d in ("OUT", "IR"):
        return 0.0
    if d == "DOUBTFUL":
        return 0.25
    if d == "QUESTIONABLE":
        return 0.75
    if d == "DTD":
        return 0.85
    return None


def espn_id_from_links(athlete):
    """The league feed's athlete objects carry no bare id — extract it from the
    playercard href ('…/id/4709695/karson-sharar'). None if absent."""
    for link in (athlete or {}).get("links", []):
        m = re.search(r"/id/(\d+)/", link.get("href", ""))
        if m:
            return m.group(1)
    return None


# ── plumbing ──────────────────────────────────────────────────────────────────

def connect():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute(DDL)
    return con


def weekof():
    out = subprocess.run(["python3", os.path.join(HERE, "ingest.py"), "weekof"],
                         capture_output=True, text=True, timeout=30).stdout.split()
    return int(out[0]), int(out[1])


def fetch_espn():
    """League injuries JSON, or None (unreachable/blocked/bad shape) — the caller
    degrades, never errors. Undocumented feed: parse defensively."""
    try:
        r = subprocess.run(["curl", "-sS", "--fail", "-m", "25", ESPN_URL],
                           capture_output=True, text=True, timeout=35)
        if r.returncode != 0:
            return None
        data = json.loads(r.stdout)
        return data if isinstance(data.get("injuries"), list) else None
    except Exception:  # noqa: BLE001
        return None


def roster_floor(con, season, week):
    """{gsis: (status, name, position, team)} from the latest roster week ≤ target
    (falls back to the latest available)."""
    wk = con.execute(
        "SELECT MAX(week) FROM rosters WHERE season=? AND week<=?", (season, week)).fetchone()[0]
    if wk is None:
        wk = con.execute("SELECT MAX(week) FROM rosters WHERE season=?", (season,)).fetchone()[0]
    if wk is None:
        return {}, None
    rows = con.execute(
        "SELECT gsis_id, status, full_name, position, team FROM rosters "
        "WHERE season=? AND week=? AND gsis_id IS NOT NULL", (season, wk)).fetchall()
    return {r["gsis_id"]: (r["status"], r["full_name"], r["position"], r["team"])
            for r in rows}, wk


def cmd_sync(season, week, use_espn=True):
    con = connect()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    floor, roster_wk = roster_floor(con, season, week)
    if not floor:
        sys.exit("no roster rows in the store — run nfl_data.sh sync first")

    espn_bridge = {r["espn_id"]: r["gsis_id"] for r in
                   con.execute("SELECT espn_id, gsis_id FROM players "
                               "WHERE espn_id IS NOT NULL")}
    name_bridge = {}
    for r in con.execute("SELECT gsis_id, display_name, latest_team FROM players"):
        name_bridge[(re.sub(r"[^a-z]", "", (r["display_name"] or "").lower()),
                     r["latest_team"])] = r["gsis_id"]
    team_abbr = {r["team_name"]: r["team_abbr"] for r in
                 con.execute("SELECT team_name, team_abbr FROM teams")}

    con.execute("DELETE FROM availability WHERE season=? AND week=?", (season, week))
    n_roster_out = 0
    for gsis, (status, name, pos, team) in floor.items():
        if (status or "").upper() in ROSTER_OUT:
            con.execute(
                "INSERT OR REPLACE INTO availability VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (season, week, gsis, name, pos, team, f"OUT_ROSTER({status})",
                 None, None, 0.0, "rosters", None, now))
            n_roster_out += 1

    espn = fetch_espn() if use_espn else None
    n_listed = n_fallback = 0
    if espn:
        for tm in espn["injuries"]:
            abbr = team_abbr.get(tm.get("displayName", ""), None)
            for inj in tm.get("injuries", []):
                desig = map_status(inj.get("status"))
                if desig is None:
                    continue
                ath = inj.get("athlete") or {}
                eid = espn_id_from_links(ath)
                gsis = espn_bridge.get(eid)
                src = "espn"
                if gsis is None:      # id-bridge miss → flagged name fallback
                    key = (re.sub(r"[^a-z]", "", (ath.get("displayName") or "").lower()), abbr)
                    gsis = name_bridge.get(key)
                    src = "espn~name"
                    if gsis is None:
                        continue
                    n_fallback += 1
                rstat = (floor.get(gsis, (None,))[0] or "")
                det = (inj.get("details") or {})
                con.execute(
                    "INSERT OR REPLACE INTO availability VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (season, week, gsis, ath.get("displayName"),
                     (ath.get("position") or {}).get("abbreviation")
                     if isinstance(ath.get("position"), dict) else ath.get("position"),
                     abbr or floor.get(gsis, (None, None, None, None))[3],
                     desig, det.get("detail") or det.get("type"),
                     det.get("returnDate"), p_plays(desig, rstat), src,
                     inj.get("status"), now))
                n_listed += 1
    con.commit()
    print(f"availability sync — {season} W{week} (roster floor: week {roster_wk})")
    print(f"  roster hard-OUTs (RES/PUP/NFI/SUS…): {n_roster_out}")
    if espn:
        print(f"  ESPN listings written: {n_listed} "
              f"({n_fallback} via flagged name-fallback joins)")
    else:
        why = "disabled (--no-espn)" if not use_espn else "UNREACHABLE"
        print(f"  ⚠ DEGRADED MODE — ESPN {why}: no practice-report layer this sync.")
        print("    Q/D/O designations UNKNOWN; only roster hard-OUTs are marked.")
        print("    Legs on injury-rumored players must be treated PENDING-AVAILABILITY.")
    con.close()


def cmd_team(abbr):
    con = connect()
    abbr = abbr.upper()
    rows = con.execute(
        "SELECT * FROM availability WHERE team=? ORDER BY p_plays, position, name",
        (abbr,)).fetchall()
    if not rows:
        print(f"  ({abbr}: no availability rows — run sync, or genuinely clean)")
        return
    src_note = " (⚠ includes degraded roster-only rows)" if all(
        r["source"] == "rosters" for r in rows) else ""
    print(f"═══ {abbr} availability board — synced {rows[0]['updated_at']}{src_note} ═══")
    for r in rows:
        pp = f"{r['p_plays']:.2f}" if r["p_plays"] is not None else "?"
        det = f" — {r['detail']}" if r["detail"] else ""
        ret = f" (ret {r['ret_date']})" if r["ret_date"] else ""
        flag = "~" if r["source"] == "espn~name" else " "
        print(f" {flag}{r['position'] or '?':<4} {r['name']:<26} {r['designation']:<18} "
              f"P(plays)={pp}{det}{ret}")
    con.close()


def cmd_gate(season, week):
    """Per-game availability gate rows — the M3 acceptance table. QBs loudest."""
    con = connect()
    games = con.execute(
        "SELECT * FROM games WHERE season=? AND week=? ORDER BY kickoff_utc",
        (season, week)).fetchall()
    if not games:
        sys.exit(f"no games for {season} W{week}")
    av = con.execute(
        "SELECT * FROM availability WHERE season=? AND week=?", (season, week)).fetchall()
    by_team = {}
    for r in av:
        by_team.setdefault(r["team"], []).append(r)
    any_espn = any(r["source"].startswith("espn") for r in av)
    syncts = av[0]["updated_at"] if av else "NEVER"
    print(f"═══ availability gate — {season} W{week} (synced {syncts}; "
          f"{'ESPN live' if any_espn else '⚠ DEGRADED: roster floor only'}) ═══")
    for g in games:
        flags = []
        for side, qb_id, qb_name in (("away", g["away_qb_id"], g["away_qb_name"]),
                                     ("home", g["home_qb_id"], g["home_qb_name"])):
            hit = next((r for r in av if r["gsis_id"] == qb_id), None)
            if hit:
                flags.append(f"⚠ QB {qb_name} {hit['designation']}")
        a_n = len(by_team.get(g["away_team"], []))
        h_n = len(by_team.get(g["home_team"], []))
        listed = f"listed {g['away_team']}:{a_n} {g['home_team']}:{h_n}"
        outs = [r for t in (g["away_team"], g["home_team"])
                for r in by_team.get(t, []) if (r["p_plays"] or 0) == 0.0
                and not r["designation"].startswith("OUT_ROSTER")]
        if outs:
            listed += f"  OUT/IR: {', '.join(o['name'] for o in outs[:4])}" \
                      + (" …" if len(outs) > 4 else "")
        state = "✓" if not flags else "⚠"
        print(f"  {state} {g['away_team']:>3} @ {g['home_team']:<3} "
              f"{g['kickoff_et']:<22} {listed}" + ("  " + "; ".join(flags) if flags else ""))
    con.close()


def cmd_player(namefrag):
    con = connect()
    rows = con.execute(
        "SELECT * FROM availability WHERE name LIKE ? ORDER BY season DESC, week DESC "
        "LIMIT 5", (f"%{namefrag}%",)).fetchall()
    if not rows:
        print(f"  (no availability listing matching {namefrag!r} — cleared, or not synced)")
        return
    for r in rows:
        pp = f"{r['p_plays']:.2f}" if r["p_plays"] is not None else "?"
        print(f"  {r['season']} W{r['week']}  {r['name']} ({r['position']}, {r['team']}) "
              f"{r['designation']}  P(plays)={pp}  {r['detail'] or ''} "
              f"[{r['source']} @ {r['updated_at']}]")
    con.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("sync")
    sp.add_argument("--season", type=int)
    sp.add_argument("--week", type=int)
    sp.add_argument("--no-espn", action="store_true")
    tp = sub.add_parser("team")
    tp.add_argument("abbr")
    gp = sub.add_parser("gate")
    gp.add_argument("season", type=int, nargs="?")
    gp.add_argument("week", type=int, nargs="?")
    pp_ = sub.add_parser("player")
    pp_.add_argument("name")
    args = ap.parse_args()
    if args.cmd == "sync":
        s, w = (args.season, args.week) if args.season and args.week else weekof()
        cmd_sync(s, w, use_espn=not args.no_espn and not os.environ.get("ESPN_DISABLE"))
    elif args.cmd == "team":
        cmd_team(args.abbr)
    elif args.cmd == "gate":
        s, w = (args.season, args.week) if args.season and args.week else weekof()
        cmd_gate(s, w)
    elif args.cmd == "player":
        cmd_player(args.name)


if __name__ == "__main__":
    main()
