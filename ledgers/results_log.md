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

| Week | Leg | leg_id | Type | Price | Book | TrueP | ImplP | Edge | Grade | Result | Played | CLV | Bucket |  Stake |
|------|-----|--------|------|-------|------|-------|-------|------|-------|--------|--------|-----|--------|-------|

## Recommended but NOT played (calibration both ways)

| Week | Leg | leg_id | Type | Price | Book | TrueP | ImplP | Edge | Grade | Result | Played | CLV | Bucket |  Stake |
|------|-----|--------|------|-------|------|-------|-------|------|-------|--------|--------|-----|--------|-------|
| 2026-W01 | SEA ML (NE@SEA, Wed opener) [adj: none] | 2026-W01:2026_01_NE_SEA:h2h:SEA:: | ML-fav | -190 | BetMGM | 64.3% | 64.3% | +0.0 | scan | TBD | N | = 64%cl | S |  |
| 2026-W01 | NE@SEA Under 44.0 [adj: none] | 2026-W01:2026_01_NE_SEA:totals:Under:44: | total | -107 | LowVig.ag | 50.0% | 50.0% | +0.0 | scan | TBD | N | = 50%cl | S |  |

| 2026-W01 | NE@SEA Under 44.5 [adj: none] | 2026-W01:2026_01_NE_SEA:totals:Under:44.5: | total | -105 | FanDuel | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | LA ML (SF@LA) [adj: none] | 2026-W01:2026_01_SF_LA:h2h:LA:: | ML-fav | -190 | BetMGM | 64.2% | 64.2% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | SF@LA Under 48.5 [adj: none] | 2026-W01:2026_01_SF_LA:totals:Under:48.5: | total | -107 | LowVig.ag | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | PIT ML (ATL@PIT) [adj: none] | 2026-W01:2026_01_ATL_PIT:h2h:PIT:: | ML-fav | -152 | FanDuel | 60.1% | 60.1% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | ATL@PIT Under 41.5 [adj: none] | 2026-W01:2026_01_ATL_PIT:totals:Under:41.5: | total | -105 | DraftKings | 49.8% | 49.8% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | BAL ML (BAL@IND) [adj: none] | 2026-W01:2026_01_BAL_IND:h2h:BAL:: | ML-fav | -180 | DraftKings | 63.0% | 63.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | BAL@IND Under 48 [adj: none] | 2026-W01:2026_01_BAL_IND:totals:Under:48: | total | -108 | Caesars | 50.7% | 50.7% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | BUF ML (BUF@HOU) [adj: none] | 2026-W01:2026_01_BUF_HOU:h2h:BUF:: | ML-fav | -105 | BetMGM | 50.6% | 50.6% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | BUF@HOU Under 44.5 [adj: none] | 2026-W01:2026_01_BUF_HOU:totals:Under:44.5: | total | -107 | LowVig.ag | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | CHI ML (CHI@CAR) [adj: none] | 2026-W01:2026_01_CHI_CAR:h2h:CHI:: | ML-fav | -145 | LowVig.ag | 58.2% | 58.2% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | CHI@CAR Under 46 [adj: none] | 2026-W01:2026_01_CHI_CAR:totals:Under:46: | total | -107 | LowVig.ag | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | CIN ML (TB@CIN) [adj: none] | 2026-W01:2026_01_TB_CIN:h2h:CIN:: | ML-fav | -185 | Bovada | 64.2% | 64.2% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | TB@CIN Under 51 [adj: none] | 2026-W01:2026_01_TB_CIN:totals:Under:51: | total | -107 | LowVig.ag | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | JAX ML (CLE@JAX) [adj: none] | 2026-W01:2026_01_CLE_JAX:h2h:JAX:: | ML-fav | -360 | BetUS | 76.7% | 76.7% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | CLE@JAX Under 40.5 [adj: none] | 2026-W01:2026_01_CLE_JAX:totals:Under:40.5: | total | -104 | FanDuel | 49.7% | 49.7% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | DET ML (NO@DET) [adj: none] | 2026-W01:2026_01_NO_DET:h2h:DET:: | ML-fav | -325 | DraftKings | 74.0% | 74.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | NO@DET Under 49.5 [adj: none] | 2026-W01:2026_01_NO_DET:totals:Under:49.5: | total | -110 | Bovada | 50.9% | 50.9% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | TEN ML (NYJ@TEN) [adj: none] | 2026-W01:2026_01_NYJ_TEN:h2h:TEN:: | ML-fav | -138 | FanDuel | 57.1% | 57.1% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | NYJ@TEN Under 38.5 [adj: none] | 2026-W01:2026_01_NYJ_TEN:totals:Under:38.5: | total | -104 | Caesars | 49.3% | 49.3% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | LAC ML (ARI@LAC) [adj: none] | 2026-W01:2026_01_ARI_LAC:h2h:LAC:: | ML-fav | -500 | BetRivers | 82.2% | 82.2% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | ARI@LAC Under 46 [adj: none] | 2026-W01:2026_01_ARI_LAC:totals:Under:46: | total | -108 | Caesars | 50.3% | 50.3% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | MIN ML (GB@MIN) [adj: none] | 2026-W01:2026_01_GB_MIN:h2h:MIN:: | ML-fav | -105 | DraftKings | 50.6% | 50.6% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | GB@MIN Under 45 [adj: none] | 2026-W01:2026_01_GB_MIN:totals:Under:45: | total | -107 | LowVig.ag | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | LV ML (MIA@LV) [adj: none] | 2026-W01:2026_01_MIA_LV:h2h:LV:: | ML-fav | -190 | BetUS | 64.3% | 64.3% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | MIA@LV Under 40.5 [adj: none] | 2026-W01:2026_01_MIA_LV:totals:Under:40.5: | total | -107 | LowVig.ag | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | PHI ML (WAS@PHI) [adj: none] | 2026-W01:2026_01_WAS_PHI:h2h:PHI:: | ML-fav | -215 | BetUS | 67.0% | 67.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | WAS@PHI Under 47.5 [adj: none] | 2026-W01:2026_01_WAS_PHI:totals:Under:47.5: | total | -105 | FanDuel | 50.4% | 50.4% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | DAL ML (DAL@NYG) [adj: none] | 2026-W01:2026_01_DAL_NYG:h2h:DAL:: | ML-fav | -145 | BetOnline.ag | 58.2% | 58.2% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | DAL@NYG Under 48.5 [adj: none] | 2026-W01:2026_01_DAL_NYG:totals:Under:48.5: | total | -109 | Caesars | 50.5% | 50.5% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | KC ML (DEN@KC) [adj: none] | 2026-W01:2026_01_DEN_KC:h2h:KC:: | ML-fav | -148 | LowVig.ag | 58.5% | 58.5% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | DEN@KC Under 43.5 [adj: none] | 2026-W01:2026_01_DEN_KC:totals:Under:43.5: | total | -110 | BetRivers | 50.7% | 50.7% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | SEA -3.5 (NE@SEA) [adj: none] | 2026-W01:2026_01_NE_SEA:spreads:SEA:-3.5: | spread | -105 | LowVig.ag | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | LA -3.5 (SF@LA) [adj: none] | 2026-W01:2026_01_SF_LA:spreads:LA:-3.5: | spread | -105 | Bovada | 51.1% | 51.1% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | PIT -3 (ATL@PIT) [adj: none] ⚠PENDING(Penix Jr Q) | 2026-W01:2026_01_ATL_PIT:spreads:PIT:-3: | spread | -105 | BetRivers | 50.6% | 50.6% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | BAL -3.5 (BAL@IND) [adj: none] | 2026-W01:2026_01_BAL_IND:spreads:BAL:-3.5: | spread | +100 | LowVig.ag | 48.9% | 48.9% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | BUF -1.5 (BUF@HOU) [adj: none] | 2026-W01:2026_01_BUF_HOU:spreads:BUF:-1.5: | spread | +100 | Caesars | 48.6% | 48.6% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | CHI -2.5 (CHI@CAR) [adj: none] | 2026-W01:2026_01_CHI_CAR:spreads:CHI:-2.5: | spread | -114 | BetRivers | 51.3% | 51.3% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | CIN -3.5 (TB@CIN) [adj: none] | 2026-W01:2026_01_TB_CIN:spreads:CIN:-3.5: | spread | +100 | LowVig.ag | 49.4% | 49.4% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | JAX -7.5 (CLE@JAX) [adj: none] | 2026-W01:2026_01_CLE_JAX:spreads:JAX:-7.5: | spread | -105 | LowVig.ag | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | DET -7 (NO@DET) [adj: none] | 2026-W01:2026_01_NO_DET:spreads:DET:-7: | spread | -105 | LowVig.ag | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | TEN -3 (NYJ@TEN) [adj: none] | 2026-W01:2026_01_NYJ_TEN:spreads:TEN:-3: | spread | +100 | DraftKings | 47.8% | 47.8% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | LAC -11.5 (ARI@LAC) [adj: none] | 2026-W01:2026_01_ARI_LAC:spreads:LAC:-11.5: | spread | -110 | DraftKings | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | GB -1.5 (GB@MIN) [adj: none] | 2026-W01:2026_01_GB_MIN:spreads:GB:-1.5: | spread | +100 | DraftKings | 47.8% | 47.8% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | LV -3.5 (MIA@LV) [adj: none] | 2026-W01:2026_01_MIA_LV:spreads:LV:-3.5: | spread | -110 | DraftKings | 51.2% | 51.2% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | PHI -4.5 (WAS@PHI) [adj: none] | 2026-W01:2026_01_WAS_PHI:spreads:PHI:-4.5: | spread | -105 | LowVig.ag | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | DAL -2.5 (DAL@NYG) [adj: none] | 2026-W01:2026_01_DAL_NYG:spreads:DAL:-2.5: | spread | -115 | DraftKings | 52.3% | 52.3% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | KC -3 (DEN@KC) [adj: none] ⚠PENDING(Mahomes Q) | 2026-W01:2026_01_DEN_KC:spreads:KC:-3: | spread | +103 | LowVig.ag | 48.0% | 48.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | NO@DET Under 48.5 [adj: none] | 2026-W01:2026_01_NO_DET:totals:Under:48.5: | total | -102 | DraftKings | 48.3% | 48.3% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | HOU +0.5 (BUF@HOU) [adj: none] | 2026-W01:2026_01_BUF_HOU:spreads:HOU:+0.5: | spread | -110 | MyBookie.ag | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | CHI@CAR Under 47.5 [adj: none] — NEW RUNG (run 19): the CHI@CAR total moved UP ~1pt since run 18; the 45.5 and 46 rungs are gone and 12 of 22 quotes now sit on 47.5 | 2026-W01:2026_01_CHI_CAR:totals:Under:47.5: | total | -105 | Bovada | 49.8% | 49.8% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | CHI@CAR Under 47 [adj: none] — NEW RUNG (run 19) | 2026-W01:2026_01_CHI_CAR:totals:Under:47: | total | -109 | Caesars | 49.9% | 49.9% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | CLE +7 (CLE@JAX) [adj: none] — NEW RUNG (run 19): a 7.0 rung appeared alongside the 7.5, which makes the already-logged CLE +7.5 a genuine key-7 cross for the first time | 2026-W01:2026_01_CLE_JAX:spreads:CLE:+7: | spread | -105 | Fanatics | 48.9% | 48.9% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | Cooper Kupp Over 30.5 rec yds (NE@SEA) [adj: none] ⚠1-BOOK BASELINE (Fanatics only, hold 7.1pp) — NEW MARKET (run 19), replaced the JSN rec-yds market. Kupp is SEA WR3 (behind JSN and Shaheed); 2025 base rate 9/16 (56.3%) sits just under the -140 breakeven of 58.33% | 2026-W01:2026_01_NE_SEA:player_reception_yds:Over:30.5:00-0033908 | prop | -140 | Fanatics | 54.5% | 54.5% | +0.0 | scan (1-book) | TBD | N | — | S |  |
| 2026-W01 | Sam Darnold Over 235.5 pass yds (NE@SEA) [adj: none] ⚠1-BOOK BASELINE (Fanatics only, hold 7.0pp) — NEW MARKET (run 19), replaced the Maye pass-yds market. Darnold is on the FAVOURITE so script_pass_dog does NOT fire; 2025 base rate 10/17 (58.8%) is a raw prior-season rate, not a TrueP | 2026-W01:2026_01_NE_SEA:player_pass_yds:Over:235.5:00-0034869 | prop | -115 | Fanatics | 50.0% | 50.0% | +0.0 | scan (1-book) | TBD | N | — | S |  |
| 2026-W01 | CHI@CAR Over 48 [adj: none] — NEW RUNG (run 20): the total's third consecutive upward step (runs 18→20: 45.5-46.5 → 46.5-47.5 → 46.5-48.0); 8 of 20 quotes now sit on 48 | 2026-W01:2026_01_CHI_CAR:totals:Over:48: | total | -110 | Bovada | 51.2% | 51.2% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | CHI@CAR Under 48 [adj: none] — NEW RUNG (run 20): companion to the Over 48; the Under 45.5/46/47 rungs logged by runs 13-19 are all now dead on the board | 2026-W01:2026_01_CHI_CAR:totals:Under:48: | total | +100 | BetUS | 48.8% | 48.8% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | LA -3.5 (SF@LA) [adj: none] — SUPERSEDES the run-13 row: price moved -105→-110, no-vig 51.1%→51.7%. This rung was the BOARD'S BEST LEG at runs 18-19 (-0.12pp, hold +0.24pp); the hold has widened to +1.40pp and it is no longer the best leg | 2026-W01:2026_01_SF_LA:spreads:LA:-3.5: | spread | -110 | Bovada | 51.7% | 51.7% | +0.0 | scan (reprice) | TBD | N | — | S |  |
| 2026-W01 | WAS@PHI Under 47.5 [adj: none] — SUPERSEDES the run-13 row: price moved -105→-115, no-vig 50.4%→51.1%; largest single-leg implied move on the board this run (+2.27pp) | 2026-W01:2026_01_WAS_PHI:totals:Under:47.5: | total | -115 | DraftKings | 51.1% | 51.1% | +0.0 | scan (reprice) | TBD | N | — | S |  |
| 2026-W01 | BUF -1.5 (BUF@HOU) [adj: none] — SUPERSEDES the run-13 row: price moved +100→-108, no-vig 48.6%→49.6% (+1.92pp implied); the HOU +0.5 and HOU -0 rungs are gone, so the pick-em ladder has narrowed to 0/1/1.5 | 2026-W01:2026_01_BUF_HOU:spreads:BUF:-1.5: | spread | -108 | DraftKings | 49.6% | 49.6% | +0.0 | scan (reprice) | TBD | N | — | S |  |
| 2026-W01 | TB ML (TB@CIN) [adj: none] — run 25: the BEST leg on the ENTIRE 174-leg board and a NEW best (run 24's was WAS +198). +185 be 35.09% vs no-vig TrueP 34.88% = -0.21pp. The TB@CIN h2h rung holds +0.60pp, a PORT RECORD for tightness (prior best +0.77pp) — the closest this board has come to a fair price, and still on the wrong side of zero -> NO BET | 2026-W01:2026_01_TB_CIN:h2h:TB:: | ML-dog | +185 | Bovada | 34.9% | 35.1% | -0.2 | scan (board best, sub-gate) | TBD | N | — | S |  |
| 2026-W01 | NE ML (NE@SEA, Wed opener) [adj: none] — run 25: second-best leg on the board at -0.23pp; +175 be 36.36% vs no-vig 36.13%. Rung holds +0.65pp, the second-tightest of the port. The SEA side of this rung was logged in run 1; the NE side had never been rowed -> NO BET | 2026-W01:2026_01_NE_SEA:h2h:NE:: | ML-dog | +175 | Bovada | 36.1% | 36.4% | -0.2 | scan (sub-gate) | TBD | N | — | S |  |
| 2026-W01 | Rashid Shaheed Over 2.5 receptions (NE@SEA) [adj: none] — run 25: the TIGHTEST PROP RUNG OF THE PORT at +3.03pp hold, roughly half the 5.95-7.19pp band every prior prop board has shown. +108 be 48.08% vs no-vig 46.67% = -1.41pp, the best RAW prop read logged. SEA is the 3.5-pt FAVOURITE so script_pass_dog does NOT apply (team by store ID join, not memory) -> NO BET | 2026-W01:2026_01_NE_SEA:player_receptions:Over:2.5:00-0037545 | prop | +108 | BetRivers | 46.7% | 48.1% | -1.4 | scan (4-book baseline, sub-gate) | TBD | N | — | S |  |
| 2026-W01 | Cooper Kupp Over 2.5 receptions (NE@SEA) [adj: none] — run 25: second-tightest prop rung of the port at +3.05pp hold. -113 be 53.05% vs no-vig 51.49% = -1.57pp. Also on SEA, the favourite, so no script_pass_dog. Two sub-3.1pp prop rungs appearing at once is the first sign of a prop market tightening toward the featured board's 0.60-5.11pp range -> NO BET | 2026-W01:2026_01_NE_SEA:player_receptions:Over:2.5:00-0033908 | prop | -113 | BetRivers | 51.5% | 53.1% | -1.6 | scan (4-book baseline, sub-gate) | TBD | N | — | S |  |

### Played-ticket record (parlays)

| Week | Ticket | Odds | Stake | Return | P-L | Result |
|------|--------|------|-------|--------|-----|--------|

## Backtest / pipeline-validation rows (Bucket=BT — never counted as live calibration)

| Week | Leg | leg_id | Type | Price | Book | TrueP | ImplP | Edge | Grade | Result | Played | CLV | Bucket |  Stake |
|------|-----|--------|------|-------|------|-------|-------|------|-------|--------|--------|-----|--------|-------|
| 2025-W10 | CHI ML (NYG@CHI close) | 2025-W10:2025_10_NYG_CHI:h2h:CHI:: | ML-fav | -218 | close | 68%* | 65.8% | +2.2 | BT | **W** (CHI 24-20) | N | + 66%cl bf | BT |  |
| 2025-W10 | CHI -4.5 (NYG@CHI close) | 2025-W10:2025_10_NYG_CHI:spreads:CHI:-4.5: | spread | -112 | close | 55%* | 50.4% | +4.6 | BT | **L** (CHI 24-20 w/ -4.5 → margin +4) | N | = 50%cl bf | BT |  |
| 2025-W10 | NO-CAR Under 38.5 (close) | 2025-W10:2025_10_NO_CAR:totals:Under:38.5: | total | -105 | close | 53%* | 48.8% | +4.2 | BT | **W** (total 24 vs Under 38.5) | N | + 51%cl bf | BT |  |
| 2025-W10 | JAX ML (JAX@HOU close) | 2025-W10:2025_10_JAX_HOU:h2h:JAX:: | ML | -115 | close | 55%* | 51.2% | +3.8 | BT | **L** (JAX 29-36) | N | − 49%cl bf | BT |  |
| 2025-W10 | Josh Allen Over 249.5 pass yds | 2025-W10:2025_10_BUF_MIA:player_pass_yds:Over:249.5:00-0034857 | QB prop | -110 | demo | 55%* | 50.0% | +5.0 | BT | **W** (Josh Allen 306 vs Over 249.5) | N | — | BT |  |
| 2025-W10 | De'Von Achane anytime TD | 2025-W10:2025_10_BUF_MIA:player_anytime_td:Yes::00-0039040 | ATD | -140 | demo | 60%* | 58.3% | +1.7 | BT | **W** (De'Von Achane TDs=2) | N | — | BT |  |
| 2025-W10 | MIA team total Over 21 | 2025-W10:2025_10_BUF_MIA:team_total:MIA_Over:21: | team total | -110 | demo | 55%* | 52.4% | +2.6 | BT | **W** (MIA scored 30 vs Over 21) | N | — | BT |  |
| 2026-W01 | ARI +10 (ARI@LAC) [adj: none] | 2026-W01:2026_01_ARI_LAC:spreads:ARI:+10: | spread | -110 | BetUS | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | LAC -10.5 (ARI@LAC) [adj: none] | 2026-W01:2026_01_ARI_LAC:spreads:LAC:-10.5: | spread | -102 | LowVig.ag | 49.3% | 49.3% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | ARI@LAC Over 46.5 [adj: none] | 2026-W01:2026_01_ARI_LAC:totals:Over:46.5: | total | -105 | Caesars | 49.4% | 49.4% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | ATL +2.5 (ATL@PIT) [adj: none] ⚠PENDING(Penix Jr Q) | 2026-W01:2026_01_ATL_PIT:spreads:ATL:+2.5: | spread | -102 | FanDuel | 48.1% | 48.1% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | ATL@PIT Under 42 [adj: none] ⚠PENDING(Penix Jr Q) | 2026-W01:2026_01_ATL_PIT:totals:Under:42: | total | -110 | Bovada | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | BAL@IND Under 47.5 [adj: none] | 2026-W01:2026_01_BAL_IND:totals:Under:47.5: | total | -105 | Bovada | 48.9% | 48.9% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | BAL@IND Over 48.5 [adj: none] | 2026-W01:2026_01_BAL_IND:totals:Over:48.5: | total | +100 | Caesars | 48.8% | 48.8% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | HOU -0 (BUF@HOU) [adj: none] | 2026-W01:2026_01_BUF_HOU:spreads:HOU:-0: | spread | -105 | LowVig.ag | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | HOU -1 (BUF@HOU) [adj: none] | 2026-W01:2026_01_BUF_HOU:spreads:HOU:-1: | spread | -105 | Bovada | 49.4% | 49.4% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | CHI -3 (CHI@CAR) [adj: none] | 2026-W01:2026_01_CHI_CAR:spreads:CHI:-3: | spread | +100 | LowVig.ag | 48.8% | 48.8% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | CHI@CAR Under 45.5 [adj: none] | 2026-W01:2026_01_CHI_CAR:totals:Under:45.5: | total | -106 | Caesars | 49.6% | 49.6% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | CHI@CAR Under 46.5 [adj: none] | 2026-W01:2026_01_CHI_CAR:totals:Under:46.5: | total | -110 | DraftKings | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | DAL -3 (DAL@NYG) [adj: none] | 2026-W01:2026_01_DAL_NYG:spreads:DAL:-3: | spread | +100 | BetUS | 48.3% | 48.3% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | DAL@NYG Under 49 [adj: none] | 2026-W01:2026_01_DAL_NYG:totals:Under:49: | total | -107 | LowVig.ag | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | DEN +2.5 (DEN@KC) [adj: none] ⚠PENDING(Mahomes Q) | 2026-W01:2026_01_DEN_KC:spreads:DEN:+2.5: | spread | +101 | Caesars | 48.7% | 48.7% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | DEN@KC Under 42.5 [adj: none] ⚠PENDING(Mahomes Q) | 2026-W01:2026_01_DEN_KC:totals:Under:42.5: | total | -107 | Caesars | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | DEN@KC Under 43 [adj: none] ⚠PENDING(Mahomes Q) | 2026-W01:2026_01_DEN_KC:totals:Under:43: | total | -110 | MyBookie.ag | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | MIN -0 (GB@MIN) [adj: none] | 2026-W01:2026_01_GB_MIN:spreads:MIN:-0: | spread | -105 | LowVig.ag | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | MIN -1 (GB@MIN) [adj: none] | 2026-W01:2026_01_GB_MIN:spreads:MIN:-1: | spread | -109 | BetUS | 49.9% | 49.9% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | GB@MIN Under 44.5 [adj: none] | 2026-W01:2026_01_GB_MIN:totals:Under:44.5: | total | -105 | FanDuel | 48.9% | 48.9% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | GB@MIN Under 45.5 [adj: none] | 2026-W01:2026_01_GB_MIN:totals:Under:45.5: | total | -109 | BetRivers | 49.9% | 49.9% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | MIA +4 (MIA@LV) [adj: none] | 2026-W01:2026_01_MIA_LV:spreads:MIA:+4: | spread | -110 | Bovada | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | MIA@LV Over 40 [adj: none] | 2026-W01:2026_01_MIA_LV:totals:Over:40: | total | -110 | BetRivers | 49.8% | 49.8% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | SEA -4 (NE@SEA) [adj: none] | 2026-W01:2026_01_NE_SEA:spreads:SEA:-4: | spread | -105 | Bovada | 48.9% | 48.9% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | NO +6.5 (NO@DET) [adj: none] | 2026-W01:2026_01_NO_DET:spreads:NO:+6.5: | spread | +101 | Caesars | 48.2% | 48.2% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | NO@DET Under 49 [adj: none] | 2026-W01:2026_01_NO_DET:totals:Under:49: | total | -102 | LowVig.ag | 49.1% | 49.1% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | NYJ +2 (NYJ@TEN) [adj: none] | 2026-W01:2026_01_NYJ_TEN:spreads:NYJ:+2: | spread | +100 | BetUS | 47.8% | 47.8% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | NYJ +2.5 (NYJ@TEN) [adj: none] | 2026-W01:2026_01_NYJ_TEN:spreads:NYJ:+2.5: | spread | +100 | LowVig.ag | 48.8% | 48.8% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | NYJ@TEN Under 39 [adj: none] | 2026-W01:2026_01_NYJ_TEN:totals:Under:39: | total | -110 | Bovada | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | NYJ@TEN Under 39.5 [adj: none] | 2026-W01:2026_01_NYJ_TEN:totals:Under:39.5: | total | -110 | MyBookie.ag | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | NYJ@TEN Under 40 [adj: none] | 2026-W01:2026_01_NYJ_TEN:totals:Under:40: | total | -107 | LowVig.ag | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | TB@CIN Under 51.5 [adj: none] | 2026-W01:2026_01_TB_CIN:totals:Under:51.5: | total | -108 | FanDuel | 49.8% | 49.8% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | PHI -5.5 (WAS@PHI) [adj: none] | 2026-W01:2026_01_WAS_PHI:spreads:PHI:-5.5: | spread | -105 | FanDuel | 48.9% | 48.9% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | WAS@PHI Under 47 [adj: none] | 2026-W01:2026_01_WAS_PHI:totals:Under:47: | total | -110 | BetUS | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |

