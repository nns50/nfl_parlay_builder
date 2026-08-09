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
    ap.add_argument("--reseed", action="store_true",
                    help="rewrite config/corr_matrix.csv from the MEASURED rho "
                         "(rho = sin(pi*phi/2), the inverse of the attenuation the "
                         "docstring describes). Only pairs with n>=200 are rewritten.")
    args = ap.parse_args()
    seasons = tuple(int(s) for s in args.seasons.split(","))

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    ph = ",".join("?" * len(seasons))

    # per-player weekly lines (REG only), season medians, team leaders
    rows = con.execute(
        f"SELECT season, week, team, player_id, player_display_name, position, "
        f"passing_yards, attempts, receiving_yards, rushing_yards, carries, "
        f"passing_tds, receiving_tds, rushing_tds, fg_made, pat_made "
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

    # ── EXPANDED COVERAGE (2026-08-09). The matrix shipped 21 rows but only 6 had a
    # measurement path; the 5 that got re-seeded moved by up to 2x IN BOTH DIRECTIONS
    # (team_ml×team_total_o 0.30→0.60, rb_att×qb_att −0.30→−0.15), so the remaining
    # structural guesses could not be trusted either. For a PARLAY these errors compound
    # into the floor, which is the number the whole ticket rests on.
    p7 = []    # qb_pass_yds_o × qb_pass_tds_o (same team)
    p8 = []    # qb_pass_tds_o × anytime_td (same team, WR1 scores)
    p9 = []    # qb_pass_yds_o × game_total_o
    p10 = []   # wr_rec_yds_o × game_total_o
    p11 = []   # team_ml × rb_rush_att_o (same team)
    p12 = []   # rb_rush_yds_o × game_total_u
    p13 = []   # qb_pass_yds_o × team_ml (same team)
    p14 = []   # wr_rec_yds_o × wr_rec_yds_o (two same-team receivers)
    p15 = []   # team_ml × team_total_o (OPPOSING team total)
    p16 = []   # anytime_td × team_total_o (same team)
    p17 = []   # kicker_pts_o × team_total_o (same team)
    p18 = []   # team_spread(cover) × team_ml (same team)
    p19 = []   # anytime_td × game_total_o

    def top2(season, team, pos, field):
        """Two highest-volume players at a position (for the same-team WR pair)."""
        agg = {}
        for r in rows:
            if r["season"] == season and r["team"] == team and r["position"] == pos:
                agg[r["player_id"]] = agg.get(r["player_id"], 0) + (r[field] or 0)
        return [pid for pid, _ in sorted(agg.items(), key=lambda kv: -kv[1])[:2]]

    for season in seasons:
        for team in teams:
            qb = leader(season, team, "QB", "passing_yards")
            wr = leader(season, team, "WR", "receiving_yards")
            rb = leader(season, team, "RB", "rushing_yards")
            k = leader(season, team, "K", "fg_made")
            wr2 = top2(season, team, "WR", "receiving_yards")
            if not qb:
                continue
            qmed = season_median(season, qb, "passing_yards")
            qtmed = season_median(season, qb, "passing_tds")
            wmed = season_median(season, wr, "receiving_yards") if wr else None
            rmed = season_median(season, rb, "rushing_yards") if rb else None
            ramed = season_median(season, rb, "carries") if rb else None
            if qmed is None:
                continue
            for wk, qrow in weekly[(season, qb)].items():
                q_over = (qrow["passing_yards"] or 0) > qmed
                side_g = game_by_team_week.get((season, wk, team))
                if qtmed is not None:
                    p7.append((q_over, (qrow["passing_tds"] or 0) > qtmed))
                if wr and wk in weekly[(season, wr)]:
                    wrow = weekly[(season, wr)][wk]
                    if qtmed is not None:
                        p8.append(((qrow["passing_tds"] or 0) > qtmed,
                                   (wrow["receiving_tds"] or 0) >= 1))
                if not side_g:
                    continue
                side, g = side_g
                own = g["home_score"] if side == "home" else g["away_score"]
                opp = g["away_score"] if side == "home" else g["home_score"]
                won = own > opp
                tl, sp = g["total_line"], from_store_line(g["spread_line"])
                tot = g["home_score"] + g["away_score"]
                p13.append((q_over, won))
                if tl is not None and abs(tot - tl) > 1e-9:
                    p9.append((q_over, tot > tl))
                    if wmed is not None and wk in weekly[(season, wr)]:
                        p10.append(((weekly[(season, wr)][wk]["receiving_yards"] or 0)
                                    > wmed, tot > tl))
                    if rmed is not None and wk in weekly[(season, rb)]:
                        p12.append(((weekly[(season, rb)][wk]["rushing_yards"] or 0)
                                    > rmed, tot < tl))
                if ramed is not None and wk in weekly[(season, rb)]:
                    p11.append((won, (weekly[(season, rb)][wk]["carries"] or 0) > ramed))
                if len(wr2) == 2 and all(wk in weekly[(season, p)] for p in wr2):
                    m0 = season_median(season, wr2[0], "receiving_yards")
                    m1 = season_median(season, wr2[1], "receiving_yards")
                    if m0 is not None and m1 is not None:
                        p14.append(((weekly[(season, wr2[0])][wk]["receiving_yards"] or 0) > m0,
                                    (weekly[(season, wr2[1])][wk]["receiving_yards"] or 0) > m1))
                if sp is not None and tl is not None:
                    hi, ai = implied_totals(sp, tl)
                    own_imp = hi if side == "home" else ai
                    own_over = own > own_imp
                    p15.append((won, (opp > (ai if side == "home" else hi))))
                    margin = own - opp
                    cover_line = -sp if side == "home" else sp
                    if abs(margin + cover_line) > 1e-9:
                        p18.append((margin > -cover_line, won))
                    if wr and wk in weekly[(season, wr)]:
                        p16.append(((weekly[(season, wr)][wk]["receiving_tds"] or 0) >= 1,
                                    own_over))
                    if k and wk in weekly[(season, k)]:
                        krow = weekly[(season, k)][wk]
                        kpts = 3 * (krow["fg_made"] or 0) + (krow["pat_made"] or 0)
                        kmed = season_median(season, k, "fg_made")
                        if kmed is not None:
                            p17.append((kpts > 7, own_over))
                if tl is not None and abs(tot - tl) > 1e-9 and wr and wk in weekly[(season, wr)]:
                    p19.append(((weekly[(season, wr)][wk]["receiving_tds"] or 0) >= 1,
                                tot > tl))

    checks = [
        ("qb_pass_yds_o × wr_rec_yds_o (same team)", 0.45, p1),
        ("team_ml × rb_rush_yds_o (same team)", 0.30, p2),
        ("qb_pass_yds_o × qb_pass_yds_o (opposing)", 0.20, p3),
        ("rb_rush_att_o × qb_pass_att_o (same team)", -0.30, p4),
        ("game_total_o × team_total_o", 0.55, p5),
        ("team_ml × team_total_o (same team)", 0.30, p6),
        ("qb_pass_yds_o × qb_pass_tds_o (same team)", 0.40, p7),
        ("qb_pass_tds_o × anytime_td (same team)", 0.35, p8),
        ("qb_pass_yds_o × game_total_o", 0.35, p9),
        ("wr_rec_yds_o × game_total_o", 0.25, p10),
        ("team_ml × rb_rush_att_o (same team)", 0.35, p11),
        ("rb_rush_yds_o × game_total_u", 0.15, p12),
        ("qb_pass_yds_o × team_ml (same team)", 0.10, p13),
        ("wr_rec_yds_o × wr_rec_yds_o (same team)", -0.15, p14),
        ("team_ml × team_total_o (OPPOSING)", -0.20, p15),
        ("anytime_td × team_total_o (same team)", 0.30, p16),
        ("kicker_pts_o × team_total_o (same team)", 0.30, p17),
        ("team_spread × team_ml (same team)", 0.75, p18),
        ("anytime_td × game_total_o", 0.20, p19),
    ]
    # matrix key for each check, so a measurement can be written back to the CSV
    KEYS = {
        "qb_pass_yds_o × wr_rec_yds_o (same team)": ("qb_pass_yds_o", "wr_rec_yds_o", "Y"),
        "team_ml × rb_rush_yds_o (same team)": ("team_ml", "rb_rush_yds_o", "Y"),
        "qb_pass_yds_o × qb_pass_yds_o (opposing)": ("qb_pass_yds_o", "qb_pass_yds_o", "N"),
        "rb_rush_att_o × qb_pass_att_o (same team)": ("rb_rush_att_o", "qb_pass_att_o", "Y"),
        "game_total_o × team_total_o": ("game_total_o", "team_total_o", "any"),
        "team_ml × team_total_o (same team)": ("team_ml", "team_total_o", "Y"),
        "qb_pass_yds_o × qb_pass_tds_o (same team)": ("qb_pass_yds_o", "qb_pass_tds_o", "Y"),
        "qb_pass_tds_o × anytime_td (same team)": ("qb_pass_tds_o", "anytime_td", "Y"),
        "qb_pass_yds_o × game_total_o": ("qb_pass_yds_o", "game_total_o", "any"),
        "wr_rec_yds_o × game_total_o": ("wr_rec_yds_o", "game_total_o", "any"),
        "team_ml × rb_rush_att_o (same team)": ("team_ml", "rb_rush_att_o", "Y"),
        "rb_rush_yds_o × game_total_u": ("rb_rush_yds_o", "game_total_u", "any"),
        "qb_pass_yds_o × team_ml (same team)": ("qb_pass_yds_o", "team_ml", "Y"),
        "wr_rec_yds_o × wr_rec_yds_o (same team)": ("wr_rec_yds_o", "wr_rec_yds_o", "Y"),
        "team_ml × team_total_o (OPPOSING)": ("team_ml", "team_total_o", "N"),
        "anytime_td × team_total_o (same team)": ("anytime_td", "team_total_o", "Y"),
        "kicker_pts_o × team_total_o (same team)": ("kicker_pts_o", "team_total_o", "Y"),
        "team_spread × team_ml (same team)": ("team_spread", "team_ml", "Y"),
        "anytime_td × game_total_o": ("anytime_td", "game_total_o", "any"),
    }
    measured = {}
    for name, seed, pairs in checks:
        f, n = phi(pairs)
        if f is not None and n >= 200 and name in KEYS:
            measured[KEYS[name]] = (math.sin(math.pi * f / 2), f, n)

    if args.reseed:
        import csv as _csv
        mp = os.path.join(REPO, "config", "corr_matrix.csv")
        with open(mp, newline="", encoding="utf-8") as fh:
            hdr, rows_csv = None, []
            for i, row in enumerate(_csv.reader(fh)):
                if i == 0:
                    hdr = row
                else:
                    rows_csv.append(row)
        changed = 0
        tag = f"backtest-{min(seasons)}-{max(seasons)}"
        for r in rows_csv:
            key = (r[0], r[1], r[2])
            if key not in measured:
                continue
            rho, f, n = measured[key]
            old_rho = r[3]
            new_rho = f"{rho:.2f}"
            if old_rho == new_rho and r[4] == tag:
                continue
            r[3], r[4] = new_rho, tag
            r[5] = (f"measured phi={f:+.3f} n={n} -> rho=sin(pi*phi/2)={rho:+.2f} "
                    f"(was {old_rho})")
            changed += 1
        with open(mp, "w", newline="", encoding="utf-8") as fh:
            w = _csv.writer(fh)
            w.writerow(hdr)
            w.writerows(rows_csv)
        print(f"  ✓ re-seeded {changed} row(s) of config/corr_matrix.csv from measurement")

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
