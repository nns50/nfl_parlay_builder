#!/usr/bin/env python3
"""propquote.py — one-shot player-prop pricing: every posted line, best price per side,
devigged — for ANY prop market (kprice.py generalized per PORT_PLAN §3).

WHY THIS EXISTS (ported doctrine)
    Two standing rules need real prop prices: "never estimate alt prices — books juice
    the safety alt" and "whenever an Over is faded, price the Under." One command:
    resolve the player from the CONTEXT STORE (ID-first, not surname regex), find their
    team's odds event this week, pull <market> + <market>_alternate (~2 credits), print
    best-price-per-side PER LINE with the no-vig split — paste-ready for truep/ticket.

QUOTA
    Refuses to spend when the API reports < CREDIT_FLOOR_PROPS remaining (markets.conf)
    unless --force. Refuses started events (in-game prices are not pre-game lines).

USAGE
    tools/propquote.py "Josh Allen" player_pass_yds
    tools/propquote.py Nacua player_reception_yds --standard-only     # 1 credit
    tools/propquote.py Bass player_field_goals --event <odds_event_id>
    tools/propquote.py "J. Cook" player_rush_yds --season 2026 --week 1
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DB = os.environ.get("NFL_DB", os.path.join(REPO, "data", "context.db"))
CONF = os.path.join(REPO, "config", "markets.conf")
ODDS = os.path.join(HERE, "odds_api.sh")


def conf(key, default=None):
    with open(CONF, encoding="utf-8") as fh:
        for ln in fh:
            if ln.startswith(key + "="):
                return ln.strip().split("=", 1)[1]
    return default


def _ascii(s):
    s = unicodedata.normalize("NFD", s or "")
    return "".join(ch for ch in s if not unicodedata.combining(ch)).lower()


def _sh(args, timeout=60):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout


def imp(price):
    p = float(price)
    return 100.0 / (p + 100.0) if p > 0 else (-p) / ((-p) + 100.0)


# ── pure pricing helpers (selftest-covered; shared shape with the MLB kprice) ──

def best_by_point(event_json, player_name, market_prefix):
    """{point: {'Over'|'Yes': (price, book), …}} best price per side per line for the
    named player across books whose market key starts with market_prefix (catches the
    _alternate variant too). Refuses same-surname ambiguity: >1 distinct description
    matching → {} (caller passes a fuller name)."""
    want = _ascii(player_name)
    table = {}
    names = set()
    for bk in (event_json or {}).get("bookmakers", []):
        book = bk.get("title", "?")
        for mkt in bk.get("markets", []):
            if not str(mkt.get("key", "")).startswith(market_prefix):
                continue
            for o in mkt.get("outcomes", []):
                desc = o.get("description", "")
                if want not in _ascii(desc):
                    continue
                names.add(desc)
                side, pt, pr = o.get("name"), o.get("point"), o.get("price")
                if side is None or pr is None:
                    continue
                pt = pt if pt is not None else 0.0   # Yes/No markets (anytime TD) have no point
                cur = table.setdefault(pt, {})
                if side not in cur or pr > cur[side][0]:
                    cur[side] = (pr, book)
    if len(names) > 1:
        return {}
    return table


def novig_at_point(entry):
    """Two-sided entry → (side_a_novig, side_b_novig) in dict order, or None if
    one-sided (Over/Under or Yes/No alike)."""
    sides = list(entry.keys())
    if len(sides) < 2:
        return None
    ia, ib = imp(entry[sides[0]][0]), imp(entry[sides[1]][0])
    s = ia + ib
    return ia / s, ib / s


# ── resolution via the context store (ID-first, the port's core doctrine) ─────

def resolve_player(namefrag):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT gsis_id, display_name, position, latest_team FROM players "
        "WHERE display_name LIKE ? AND status='ACT' ORDER BY last_season DESC LIMIT 5",
        (f"%{namefrag}%",)).fetchall()
    if not rows:
        rows = con.execute(   # retry without the ACT filter (offseason status quirks)
            "SELECT gsis_id, display_name, position, latest_team FROM players "
            "WHERE display_name LIKE ? ORDER BY last_season DESC LIMIT 5",
            (f"%{namefrag}%",)).fetchall()
    con.close()
    if not rows:
        sys.exit(f"no player matching {namefrag!r} in the store (sync players?)")
    if len(rows) > 1 and _ascii(rows[0]["display_name"]) != _ascii(namefrag):
        listing = "\n  ".join(f"{r['display_name']} ({r['position']}, {r['latest_team']})"
                              for r in rows)
        sys.exit(f"{len(rows)} players match {namefrag!r} — be more specific:\n  {listing}")
    return rows[0]


def team_full_name(abbr):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    r = con.execute("SELECT team_name FROM teams WHERE team_abbr=?", (abbr,)).fetchone()
    con.close()
    if not r:
        sys.exit(f"team {abbr!r} not in teams table")
    return r[0]


def find_event(team_name, scope="reg"):
    """(event_id, commence_iso, matchup) from the FREE events feed."""
    out = _sh(["bash", ODDS, "events", scope])
    hits = []
    for ln in out.splitlines():
        parts = ln.split(None, 2)
        if len(parts) == 3 and _ascii(team_name) in _ascii(parts[2]):
            hits.append((parts[0], parts[1], parts[2]))
    if not hits:
        sys.exit(f"no upcoming odds event for {team_name!r} (bye week / season gap?)")
    return hits[0]     # events feed is chronological — nearest first


def quota_remaining():
    m = re.search(r"remaining:\s*([\d,]+)", _sh(["bash", ODDS, "quota"], 40))
    return int(m.group(1).replace(",", "")) if m else None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("player", help="player name fragment (resolved via the store)")
    ap.add_argument("market", help="prop market key, e.g. player_pass_yds")
    ap.add_argument("--event", help="explicit odds event id (skips resolution)")
    ap.add_argument("--scope", default="reg", choices=("reg", "pre"))
    ap.add_argument("--standard-only", action="store_true",
                    help="skip the _alternate market (1 credit instead of 2)")
    ap.add_argument("--force", action="store_true", help="bypass quota/started guards")
    args = ap.parse_args()

    floor = int(conf("CREDIT_FLOOR_PROPS", "1000"))
    rem = quota_remaining()
    markets = args.market if args.standard_only else f"{args.market},{args.market}_alternate"
    ncred = 1 if args.standard_only else 2
    if not args.force and (rem is None or rem < floor):
        sys.exit(f"⛔ REFUSING to spend ~{ncred} credit(s): API reports {rem} remaining "
                 f"(< CREDIT_FLOOR_PROPS={floor}). Hand-price from a book, or --force.")

    p = resolve_player(args.player)
    if args.event:
        eid, commence, matchup = args.event, None, "(explicit event)"
    else:
        team = team_full_name(p["latest_team"])
        eid, commence, matchup = find_event(team, args.scope)
    if not args.force and commence and commence <= datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"):
        sys.exit(f"⛔ {matchup} already started — the props feed serves IN-GAME prices, "
                 f"not pre-game lines. --force only for research.")

    print(f"{p['display_name']} ({p['position']}, {p['latest_team']}) — {matchup} "
          f"event {eid}\nmarkets: {markets} (~{ncred} credits, {rem} remaining)")
    raw = _sh(["bash", ODDS, "raw",
               f"sports/{conf('SPORT_KEY_REG') if args.scope == 'reg' else conf('SPORT_KEY_PRE')}"
               f"/events/{eid}/odds?regions={conf('REGIONS')}&markets={markets}"
               f"&oddsFormat=american&dateFormat=iso"])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(f"unparseable response: {raw[:200]}")
    if isinstance(data, dict) and data.get("error_code"):
        sys.exit(f"props fetch error: {data.get('error_code')} — {data.get('message', '')[:140]}")

    table = best_by_point(data, p["display_name"], args.market)
    if not table:
        sys.exit("no outcomes for this player in the response — market not posted yet "
                 "(normal outside game week / preseason), tier lacks props, or an "
                 "ambiguous name (pass a fuller one). Coverage row logged either way.")

    def balance(pt):
        nv = novig_at_point(table[pt])
        sides = list(table[pt].keys())
        return abs(nv[0] - 0.5) if nv and len(sides) == 2 else 9
    two_sided = [pt for pt in table if novig_at_point(table[pt])]
    std = min(two_sided, key=balance) if two_sided else None

    print("─" * 76)
    print(f"{'line':>7}  {'best sideA':>18}  {'best sideB':>18}  {'no-vig A%':>9}  {'no-vig B%':>9}")
    for pt in sorted(table):
        e = table[pt]
        sides = list(e.keys())
        a = f"{sides[0]} {e[sides[0]][0]:+.0f} @{e[sides[0]][1]}"
        b = f"{sides[1]} {e[sides[1]][0]:+.0f} @{e[sides[1]][1]}" if len(sides) > 1 else "—"
        nv = novig_at_point(e)
        na = f"{nv[0]*100:.1f}%" if nv else "1-sided"
        nb = f"{nv[1]*100:.1f}%" if nv else ""
        tag = "  ← STANDARD (most balanced juice)" if std is not None and pt == std else ""
        print(f"{pt:>7g}  {a:>18}  {b:>18}  {na:>9}  {nb:>9}{tag}")
    print("─" * 76)
    print("Feed the chosen line into the pricing chain (devig → truep → ticket). Doctrine:")
    print("never assume the safety alt is cheap — price it (the MLB Burns burn, kept).")


if __name__ == "__main__":
    main()
