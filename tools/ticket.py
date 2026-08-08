#!/usr/bin/env python3
"""ticket.py — exhaustive target-band ticket search, re-engined on corr.py (PORT_PLAN §3).

PORTED (the MLB construction lessons, bought with money): construction is a SEARCH, not an
assembly; the payout/floor FRONTIER makes the band's cost visible; the band pick is the
max-floor route to the payout; ¼-Kelly on the ticket's own edge; NO BET is a valid output.

RE-ENGINED FOR NFL: same-game combos are the DEFAULT ticket shape, not the exception —
    • ρ comes from config/corr_matrix.csv via each leg's FAMILY (+ team side); a declared
      tier is the explicit override for that game's pair;
    • same-game groups of 2-3 legs price jointly via the Gaussian copula (corr.joint_prob)
      — the old one-pair-per-ticket limit is superseded by the engine;
    • blocked combos (config/blocked_combos.csv) are rejected with the reason;
    • negative-ρ pairs are rejected (legs fight — ported doctrine);
    • an UNKNOWN same-game pair (no family match, no tier) is rejected: unclear
      correlation is still one-leg-per-game, never silently assumed independent;
    • every same-game group in the band pick prints its MIN ACCEPTABLE SGP QUOTE.

LEG FORMAT (repeatable --leg, or --file, '#' comments ok)
    TrueP:price:game[:label[:famOrTier[:team]]]
      TrueP   whole-number percent (the PRE-REGISTERED true prob)
      price   BEST shopped American price
      game    shared id for same-game legs (e.g. 2026_01_BUF_HOU)
      label   free text ("Allen O249.5 pass yds")
      famOrTier  a corr family (qb_pass_yds_o, team_ml, game_total_u, …) — matrix ρ;
                 OR a legacy tier (strong/moderate/weak/neg-*) — explicit pair override
      team    team abbr for the family's side (resolves same-team vs opposing rows)

USAGE
    tools/ticket.py --leg "60:-140:G1:BUF ML:team_ml:BUF" \\
                    --leg "58:-115:G1:Allen O249.5:qb_pass_yds_o:BUF" \\
                    --leg "57:-110:G2:Total U44.5:game_total_u"
    tools/ticket.py --file legs.txt --min-price 180 --max-price 260 --top 5
"""
import argparse
import itertools
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from corr import (CORR, blocked, build_R, joint_prob, load_blocklist,  # noqa: E402
                  load_matrix, pair_rho)
from parlay import american_from_dec, dec_from_american  # noqa: E402


def parse_leg(spec):
    parts = spec.split(":")
    if len(parts) < 3:
        raise ValueError(f"leg {spec!r}: need TrueP:price:game[:label[:famOrTier[:team]]]")
    tp = float(parts[0])
    if tp < 1:
        raise ValueError(f"leg {spec!r}: TrueP looks like a fraction — whole-number percent")
    if not (0 < tp < 100):
        raise ValueError(f"leg {spec!r}: TrueP must be in (0,100)")
    price = float(parts[1])
    if abs(price) < 100:
        raise ValueError(f"leg {spec!r}: price {parts[1]!r} isn't American odds")
    game = parts[2].strip()
    if not game:
        raise ValueError(f"leg {spec!r}: empty game id")
    label = parts[3].strip() if len(parts) > 3 and parts[3].strip() else f"{tp:.0f}%@{price:+.0f}"
    fot = parts[4].strip() if len(parts) > 4 and parts[4].strip() else None
    team = parts[5].strip().upper() if len(parts) > 5 and parts[5].strip() else None
    tier, family = None, None
    if fot:
        if fot in CORR:
            tier = fot
        else:
            family = fot
    dec = dec_from_american(price)
    return {"p": tp / 100.0, "price": price, "dec": dec, "game": game, "label": label,
            "tier": tier, "family": family, "team": team,
            "edge_pp": (tp / 100.0 - 1.0 / dec) * 100}


def group_by_game(legs):
    by = {}
    for l in legs:
        by.setdefault(l["game"], []).append(l)
    return by