<!-- Run 12 (2026-08-10 23:0xZ build): 9 rungs newly quoted since the run-11 board; one row per RUNG
     (the two sides of a rung are one observation), side = the better-edge side. -->
| 2026-W01 | ARI +9.5 (ARI@LAC) [adj: none] | 2026-W01:2026_01_ARI_LAC:spreads:ARI:+9.5: | spread | -110 | BetRivers | 49.7% | 49.7% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | ATL@PIT Over 42.5 [adj: none] ⚠PENDING(Penix Jr Q) | 2026-W01:2026_01_ATL_PIT:totals:Over:42.5: | total | -105 | DraftKings | 49.8% | 49.8% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | IND +3 (BAL@IND) [adj: none] | 2026-W01:2026_01_BAL_IND:spreads:IND:+3: | spread | +100 | Bovada | 47.8% | 47.8% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | HOU -1.5 (BUF@HOU) [adj: none] | 2026-W01:2026_01_BUF_HOU:spreads:HOU:-1.5: | spread | -102 | FanDuel | 48.1% | 48.1% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | HOU +1 (BUF@HOU) [adj: none] | 2026-W01:2026_01_BUF_HOU:spreads:HOU:+1: | spread | -110 | BetRivers | 49.7% | 49.7% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | MIN -1.5 (GB@MIN) [adj: none] | 2026-W01:2026_01_GB_MIN:spreads:MIN:-1.5: | spread | -110 | MyBookie.ag | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | GB -1 (GB@MIN) [adj: none] | 2026-W01:2026_01_GB_MIN:spreads:GB:-1: | spread | -110 | BetRivers | 49.7% | 49.7% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | NE@SEA Under 43.5 [adj: none] | 2026-W01:2026_01_NE_SEA:totals:Under:43.5: | total | -107 | LowVig.ag | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | WAS@PHI Over 46.5 [adj: none] | 2026-W01:2026_01_WAS_PHI:totals:Over:46.5: | total | -105 | FanDuel | 48.9% | 48.9% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | CAR +2 (CHI@CAR) [adj: none] | 2026-W01:2026_01_CHI_CAR:spreads:CAR:+2: | spread | +100 | BetUS | 47.8% | 47.8% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | DAL@NYG Over 48 [adj: none] | 2026-W01:2026_01_DAL_NYG:totals:Over:48: | total | -110 | Fanatics | 50.0% | 50.0% | +0.0 | scan | TBD | N | — | S |  |
| 2026-W01 | Drake Maye Over 215.5 pass yds (NE@SEA) [adj: script_pass_dog+3] ⚠1-BOOK BASELINE (Fanatics only, hold 6.9pp) — clears no-vig gate, FAILS the price test (-120 be 54.55% vs TrueP 54.0% = -0.55pp) → NO BET | 2026-W01:2026_01_NE_SEA:player_pass_yds:Over:215.5:00-0039851 | prop | -120 | Fanatics | 54.0% | 51.0% | +3.0 | scan (1-book, unbettable price) | TBD | N | — | S |  |
| 2026-W01 | Jaxon Smith-Njigba Over 90.5 rec yds (NE@SEA) [adj: none] ⚠1-BOOK BASELINE (Fanatics only, hold 6.9pp) | 2026-W01:2026_01_NE_SEA:player_reception_yds:Over:90.5:00-0038543 | prop | -110 | Fanatics | 49.0% | 49.0% | +0.0 | scan (1-book) | TBD | N | — | S |  |
| 2026-W01 | Sam Darnold Over 5.5 rush yds (NE@SEA) [adj: none] ⚠1-BOOK BASELINE (Fanatics only, hold 7.1pp) | 2026-W01:2026_01_NE_SEA:player_rush_yds:Over:5.5:00-0034869 | prop | -140 | Fanatics | 54.5% | 54.5% | +0.0 | scan (1-book) | TBD | N | — | S |  |

