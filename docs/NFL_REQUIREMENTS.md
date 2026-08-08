# NFL REQUIREMENTS — what actually changes from MLB

Phase 2b deliverable. NFL is not "MLB with different stat names": the slate unit, the
availability mechanics, the volume model, and above all the correlation structure are
different *kinds* of problems. Data-availability facts cited here are established (with
verification status) in `DATA_SOURCES.md`.

---

## 1. Schedule / time model — the unit is a WEEK with per-game locks

### 1.1 The shape of a week (verified against the real 2026 schedule)

- REG season: 18 weeks / 272 games, ~13–16 games in a typical week (byes weeks 5–14 reduce
  the count; up to 6 teams off). Windows in a normal week: TNF; Sunday early (13:00 ET, 7–9
  games), Sunday late (16:05/16:25 ET, 3–4), SNF; MNF (occasionally a doubleheader);
  plus scattered internationals at 09:30 ET and late-season Sat/Fri games.
- **Do not hardcode the window taxonomy.** The verified 2026 Week 1 opens on a **Wednesday**
  (NE@SEA, 9/9 20:20 ET) with a Thursday neutral-site game (SF@LA) — and flex scheduling
  moves SNF/late-window games mid-season. Windows are computed by clustering kickoff times
  from `schedules`/the odds events feed; labels (TNF/SNF…) are cosmetic output only.
- Season types: PRE / REG / POST from `schedules.game_type`; at the market layer preseason is
  a separate sport key (verified). POST changes the universe (single-elimination, 6→4→2→1
  games/week) but not the mechanics.

### 1.2 Consequences for the app

| MLB concept | NFL replacement |
|---|---|
| Daily slate, one build file per date | **Week is the container** (`builds/2026-W01.md`), games carry their own kickoff; scan tables grouped by window |
| One slate lock (~first pitch cluster) | **Per-game lock times.** Every leg carries its event's kickoff; gates evaluate per leg, not per run. A Sunday build is partially locked (TNF already played) — normal state, not an edge case |
| 3 fixed daily runs (11/16/18 ET) | **Weekly run skeleton keyed to the week's own shape** (see PORT_PLAN §6: Tue review/settle, Wed/Thu build, Fri injury-designation update, per-window lock runs incl. Sunday morning, Mon wrap) + the per-kickoff poll scheduler for prices |
| "Yesterday" settle | "Last completed window" settle; the week closes Tue morning |
| 90-min odds-cache freshness | Phase-dependent freshness (stable Tue–Thu; minutes matter inside T-2h) |
| Doubleheader G1/G2 disambiguation | Dropped. New identity need instead: **cross-source game ID join** (odds event id ↔ `schedules.game_id` ↔ espn id) — schedules carries the join keys |
| Season within one calendar year (`ledger-epoch`) | **`season + week` keys everywhere** (season spans the new year; playoffs are Jan) |

### 1.3 Staleness model

