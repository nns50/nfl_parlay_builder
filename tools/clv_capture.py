#!/usr/bin/env python3
"""clv_capture.py — fill the ledger's CLV cells from window closes, by leg_id.

WHY THIS EXISTS (ported doctrine)
    CLV is the primary scoreboard at small samples — a row without a closing line is
    half-logged. The scheduler's T-5m featured poll IS the close snapshot for each
    window (the cached board); props close from the per-event feed (quota-gated).
    Verdict = closing no-vig vs the row's logged no-vig ImplP, ±0.5pp dead-band:
    `+ 55%cl` / `− 48%cl` / `= 50%cl`. Also prints ⚠ EDGE GONE when the close has
    moved past a TBD leg's TrueP (or inside the +2pp gate) — a leg whose edge
    evaporated at the close must NOT be (re)bet.

HONESTY GUARDS (all ported, all bought with MLB losses)
    • A cache warmed AFTER a game's kickoff holds an IN-GAME line, not a close →
      ⚠ MANUAL, never a fake verdict.
    • The closing board no longer quoting the bet's point (the NUMBER moved) →
      MANUAL with the nearest quoted point's close printed for the hand-fill.
    • One-sided / implausible (≥95%/≤5%) closes → MANUAL.
    • Idempotent: rows with a filled CLV cell are skipped; re-running spends nothing.

USAGE
    tools/clv_capture.py <season> <week>            # read-only proposals
    tools/clv_capture.py <season> <week> --apply    # write CLV cells in place
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from legs import COL, is_leg_row, parse_leg_id, set_cell, split_row  # noqa: E402

DB = os.environ.get("NFL_DB", os.path.join(REPO, "data", "context.db"))
LEDGER = os.environ.get("NFL_LEDGER", os.path.join(REPO, "ledgers", "results_log.md"))
CACHE_DIR = os.path.join(REPO, "data", ".cache")
CONF = os.path.join(REPO, "config", "markets.conf")


def conf(key, default=None):
    with open(CONF, encoding="utf-8") as fh:
        for ln in fh:
            if ln.startswith(key + "="):
                return ln.strip().split("=", 1)[1]
    return default


def imp(price):
    p = float(price)
    return 100.0 / (p + 100.0) if p > 0 else (-p) / ((-p) + 100.0)


def _pct(s):
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", s or "")
    return float(m.group(1)) if m else None


# ── pure close computation from a cached board event (selftest-covered) ───────

def close_novig(event, market, side, point, home_abbr_names):
    """Closing no-vig prob (0-1) for OUR side from one cached event, or (None, why).
    home_abbr_names: {abbr: full_name} for side resolution on h2h/spreads."""
    outs = []
    for bk in (event or {}).get("bookmakers", []):
        for mkt in bk.get("markets", []):
            if mkt.get("key") != market:
                continue
            for o in mkt.get("outcomes", []):
                outs.append((o.get("name", ""), o.get("point"), o.get("price")))
    if not outs:
        return None, f"no {market} prices in the cached close"

    if market == "h2h":
        my_name = home_abbr_names.get(side)
        if not my_name:
            return None, f"cannot resolve side {side!r} to a team name"
        pool = [(n, p) for n, _, p in outs if p is not None]

        def mine(n):
            return n == my_name
    elif market == "totals":
        pool = [(n, p) for n, pt, p in outs
                if p is not None and pt is not None and abs(pt - point) < 1e-9]
        if not pool:
            pts = sorted({pt for _, pt, _ in outs if pt is not None})
            near = min(pts, key=lambda x: abs(x - point)) if pts else None
            return None, (f"closing board no longer quotes total {point:g} "
                          f"(nearest: {near}) — the NUMBER moved; hand-fill the close")

        def mine(n):
            return n == side
    elif market == "spreads":
        my_name = home_abbr_names.get(side)
        if not my_name:
            return None, f"cannot resolve side {side!r}"
        pool = [(n, p) for n, pt, p in outs
                if p is not None and pt is not None and abs(abs(pt) - abs(point)) < 1e-9]
        if not pool:
            return None, f"closing board no longer quotes the ±{abs(point):g} spread"

        def mine(n):
            return n == my_name
    else:
        return None, f"market {market!r} closes via the props feed / manual"

    best = {}
    for n, p in pool:
        if n not in best or p > best[n]:
            best[n] = p
    if len(best) < 2:
        return None, "only one side priced at the close — can't devig"
    my = [n for n in best if mine(n)]
    if len(my) != 1:
        return None, "couldn't isolate our side on the closing board"
    over = sum(imp(p) for p in best.values())
    nv = imp(best[my[0]]) / over
    if nv >= 0.95 or nv <= 0.05:
        return None, "implausible closing no-vig (≥95%/≤5%) — stale/settled feed"
    return (nv, f"close best {my[0]} {best[my[0]]:+.0f} → no-vig {nv*100:.1f}%"), None


def verdict_from_close(closing_pct, implp_pct):
    if implp_pct is None or closing_pct is None:
        return None
    d = closing_pct - implp_pct
    ch = "+" if d > 0.5 else "−" if d < -0.5 else "="
    return f"{ch} {round(closing_pct)}%cl"


def edge_warning(closing_pct, truep_pct):
    if truep_pct is None or closing_pct is None:
        return None
    if closing_pct >= truep_pct:
        return (f"⚠ EDGE GONE at the close — closing no-vig {closing_pct:.1f}% ≥ TrueP "
                f"{truep_pct:.0f}%; do NOT (re)bet at the current number")
    if closing_pct > truep_pct - 2:
        return f"⚠ close leaves {truep_pct - closing_pct:+.1f}pp — under the +2pp gate"
    return None


def cache_is_stale_for(cache_mtime_iso, kickoff_iso):
    return bool(cache_mtime_iso and kickoff_iso and cache_mtime_iso > kickoff_iso)


# ── board/props access ────────────────────────────────────────────────────────

def load_board(season, week):
    sport = conf("SPORT_KEY_REG")
    p = os.path.join(CACHE_DIR, f"board_{sport}_{season}-W{week}.json")
    if not os.path.exists(p):
        return None, None, None
    with open(p, encoding="utf-8") as fh:
        data = json.load(fh)
    mt = datetime.fromtimestamp(os.path.getmtime(p), tz=timezone.utc)
    return data, mt.strftime("%Y-%m-%dT%H:%M:%SZ"), p


def main():
    args = sys.argv[1:]
    apply_mode = "--apply" in args
    pos = [a for a in args if not a.startswith("--")]
    if len(pos) < 2:
        sys.exit("usage: clv_capture.py <season> <week> [--apply]")
    season, week = int(pos[0]), int(pos[1])

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    games = {g["game_id"]: g for g in con.execute(
        "SELECT * FROM games WHERE season=? AND week=?", (season, week))}
    abbr_names = {r["team_abbr"]: r["team_name"] for r in
                  con.execute("SELECT team_abbr, team_name FROM teams")}
    player_names = {r["gsis_id"]: r["display_name"] for r in
                    con.execute("SELECT gsis_id, display_name FROM players")}

    board, cache_ts, board_path = load_board(season, week)
    with open(LEDGER, encoding="utf-8") as fh:
        lines = fh.read().split("\n")

    def find_event(game):
        if not board or not game:
            return None
        an, hn = abbr_names.get(game["away_team"]), abbr_names.get(game["home_team"])
        for ev in board:
            if ev.get("away_team") == an and ev.get("home_team") == hn:
                return ev
        return None

    print("=" * 70)
    print(f"  CLV CAPTURE — {season} W{week}  "
          f"({'APPLY' if apply_mode else 'read-only'})   "
          f"close source: {os.path.basename(board_path) if board else 'NO BOARD CACHE'}"
          f"{f' @ {cache_ts}' if cache_ts else ''}")
    print("=" * 70)

    n_open = applied = 0
    for i, ln in enumerate(lines):
        if not is_leg_row(ln):
            continue
        c = split_row(ln)
        leg = parse_leg_id(c[COL["leg_id"]])
        if leg["season"] != season or leg["week"] != week:
            continue
        if c[COL["clv"]] not in ("—", "-", ""):
            continue                                   # idempotent: filled rows skip
        if "tbd" not in c[COL["result"]].lower():
            pass                                       # decided rows still deserve CLV
        n_open += 1
        game = games.get(leg["game_id"])
        label = c[COL["leg"]][:44]
        pt_txt = f" {leg['point']:g}" if leg["point"] is not None else ""
        print(f"── {label}  [{leg['market']} {leg['side']}{pt_txt}]")
        if leg["market"] in ("h2h", "spreads", "totals"):
            if board is None:
                print("   ⚠ MANUAL — no board cache for this week (run odds_api.sh board)")
                continue
            ev = find_event(game)
            if ev is None:
                print("   ⚠ MANUAL — game not in the cached close board")
                continue
            if cache_is_stale_for(cache_ts, ev.get("commence_time")):
                print("   ⚠ MANUAL — cache warmed AFTER kickoff: in-game line, not a close")
                continue
            got, err = close_novig(ev, leg["market"], leg["side"], leg["point"], abbr_names)
            if err:
                print(f"   ⚠ MANUAL — {err}")
                continue
            nv, desc = got
        elif leg["market"].startswith("player_"):
            print("   ⚠ MANUAL — prop closes come from the per-event feed at the window "
                  "close (scheduler T-5m props poll); hand-fill if that poll was missed")
            continue
        else:
            print("   ⚠ MANUAL — team totals / unrecognized market close by hand")
            continue
        closing_pct = nv * 100
        print(f"   {desc}")
        verdict = verdict_from_close(closing_pct, _pct(c[COL["implp"]]))
        warn = edge_warning(closing_pct, _pct(c[COL["truep"]]))
        if warn:
            print(f"   {warn}")
        if verdict:
            print(f"   → CLV verdict: {verdict}")
            if apply_mode:
                lines[i] = set_cell(lines[i], COL["clv"], verdict)
                applied += 1

    if not n_open:
        print("  (no open-CLV rows for this week)")
    if apply_mode and applied:
        with open(LEDGER, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        print(f"  ✓ wrote {applied} CLV verdict(s)")
    print("=" * 70)


if __name__ == "__main__":
    main()
