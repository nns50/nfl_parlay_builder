#!/usr/bin/env python3
"""corr_backtest.py — sanity-check the corr_matrix seeds against HISTORY (M4 acceptance).

WHY THIS EXISTS
    The correlation matrix ships with structural seeds. This measures the EMPIRICAL joint
    behavior of the same leg-family pairs across the store's completed seasons and prints
    them side by side, so the seeds are sanity-checked (sign + ordering) against data
    before any money logic leans on them — and re-seeded from evidence as it accrues.

METHOD
    For player pairs: binary indicators "over his own season median" (players with ≥6
    games), φ (phi) coefficient across team-weeks. For market pairs: actual closing
    lines from schedules (total_line, spread-implied team totals) vs final scores.
    NOTE: φ between Bernoullis UNDER-reads the Gaussian copula ρ that generates them
    (attenuation: for p≈.5, φ ≈ (2/π)·arcsin ρ — e.g. ρ .45 → φ ≈ .30). The check is
    SIGN + ORDERING, not equality; the printout shows the attenuation-adjusted target.

USAGE
    tools/corr_backtest.py [--seasons 2024,2025]
"""
import argparse
import math
import os
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from implied import implied_totals, from_store_line  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("NFL_DB", os.path.join(REPO, "data", "context.db"))


def phi(pairs):
    """φ coefficient for [(a,b)] binary pairs."""
    n = len(pairs)
    if n < 30:
        return None, n
    n11 = sum(1 for a, b in pairs if a and b)
    n10 = sum(1 for a, b in pairs if a and not b)
    n01 = sum(1 for a, b in pairs if not a and b)
    n00 = n - n11 - n10 - n01
    denom = math.sqrt((n11 + n10) * (n01 + n00) * (n11 + n01) * (n10 + n00))
    if denom == 0:
        return None, n
    return (n11 * n00 - n10 * n01) / denom, n