NFL data is nearly static within the week until specific events fire (practice reports,
designations, weather inside 48h, inactives at T-90m, line moves). So: context store
refreshes on its per-dataset cadence with *event-driven* re-evaluation of affected legs
(the `recheck.py` diff pattern, generalized from "SP changed" to "QB status changed /
designation posted / total moved 2+ / wind forecast crossed 15mph"), instead of MLB's
"re-verify the whole world 3×/day".

---

## 2. Injury mechanics — a week-long ladder, not a lineup posting

MLB's binary gate (lineup posted ~2-3h before, CONFIRMED/PENDING) becomes a **stateful
per-player availability ladder across the week**:

```
Wed/Thu/Fri  practice participation  DNP / LP / FP     (trend matters: DNP→LP→FP ≈ playing;
                                                        FP→LP→DNP ≈ trending out)
Fri          game-status designation  OUT / DOUBTFUL / QUESTIONABLE / (none)
T-90min      inactives list           the only ground truth; ~7 players/team
kickoff      lock
```

### 2.1 Model it as its own thing (per the task): `availability` state per (player, week)

- States: `CLEARED` (no listing) → `LISTED(Q/D/O + practice trend)` → `INACTIVE`/`ACTIVE`
  (T-90m truth) → `LOCKED`. Each state carries source + timestamp (the freshness doctrine).
- **Leg confidence over the week** (the task's explicit ask): a leg on a listed player carries
  an availability haircut that *changes as the week progresses* — e.g. TrueP multiplier
  `P(plays)` with defaults of order O≈0, D≈0.25, Q≈0.75 (Q with full Friday practice ≈0.9;
  Q with DNP-DNP-LP ≈0.5). Defaults are [ASSUMPTION — directional]; they get their own
  calibration dimension (`avail_q`, etc.) so the ledger can tune them like any adjustment.
  Additionally, the *replacement effect* matters in NFL (an OUT WR1 changes every teammate's
  target share) — availability changes re-trigger the volume model for the whole team, which
  is what the recheck-diff generalization exists to catch.
- Gate policy by phase: before Friday designations a leg on a listed player is at most
  PENDING-AVAILABILITY; after Friday, Q/D legs are flagged with the haircut applied; inside
  T-2h an unresolved Q needs the inactives check before lock (books void props of inactive
  players — same reason MLB voids DNP props); after T-90m the state is truth.
- QB is special: the QB's status reprices the *entire game* (spread/total move, every
  teammate's props) — the NFL analog of the SP-scratch invalidation class (E3/E4), wired
  into the same diff mechanism.

### 2.2 Data reality (from DATA_SOURCES §2.3/§3.1 — this shapes the design)

nflverse `injuries` (the official practice-report dataset) is **dead for 2025+**, and ESPN
(the practice/inactives source) is **currently unreachable from this environment** and
undocumented. Therefore the ladder must run **degraded by default**: `weekly_rosters` status
(IR/PUP/ACT) + `depth_charts` movement give the coarse availability floor; ESPN, when
enabled/reachable, upgrades it to the full Q/D/O + practice-trend ladder; absent both, legs on
uncertain players simply stay at PENDING-AVAILABILITY and the build says so. The app is
correct — just more conservative — with the enrichment off (task requirement).

---

## 3. Market mapping — MLB props → NFL prop universe

| MLB prop (leg type) | NFL analog(s) | Notes for the port |
|---|---|---|
| Pitcher Ks (the flagship) | **QB pass yds** (flagship volume prop) + pass TDs | Same role: high-liquidity, alt ladder, market-efficient. K-alt-ladder doctrine (one-lower alt, never estimate alt prices) transfers to `_alternate` yardage lines |
| K-Under discipline | Pass/rush/rec yds Unders | Same public-Over shading logic; same "books may already price it" caveat |
| Hits O0.5 (hitter floor prop) | **Receptions** (PPR-style floor prop) | Volume-driven, lineup-sensitive → snap/target share replaces batting order |
| Total bases | **Rec yds / rush yds** | Multi-outcome "softer than binary" family |
| HR (long-tail) | **Anytime TD** (and 1st TD = the extreme tail) | Same book-shading dynamics on stars; value hides mid-depth (the goal-line RB / slot WR in a high-total game) |
| RBI / runs (team-total correlated) | Anytime TD, red-zone volume props | Same "pair with team-total Over" structure — but in NFL that correlation is much stronger and priced (see §5) |
| SB / niche props | Longest completion/reception, INTs thrown, kicker points, defense | Thin/illiquid tier — C-tier, off by default (DATA_SOURCES §1.3) |
| Run line ±1.5 (margin) | **Spread** (key numbers 3/6/7 — margin distribution is lumpy, unlike run margins) | Spread-vs-ML pricing intuition must be re-learned; alt spreads cross key numbers |
| NRFI/YRFI side-tracker | Candidate analog: 1st-drive-points or 1H total | DROP at port (see PORT_PLAN decisions) — don't recreate until the core loop runs |

Settlement source per leg type: `stats_player` weekly rows (pass/rush/rec/def), `schedules`
finals (ML/spread/totals/team totals). Two flagged settle risks: kicking fields in
`stats_player` [ASSUMPTION — verify M1]; tackle props settle against press-box stats that
pbp-derived counts don't always match → defensive props stay MANUAL-settle (and C-tier)
until proven.

---

## 4. Modeling inputs — the part that actually differs

The MLB TrueP method survives (market no-vig baseline + fixed, named, ledger-audited
adjustments — it's sport-agnostic and it's the part of the system that measured well). What
changes is the **adjustment registry content** and the **pre-baseline volume arithmetic**:

### 4.1 Implied team totals (new primitive, replaces "SP quality vs lineup")

From the two most liquid numbers: `home_implied = total/2 − spread_home/2` (spread_home
negative for favorites), away symmetric. Every team-level and TD/yardage read anchors on it.
This is a *derivation*, not a model — it must live in the shared pricing lib (the NFL analog
of devig.sh's role: kill the by-hand arithmetic).

### 4.2 Game script (no MLB analog — the load-bearing new concept)

Favored teams run more late; trailing teams throw more. Encoded as adjustment inputs:
spread direction × total level → lean RB-attempts/rush-yds toward favorites, pass-volume
(attempts/completions/rec) toward underdogs/high totals; blowout risk caps starter snaps on
big favorites (starters sit in garbage time). Registry entries like `script_rush_fav`,
`script_pass_dog`, `blowout_snap_cap` with fixed pp magnitudes, calibrated by the ledger
exactly like `ace_edge` was.

### 4.3 Volume proxies (replace batting order / PA logic)

Priority given data reality (DATA_SOURCES §2.3): **snap share** (snap_counts, 6h cadence) ×
**target share / carry share** (stats_player weekly) × **depth-chart role**; enrich with
red-zone shares and pace/plays (pbp), aDOT (NGS), PROE (pbp/ftn). Route participation is
backtest-only (post-season release) — the in-season volume model must be explicitly built on
the first three. Pace/PROE combine into expected team plays → expected attempts/targets →
yards via efficiency priors; that arithmetic chain is the "SP-freshness block" analog: shown
per leg, date-stamped per input.

### 4.4 Matchup

Defensive efficiency **allowed by position** (RB/WR/TE splits from stats_player aggregation;
pfr_advstats pressures/coverage), O-line vs pass rush (sacks allowed vs generated, pressure
rates) gating QB props and sack props, secondary vs aDOT profile. Same doctrine shape as
"opposing-lineup K% vs handedness": one deterministic number per matchup, pulled from the
store, cited in the leg block.

### 4.5 Weather (much more material than MLB)

Wind ≥ ~15 mph: suppresses deep passing, FG range, totals — flag pass-yds Overs, kicker
props, game-total Overs; precip: ball security, unders lean; cold extremes: kicking + passing
efficiency; **dome = first-class boolean** short-circuiting all of it (schedules.roof +
stadium table). Forecast from Open-Meteo (verified working) at T-24h and T-2h; adjustments
enter the registry as named entries (`wind_under`, `wind_kicker_fade`, `dome_neutral`) with
modest magnitudes, same as the MLB park/weather family. The 15 mph threshold is
[ASSUMPTION — directional] pending its own calibration dimension.

---

## 5. Correlation — the biggest single delta; MLB's model is too naive to port as-is

**Finding from the audit (stated plainly, per the task):** the MLB correlation machinery
(`parlay.py` + `ticket.py`) models exactly **one 2-leg pair per ticket** with hand-assigned
qualitative tiers (ρ ±0.15/0.30/0.45), treats 3+ legs as independent, and treats same-game
stacking as the exception. That was adequate for MLB, where cross-game legs genuinely are
~independent and same-game pairs are occasional. **It is structurally inadequate for NFL**,
where the *default* attractive ticket is a same-game stack and nearly every prop pair in a
game is materially correlated:

- QB pass yds ↔ WR1 rec yds (strong +, mechanical: shared yardage), QB pass TDs ↔ WR anytime
  TD, RB rush yds ↔ team favored/ML (game script), team total Over ↔ every skill-position
  Over, game total ↔ both QBs' volume; negative structures: RB rush attempts ↔ own QB pass
  attempts (scripts fight), WR2 targets ↔ WR1 targets (shared pool), defense/kicker crosses.
  Cross-game legs remain ≈independent — that part of MLB doctrine ports.
- Books know this: **SGP engines reprice correlated combinations** (a QB-yds + WR1-yds SGP
  pays far under the independent product) and **block some same-game combinations outright**
  (frequently: player prop × game spread/total crosses, or redundant pairs). "Independent
  price × naive product" comparisons are therefore *systematically wrong* in NFL — sometimes
  by 20%+ — rather than occasionally wrong.

### Required upgrades (design, for PORT_PLAN)

1. **Correlation matrix as data, not per-leg CLI flags**: a versioned table of leg-type-pair →
   ρ tier (same-game), seeded from structural reasoning + backtestable against pbp/stats
   history (both weekly outcome joints from stats_player and priced-SGP reverse-engineering);
   hand-tiers remain the override, not the default input.
2. **Multi-leg joint pricing beyond one pair**: at minimum support N same-game legs via a
   Gaussian-copula over the pairwise ρ matrix (keeps the current `joint2` as its 2-leg case);
   ticket enumeration must price *every* same-game subset, because in NFL the recommended
   ticket will usually contain one.
3. **SGP-quote comparison as a first-class step** (not an optional `--sgp` flag): for any
   same-game ticket the tool's output is "minimum acceptable SGP quote" + "bet legs
   separately if the quote is under X" — MLB's `min_sgp_price` generalized.
4. **Blocked-combo awareness**: a book-agnostic blocklist table (pairs books commonly refuse)
   so the optimizer doesn't recommend an unbettable ticket; surfaced as a warning with the
   nearest bettable alternative.
5. **UI surfacing** (decision (b) in PORT_PLAN §7): correlation shown as a *feature* —
   suggested positive stacks with their floor gain (the MLB "ML + own SP K-Over buys 4-9pp"
   pattern, which in NFL becomes "QB-yds + WR1-yds needs the SGP quote vs independent" math),
   plus warnings on negative/blocked combos, plus corrected (never naive-product) payout
   expectations everywhere.

Numeric ρ seeds are [ASSUMPTION — directional] until backtested (M4 acceptance); the
*structure* (matrix + copula + SGP-floor + blocklist) is the requirement.

---

## 6. Preseason (immediate, it's August)

Separate odds sport key (verified active); featured markets only by default; **no player
props** [ASSUMPTION per book behavior — the scheduler treats absence as normal];
starters play snap-count-scripted cameos so nothing from the REG volume model applies.
Requirement: the app detects PRE (schedules.game_type / sport key), disables the prop
pipeline and volume model, allows featured-market paper builds only (clearly labeled), and
uses preseason weeks to soak-test ingest, polling, settlement, and CLV plumbing before Week 1
— which is exactly the milestone sequencing opportunity PORT_PLAN's M-plan exploits.
