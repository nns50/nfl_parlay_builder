# $10 Rollover Bankroll — full-compounding ladder (NFL, weekly cadence)

**The game (ported; cadence per resolved decision (f)).** Start at **$10**. **One roll per
WEEK**: the single safest qualifying favorite on the whole board, placed at its own window
lock. Roll the full return. **4 consecutive wins → STOP & withdraw.** Any loss → restart at
$10 next week.

**Honest framing (read every time).** Full rollover is maximum variance — the median attempt
busts; the value lives in the rare 4-win run; downside capped at $10/attempt. ~4 weeks per
attempt at NFL cadence. This is a capped-risk side game, not an income strategy.

## Rules
1. Stake = the whole balance, every roll.
2. Pick = the single highest-floor favorite **on the whole week's board, independent of the
   parlay build**, that clears the min-edge gate (devigged ≥ +2pp) and every pre-lock gate
   (weekcheck clean for that game, availability gate ✓, price from a real book), and is not
   on the fade registry's fade-as-favorite list.
3. Single leg, no parlay. No qualifying play that week → NO BET, balance carries.
4. Settle from `nfl_data.sh finals`; log below; commit with the week's wrap.

## Attempts

| Attempt | Week | Roll | Balance before | Bet (leg @ book, decimal) | TrueP | Result | Balance after | Note |
|---------|------|------|----------------|---------------------------|-------|--------|---------------|------|
