# Fade Registry — living list of active fades + validation log (NFL)

**Purpose (ported structure; entries start EMPTY — MLB burn history does not port).**
One canonical place for every fade the process leans on, each with its **reason**, **date
added**, and a **running W/L validation log**. A "fade W" = the fade was correct.
`CLAUDE.md` holds doctrine; this file holds the live entries and is the source of truth
for what is active right now.

## Validation protocol (run at the Tuesday wrap)
1. **Consult before building.** Don't bet against an ACTIVE entry's direction without
   checking its recent log.
2. **Validate on every settle**: for each active entry touching a settled game, append a
   dated W/L, bump the tally, update Last-validated.
3. **Status transitions**: ACTIVE → NEUTRAL at ~.500 over the last ~4-5 tests; NEUTRAL →
   RETIRED when the reason lapses; NEW entries seed with the triggering game.
4. **Team-form transitions anchor to POINT DIFFERENTIAL over a window, not W-L streaks**
   (the ported run-diff rule — streaks are the noisiest stat on the board).
5. Promotion bar (ported): process lessons after 2-3 sightings; hit-rate claims need
   n≥20-30 decided legs — below that they stay "early signal — directional only."

## A. Team fades — FADE AS FAVORITE
| ID | Team | Reason | Added | Last val | Fade log | Status |
|----|------|--------|-------|----------|----------|--------|

## B. Team value — QUIETLY-LIVE UNDERDOGS
| ID | Team | Reason | Added | Last val | Value log | Status |
|----|------|--------|-------|----------|-----------|--------|

## C. Prop / market fades (volume traps, weather overrides, funnel mirages)
| ID | Fade | Reason | Added | Last val | Fade log | Status |
|----|------|--------|-------|----------|----------|--------|

## D. Construction fades (ticket shapes that keep losing)
| ID | Fade | Reason | Added | Last val | Fade log | Status |
|----|------|--------|-------|----------|----------|--------|

## E. Data / status traps (verification gates)
| ID | Trap | Reason | Added | Last val | Log | Status |
|----|------|--------|-------|----------|-----|--------|

## Retired (kept for history)
(none yet)