| 2026-W01 | Jaxon Smith-Njigba Over 90.5 rec yds (NE@SEA) [adj: none] ⚠1-BOOK BASELINE (Fanatics only, hold 6.9pp) — SUPERSEDES the run-17 row: price moved -110→-120, no-vig Over 49.0%→51.0% (+2.0pp toward the Over) | 2026-W01:2026_01_NE_SEA:player_reception_yds:Over:90.5:00-0038543 | prop | -120 | Fanatics | 51.0% | 51.0% | +0.0 | scan (1-book, reprice) | TBD | N | — | S |  |
| 2026-W01 | Sam Darnold Over 5.5 rush yds (NE@SEA) [adj: none] ⚠1-BOOK BASELINE (Fanatics only, hold 7.6pp) — SUPERSEDES the run-17 row: price moved -140→-150, no-vig 54.5%→55.8%; 2025 base rate 6/17 (35%) sits 20.8pp BELOW the priced Over — flag only, no registered adjustment | 2026-W01:2026_01_NE_SEA:player_rush_yds:Over:5.5:00-0034869 | prop | -150 | Fanatics | 55.8% | 55.8% | +0.0 | scan (1-book, reprice) | TBD | N | — | S |  |
| 2026-W01 | HOU -1.5 (BUF@HOU) [adj: none] — SUPERSEDES the run-18 row: price UNCHANGED at -102 @FanDuel, but the paired BUF +1.5 side moved, so no-vig 48.1%→49.6% (+1.54pp, the largest implied move on the board this run). A rung can reprice without its own quote moving | 2026-W01:2026_01_BUF_HOU:spreads:HOU:-1.5: | spread | -102 | FanDuel | 49.6% | 49.6% | +0.0 | scan (reprice) | TBD | N | — | S |  |
| 2026-W01 | ARI@LAC Under 46 [adj: none] — SUPERSEDES the run-18 row: best price moved -108 @Caesars → -102 @LowVig.ag, no-vig 50.3%→48.8% (-1.53pp, toward the Over) | 2026-W01:2026_01_ARI_LAC:totals:Under:46: | total | -102 | LowVig.ag | 48.8% | 48.8% | +0.0 | scan (reprice) | TBD | N | — | S |  |
| 2026-W01 | DAL -3 (DAL@NYG) [adj: none] — SUPERSEDES the run-16 row: price moved +100 @BetUS → -105 @Bovada, no-vig 48.3%→49.4% (+1.14pp toward Dallas) | 2026-W01:2026_01_DAL_NYG:spreads:DAL:-3: | spread | -105 | Bovada | 49.4% | 49.4% | +0.0 | scan (reprice) | TBD | N | — | S |  |
| 2026-W01 | IND +3 (BAL@IND) [adj: none] — SUPERSEDES the run-18 row: price moved +100 → -105, both @Bovada, no-vig 47.8%→48.9% (+1.12pp toward the Colts) | 2026-W01:2026_01_BAL_IND:spreads:IND:+3: | spread | -105 | Bovada | 48.9% | 48.9% | +0.0 | scan (reprice) | TBD | N | — | S |  |
| 2026-W01 | BAL@IND Under 47.5 [adj: none] — SUPERSEDES the run-16 row: price moved -105 → -110, both @Bovada, no-vig 48.9%→50.0% (+1.10pp toward the Under) | 2026-W01:2026_01_BAL_IND:totals:Under:47.5: | total | -110 | Bovada | 50.0% | 50.0% | +0.0 | scan (reprice) | TBD | N | — | S |  |
| 2026-W01 | PHI -5.5 (WAS@PHI) [adj: none] — SUPERSEDES the run-17 row: price moved -105 → -110, both @FanDuel, no-vig 48.9%→50.0% (+1.10pp toward Philadelphia) | 2026-W01:2026_01_WAS_PHI:spreads:PHI:-5.5: | spread | -110 | FanDuel | 50.0% | 50.0% | +0.0 | scan (reprice) | TBD | N | — | S |  |
| 2026-W01 | WAS@PHI Over 46.5 [adj: none] — SUPERSEDES the run-18 row: price UNCHANGED at -105 @FanDuel; the paired Under moved, no-vig 48.9%→50.0% (+1.10pp) | 2026-W01:2026_01_WAS_PHI:totals:Over:46.5: | total | -105 | FanDuel | 50.0% | 50.0% | +0.0 | scan (reprice) | TBD | N | — | S |  |
| 2026-W01 | CHI@CAR Under 46.5 [adj: none] — SUPERSEDES the run-16 row: price moved -110 → -105, both @DraftKings, no-vig 50.0%→48.9% (-1.08pp); consistent with the total's four-run upward drift | 2026-W01:2026_01_CHI_CAR:totals:Under:46.5: | total | -105 | DraftKings | 48.9% | 48.9% | +0.0 | scan (reprice) | TBD | N | — | S |  |
| 2026-W01 | LA -4 (SF@LA) [adj: none] — NEW RUNG (run 22): a 4.0 rung appeared @LowVig.ag at +100, alongside the surviving -3.5. Two-sided (SF +4 -110 @LowVig.ag), no-vig 48.8% — a hair short of a genuine 3.5→4 key cross | 2026-W01:2026_01_SF_LA:spreads:LA:-4: | spread | +100 | LowVig.ag | 48.8% | 48.8% | +0.0 | scan (new rung) | TBD | N | — | S |  |
| 2026-W01 | PHI -5 (WAS@PHI) [adj: none] — NEW RUNG (run 22): a 5.0 rung appeared @BetMGM at -110, filling in between 4.5 and 5.5. Two-sided, no-vig 50.0% flat — WAS@PHI is a three-rung game (4.5 / 5.0 / 5.5) with no key cross | 2026-W01:2026_01_WAS_PHI:spreads:PHI:-5: | spread | -110 | BetMGM | 50.0% | 50.0% | +0.0 | scan (new rung) | TBD | N | — | S |  |
| 2026-W01 | MIN -0 (GB@MIN) [adj: none] — SUPERSEDES the run-16 row: price moved -105 → -116 @LowVig.ag, no-vig 50.0%→52.4% (+2.40pp toward Minnesota) — the largest reprice on this run | 2026-W01:2026_01_GB_MIN:spreads:MIN:-0: | spread | -116 | LowVig.ag | 52.4% | 52.4% | +0.0 | scan (reprice) | TBD | N | — | S |  |
| 2026-W01 | HOU -1.5 (BUF@HOU) [adj: none] — SUPERSEDES the run-19 row: price UNCHANGED at -102 @FanDuel; the paired BUF +1.5 moved -120 → -110, no-vig 49.6%→48.1% (-1.53pp away from Houston) | 2026-W01:2026_01_BUF_HOU:spreads:HOU:-1.5: | spread | -102 | FanDuel | 48.1% | 48.1% | +0.0 | scan (reprice) | TBD | N | — | S |  |
| 2026-W01 | LA -3.5 (SF@LA) [adj: none] — SUPERSEDES the run-20 row: book moved Bovada → DraftKings at -110, no-vig 51.7%→50.6% (-1.14pp) — the best leg on the board at run 18/19 continues to slide, and gained a companion 4.0 rung this run | 2026-W01:2026_01_SF_LA:spreads:LA:-3.5: | spread | -110 | DraftKings | 50.6% | 50.6% | +0.0 | scan (reprice) | TBD | N | — | S |  |
| 2026-W01 | HOU -0 (BUF@HOU) [adj: none] — SUPERSEDES the run-16 row: price moved -105 → -110 @LowVig.ag, no-vig 50.0%→51.2% (+1.16pp toward Houston) | 2026-W01:2026_01_BUF_HOU:spreads:HOU:-0: | spread | -110 | LowVig.ag | 51.2% | 51.2% | +0.0 | scan (reprice) | TBD | N | — | S |  |
| 2026-W01 | DAL@NYG Under 48 [adj: none] — SUPERSEDES the run-16 row: book moved BetUS → MyBookie.ag at -110, no-vig 48.8%→50.0% (+1.20pp toward the Under) | 2026-W01:2026_01_DAL_NYG:totals:Under:48: | total | -110 | MyBookie.ag | 50.0% | 50.0% | +0.0 | scan (reprice) | TBD | N | — | S |  |
| 2026-W01 | DAL@NYG Over 48 [adj: none] — SUPERSEDES the run-16 row: book moved Bovada → MyBookie.ag at -110, no-vig 51.2%→50.0% (-1.20pp; the paired Under moved harder) | 2026-W01:2026_01_DAL_NYG:totals:Over:48: | total | -110 | MyBookie.ag | 50.0% | 50.0% | +0.0 | scan (reprice) | TBD | N | — | S |  |
| 2026-W01 | TEN -3 (NYJ@TEN) [adj: none] — SUPERSEDES the run-19 row: price flipped -105 → +100 @DraftKings, no-vig 47.8%→48.8% (+1.04pp toward the Titans) | 2026-W01:2026_01_NYJ_TEN:spreads:TEN:-3: | spread | +100 | DraftKings | 48.8% | 48.8% | +0.0 | scan (reprice) | TBD | N | — | S |  |

