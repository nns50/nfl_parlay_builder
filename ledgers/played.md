# Played legs — what you actually bet

**Edit this file from your phone** (GitHub → this file → pencil icon → Commit). The next
scheduled run reconciles it into `results_log.md`, setting `Played=Y` and the `Stake` cell
on the matching row. Reconciliation is idempotent — a line that is already applied is a
no-op, so re-running never double-counts.

## Why this file exists

ROI is fiction until real stakes are logged. Every row in `results_log.md` is a leg the
system *recommended*; without this file, nothing records which ones you actually took or
for how much, so per-leg ROI, the ¼-Kelly staking check, and the standalone-vs-parlay
split can never be computed from anything but assumption.

## Format — one bet per line, under `## Bets`

```
<leg_id> | <stake>            # stake in dollars: 25, $25 — or units: 2u
```

The `leg_id` is the third column of any row in `results_log.md` (and appears in every
build file and notification), e.g.:

```
2026-W01:2026_01_NE_SEA:h2h:SEA:: | 25
2026-W01:2026_01_NE_SEA:totals:Under:44.5: | $10
2026-W01:2026_01_DEN_KC:spreads:KC:-2.5: | 1.5u
```

Rules the reconciler enforces, so a typo fails loudly instead of silently:
- A `leg_id` with no matching ledger row is **reported as an error**, never ignored.
- A duplicate `leg_id` in this file is an error (one stake per leg — supersede by editing
  the existing line, matching the ledger's supersede-never-edit-in-place spirit).
- A non-numeric stake is an error.
- Blank lines and `#` comments are ignored.

Parlay tickets keep using the `## Played-ticket` section of `results_log.md` — this file is
for individual legs.

## Bets

<!-- add lines below this marker -->
