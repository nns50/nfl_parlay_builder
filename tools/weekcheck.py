#!/usr/bin/env python3
"""weekcheck.py — pre-lock week re-verify: snapshot the premises, diff them MECHANICALLY.

WHY THIS EXISTS (recheck.py generalized — PORT_PLAN §3)
    The MLB burn class this descends from: "the starter I built the leg on is not the
    starter anymore, and nothing noticed." The NFL premises that can silently rot between
    build and kickoff: the starting QB (reprices the whole game), a player's availability
    designation (Q→OUT voids props), the market number itself (spread/total moves past the
    build's basis), the wind forecast crossing the suppression threshold, a flexed/moved
    kickoff, and the game simply having started. The build run SNAPSHOTS all of it
    (committed under data/weeks/ as the audit record); every later run DIFFS live state
    against the snapshot — findings scream BEFORE lock, and exit 1 so a run can't miss it.

USAGE
    tools/weekcheck.py snap [<season> <week>]   # write data/weeks/<S>-W<W>/snapshot.json
    tools/weekcheck.py diff [<season> <week>]   # live vs snapshot; exit 1 on ⚠/⛔
    tools/weekcheck.py --selftest               # offline fixture test of the diff logic

WHAT THE DIFF FLAGS
    ⛔ game started (kickoff passed)      → status gate CLOSED for that game's legs
    ⚠ kickoff moved ≥ 5 min              → flex/reschedule: re-verify everything
    ⚠ QB changed                          → every leg premised on that game is INVALID
    ⚠ availability worsened to OUT/IR     → props void; volume model re-runs for the team
    ⚠ new player listed (was clean)       → re-check dependent legs
    ⚠ spread moved ≥ 1.5 / total ≥ 2.0    → the market re-priced the game past the build
    ⚠ wind crossed the 15 mph threshold   → totals/kick/pass legs re-verify
    ⚠ game gone from the schedule         → PPD/moved: void dependent legs
"""
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DB = os.environ.get("NFL_DB", os.path.join(REPO, "data", "context.db"))
WEEKS_DIR = os.environ.get("NFL_WEEKS_DIR", os.path.join(REPO, "data", "weeks"))

SPREAD_MOVE = 1.5
TOTAL_MOVE = 2.0
WIND_FLAG = 15.0
KICK_MOVE_MIN = 5


# ── state assembly ────────────────────────────────────────────────────────────

