#!/usr/bin/env python3
"""corr.py — correlation engine v2: matrix-driven, multi-leg, same-game joint pricing.

WHY THIS EXISTS (NFL_REQUIREMENTS §5 — the biggest single delta from MLB)
    The MLB model priced exactly ONE hand-tiered 2-leg pair per ticket and treated 3+
    legs as independent — adequate for MLB, structurally wrong for NFL where the default
    attractive ticket is a same-game stack and nearly every prop pair in a game is
    materially correlated. This engine:
      • takes ρ from config/corr_matrix.csv keyed by LEG FAMILY pair + same-team flag
        (data, versioned, backtestable — hand tiers become the override, not the input);
      • prices N same-game legs jointly via a Gaussian copula (closed-form bivariate
        normal for pairs; seeded Monte-Carlo for 3+ — deterministic across runs);
      • flips ρ sign when a leg is the Under/opposite orientation of its family;
      • consults config/blocked_combos.csv (combinations books refuse / contradictions);
      • returns None for UNKNOWN same-game pairs — the caller must reject or demand an
        explicit tier, never silently assume independence inside one game (ported
        "unclear correlation = one leg per game" doctrine).

LEG DESCRIPTOR (dict): {p: 0..1, game: str, team: str|None, family: str|None}
    family strings: qb_pass_yds_o, wr_rec_yds_o, rb_rush_yds_o, rb_rush_att_o,
    qb_pass_tds_o, qb_pass_att_o, team_ml, team_spread, team_total_o/u,
    game_total_o/u, anytime_td, kicker_pts_o — '_o'/'_u' is the orientation suffix.
"""
import csv
import math
import os
import random
from statistics import NormalDist

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MATRIX_CSV = os.environ.get("NFL_CORR_MATRIX", os.path.join(REPO, "config", "corr_matrix.csv"))
BLOCK_CSV = os.environ.get("NFL_BLOCKLIST", os.path.join(REPO, "config", "blocked_combos.csv"))

ND = NormalDist()

# Legacy qualitative tiers (parlay.py CLI compat + explicit per-pair overrides).
CORR = {
    "strong": 0.45, "moderate": 0.30, "weak": 0.15, "none": 0.0,
    "neg-weak": -0.15, "neg-moderate": -0.30, "neg-strong": -0.45,
}


# ── matrix / blocklist loading ────────────────────────────────────────────────

def _load_pairs(path, value_field):
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            a, b = r["family_a"].strip(), r["family_b"].strip()
            key_t = r["same_team"].strip() or "any"
            val = float(r[value_field]) if value_field == "rho" else r[value_field].strip()
            out[(a, b, key_t)] = val
            out[(b, a, key_t)] = val
    return out


def load_matrix(path=MATRIX_CSV):
    return _load_pairs(path, "rho")


def load_blocklist(path=BLOCK_CSV):
    return _load_pairs(path, "reason")


def split_orientation(family):
    """'game_total_u' → ('game_total_o', -1); 'team_ml' → ('team_ml', +1).
    Canonical storage orientation is '_o' (or none)."""
    f = (family or "").strip()
    if f.endswith("_u"):
        return f[:-2] + "_o", -1
    return f, +1


def _lookup(table, fa, fb, same_team):
    keys = ["Y" if same_team else "N", "any"] if same_team is not None else ["any"]
    for kt in keys:
        if (fa, fb, kt) in table:
            return table[(fa, fb, kt)]
    return None


def pair_rho(leg_a, leg_b, matrix=None):
    """ρ for two legs. 0.0 = known-independent (different games). None = same game
    but the pair is UNKNOWN to the matrix — caller must reject or demand a tier."""
    if leg_a["game"] != leg_b["game"]:
        return 0.0
    matrix = matrix if matrix is not None else load_matrix()
    fa, fb = leg_a.get("family"), leg_b.get("family")
    if not fa or not fb:
        return None
    ta, tb = leg_a.get("team"), leg_b.get("team")
    same_team = (ta == tb) if (ta and tb) else None
    # direct lookup honors explicit mixed-orientation rows (e.g. rush_o × total_u)
    direct = _lookup(matrix, fa, fb, same_team)
    if direct is not None:
        return direct
    ca, sa = split_orientation(fa)
    cb, sb = split_orientation(fb)
    canon = _lookup(matrix, ca, cb, same_team)
    if canon is not None:
        return canon * sa * sb
    return None


