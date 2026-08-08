#!/usr/bin/env python3
"""legs.py — the structured leg identity (PORT_PLAN deviation #2) + ledger row plumbing.

WHY THIS EXISTS
    The MLB app's single biggest bug class was leg-as-free-text: every tool re-parsed
    markdown cells with regexes (the selftest there is a museum of the resulting
    regressions). Here every ledger row carries a canonical leg_id; settle/CLV/calib
    JOIN on it structurally and the human-readable label is rendering, never schema.

LEG_ID FORMAT (6 colon-fields; game_id/gsis contain no colons)
    {season}-W{week}:{game_id}:{market}:{side}:{point}:{gsis_id}
    e.g. 2026-W01:2026_01_BUF_HOU:player_pass_yds:Over:249.5:00-0034857
         2026-W01:2026_01_NE_SEA:h2h:SEA::
         2026-W01:2026_01_NE_SEA:spreads:NE:+3.5:
         2026-W01:2026_01_NE_SEA:totals:Under:44.5:
    market = The Odds API market key (or h2h/spreads/totals/team_total).
    side   = team abbr (h2h/spreads), <TEAM>_Over|<TEAM>_Under (team_total),
             or Over/Under/Yes/No (totals/props).
    point  = the line (signed for spreads, from the bet side's perspective); empty for
             h2h/anytime_td.

LEDGER ROW LAYOUT (fixed pipe indexes — cell-surgical writes depend on them)
    | Week | Leg | leg_id | Type | Price | Book | TrueP | ImplP | Edge | Grade
    | Result | Played | CLV | Bucket |
"""
import re

# pipe-split indexes for a ledger row line ("|" col0 empty | Week=1 | ... )
COL = {"week": 1, "leg": 2, "leg_id": 3, "type": 4, "price": 5, "book": 6,
       "truep": 7, "implp": 8, "edge": 9, "grade": 10, "result": 11,
       "played": 12, "clv": 13, "bucket": 14}
N_COLS = 15   # includes leading empty + trailing empty after last pipe

# market key → how it settles from the store
#   ("game",)                     : from games scores (h2h/spreads/totals/team_total)
#   ("stat", col) / ("stat_sum", cols) : player_week column(s) vs point
#   ("stat_flag", cols)           : Yes/No — sum(cols) ≥ 1 (anytime TD)
#   ("manual", reason)            : never auto-settled
MARKET_STAT = {
    "h2h": ("game",), "spreads": ("game",), "totals": ("game",), "team_total": ("game",),
    "player_pass_yds": ("stat", "passing_yards"),
    "player_pass_tds": ("stat", "passing_tds"),
    "player_pass_attempts": ("stat", "attempts"),
    "player_pass_completions": ("stat", "completions"),
    "player_pass_interceptions": ("stat", "passing_interceptions"),
    "player_rush_yds": ("stat", "rushing_yards"),
    "player_rush_attempts": ("stat", "carries"),
    "player_receptions": ("stat", "receptions"),
    "player_reception_yds": ("stat", "receiving_yards"),
    "player_rush_reception_yds": ("stat_sum", ("rushing_yards", "receiving_yards")),
    "player_pass_rush_yds": ("stat_sum", ("passing_yards", "rushing_yards")),
    "player_pass_rush_reception_yds":
        ("stat_sum", ("passing_yards", "rushing_yards", "receiving_yards")),
    "player_anytime_td": ("stat_flag", ("rushing_tds", "receiving_tds")),
    "player_field_goals": ("stat", "fg_made"),
    "player_kicking_points": ("kicking_points",),   # 3*fg_made + pat_made
    # C-tier / settle-fragile — press-box stats don't match pbp-derived counts
    "player_sacks": ("manual", "defensive props settle MANUAL (press-box vs pbp mismatch)"),
    "player_solo_tackles": ("manual", "defensive props settle MANUAL"),
    "player_tackles_assists": ("manual", "defensive props settle MANUAL"),
    "player_pass_longest_completion": ("manual", "longest-play props settle MANUAL"),
    "player_reception_longest": ("manual", "longest-play props settle MANUAL"),
    "player_rush_longest": ("manual", "longest-play props settle MANUAL"),
}

LEGID_RX = re.compile(
    r"^(\d{4})-W(\d{1,2}):([A-Za-z0-9_]+):([A-Za-z0-9_]+):([A-Za-z0-9_]*)"
    r":([^:]*):([^:]*)$")


def format_leg_id(season, week, game_id, market, side, point=None, gsis_id=None):
    pt = "" if point is None else (f"{point:+g}" if market == "spreads" else f"{point:g}")
    return f"{season}-W{week:02d}:{game_id}:{market}:{side}:{pt}:{gsis_id or ''}"


def parse_leg_id(s):
    """→ dict or None. Strips markdown noise defensively (bold, backticks)."""
    m = LEGID_RX.match((s or "").strip().strip("`").replace("**", ""))
    if not m:
        return None
    season, week, game_id, market, side, point_s, gsis = m.groups()
    point = float(point_s) if point_s not in ("", None) else None
    return {"season": int(season), "week": int(week), "game_id": game_id,
            "market": market, "side": side, "point": point,
            "gsis_id": gsis or None}


def split_row(line):
    """Ledger row line → list of stripped cells (raw pipe split, indexes per COL)."""
    return [c.strip() for c in line.split("|")]


def is_leg_row(line):
    c = split_row(line)
    return (len(c) >= N_COLS and c[COL["leg_id"]]
            and parse_leg_id(c[COL["leg_id"]]) is not None)


def set_cell(line, col_index, value):
    """Replace ONE cell of a ledger row, preserving everything else exactly."""
    parts = line.split("|")
    if len(parts) <= col_index:
        return line
    parts[col_index] = f" {value} "
    return "|".join(parts)


# ── settle verdict math (pure; selftest-covered; ports the MLB semantics) ─────

def ou_verdict(side, point, value):
    """Over/Under vs a line; integer lines can Push."""
    if abs(value - point) < 1e-9:
        return "Push"
    if side.lower().startswith("o"):
        return "W" if value > point else "L"
    return "W" if value < point else "L"


def spread_verdict(own, opp, point):
    """Margin-settled (the ported RL-by-MARGIN rule): a −1.5 side must win by 2+."""
    adj = own - opp + point
    if abs(adj) < 1e-9:
        return "Push"
    return "W" if adj > 0 else "L"


def flag_verdict(side, count):
    """Yes/No markets (anytime TD)."""
    hit = count >= 1
    if side.lower().startswith("y"):
        return "W" if hit else "L"
    return "L" if hit else "W"
