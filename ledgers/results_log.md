# Results & Calibration Ledger — NFL
<!-- Season-week keys everywhere; no ledger-epoch needed (the MLB M/D ambiguity class is gone). -->

**Purpose.** Every **recommended leg** (and especially every **played** leg) gets a row with
the **pre-registered TrueP**, the **best-shopped price**, the **closing line** (CLV), and the
**result** — so the process is measured, not vibed. Ported doctrine, NFL keys.

**Columns.**
- **leg_id** = the structured identity (`{season}-W{week}:{game_id}:{market}:{side}:{point}:{gsis}`).
  Tools JOIN on it — never on the label text. `tools/legs.py` is the codec.
- **TrueP** = pre-bet true-prob, **written at bet time, never reconstructed** (a back-filled
  number is calibration-invalid). Derive via `truep.py`; paste its `[adj: …]` tag into the Leg cell.
- **ImplP** = the price's **NO-VIG** implied prob (devig both sides; `devig.sh`).
- **Edge** = TrueP − no-vig ImplP. Min-edge gate: **≥ +2pp standalone / ≥ +3-4pp parlay anchor**,
  vs the BEST-shopped price. Nothing clears → NO BET is the honest output.
- **Grade** = process grade written BEFORE the result (was this +EV given what we knew?).
  A losing +EV bet is a GOOD bet; a winning -EV bet is a LEAK.
- **Result** = W / L / Push / Void / TBD. **Played** = Y only if actually bet.
- **CLV** = closing-line verdict (`+ 55%cl` / `− 48%cl` / `= 50%cl`, ±0.5pp dead-band) —
  the primary scoreboard at small samples; filled by `clv_capture.py --apply`, never faked.
- **Bucket** = S (standalone) / P (parlay ticket leg) / BT (backtest-validation row — excluded
  from live calibration).

**Protocol (per run):** log EVERY scan candidate (bet or not — it multiplies the calibration
sample for free); supersede, never edit-in-place; reconcile rollups with `calib.py` (M6) on
every settle.

---

## Played legs (the calibration core)

| Week | Leg | leg_id | Type | Price | Book | TrueP | ImplP | Edge | Grade | Result | Played | CLV | Bucket |
|------|-----|--------|------|-------|------|-------|-------|------|-------|--------|--------|-----|--------|

## Recommended but NOT played (calibration both ways)

| Week | Leg | leg_id | Type | Price | Book | TrueP | ImplP | Edge | Grade | Result | Played | CLV | Bucket |
|------|-----|--------|------|-------|------|-------|-------|------|-------|--------|--------|-----|--------|
| 2026-W01 | SEA ML (NE@SEA, Wed opener) [adj: none] | 2026-W01:2026_01_NE_SEA:h2h:SEA:: | ML-fav | -190 | BetMGM | 64.3% | 64.3% | +0.0 | scan | TBD | N | = 64%cl | S |
| 2026-W01 | NE@SEA Under 44.0 [adj: none] | 2026-W01:2026_01_NE_SEA:totals:Under:44: | total | -107 | LowVig.ag | 50.0% | 50.0% | +0.0 | scan | TBD | N | = 50%cl | S |

### Played-ticket record (parlays)

| Week | Ticket | Odds | Stake | Return | P-L | Result |
|------|--------|------|-------|--------|-----|--------|

## Backtest / pipeline-validation rows (Bucket=BT — never counted as live calibration)

| Week | Leg | leg_id | Type | Price | Book | TrueP | ImplP | Edge | Grade | Result | Played | CLV | Bucket |
|------|-----|--------|------|-------|------|-------|-------|------|-------|--------|--------|-----|--------|
| 2025-W10 | CHI ML (NYG@CHI close) | 2025-W10:2025_10_NYG_CHI:h2h:CHI:: | ML-fav | -218 | close | 68%* | 65.8% | +2.2 | BT | **W** (CHI 24-20) | N | + 66%cl bf | BT |
| 2025-W10 | CHI -4.5 (NYG@CHI close) | 2025-W10:2025_10_NYG_CHI:spreads:CHI:-4.5: | spread | -112 | close | 55%* | 50.4% | +4.6 | BT | **L** (CHI 24-20 w/ -4.5 → margin +4) | N | = 50%cl bf | BT |
| 2025-W10 | NO-CAR Under 38.5 (close) | 2025-W10:2025_10_NO_CAR:totals:Under:38.5: | total | -105 | close | 53%* | 48.8% | +4.2 | BT | **W** (total 24 vs Under 38.5) | N | + 51%cl bf | BT |
| 2025-W10 | JAX ML (JAX@HOU close) | 2025-W10:2025_10_JAX_HOU:h2h:JAX:: | ML | -115 | close | 55%* | 51.2% | +3.8 | BT | **L** (JAX 29-36) | N | − 49%cl bf | BT |
| 2025-W10 | Josh Allen Over 249.5 pass yds | 2025-W10:2025_10_BUF_MIA:player_pass_yds:Over:249.5:00-0034857 | QB prop | -110 | demo | 55%* | 50.0% | +5.0 | BT | **W** (Josh Allen 306 vs Over 249.5) | N | — | BT |
| 2025-W10 | De'Von Achane anytime TD | 2025-W10:2025_10_BUF_MIA:player_anytime_td:Yes::00-0039040 | ATD | -140 | demo | 60%* | 58.3% | +1.7 | BT | **W** (De'Von Achane TDs=2) | N | — | BT |
| 2025-W10 | MIA team total Over 21 | 2025-W10:2025_10_BUF_MIA:team_total:MIA_Over:21: | team total | -110 | demo | 55%* | 52.4% | +2.6 | BT | **W** (MIA scored 30 vs Over 21) | N | — | BT |

## Rollup (reconciled by calib.py from M6 — until then, raw rows only)