def legality(legs, matrix, blocklist):
    """(ok, reason). Doctrine: blocked pairs, negative-ρ pairs, and UNKNOWN same-game
    pairs are all illegal constructions."""
    for gl in group_by_game(legs).values():
        if len(gl) > 3:
            return False, f"{gl[0]['game']}: >3 legs in one game"
        for a, b in itertools.combinations(gl, 2):
            reason = blocked(a, b, blocklist)
            if reason:
                return False, f"{a['game']}: BLOCKED — {reason}"
            if a["tier"] and b["tier"]:
                if a["tier"] != b["tier"]:
                    return False, f"{a['game']}: contradictory tiers ({a['tier']} vs {b['tier']})"
                r = CORR[a["tier"]]
            else:
                r = pair_rho(a, b, matrix)
            if r is None:
                return False, (f"{a['game']}: unknown same-game correlation "
                               f"({a['label']} × {b['label']}) — declare families or a "
                               f"tier, or one leg per game")
            if r < 0:
                return False, (f"{a['game']}: negatively-correlated pair "
                               f"(ρ={r:+.2f}) — legs fight; skip")
    return True, None


def ticket_prob(legs, matrix):
    """True combined prob: independent across games, copula-joint within each game.
    Returns (p, notes)."""
    p = 1.0
    notes = []
    for game, gl in group_by_game(legs).items():
        if len(gl) == 1:
            p *= gl[0]["p"]
            continue
        overrides = {}
        for i, j in itertools.combinations(range(len(gl)), 2):
            if gl[i]["tier"] and gl[j]["tier"] and gl[i]["tier"] == gl[j]["tier"]:
                overrides[(i, j)] = CORR[gl[i]["tier"]]
        R, _ = build_R(gl, matrix, overrides)
        gp = joint_prob([l["p"] for l in gl], R)
        p *= gp
        rho_txt = ",".join(f"{R[i][j]:+.2f}" for i, j in
                           itertools.combinations(range(len(gl)), 2))
        notes.append(f"{game} {len(gl)}-leg stack (ρ {rho_txt}) joint {gp*100:.1f}%")
    return p, notes


def quarter_kelly(p, dec, cap=2.0):
    b = dec - 1.0
    if b <= 0:
        return 0.0
    f = (p * dec - 1.0) / b
    return max(0.0, min(cap, f * 25.0))


def min_sgp_price(group_p, floor_edge_pp=3.0):
    be = group_p - floor_edge_pp / 100.0
    if be <= 0:
        return None
    return american_from_dec(1.0 / be)