| 2026-W01 | CHI@CAR Over 48 [adj: none] — SUPERSEDES the run-20 row: book of record moved Bovada -110 → MyBookie.ag -110, no-vig 51.2%→50.0% (-1.20pp; the paired Under repriced harder) | 2026-W01:2026_01_CHI_CAR:totals:Over:48: | total | -110 | MyBookie.ag | 50.0% | 50.0% | +0.0 | scan (reprice) | TBD | N | — | S |  |
| 2026-W01 | CHI@CAR Under 48 [adj: none] — SUPERSEDES the run-20 row: price moved BetUS +100 → MyBookie.ag -110, no-vig 48.8%→50.0% (+1.20pp toward the Under) | 2026-W01:2026_01_CHI_CAR:totals:Under:48: | total | -110 | MyBookie.ag | 50.0% | 50.0% | +0.0 | scan (reprice) | TBD | N | — | S |  |
| 2026-W01 | WAS@PHI Washington ML [adj: none] — run 24: the BOARD'S BEST LEG this run (-0.26pp) and the tightest rung of the port (hold +0.77pp); the WAS side of this rung had never been logged. Still FAILS the price test (+198 be 33.56% vs no-vig 33.30%) -> NO BET | 2026-W01:2026_01_WAS_PHI:h2h:WAS:: | ML | +198 | FanDuel | 33.3% | 33.3% | +0.0 | scan (best-on-board, sub-gate) | TBD | N | — | S |  |
| 2026-W01 | BAL@IND Under 47.5 [adj: none] — SUPERSEDES the run-19 row: price moved -110 -> -105 @Bovada, no-vig 50.0%->48.9% (-1.08pp, the LARGEST no-vig move on the run-24 board); the 47.5 number itself did not move | 2026-W01:2026_01_BAL_IND:totals:Under:47.5: | total | -105 | Bovada | 48.9% | 48.9% | +0.0 | scan (reprice) | TBD | N | — | S |  |
| 2026-W01 | BAL@IND Colts +3 [adj: none] — SUPERSEDES the run-19 row: price moved -105 -> +100 @Bovada, no-vig 48.9%->47.8% (-1.07pp); sits exactly ON the key number, so key_number_edge does NOT apply (run-23 reading) | 2026-W01:2026_01_BAL_IND:spreads:IND:+3: | spread | +100 | Bovada | 47.8% | 47.8% | +0.0 | scan (reprice) | TBD | N | — | S |  |
| 2026-W01 | Drake Maye Over 1.5 pass TDs (NE@SEA) [adj: script_pass_dog+3] — run 24: the BEST script_pass_dog read on the reopened 4-book prop board (NE +3.5 dog). Clears no-vig, FAILS the gate: +160 be 38.46% vs TrueP 39.21% = +0.75pp vs a +2pp gate. Hold on the rung is +6.20pp — WIDTH, not edge -> NO BET | 2026-W01:2026_01_NE_SEA:player_pass_tds:Over:1.5:00-0039851 | prop | +160 | BetRivers | 39.2% | 36.2% | +3.0 | scan (4-book baseline, sub-gate) | TBD | N | — | S |  |
| 2026-W01 | Christian McCaffrey Over 4.5 receptions (SF@LA) [adj: script_pass_dog+3] — run 24: second-best dog-roster read (SF +3.5). +110 be 47.62% vs TrueP 47.94% = +0.32pp vs a +2pp gate; hold +5.95pp, the TIGHTEST prop rung on the board and still ~6pp -> NO BET | 2026-W01:2026_01_SF_LA:player_receptions:Over:4.5:00-0033280 | prop | +110 | BetRivers | 47.9% | 44.9% | +3.0 | scan (4-book baseline, sub-gate) | TBD | N | — | S |  |
| 2026-W01 | Brock Purdy Over 1.5 pass TDs (SF@LA) [adj: script_pass_dog+3] — run 24: dog-QB read, lands exactly at breakeven. -103 be 50.74% vs TrueP 50.73% = -0.00pp vs a +2pp gate; hold +6.29pp -> NO BET | 2026-W01:2026_01_SF_LA:player_pass_tds:Over:1.5:00-0037834 | prop | -103 | BetRivers | 50.7% | 47.7% | +3.0 | scan (4-book baseline, sub-gate) | TBD | N | — | S |  |

## Rollup (reconciled by calib.py from M6 — until then, raw rows only)
