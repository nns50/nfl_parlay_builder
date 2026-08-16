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
## Rollup (reconciled by calib.py from M6 — until then, raw rows only)