def build_state(season, week):
    """The premises worth diffing, from the store (games/availability/weather)."""
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    games = {}
    for g in con.execute("SELECT * FROM games WHERE season=? AND week=?", (season, week)):
        games[g["game_id"]] = {
            "kickoff_utc": g["kickoff_utc"],
            "away": g["away_team"], "home": g["home_team"],
            "away_qb": g["away_qb_name"], "home_qb": g["home_qb_name"],
            "away_qb_id": g["away_qb_id"], "home_qb_id": g["home_qb_id"],
            "spread_line": g["spread_line"], "total_line": g["total_line"],
            "final": g["home_score"] is not None,
        }
    avail = {}
    try:
        for r in con.execute("SELECT gsis_id, name, team, designation, p_plays "
                             "FROM availability WHERE season=? AND week=?", (season, week)):
            avail[r["gsis_id"]] = {"name": r["name"], "team": r["team"],
                                   "designation": r["designation"], "p_plays": r["p_plays"]}
    except sqlite3.OperationalError:
        pass                                  # availability not synced yet — fine
    wind = {}
    try:
        for r in con.execute("SELECT game_id, wind_mph FROM weather"):
            if r["game_id"] in games and r["wind_mph"] is not None:
                wind[r["game_id"]] = r["wind_mph"]
    except sqlite3.OperationalError:
        pass
    con.close()
    return {"season": season, "week": week,
            "taken_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "games": games, "availability": avail, "wind": wind}


# ── pure diff (selftest-covered) ──────────────────────────────────────────────

def diff_states(old, new, now_iso):
    """[(severity, message)] — the whole point. Pure over two state dicts."""
    out = []
    og, ng = old["games"], new["games"]
    for gid, o in og.items():
        n = ng.get(gid)
        label = f"{o['away']}@{o['home']}"
        if n is None:
            out.append(("⚠", f"{label}: game GONE from the schedule — PPD/moved? "
                             f"Void dependent legs."))
            continue
        if not o["final"] and o["kickoff_utc"] and o["kickoff_utc"] <= now_iso:
            out.append(("⛔", f"{label}: kickoff has PASSED ({o['kickoff_utc']}) — "
                             f"status gate CLOSED, cannot lock."))
        if o["kickoff_utc"] and n["kickoff_utc"] and o["kickoff_utc"] != n["kickoff_utc"]:
            try:
                dt_o = datetime.strptime(o["kickoff_utc"], "%Y-%m-%dT%H:%M:%SZ")
                dt_n = datetime.strptime(n["kickoff_utc"], "%Y-%m-%dT%H:%M:%SZ")
                if abs((dt_n - dt_o).total_seconds()) >= KICK_MOVE_MIN * 60:
                    out.append(("⚠", f"{label}: kickoff MOVED {o['kickoff_utc']} → "
                                     f"{n['kickoff_utc']} (flex/reschedule) — re-verify "
                                     f"windows, weather, and every dependent leg."))
            except ValueError:
                pass
        for side in ("away", "home"):
            oq, nq = o.get(f"{side}_qb"), n.get(f"{side}_qb")
            if oq and nq and oq != nq:
                out.append(("⚠", f"{label}: {side.upper()} QB CHANGED {oq} → {nq} — "
                                 f"every leg premised on this game is INVALID "
                                 f"(spread/total/props all reprice)."))
        for field, thresh, name in (("spread_line", SPREAD_MOVE, "spread"),
                                    ("total_line", TOTAL_MOVE, "total")):
            ov, nv = o.get(field), n.get(field)
            if ov is not None and nv is not None and abs(nv - ov) >= thresh:
                out.append(("⚠", f"{label}: {name} MOVED {ov:g} → {nv:g} "
                                 f"(≥{thresh:g}) — the market re-priced this game past "
                                 f"the build's basis; re-derive TrueP before locking."))
    oa, na = old.get("availability", {}), new.get("availability", {})
    for pid, n in na.items():
        o = oa.get(pid)
        if o is None:
            if (n.get("p_plays") or 1) < 1:
                out.append(("⚠", f"{n['name']} ({n['team']}): NEWLY LISTED "
                                 f"{n['designation']} since the snapshot — re-check "
                                 f"dependent legs."))
        elif (n.get("p_plays") or 0) == 0.0 and (o.get("p_plays") or 0) > 0.0:
            out.append(("⚠", f"{n['name']} ({n['team']}): availability WORSENED "
                             f"{o['designation']} → {n['designation']} — props void; "
                             f"re-run the team's volume read."))
    ow, nw = old.get("wind", {}), new.get("wind", {})
    for gid, nv in nw.items():
        ov = ow.get(gid)
        g = ng.get(gid) or og.get(gid) or {}
        label = f"{g.get('away','?')}@{g.get('home','?')}"
        if ov is not None and ov < WIND_FLAG <= nv:
            out.append(("⚠", f"{label}: wind forecast CROSSED {WIND_FLAG:.0f} mph "
                             f"({ov:.0f} → {nv:.0f}) — totals/kicking/pass-yds legs "
                             f"re-verify."))
    return out


# ── commands ──────────────────────────────────────────────────────────────────

def snap_path(season, week):
    return os.path.join(WEEKS_DIR, f"{season}-W{week:02d}", "snapshot.json")


def weekof():
    out = subprocess.run(["python3", os.path.join(HERE, "ingest.py"), "weekof"],
                         capture_output=True, text=True, timeout=30).stdout.split()
    return int(out[0]), int(out[1])


def cmd_snap(season, week):
    st = build_state(season, week)
    if not st["games"]:
        sys.exit(f"no games for {season} W{week} — sync first")
    p = snap_path(season, week)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(st, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(f"snapshot: {len(st['games'])} games, {len(st['availability'])} availability "
          f"rows, {len(st['wind'])} wind reads → {os.path.relpath(p, REPO)}")
    print("→ commit this with the build; later runs diff live state against it.")


def cmd_diff(season, week):
    p = snap_path(season, week)
    if not os.path.exists(p):
        print(f"no snapshot at {os.path.relpath(p, REPO)} — run "
              f"'weekcheck.py snap {season} {week}' at build time first.")
        return 0
    with open(p, encoding="utf-8") as fh:
        old = json.load(fh)
    new = build_state(season, week)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    findings = diff_states(old, new, now_iso)
    print(f"weekcheck {season} W{week}: snapshot {old['taken_at']} vs live now")
    if not findings:
        print("  ✓ no QB changes, no availability drops, no material line moves, "
              "no kickoff/wind changes — premises stand.")
        return 0
    for sev, msg in findings:
        print(f"  {sev} {msg}")
    return 1


def selftest():
    """Offline: every finding class fires on an injected change; unchanged is silent."""
    base = {
        "games": {
            "G1": {"kickoff_utc": "2026-09-13T17:00:00Z", "away": "BUF", "home": "HOU",
                   "away_qb": "Josh Allen", "home_qb": "CJ Stroud",
                   "away_qb_id": "1", "home_qb_id": "2",
                   "spread_line": -1.5, "total_line": 44.5, "final": False},
            "G2": {"kickoff_utc": "2026-09-13T20:25:00Z", "away": "GB", "home": "MIN",
                   "away_qb": "QB A", "home_qb": "QB B", "away_qb_id": "3",
                   "home_qb_id": "4", "spread_line": -1.5, "total_line": 45.5,
                   "final": False},
        },
        "availability": {"P1": {"name": "Star WR", "team": "BUF",
                                "designation": "QUESTIONABLE", "p_plays": 0.75}},
        "wind": {"G1": 8.0},
    }
    import copy
    new = copy.deepcopy(base)
    new["games"]["G1"]["home_qb"] = "Backup Arm"                  # QB change
    new["games"]["G1"]["total_line"] = 41.0                        # total moved 3.5
    new["games"]["G2"]["kickoff_utc"] = "2026-09-14T00:20:00Z"     # flexed
    new["availability"]["P1"] = {"name": "Star WR", "team": "BUF",
                                 "designation": "OUT", "p_plays": 0.0}   # worsened
    new["availability"]["P2"] = {"name": "New Guy", "team": "HOU",
                                 "designation": "DOUBTFUL", "p_plays": 0.25}  # newly listed
    new["wind"]["G1"] = 18.0                                       # crossed 15
    f = diff_states(base, new, "2026-09-12T00:00:00Z")
    msgs = "\n".join(m for _, m in f)
    started = diff_states(base, new, "2026-09-13T18:00:00Z")
    clean = diff_states(base, base, "2026-09-12T00:00:00Z")
    gone = copy.deepcopy(base)
    del gone["games"]["G2"]
    f_gone = diff_states(base, gone, "2026-09-12T00:00:00Z")
    checks = [
        ("QB change flagged", "QB CHANGED CJ Stroud → Backup Arm" in msgs),
        ("total move flagged", "total MOVED 44.5 → 41" in msgs),
        ("unchanged spread silent", "spread MOVED" not in msgs),
        ("kickoff flex flagged", "kickoff MOVED" in msgs),
        ("availability worsened flagged", "WORSENED QUESTIONABLE → OUT" in msgs),
        ("newly listed flagged", "NEWLY LISTED DOUBTFUL" in msgs),
        ("wind crossing flagged", "CROSSED 15 mph" in msgs),
        ("started game ⛔", any(s == "⛔" and "PASSED" in m for s, m in started)),
        ("clean diff is silent", clean == []),
        ("vanished game flagged", any("GONE from the schedule" in m for _, m in f_gone)),
    ]
    bad = [n for n, okk in checks if not okk]
    for n, okk in checks:
        print(f"  {'✓' if okk else '✗'} {n}")
    print(f"── weekcheck self-test: {'ALL PASSED' if not bad else f'{len(bad)} FAILED'}")
    return 0 if not bad else 1


def main():
    args = sys.argv[1:]
    if args and args[0] == "--selftest":
        sys.exit(selftest())
    if not args or args[0] not in ("snap", "diff"):
        print(__doc__)
        sys.exit(1)
    if len(args) >= 3:
        season, week = int(args[1]), int(args[2])
    else:
        season, week = weekof()
    if args[0] == "snap":
        cmd_snap(season, week)
    else:
        sys.exit(cmd_diff(season, week))


if __name__ == "__main__":
    main()
