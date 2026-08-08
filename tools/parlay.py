#!/usr/bin/env python3
"""parlay.py — true combined probability of a parlay, correlation-aware, vs the offered price.

PORTED INTERFACE (MLB habit-compat), v2 ENGINE: the joint prob now comes from corr.py's
Gaussian copula (closed-form bivariate) instead of the old covariance approximation —
deterministic, Fréchet-safe, and consistent with ticket.py's multi-leg pricing. Tiers map
to the same ρ values as before. For matrix-driven family correlation and whole-ticket
search, use ticket.py — this tool prices ONE ticket you already have in hand.

USAGE
    tools/parlay.py --leg 59:-120 --leg 66:-188                 # independent 2-leg
    tools/parlay.py --leg 59:-120 --leg 66:-188 --corr moderate # same-game, +correlated
    tools/parlay.py --leg 60:-130 --leg 55:+110 --corr moderate --sgp +320
    Each --leg is TrueP%[:americanPrice]. --corr models the 2-leg pair; 3+ legs are
    treated independent here (ticket.py handles N-leg same-game groups).
"""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from corr import CORR, bvn_prob  # noqa: E402 — single source of truth for tiers + joint


def dec_from_american(a):
    return 1 + (a / 100.0 if a > 0 else 100.0 / -a)


def american_from_dec(d):
    if d <= 1:
        return float("nan")
    return (d - 1) * 100 if d >= 2 else -100 / (d - 1)


def parse_leg(s):
    tp, _, price = s.partition(":")
    val = float(tp)
    if val < 1:
        raise ValueError(f"leg TrueP {tp!r} looks like a fraction — use whole-number "
                         f"percent (60, not 0.60)")
    if not (0 < val < 100):
        raise ValueError(f"leg TrueP {tp!r} must be a percent in (0,100)")
    return val / 100.0, (float(price) if price else None)


def gate(edge_pp):
    if edge_pp >= 3:
        return "✓ clears the +3-4pp parlay-anchor bar"
    if edge_pp >= 0:
        return "✗ positive but under the parlay bar — thin, near-fair"
    return "✗ NEGATIVE edge — the price is worse than the true odds (-EV)"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--leg", action="append", required=True)
    ap.add_argument("--corr", default="none", choices=sorted(CORR))
    ap.add_argument("--sgp", type=float, default=None)
    args = ap.parse_args()

    try:
        legs = [parse_leg(x) for x in args.leg]
    except ValueError as e:
        ap.error(str(e))
    probs = [p for p, _ in legs]
    prices = [pr for _, pr in legs]
    naive = math.prod(probs)
    rho = CORR[args.corr]

    if len(legs) == 2 and args.corr != "none":
        true_comb = bvn_prob(probs[0], probs[1], rho)
        corr_note = f"correlation '{args.corr}' (ρ≈{rho:+.2f}, Gaussian copula)"
    else:
        true_comb = naive
        corr_note = "independent (product)"
        if len(legs) != 2 and args.corr != "none":
            corr_note += "  ⚠ --corr models a 2-leg pair only; use ticket.py for N-leg groups"

    print("─" * 64)
    print(f"legs: {', '.join(f'{p*100:.0f}%' + (f'@{pr:+.0f}' if pr else '') for p, pr in legs)}")
    print(f"naive independent combined : {naive*100:5.1f}%")
    print(f"true combined ({corr_note}) : {true_comb*100:5.1f}%")
    if len(legs) == 2 and rho > 0:
        print(f"  → positive correlation ADDS {(true_comb-naive)*100:+.1f}pp of win prob")
    elif len(legs) == 2 and rho < 0:
        print(f"  → negative correlation REMOVES {(naive-true_comb)*100:.1f}pp — these legs "
              f"fight; usually skip")
    fair_dec = 1 / true_comb if true_comb > 0 else float("inf")
    print(f"fair odds for true combined: {fair_dec:.3f} dec ({american_from_dec(fair_dec):+.0f})")
    print("─" * 64)
    if all(pr is not None for pr in prices):
        indep_dec = math.prod(dec_from_american(pr) for pr in prices)
        be = 1 / indep_dec
        ev = true_comb * indep_dec - 1
        edge = (true_comb - be) * 100
        print(f"INDEPENDENT product price  : {indep_dec:.3f} dec ({american_from_dec(indep_dec):+.0f})")
        print(f"  breakeven {be*100:.1f}%  | edge {edge:+.1f}pp | EV {ev*100:+.1f}%  → {gate(edge)}")
        if args.sgp is not None:
            sgp_dec = dec_from_american(args.sgp)
            ev_s = true_comb * sgp_dec - 1
            edge_s = (true_comb - 1 / sgp_dec) * 100
            print(f"SGP offered price          : {sgp_dec:.3f} dec ({args.sgp:+.0f})")
            print(f"  breakeven {100/sgp_dec:.1f}%  | edge {edge_s:+.1f}pp | EV {ev_s*100:+.1f}%  → {gate(edge_s)}")
            better = "SGP" if ev_s > ev else "INDEPENDENT product"
            print("─" * 64)
            print(f"➡ TAKE THE {better} — higher EV ({max(ev_s, ev)*100:+.1f}% vs {min(ev_s, ev)*100:+.1f}%).")
            if args.corr == "none":
                print("  (note: an SGP usually IS correlated — set --corr so the verdict is honest.)")
        else:
            print("─" * 64)
            print(f"➡ Verdict: {gate(edge)}.  Add --sgp <price> to compare a quote.")
    else:
        print("(add :price to each --leg for breakeven / EV / SGP comparison.)")
    print("─" * 64)


if __name__ == "__main__":
    main()
