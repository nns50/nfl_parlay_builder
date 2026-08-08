#!/usr/bin/env python3
"""poll_scheduler.py — per-kickoff market polling planner + credit budgeter (stdlib only).

WHY THIS EXISTS (PORT_PLAN M2; DATA_SOURCES §1.4)
    The MLB app polled one daily slate on a global refresh. NFL is ~16 events/week
    clustered into ~6 kickoff windows across 5+ days, with per-event-billed props that
    only post in game week. A global loop either goes stale or burns credits pricing
    Sunday's game on Monday. This gives every event a poll plan keyed to ITS OWN
    kickoff (phases from config/markets.conf), batches whatever is due when a run
    fires, and — before any real spend — can DRY-RUN a whole week and price it against
    the budget, so a config change that blows the credit model is caught in planning,
    not on the invoice.

MODES
    plan <season> <week> [--now ISO]   # simulate the whole week: poll counts + credit
                                       # estimate per phase, vs BUDGET_WEEKLY_SOFT
    due  <season> <week> [--now ISO] [--mark] [--skip-quota-check]
                                       # what should be polled RIGHT NOW (consumed by
                                       # runs); --mark stamps state so re-runs inside
                                       # an interval are no-ops (idempotent)

PHASE MODEL
    CADENCE_* = "t_start_min:interval_min,..." — brackets read tightest-last; an event
    at m minutes to kickoff is governed by the LAST phase whose start ≥ m. interval 0 =
    exactly one poll inside that bracket (the CLOSE snapshot, T-5m). m ≤ 0 = started →
    no polling (the in-game-price guard lives in odds_api.sh too).
    Featured polls are SHARED (one board call covers the scope); props are PER EVENT.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CONF = os.path.join(REPO, "config", "markets.conf")
DB = os.environ.get("NFL_DB", os.path.join(REPO, "data", "context.db"))
STATE = os.environ.get("NFL_POLL_STATE",
                       os.path.join(REPO, "data", ".cache", "poll_state.json"))
FEATURED_COST = 3          # 3 featured markets × 1 region
PLAN_LOOKBACK_MIN = 5 * 24 * 60   # "week open" = 5 days before the first kickoff


# ── config / pure helpers (selftest-covered) ──────────────────────────────────

def read_conf(path=CONF):
    out = {}
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, _, v = ln.partition("=")
                out[k.strip()] = v.strip()
    return out


def parse_cadence(spec):
    """'99999:720,4320:480,5:0' → [(99999,720),(4320,480),(5,0)] sorted start-desc."""
    phases = []
    for part in spec.split(","):
        a, _, b = part.strip().partition(":")
        phases.append((int(a), int(b)))
    return sorted(phases, key=lambda p: -p[0])


def interval_for(minutes_to_kick, phases):
    """Governing interval for an event m minutes from kickoff; None = no polling
    (started, or earlier than the widest bracket)."""
    if minutes_to_kick <= 0:
        return None
    governing = None
    for start, interval in phases:          # start-desc; tightest containing wins
        if start >= minutes_to_kick:
            governing = interval
    return governing


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def simulate_week(kickoffs, phases_f, phases_p, n_prop_markets,
                  featured_cost=FEATURED_COST, start=None, props_enabled=True):
    """Pure whole-week simulation → poll/credit counts per stream.
    kickoffs: [datetime]. Ticks 1 minute from `start` (default: first kickoff −
    PLAN_LOOKBACK) to last kickoff. Featured: shared — fires on the TIGHTEST
    interval among live upcoming events; one forced close poll as each close
    bracket opens. Props: per event on its own cadence."""
    kickoffs = sorted(kickoffs)
    if not kickoffs:
        return {"featured_polls": 0, "props_polls": 0, "featured_credits": 0,
                "props_credits": 0, "total_credits": 0, "by_phase": {}}
    t = start or (kickoffs[0] - timedelta(minutes=PLAN_LOOKBACK_MIN))
    end = kickoffs[-1]
    close_start = min((s for s, i in phases_f if i == 0), default=5)
    last_f = None
    # props state is PER EVENT (indexed) — keying by kickoff datetime collapsed the
    # 9 simultaneous Sun-early games into one and undercounted the week 3× (caught
    # by the selftest budget-floor assertion on first run; pinned there).
    last_p = [None] * len(kickoffs)
    f_polls = 0
    p_polls = 0
    by_phase = {}

    def phase_tag(interval):
        return f"int={interval}m" if interval else "close"

    while t <= end:
        mins = {k: (k - t).total_seconds() / 60.0 for k in kickoffs}
        # featured (shared): tightest governing interval among not-started events
        ivals = [interval_for(m, phases_f) for m in mins.values() if m > 0]
        ivals = [i for i in ivals if i is not None]
        fire = False
        tag = None
        if any(0 < m <= close_start for m in mins.values()):
            need_close = any(0 < m <= close_start
                             and (last_f is None or last_f < k - timedelta(minutes=close_start))
                             for k, m in mins.items())
            if need_close:
                fire, tag = True, "close"
        if not fire:
            live = [i for i in ivals if i > 0]
            if live:
                iv = min(live)
                if last_f is None or (t - last_f).total_seconds() / 60.0 >= iv:
                    fire, tag = True, phase_tag(iv)
        if fire:
            f_polls += 1
            last_f = t
            by_phase[f"featured {tag}"] = by_phase.get(f"featured {tag}", 0) + 1
        # props (per event)
        if props_enabled:
            for i, k in enumerate(kickoffs):
                m = (k - t).total_seconds() / 60.0
                iv = interval_for(m, phases_p)
                if iv is None:
                    continue
                if iv == 0:
                    if last_p[i] is None or last_p[i] < k - timedelta(minutes=close_start):
                        p_polls += 1
                        last_p[i] = t
                        by_phase["props close"] = by_phase.get("props close", 0) + 1
                elif last_p[i] is None or (t - last_p[i]).total_seconds() / 60.0 >= iv:
                    p_polls += 1
                    last_p[i] = t
                    by_phase[f"props int={iv}m"] = by_phase.get(f"props int={iv}m", 0) + 1
        t += timedelta(minutes=1)
    return {"featured_polls": f_polls, "props_polls": p_polls,
            "featured_credits": f_polls * featured_cost,
            "props_credits": p_polls * n_prop_markets,
            "total_credits": f_polls * featured_cost + p_polls * n_prop_markets,
            "by_phase": by_phase}


# ── store access ──────────────────────────────────────────────────────────────

def week_games(season, week):
    import sqlite3
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT game_id, away_team, home_team, kickoff_utc, game_type FROM games "
        "WHERE season=? AND week=? AND kickoff_utc IS NOT NULL ORDER BY kickoff_utc",
        (season, week)).fetchall()
    con.close()
    return rows


def quota_remaining():
    try:
        out = subprocess.run(["bash", os.path.join(HERE, "odds_api.sh"), "quota"],
                             capture_output=True, text=True, timeout=40).stdout
        import re
        m = re.search(r"remaining:\s*([\d,]+)", out)
        return int(m.group(1).replace(",", "")) if m else None
    except Exception:  # noqa: BLE001
        return None


# ── modes ─────────────────────────────────────────────────────────────────────

def cmd_plan(season, week, now=None):
    conf = read_conf()
    phases_f = parse_cadence(conf["CADENCE_FEATURED"])
    phases_p = parse_cadence(conf["CADENCE_PROPS"])
    core = [m for m in conf["PROPS_CORE"].split(",") if m]
    budget = int(conf.get("BUDGET_WEEKLY_SOFT", "2500"))
    games = week_games(season, week)
    if not games:
        sys.exit(f"no games for {season} week {week} (run nfl_data.sh sync)")
    props_on = games[0]["game_type"] != "PRE"
    kickoffs = [parse_iso(g["kickoff_utc"]) for g in games]
    res = simulate_week(kickoffs, phases_f, phases_p, len(core),
                        start=parse_iso(now) if now else None, props_enabled=props_on)

    print("═" * 72)
    print(f"  POLL PLAN — {season} week {week} ({games[0]['game_type']}) — "
          f"{len(games)} events, {len(set(g['kickoff_utc'] for g in games))} distinct kickoffs")
    print("═" * 72)
    windows = {}
    for g in games:
        windows.setdefault(g["kickoff_utc"], []).append(f"{g['away_team']}@{g['home_team']}")
    for k in sorted(windows):
        print(f"  {k}  {len(windows[k]):>2} game(s): {', '.join(windows[k][:5])}"
              f"{' …' if len(windows[k]) > 5 else ''}")
    print("─" * 72)
    for tag in sorted(res["by_phase"]):
        print(f"  {tag:<22} {res['by_phase'][tag]:>5} polls")
    print("─" * 72)
    print(f"  featured: {res['featured_polls']} polls × {FEATURED_COST} cr = "
          f"{res['featured_credits']} cr")
    if props_on:
        print(f"  props:    {res['props_polls']} event-polls × {len(core)} markets = "
              f"{res['props_credits']} cr")
    else:
        print("  props:    disabled (preseason — featured only, per doctrine)")
    print(f"  TOTAL ESTIMATE: {res['total_credits']} credits for the week "
          f"(+ alternates on shortlisted legs + CLV backfill reserve)")
    verdict = "✓ within" if res["total_credits"] <= budget else "⚠ EXCEEDS"
    print(f"  BUDGET: {verdict} BUDGET_WEEKLY_SOFT={budget}")
    print("═" * 72)


def load_state():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    return {"featured_last": {}, "props_last": {}}


def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump(st, fh, indent=1, sort_keys=True)


def cmd_due(season, week, now=None, mark=False, skip_quota=False):
    conf = read_conf()
    phases_f = parse_cadence(conf["CADENCE_FEATURED"])
    phases_p = parse_cadence(conf["CADENCE_PROPS"])
    floor_props = int(conf.get("CREDIT_FLOOR_PROPS", "1000"))
    games = week_games(season, week)
    if not games:
        sys.exit(f"no games for {season} week {week}")
    t = parse_iso(now) if now else datetime.now(timezone.utc)
    props_on = games[0]["game_type"] != "PRE"
    scope_key = f"{season}-W{week}"
    st = load_state()
    close_start = min((s for s, i in phases_f if i == 0), default=5)
    due = []

    # featured (shared per scope)
    mins = {g["game_id"]: (parse_iso(g["kickoff_utc"]) - t).total_seconds() / 60.0
            for g in games}
    ivals = [interval_for(m, phases_f) for m in mins.values() if m > 0]
    live = [i for i in ivals if i is not None and i > 0]
    last_f = st["featured_last"].get(scope_key)
    f_due = False
    reason = ""
    if any(0 < m <= close_start for m in mins.values()):
        f_due, reason = True, f"CLOSE snapshot (event inside T-{close_start}m)"
    elif live:
        iv = min(live)
        since = None if not last_f else (t - parse_iso(last_f)).total_seconds() / 60.0
        if since is None or since >= iv:
            f_due, reason = True, f"interval {iv}m ({'never polled' if since is None else f'{since:.0f}m since last'})"
    if f_due:
        due.append(("FEATURED", scope_key, reason))

    # props (per event)
    if props_on:
        rich = True
        if not skip_quota:
            rem = quota_remaining()
            rich = rem is not None and rem >= floor_props
            if not rich:
                due.append(("NOTE", "props suppressed",
                            f"quota {rem} < CREDIT_FLOOR_PROPS={floor_props}"))
        if rich:
            for g in games:
                m = mins[g["game_id"]]
                iv = interval_for(m, phases_p)
                if iv is None:
                    continue
                last = st["props_last"].get(g["game_id"])
                since = None if not last else (t - parse_iso(last)).total_seconds() / 60.0
                if iv == 0:
                    ko = parse_iso(g["kickoff_utc"])
                    if last is None or parse_iso(last) < ko - timedelta(minutes=close_start):
                        due.append(("PROPS", g["game_id"],
                                    f"{g['away_team']}@{g['home_team']} CLOSE (T-{m:.0f}m)"))
                elif since is None or since >= iv:
                    due.append(("PROPS", g["game_id"],
                                f"{g['away_team']}@{g['home_team']} T-{m/60:.1f}h interval {iv}m"))

    if not due:
        print(f"  (nothing due at {iso(t)} — next phases idle)")
        return
    for kind, key, why in due:
        print(f"  {kind:<9} {key:<28} {why}")
    if mark:
        tstamp = iso(t)
        for kind, key, _ in due:
            if kind == "FEATURED":
                st["featured_last"][scope_key] = tstamp
            elif kind == "PROPS":
                st["props_last"][key] = tstamp
        save_state(st)
        print(f"  → state marked at {tstamp} ({STATE})")


def main():
    args = [a for a in sys.argv[1:]]
    flags = {a for a in args if a.startswith("--") and ":" not in a and "T" not in a}
    now = None
    if "--now" in args:
        now = args[args.index("--now") + 1]
    pos = [a for a in args if not a.startswith("--") and a != now]
    if len(pos) >= 3 and pos[0] in ("plan", "due"):
        cmd, season, week = pos[0], int(pos[1]), int(pos[2])
        if cmd == "plan":
            cmd_plan(season, week, now)
        else:
            cmd_due(season, week, now, mark="--mark" in flags,
                    skip_quota="--skip-quota-check" in flags)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
