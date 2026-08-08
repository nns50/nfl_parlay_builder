#!/usr/bin/env python3
"""truep.py — derive a pre-registered TrueP from a market baseline + FIXED adjustments.

PORTED MECHANISM (unchanged from the MLB app — it's the part that measured best):
    TrueP = market NO-VIG baseline (run devig.sh first) + PRE-SET, named adjustments with
    fixed pp magnitudes, so calibration measures the ADJUSTMENTS, not a gut number. A bare
    gut TrueP is calibration-invalid. Emits the machine-readable [adj: …] ledger tag; the
    measurement layer (M6 calib) scores each adjustment's skill from tagged rows.

NFL REGISTRY (all magnitudes are DIRECTIONAL SEEDS — no NFL ledger evidence exists yet;
    each entry accrues its own attribution record and gets resized only at the n≥20-30
    bar, exactly like the MLB registry lifecycle. MLB magnitudes did NOT port; these are
    structural priors from NFL_REQUIREMENTS §4.)

RULES (ported): --custom HARD-CAPPED at ±3 (a conviction >3pp must be a NAMED tag so it
    accrues a record); `~name` mirrors an adjustment's sign onto the other side.

USAGE
    tools/truep.py --list
    tools/truep.py --base-prob 54.3 --adj script_rush_fav
    tools/truep.py --base-prob 56.7 --custom "-2:short reason"
"""
import argparse

# name -> (pp, description). Direction-explicit: each entry states which SIDE it aids.
ADJUSTMENTS = {
    # ── game script (the load-bearing new concept — NFL_REQUIREMENTS §4.2) ──
    "script_rush_fav":   (+3, "RB rush-volume Over on a 3+ point favorite (favorites run late)"),
    "script_pass_dog":   (+3, "pass-volume Over (att/comp/rec) on a 3+ point dog / high total"),
    "blowout_snap_cap":  (-3, "starter volume Over on a 10+ point favorite (garbage-time rest)"),
    # ── rest / travel ──
    "rest_edge":         (+2, "our side has a 3+ day rest edge (post-bye vs short week)"),
    "short_week_road":   (-2, "road team on a short week (TNF travel spot)"),
    "intl_travel":       (-2, "team crossing 5+ timezones for an international site"),
    # ── weather (gates via weather.py; NOISIER than volume edges — don't stack) ──
    "wind_under":        (+4, "wind ≥15mph aids a game/team-total UNDER"),
    "wind_pass_fade":    (-3, "wind ≥15mph hurts pass-yds / deep-shot Overs"),
    "wind_kicker_fade":  (-4, "wind ≥15mph hurts FG/kicking-points Overs"),
    "precip_under":      (+2, "meaningful precip probability aids an UNDER"),
    "dome_pass_over":    (+2, "dome aids passing efficiency / totals Overs (mild)"),
    "cold_under":        (+2, "≤20°F aids an UNDER (kicking + passing efficiency)"),
    # ── matchup (store-backed reads — M4 seeds, deterministic sources cited per leg) ──
    "pass_funnel_def":   (+2, "defense funnels to the pass (strong run D, soft coverage)"),
    "run_funnel_def":    (+2, "defense funnels to the run — aids rush-volume Overs"),
    "ol_mismatch_sacks": (+3, "bad OL vs strong rush aids sack props / QB-under reads"),
    # ── market structure ──
    "market_disagrees":  (-4, "liquid market sits ≥5pp below the model — it sees something "
                              "(availability, weather, script); shade toward the line"),
    "key_number_edge":   (+2, "spread crossing a key number (3/7) in our favor vs the alt price"),
}


def fmt_registry():
    out = ["NFL adjustment registry (name: pp — description) — ALL DIRECTIONAL SEEDS:"]
    for k, (pp, desc) in ADJUSTMENTS.items():
        out.append(f"  {k:<18} {pp:+d}pp   {desc}")
    out.append("  custom             ±N    ad-hoc via --custom \"+N:reason\" (HARD CAP ±3)")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Derive a pre-registered TrueP from baseline + fixed adjustments.")
    ap.add_argument("--base-prob", type=float, help="market NO-VIG prob in %% (from devig.sh)")
    ap.add_argument("--adj", default="", help="comma-separated named adjustments (see --list)")
    ap.add_argument("--custom", action="append", default=[], help='ad-hoc "+N:reason" (repeatable)')
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        print(fmt_registry())
        return
    if args.base_prob is None:
        ap.error("--base-prob is required (the market no-vig prob; run devig.sh first).")

    base = args.base_prob
    applied = []
    resolved = []
    for n in [a.strip() for a in args.adj.split(",") if a.strip()]:
        mirrored = n.startswith("~")
        key = n[1:] if mirrored else n
        if key not in ADJUSTMENTS:
            ap.error(f"unknown adjustment {key!r}. Use --list.")
        pp, desc = ADJUSTMENTS[key]
        if mirrored:
            pp = -pp
        applied.append((f"{key} ({'MIRRORED: ' if mirrored else ''}{desc})", pp))
        resolved.append((key, pp))

    for c in args.custom:
        if ":" not in c:
            ap.error(f'--custom must look like "+N:reason", got {c!r}')
        mag, _, reason = c.partition(":")
        try:
            pp = float(mag)
        except ValueError:
            ap.error(f"--custom magnitude {mag!r} is not a number")
        if abs(pp) > 3.0:
            ap.error(f"--custom {pp:+g}pp exceeds the ±3 cap (ported rule: the MLB ledger "
                     f"measured the ad-hoc class at ~zero skill — no unregistered conviction "
                     f"may claim more than the class ever demonstrated). Register a NAMED "
                     f"tag instead so it accrues its own attribution record.")
        applied.append((f"custom: {reason.strip()}", pp))

    total = sum(pp for _, pp in applied)
    truep = max(1.0, min(99.0, base + total))

    print("─" * 60)
    print(f"baseline (market no-vig)         {base:6.1f}%")
    if applied:
        print("adjustments:")
        for label, pp in applied:
            print(f"  {pp:+5.1f}pp  {label}")
    else:
        print("adjustments:                     (none — TrueP = market no-vig)")
    print("─" * 60)
    print(f"net adjustment                   {total:+6.1f}pp")
    print(f"TrueP (clamped 1–99)             {truep:6.1f}%")
    print(f"pre-registered edge vs baseline  {truep - base:+6.1f}pp")
    print("─" * 60)
    tag_parts = [f"{key}{pp:+g}" for key, pp in resolved]
    tag_parts += [f"custom{float(c.partition(':')[0]):+g}" for c in args.custom]
    tag = f"[adj: {', '.join(tag_parts)}]" if tag_parts else "[adj: none]"
    print(f"Ledger tag — paste into the leg cell: {tag}")
    print("Log this TrueP at BET TIME (never reconstruct). Edge vs the BEST-priced no-vig")
    print("line is the min-edge gate: ≥+2pp standalone / ≥+3-4pp parlay anchor.")


if __name__ == "__main__":
    main()
