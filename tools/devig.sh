#!/usr/bin/env bash
#
# devig.sh — no-vig (devigged) implied-prob + edge calculator.
#
# WHY THIS EXISTS
#   Every build hand-computes the devig (raw implied → divide by the overround → no-vig)
#   and then Edge = TrueP − no-vig ImplP. Doing it by hand is slow and the arithmetic
#   slips (the reason calib.py exists). This does it deterministically so the
#   min-edge gate is computed off correct numbers.
#
# USAGE
#   tools/devig.sh <priceA> <priceB> [TrueP_for_A]
#       Two-sided market (the normal case). Devigs both sides; if TrueP% for side A is
#       given, prints Edge = TrueP − no-vig(A) and the gate verdict.
#       e.g.  tools/devig.sh -130 +110 59
#
#   tools/devig.sh <priceA> [TrueP_for_A]
#       One-sided (a prop with no posted other side). Can't devig exactly → estimates
#       no-vig by removing ~2.5pp of typical hold, and FLAGS it as an estimate.
#       e.g.  tools/devig.sh +182 60
#
# American odds: favorite negative (-130), underdog positive (+110).
set -uo pipefail

die() { echo "error: $*" >&2; exit 1; }

# american -> raw implied prob (0..1)
implied() {
  awk -v o="$1" 'BEGIN{
    if (o ~ /^[+-]?[0-9]+(\.[0-9]+)?$/) {
      if (o < 0) printf "%.6f", (-o)/((-o)+100);
      else       printf "%.6f", 100/(o+100);
    } else { print "NaN"; }
  }'
}

is_num() { [[ "$1" =~ ^[+-]?[0-9]+(\.[0-9]+)?$ ]]; }

[[ $# -ge 1 ]] || die "need at least one price. See header for usage."

A="$1"
is_num "$A" || die "priceA '$A' is not a number (use American odds like -130 or +110)."

# Decide one- vs two-sided: if $2 exists and looks like a price (|.|>=100 or has sign), treat as priceB.
B=""; TRUEP=""
if [[ $# -ge 2 ]]; then
  if is_num "$2" && awk -v x="$2" 'BEGIN{exit !(x<=-100 || x>=100)}'; then
    B="$2"; [[ $# -ge 3 ]] && TRUEP="$3"
  else
    TRUEP="$2"   # second arg is a TrueP%, one-sided market
  fi
fi

rawA=$(implied "$A")
echo "─────────────────────────────────────────────"
if [[ -n "$B" ]]; then
  is_num "$B" || die "priceB '$B' is not a number."
  rawB=$(implied "$B")
  read -r novigA novigB hold < <(awk -v a="$rawA" -v b="$rawB" 'BEGIN{
    s=a+b; printf "%.4f %.4f %.4f", a/s, b/s, (s-1);
  }')
  printf "Side A  %+6s : raw %5.1f%%  → no-vig %5.1f%%\n" "$A" "$(awk -v x="$rawA" 'BEGIN{print x*100}')" "$(awk -v x="$novigA" 'BEGIN{print x*100}')"
  printf "Side B  %+6s : raw %5.1f%%  → no-vig %5.1f%%\n" "$B" "$(awk -v x="$rawB" 'BEGIN{print x*100}')" "$(awk -v x="$novigB" 'BEGIN{print x*100}')"
  printf "Hold (overround): %.1f%%\n" "$(awk -v x="$hold" 'BEGIN{print x*100}')"
  novig_for_edge="$novigA"
else
  novig_for_edge=$(awk -v a="$rawA" 'BEGIN{e=a-0.025; if(e<0)e=0; printf "%.4f", e}')
  printf "Side A  %+6s : raw %5.1f%%\n" "$A" "$(awk -v x="$rawA" 'BEGIN{print x*100}')"
  printf "ONE-SIDED → no posted other side; no-vig ESTIMATED as raw − 2.5pp = %5.1f%%  ⚠ flag as estimate\n" \
    "$(awk -v x="$novig_for_edge" 'BEGIN{print x*100}')"
fi

if [[ -n "$TRUEP" ]]; then
  is_num "$TRUEP" || die "TrueP '$TRUEP' is not a number (percent, e.g. 59)."
  awk -v tp="$TRUEP" -v nv="$novig_for_edge" -v price="$A" 'BEGIN{
    edge = tp - nv*100;
    printf "TrueP %.1f%%  −  no-vig %.1f%%  =  Edge %+.1fpp\n", tp, nv*100, edge;
    printf "GATE: ";
    if (edge >= 4)      print "✓ clears +3-4pp PARLAY-ANCHOR bar (and +2pp standalone)";
    else if (edge >= 3) print "✓ clears +3pp parlay-anchor bar / ✓ +2pp standalone";
    else if (edge >= 2) print "✓ clears +2pp STANDALONE bar (✗ short of +3-4pp anchor)";
    else if (edge >= 0) print "✗ positive but under the +2pp gate — action, not value";
    else                print "✗ NEGATIVE edge — do not bet (this side is -EV)";
    # ¼-Kelly units on THIS price at THIS TrueP (doctrine: size by edge, cap 2u/leg;
    # 1u = 1% of the regular-play bankroll). Kelly f = (p·dec − 1)/(dec − 1).
    dec = (price < 0) ? 1 + 100/(-price) : 1 + price/100;
    p = tp/100; b = dec - 1;
    if (b > 0) {
      f = (p*dec - 1)/b; qk = f*100/4;
      if (qk < 0) qk = 0; if (qk > 2) qk = 2;
      printf "STAKE: ¼-Kelly ≈ %.2fu at this price (cap 2u; 0u = no bet). Log the REAL $ per doctrine step 11.\n", qk;
    }
  }'
fi
echo "─────────────────────────────────────────────"