def blocked(leg_a, leg_b, blocklist=None):
    """Reason string if this pair is blocked/contradictory, else None."""
    if leg_a["game"] != leg_b["game"]:
        return None
    blocklist = blocklist if blocklist is not None else load_blocklist()
    fa, fb = leg_a.get("family"), leg_b.get("family")
    if not fa or not fb:
        return None
    ta, tb = leg_a.get("team"), leg_b.get("team")
    same_team = (ta == tb) if (ta and tb) else None
    return _lookup(blocklist, fa, fb, same_team)


# ── joint pricing (Gaussian copula) ───────────────────────────────────────────

def _phi(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def bvn_prob(p1, p2, rho):
    """P(both hit) for marginals p1,p2 under a Gaussian copula with correlation rho.
    Closed-form via 1-D Simpson integration: ∫ φ(x)·Φ((z2−ρx)/√(1−ρ²)) dx, x<z1.
    Fréchet-clamped. Pure, fast (~10µs), selftest-pinned against independence/comonotone."""
    lo_bound = max(0.0, p1 + p2 - 1.0)
    hi_bound = min(p1, p2)
    if p1 <= 0 or p2 <= 0:
        return 0.0
    if p1 >= 1:
        return min(p2, 1.0)
    if p2 >= 1:
        return min(p1, 1.0)
    if abs(rho) < 1e-12:
        return p1 * p2
    rho = max(-0.999, min(0.999, rho))
    z1, z2 = ND.inv_cdf(p1), ND.inv_cdf(p2)
    denom = math.sqrt(1 - rho * rho)
    a, b, n = -8.5, z1, 400            # Simpson over x ∈ (-8.5, z1]
    if b <= a:
        return lo_bound
    h = (b - a) / n
    total = 0.0
    for i in range(n + 1):
        x = a + i * h
        w = 1 if i in (0, n) else (4 if i % 2 == 1 else 2)
        total += w * _phi(x) * ND.cdf((z2 - rho * x) / denom)
    j = total * h / 3.0
    return max(lo_bound, min(hi_bound, j))


def cholesky(R):
    """Lower-triangular Cholesky with PSD jitter (a hand-seeded matrix can be slightly
    non-PSD; jitter up to 1e-3 rather than crash)."""
    n = len(R)
    for jit in (0.0, 1e-8, 1e-5, 1e-3):
        A = [[R[i][j] + (jit if i == j else 0.0) for j in range(n)] for i in range(n)]
        L = [[0.0] * n for _ in range(n)]
        ok = True
        for i in range(n):
            for j in range(i + 1):
                s = sum(L[i][k] * L[j][k] for k in range(j))
                if i == j:
                    d = A[i][i] - s
                    if d <= 0:
                        ok = False
                        break
                    L[i][j] = math.sqrt(d)
                else:
                    L[i][j] = (A[i][j] - s) / L[j][j]
            if not ok:
                break
        if ok:
            return L
    raise ValueError("correlation matrix not positive-definite even with jitter")


def joint_prob(probs, R, samples=120_000, seed=0):
    """P(ALL legs hit) under the Gaussian copula with correlation matrix R.
    n=1 exact; n=2 closed-form bvn; n≥3 seeded Monte-Carlo (deterministic)."""
    n = len(probs)
    if n == 0:
        return 1.0
    if n == 1:
        return probs[0]
    if n == 2:
        return bvn_prob(probs[0], probs[1], R[0][1])
    L = cholesky(R)
    z = [ND.inv_cdf(max(1e-9, min(1 - 1e-9, p))) for p in probs]
    rng = random.Random(seed)
    hits = 0
    for _ in range(samples):
        g = [rng.gauss(0, 1) for _ in range(n)]
        ok = True
        for i in range(n):
            x = sum(L[i][k] * g[k] for k in range(i + 1))
            if x >= z[i]:
                ok = False
                break
        hits += ok
    j = hits / samples
    lo = max(0.0, sum(probs) - (n - 1))
    return max(lo, min(min(probs), j))


def build_R(legs, matrix=None, overrides=None):
    """Correlation matrix for a leg list. overrides: {(i,j): rho} explicit tier ρ.
    Unknown same-game pairs come back as None entries in the returned `unknown` list —
    the caller decides legality; R uses 0 for them so pricing can still be shown."""
    matrix = matrix if matrix is not None else load_matrix()
    n = len(legs)
    R = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    unknown = []
    for i in range(n):
        for j in range(i + 1, n):
            if overrides and ((i, j) in overrides or (j, i) in overrides):
                r = overrides.get((i, j), overrides.get((j, i)))
            else:
                r = pair_rho(legs[i], legs[j], matrix)
            if r is None:
                unknown.append((i, j))
                r = 0.0
            R[i][j] = R[j][i] = max(-0.98, min(0.98, r))
    return R, unknown