def fmt_ticket(t, show_kelly=True):
    legs = " × ".join(f"{l['label']} {l['price']:+.0f}" for l in t["legs"])
    line = (f"{t['payout']:+.0f}  floor {t['p']*100:5.1f}%  edge {t['edge_pp']:+5.1f}pp  "
            f"EV {t['ev']*100:+6.1f}%  | {legs}")
    if t["notes"]:
        line += f"  [{'; '.join(t['notes'])}]"
    if show_kelly:
        line += f"  | ¼-Kelly {quarter_kelly(t['p'], t['dec']):.2f}u"
    return line


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--leg", action="append", default=[])
    ap.add_argument("--file")
    ap.add_argument("--min-price", type=float, default=180)
    ap.add_argument("--max-price", type=float, default=260)
    ap.add_argument("--max-legs", type=int, default=3, choices=(1, 2, 3, 4))
    ap.add_argument("--min-edge", type=float, default=0.0,
                    help="drop legs below this TrueP−breakeven edge (vig included); the "
                         "no-vig +2pp/+3-4pp doctrine gate happens UPSTREAM via devig.sh")
    ap.add_argument("--top", type=int, default=5)
    args = ap.parse_args()

    specs = list(args.leg)
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            specs += [ln.strip() for ln in fh if ln.strip() and not ln.strip().startswith("#")]
    if len(specs) < 2:
        ap.error("need at least 2 legs (via --leg / --file)")
    try:
        pool = [parse_leg(s) for s in specs]
    except ValueError as e:
        ap.error(str(e))

    matrix = load_matrix()
    blocklist = load_blocklist()

    print("═" * 78)
    print("LEG POOL  (edge = TrueP − price breakeven, vig INCLUDED; the no-vig gate ran upstream)")
    thin = []
    for l in pool:
        g = "✓" if l["edge_pp"] >= args.min_edge else "✗ thin"
        extra = f"  fam={l['family']}@{l['team'] or '?'}" if l["family"] else \
                (f"  tier={l['tier']}" if l["tier"] else "")
        print(f"  {g}  {l['label']:<30} {l['price']:+7.0f}  TrueP {l['p']*100:4.1f}%  "
              f"be {100/l['dec']:4.1f}%  edge {l['edge_pp']:+5.1f}pp  game {l['game']}{extra}")
        if l["edge_pp"] < args.min_edge:
            thin.append(l["label"])
    kept = [l for l in pool if l["edge_pp"] >= args.min_edge]
    if thin:
        print(f"  → dropped {len(thin)} thin leg(s): {', '.join(thin)}")
    if not kept:
        print("  NO legs clear the bar → NO BET is the honest output.")
        return

    tickets, rejected = [], []
    for n in range(1, min(args.max_legs, len(kept)) + 1):
        for combo in itertools.combinations(kept, n):
            ok, why = legality(list(combo), matrix, blocklist)
            if not ok:
                rejected.append((combo, why))
                continue
            p, notes = ticket_prob(list(combo), matrix)
            dec = math.prod(l["dec"] for l in combo)
            tickets.append({"legs": combo, "p": p, "dec": dec,
                            "payout": american_from_dec(dec),
                            "ev": p * dec - 1.0, "edge_pp": (p - 1.0 / dec) * 100,
                            "notes": notes or (["SINGLE"] if n == 1 else [])})

    frontier = []
    for t in sorted(tickets, key=lambda t: (-t["p"], -t["payout"])):
        if not any(f["payout"] >= t["payout"] and f["p"] >= t["p"] and f is not t
                   for f in frontier):
            frontier.append(t)
    frontier.sort(key=lambda t: t["payout"])
    print("─" * 78)
    print("PAYOUT / FLOOR FRONTIER  (what each payout band truly costs in win prob)")
    for t in frontier:
        print("  " + fmt_ticket(t, show_kelly=False))

    band = sorted((t for t in tickets if args.min_price <= t["payout"] <= args.max_price),
                  key=lambda t: (-t["p"], -t["ev"]))
    print("─" * 78)
    print(f"TARGET BAND {args.min_price:+.0f}..{args.max_price:+.0f} — ranked by TRUE "
          f"COMBINED PROB (max-floor route to the payout)")
    if not band:
        print("  ∅ no construction reaches the band from these legs.")
        near = min(tickets, key=lambda t: abs(t["payout"] - (args.min_price + args.max_price) / 2),
                   default=None)
        if near:
            print("  closest: " + fmt_ticket(near))
        print("  Honest options: best-floor ticket BELOW the band, or NO BET — never bolt on "
              "a thin leg to reach the number (the ported D1 lesson).")
    else:
        for i, t in enumerate(band[:args.top]):
            tag = "➡ RECOMMENDED" if i == 0 else f"  #{i+1}"
            print(f"{tag}  {fmt_ticket(t)}")
            for game, gl in group_by_game(list(t["legs"])).items():
                if len(gl) < 2:
                    continue
                overrides = {}
                for a, b in itertools.combinations(range(len(gl)), 2):
                    if gl[a]["tier"] and gl[b]["tier"]:
                        overrides[(a, b)] = CORR[gl[a]["tier"]]
                R, _ = build_R(gl, matrix, overrides)
                gp = joint_prob([l["p"] for l in gl], R)
                msp = min_sgp_price(gp)
                if msp is not None:
                    print(f"      {game} stack books as an SGP — worth taking only if the "
                          f"quote beats {msp:+.0f} (edge ≥ +3pp); else bet the legs separately.")
        best_any = max(tickets, key=lambda t: t["p"])
        if band and best_any["p"] > band[0]["p"] + 1e-9:
            print(f"  ⚖ floor cost of the band: best ANY-payout construction is "
                  f"{best_any['p']*100:.1f}% at {best_any['payout']:+.0f} "
                  f"({(best_any['p']-band[0]['p'])*100:.1f}pp higher floor).")

    if rejected:
        print("─" * 78)
        print("REJECTED CONSTRUCTIONS")
        seen = set()
        for combo, why in rejected:
            if why in seen:
                continue
            seen.add(why)
            print(f"  ✗ {' × '.join(l['label'] for l in combo)} — {why}")
    print("═" * 78)
    print("Reminder: a parlay is still chalk×vig — the Tier-1 standalone is where measured "
          "edge lives. This tool only stops the band pick from being worse than it must be.")


if __name__ == "__main__":
    main()