def gauss_to_phi(rho):
    """Expected φ under the copula at p≈0.5 marginals: (2/π)·arcsin(ρ)."""
    return 2 / math.pi * math.asin(max(-1, min(1, rho)))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seasons", default="2024,2025")
    args = ap.parse_args()
    seasons = tuple(int(s) for s in args.seasons.split(","))

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    ph = ",".join("?" * len(seasons))

    # per-player weekly lines (REG only), season medians, team leaders
    rows = con.execute(
        f"SELECT season, week, team, player_id, player_display_name, position, "
        f"passing_yards, attempts, receiving_yards, rushing_yards, carries "
        f"FROM player_week WHERE season IN ({ph}) AND season_type='REG'",
        seasons).fetchall()
    weekly = defaultdict(dict)     # (season,player) -> {week: row}
    totals = defaultdict(float)
    for r in rows:
        weekly[(r["season"], r["player_id"])][r["week"]] = r
        totals[(r["season"], r["team"], r["position"], r["player_id"],
                r["player_display_name"])] += 0  # placeholder; leaders computed below

    def season_median(season, pid, field):
        vals = sorted((r[field] or 0) for r in weekly[(season, pid)].values())
        if len(vals) < 6:
            return None
        m = len(vals) // 2
        return (vals[m] if len(vals) % 2 else (vals[m - 1] + vals[m]) / 2)

    def leader(season, team, pos, field):
        """Team-season leader by summed field at a position."""
        best, best_v = None, -1
        seen = {}
        for r in rows:
            if r["season"] == season and r["team"] == team and r["position"] == pos:
                seen[r["player_id"]] = seen.get(r["player_id"], 0) + (r[field] or 0)
        for pid, v in seen.items():
            if v > best_v:
                best, best_v = pid, v
        return best

    games = con.execute(
        f"SELECT * FROM games WHERE season IN ({ph}) AND game_type='REG' "
        f"AND home_score IS NOT NULL", seasons).fetchall()

    teams = sorted({r["team"] for r in rows if r["team"]})
    checks = []

    # 1. QB pass yds over-median × WR1 rec yds over-median (same team) — seed +0.45
    # 2. team win × RB1 rush yds over-median — seed +0.30
    # 3. opposing QBs both over-median — seed +0.20
    # 4. RB1 rush att over × QB pass att over (same team) — seed −0.30
    p1, p2, p3, p4 = [], [], [], []
    game_by_team_week = {}
    for g in games:
        game_by_team_week[(g["season"], g["week"], g["home_team"])] = ("home", g)
        game_by_team_week[(g["season"], g["week"], g["away_team"])] = ("away", g)
    for season in seasons:
        for team in teams:
            qb = leader(season, team, "QB", "passing_yards")
            wr = leader(season, team, "WR", "receiving_yards")
            rb = leader(season, team, "RB", "rushing_yards")
            if not qb:
                continue
            qmed = season_median(season, qb, "passing_yards")
            qamed = season_median(season, qb, "attempts")
            wmed = season_median(season, wr, "receiving_yards") if wr else None
            rmed = season_median(season, rb, "rushing_yards") if rb else None
            ramed = season_median(season, rb, "carries") if rb else None
            if qmed is None:
                continue
            for wk, qrow in weekly[(season, qb)].items():
                q_over = (qrow["passing_yards"] or 0) > qmed
                if wmed is not None and wk in weekly[(season, wr)]:
                    w_over = (weekly[(season, wr)][wk]["receiving_yards"] or 0) > wmed
                    p1.append((q_over, w_over))
                side_g = game_by_team_week.get((season, wk, team))
                if side_g and rmed is not None and wk in weekly[(season, rb)]:
                    side, g = side_g
                    own = g["home_score"] if side == "home" else g["away_score"]
                    opp = g["away_score"] if side == "home" else g["home_score"]
                    r_over = (weekly[(season, rb)][wk]["rushing_yards"] or 0) > rmed
                    p2.append((own > opp, r_over))
                if (qamed is not None and ramed is not None
                        and wk in weekly[(season, rb)]):
                    qa_over = (qrow["attempts"] or 0) > qamed
                    ra_over = (weekly[(season, rb)][wk]["carries"] or 0) > ramed
                    p4.append((ra_over, qa_over))
    # opposing QBs
    qb_of = {}
    for season in seasons:
        for team in teams:
            q = leader(season, team, "QB", "passing_yards")
            if q and season_median(season, q, "passing_yards") is not None:
                qb_of[(season, team)] = (q, season_median(season, q, "passing_yards"))
    for g in games:
        ka = qb_of.get((g["season"], g["away_team"]))
        kh = qb_of.get((g["season"], g["home_team"]))
        if not ka or not kh:
            continue
        wa = weekly[(g["season"], ka[0])].get(g["week"])
        wh = weekly[(g["season"], kh[0])].get(g["week"])
        if wa is None or wh is None:
            continue
        p3.append(((wa["passing_yards"] or 0) > ka[1], (wh["passing_yards"] or 0) > kh[1]))

    # 5. game total over close × home team total over implied — seed +0.55
    # 6. home win × home implied-total over — seed +0.30
    p5, p6 = [], []
    for g in games:
        sp, tl = from_store_line(g["spread_line"]), g["total_line"]
        if sp is None or tl is None:
            continue
        hi, _ = implied_totals(sp, tl)
        tot = g["home_score"] + g["away_score"]
        if abs(tot - tl) < 1e-9:
            continue
        go = tot > tl
        ho = g["home_score"] > hi
        p5.append((go, ho))
        p6.append((g["home_score"] > g["away_score"], ho))

    checks = [
        ("qb_pass_yds_o × wr_rec_yds_o (same team)", 0.45, p1),
        ("team_ml × rb_rush_yds_o (same team)", 0.30, p2),
        ("qb_pass_yds_o × qb_pass_yds_o (opposing)", 0.20, p3),
        ("rb_rush_att_o × qb_pass_att_o (same team)", -0.30, p4),
        ("game_total_o × team_total_o", 0.55, p5),
        ("team_ml × team_total_o (same team)", 0.30, p6),
    ]
    print("═" * 84)
    print(f"  CORR MATRIX BACKTEST — seasons {seasons}, REG only  "
          f"(φ under-reads Gaussian ρ; check SIGN + ORDERING)")
    print("═" * 84)
    print(f"  {'pair':<44} {'n':>5} {'φ obs':>7} {'φ@seed':>7} {'seed ρ':>7}  verdict")
    ok_all = True
    for name, seed, pairs in checks:
        f, n = phi(pairs)
        if f is None:
            print(f"  {name:<44} {n:>5} {'—':>7} {'—':>7} {seed:>+7.2f}  (n<30 — no read)")
            continue
        target = gauss_to_phi(seed)
        sign_ok = (f > 0) == (seed > 0) if abs(seed) > 0.02 else True
        verdict = "✓ sign agrees" if sign_ok else "✗ SIGN DISAGREES — re-seed"
        ok_all &= sign_ok
        print(f"  {name:<44} {n:>5} {f:>+7.3f} {target:>+7.3f} {seed:>+7.2f}  {verdict}")
    print("─" * 84)
    print("  (φ@seed = the φ the seed ρ would produce at p≈.5 — the attenuation-adjusted "
          "target.\n   Re-seed magnitudes from these once a season of NFL ledger data "
          "accrues; sign disagreements are re-seeded NOW.)")
    print("═" * 84)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
