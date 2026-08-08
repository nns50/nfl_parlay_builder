# DATA SOURCES — layered spec for the NFL parlay builder

Phase 2a deliverable. Three layers: **market** (The Odds API — ported wrapper), **context**
(nflverse ingest — new, no MLB analog), **live** (ESPN + Open-Meteo — best-effort enrichment).
Everything marked **[VERIFIED]** was checked live from this environment on 2026-08-08;
everything marked **[ASSUMPTION]** must be confirmed at the milestone that first depends on it.

---

## Layer 1 — MARKET (The Odds API) — port of `odds_api.sh`

### 1.1 Verified facts [VERIFIED 2026-08-08, live API, key active, 19,556 credits remaining]

- Sport keys (from `/sports?all=true`, free): **`americanfootball_nfl`** (active),
  **`americanfootball_nfl_preseason`** (active — a *separate sport key*, not a flag on the NFL
  key), `americanfootball_nfl_super_bowl_winner` (outrights). This partially solves season-type
  detection at the market layer: August games live under the preseason key.
- `/sports/americanfootball_nfl/events` (free) already lists **all 272 regular-season games**
  (17 weeks × 16). Week 1 verified: opener **Wed 2026-09-09 20:20 ET** (NE@SEA), SF@LA Thu at a
  **Neutral** site, then the Sunday 17:00Z/20:25Z windows, SNF, MNF. Consequence: **game
  windows must be derived from `commence_time` clustering, never hardcoded weekday labels.**
- Market keys for American football (from the official betting-markets doc):
  - Featured, bulk `/odds`: `h2h`, `spreads`, `totals` (+ `outrights` on the winner key).
  - Period markets: `h2h_q1..q4`, `h2h_h1/h2`, `spreads_*`, `totals_*`, `team_totals_*` and
    `alternate_*` variants per quarter/half.
  - Player props, **per-event `/events/{eventId}/odds` only**: passing (`player_pass_yds`,
    `player_pass_tds`, `player_pass_attempts`, `player_pass_completions`,
    `player_pass_interceptions`, `player_pass_longest_completion`), rushing
    (`player_rush_yds`, `player_rush_attempts`, `player_rush_longest`, `player_rush_tds`),
    receiving (`player_receptions`, `player_reception_yds`, `player_reception_longest`,
    `player_reception_tds`), combos (`player_pass_rush_yds`, `player_rush_reception_yds`,
    `player_pass_rush_reception_yds`, + `_tds` variants), TD scorers (`player_anytime_td`,
    `player_1st_td`, `player_last_td`, `player_tds_over`), kicking (`player_field_goals`,
    `player_kicking_points`, `player_pats`), defense (`player_sacks`, `player_solo_tackles`,
    `player_tackles_assists`, `player_defensive_interceptions`, `player_assists`).
  - **Every core prop has a `_alternate` variant** (milestone/X+ lines) — the NFL analog of the
    MLB alt-K ladder.
- Cost model (same as MLB, re-confirmed by the wrapper's live behavior): credits =
  **markets × regions per request**; per-event prop calls bill per event. `/sports` and
  `/events` are free. Historical snapshots bill **10× (10 × markets × regions per timestamp)**.
- Quota telemetry via `x-requests-remaining` / `x-requests-used` headers (already parsed by the
  wrapper; keep the report-credits-every-run doctrine).

### 1.2 [ASSUMPTION — verify in M2] Prop availability timing

Books post NFL player props inside game week (typically Wed–Thu for Sunday), not weeks out;
**preseason games get no player props** (the preseason key should be polled with featured
markets only). Neither is stated in the docs; both match book behavior. The scheduler must
treat "market absent from response" as *normal pre-posting state*, not an error, and the M2
acceptance test is one real week of observed posting times.

### 1.3 Market key → app leg-type map (default reliability tiers)

| Market key(s) | App leg type | Tier |
|---|---|---|
| `h2h` | ML | **A — always offered, most efficient** |
| `spreads` (+alt) | Spread (margin-settled, push-capable) | **A** |
| `totals` (+alt) | Game total | **A** |
| `team_totals_*` | Team total (derive fair value from spread+total; see NFL_REQUIREMENTS §4.1) | **B — offered on main books, thinner** |
| `player_pass_yds`, `player_pass_tds`, `player_rush_yds`, `player_receptions`, `player_reception_yds`, `player_anytime_td` | Core player props | **A/B — near-universal on US books in game week** |
| `player_pass_attempts/completions/interceptions`, `player_rush_attempts` | Volume props | **B** |
| `player_1st_td`, `player_last_td` | Long-tail TD props | **B — offered widely but high-vig; standalone-only** |
| `player_field_goals`, `player_kicking_points`, `player_pats` | Kicking props | **B/C — fewer books** |
| `player_sacks`, `player_solo_tackles`, `player_tackles_assists`, `player_defensive_interceptions` | Defensive props | **C — THIN (few books, low limits); off by default** |
| `player_pass_longest_completion`, `player_reception_longest`, `player_rush_longest` | Longest-play props | **C — thin + settlement-fragile; off by default** |
| `*_q1/_h1` period markets | Period legs | **C — off by default (adds scan surface without demonstrated edge)** |
| `player_*_alternate` | Alt ladders (the "one-lower alt" safety knob) | On-demand only, per shortlisted leg (the MLB `kprice.py` pattern) |

Tier A/B assignments beyond the featured markets are [ASSUMPTION] until M2 logs one real week
of book counts per market; the scan output should print books-offering-count per prop so the
tiers become measured, not asserted.

### 1.4 Credit budget + per-kickoff polling scheduler (replaces the MLB global refresh)

**Why the MLB pattern doesn't transfer:** MLB = one nightly slate, one 3-credit board pull +
props sweep at 16:00. NFL = ~16 events/week clustered into ~6 kickoff windows across 5+ days,
with props that only exist in game week, per-event billed. A global "poll everything each run"
loop either goes stale (too slow) or burns credits pricing Thursday's game all Monday.

**Design — `poll_scheduler` (new tool):** each event gets a poll plan keyed to *its own
kickoff* `T`; the scheduler batches all due polls whenever a run fires and skips windows with
no due events ("idle otherwise"). Featured board = one bulk call for all events (cheap);
props = per-event calls only when due.

| Phase (relative to each event's kickoff) | Featured board (bulk, 3 cr/call) | Props (per event, `N_markets` cr) |
|---|---|---|
| Week open → T-72h | 2×/day (whole-board, shared) | none (not posted / not actionable) |
| T-72h → T-24h | 3×/day shared | 1×/day |
| T-24h → T-2h | every 6h shared | every 6h |
| **T-2h → kickoff (aggressive window)** | every 15 min | every 30 min |
| T-5m | final board poll = **the CLV close snapshot** | final props poll = prop close |
| Post-kickoff | stop (started-game guard, ported from MLB) | stop |

**Default config** (all knobs in one config file, per the requirement):
`DEFAULT_PROPS` = 8 markets (`player_pass_yds`, `player_pass_tds`,
`player_pass_interceptions`, `player_rush_yds`, `player_rush_attempts`, `player_receptions`,
`player_reception_yds`, `player_anytime_td`); regions `us`; alternates + defense/kicking/period
markets opt-in per event or per leg.

**Estimated weekly cost at the default config, 16-game week** (arithmetic shown so the knobs
are obvious):

| Component | Math | Credits/wk |
|---|---|---|
| Featured board, baseline (Tue–Sun) | ~18 shared calls × 3 | ~54 |
| Featured board, aggressive windows | ~6 windows × 8 calls × 3 | ~144 |
| Props, T-72→T-24 | 16 events × ~2 polls × 8 | ~256 |
| Props, T-24→T-2 | 16 × ~4 × 8 | ~512 |
| Props, T-2h window + close | 16 × 5 × 8 | ~640 |
| Alt-line pulls on shortlisted legs | ~10 legs × 2 markets | ~20 |
| CLV backfill reserve (historical, 30 cr/snapshot; kickoffs cluster so one snapshot covers a whole window) | ~4 snapshots | ~120 |
| **Total** | | **~1,750/wk ≈ 7,600/mo** |

Fits the paid 20K/mo tier with ~60% headroom (MLB currently burns ~1.5-2K/mo on the same key —
confirm whether the key is shared across both apps; if shared, headroom is still ~10K).
Cheapest knobs if the budget tightens, in order: halve T-2h props frequency (−320),
drop `player_rush_attempts`+`player_pass_interceptions` from the default set (−350),
skip props polling before T-24h (−256).

### 1.5 Failure behavior / fallbacks (market layer)

| Failure | Behavior |
|---|---|
| Egress denied (`x-deny-reason`) | Same as MLB: actionable "allowlist `api.the-odds-api.com`" message; routine falls back to manual price entry, flagged. |
| `DEACTIVATED_KEY` / quota exhausted | Ported guards: user-action message; prop pipeline self-gates below a credit floor (MLB's ≥5000 `rich` gate → keep, threshold configurable). |
| Event id rotation / event missing | Ported from `kprice.py`: cache-first event-id resolution off the featured cache; re-warm on `EVENT_NOT_FOUND`. |
| Market absent from response | Normal pre-posting state → leg stays PENDING-PRICE; never an error, never estimated (MLB "never estimate alt prices" doctrine). |
| Started game | Ported hard guard: prices from post-kickoff caches are neither shoppable nor closes; CLV falls to the historical backfill path. |

---

## Layer 2 — CONTEXT (nflverse) — NEW; the layer with no MLB analog

### 2.1 What nflverse actually is [VERIFIED]

`github.com/nflverse/nflverse-data` publishes datasets as **GitHub release assets** (one
release tag per dataset; files per season in csv / csv.gz / parquet / rds / qs), *not* a REST
API. Verified inventory (all three release pages enumerated 2026-08-08): `schedules`, `teams`,
`players`, `weekly_rosters`, `rosters`, `stats_player`, `stats_team` (the old `player_stats`
tag is **deprecated as of 2025-08-01** — do not build on it), `ftn_charting`, `espn_data`,
`pbp`, `pbp_participation`, `snap_counts`, `depth_charts`, `injuries`, `nextgen_stats`,
`pfr_advstats`, `officials`, `contracts`, `draft_picks`, `combine`, `trades`, `misc`.

**Download path proven end to end from this environment** [VERIFIED]:
`https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv` returned
HTTP 200 (2.17 MB). The 2026 season is present (272 REG rows). Header confirmed:

```
game_id, season, game_type(PRE/REG/POST), week, gameday, weekday, gametime,
away_team, away_score, home_team, home_score, location(Home/Neutral), result, total,
overtime, old_game_id, gsis, nfl_detail_id, pfr, pff, espn, ftn,
away_rest, home_rest, away_moneyline, home_moneyline, spread_line, away_spread_odds,
home_spread_odds, total_line, under_odds, over_odds, div_game, roof, surface, temp, wind,
away_qb_id, home_qb_id, away_qb_name, home_qb_name, away_coach, home_coach, referee,
stadium_id, stadium
```

This one file is the **backbone**: game identity + cross-source IDs (espn/pfr/gsis/ftn — the
join keys the MLB app never had), week/season-type, kickoff times, **scores → settlement**,
pre-computed rest days, roof/surface, referee, and historical **closing ML/spread/total** (a
free CLV/backtest reference).

### 2.2 Per-dataset cadence + role (cadences from the nflverse update-schedule doc [VERIFIED])

| Dataset | In-season cadence | Role in the app | Trust |
|---|---|---|---|
| `schedules` (games.csv) | **every 5 min** | Game universe, week model, kickoff times, **finals for settlement**, rest, roof, referee | Core |
| `stats_player` | nightly + points on game days | **Prop settlement source** (weekly box-score-matching lines: completions, attempts, passing_yards/tds/interceptions, carries, rushing_yards, targets, receptions, receiving_yards, + defense; 145 vars). Kicking fields to confirm at M1 [ASSUMPTION]. | Core |
| `snap_counts` | every 6h (PFR) | **In-season volume source**: snap counts/share by player — the participation fallback | Core |
| `depth_charts` | daily 07:00 UTC year-round (post-2024 source, timestamp-based) | Role/starter identification (QB1, RB committee, WR order) | Core |
| `weekly_rosters` | daily | Roster status (ACT/RES/PUP…) — coarse availability signal | Core |
| `pbp` | nightly (raw ≤15 min after each game) | Modeling: pace, PROE, red-zone shares, script splits; not needed for MVP settle | Enrich |
| `ftn_charting` | every 6h | Per-play charting 2022+ (motion/PA/screen/box counts) | Enrich |
| `nextgen_stats` | nightly | NGS weekly player metrics (aDOT, time-to-throw, etc.) | Enrich |
| `pfr_advstats` | daily | Advanced def/off splits (pressures, blitz rates) | Enrich |
| `officials` | in-season | Referee assignments (crossable with `schedules.referee`) | Enrich |
| `teams`, `players` | occasional | **The canonical team/player tables** — ends the MLB pattern of nickname dicts duplicated per tool | Core |

### 2.3 ⚠ The two datasets that DON'T work the way we'd want [VERIFIED — this is the finding]

1. **`injuries` is dead for current seasons.** The nflverse update schedule states the source
   ended after the 2024 season: *"At the moment, there is no 2025 data"*, no ETA. The release
   still exists (historical through 2024) — useful for backtests, **unusable for the in-week
   practice-report ladder.** Consequence: the injury layer must be built on ESPN (best-effort,
   Layer 3) + `weekly_rosters` status + `depth_charts` movement, with the *practice-report*
   fields (Wed/Thu/Fri participation, Q/D designations) treated as an enrichment that can be
   absent. NFL_REQUIREMENTS §3 designs the confidence ladder to degrade accordingly.
2. **`pbp_participation` (route participation / personnel) is post-season-only for 2023+.**
   Assets exist 2016–2025 [VERIFIED: `pbp_participation_2025.*` last updated 2026-02-10], but
   the schedule doc is explicit: FTN-sourced 2023+ participation **"does not update during the
   season."** Consequence, exactly as the task suspected: **route participation is a backtest
   feature only. In-season volume estimation = snap share (`snap_counts`, 6h cadence) ×
   target share (`stats_player` weekly targets) × depth-chart role.** The plan says this
   explicitly and the volume model must not silently assume route data exists for the current
   week.

### 2.4 Ingest design (pre-computed store — the architectural break from MLB)

- **Format decision:** use the **csv / csv.gz release variants, not parquet.** Verified: this
  environment has stdlib-only Python (no pyarrow, no pandas, no duckdb; sqlite3 3.45 present).
  Parquet would force a dependency the stack doesn't have; csv.gz sizes are fine (schedules
  2.2 MB, snap_counts ~2 MB/season, stats_player ~seasonal shards).
- **Store:** normalize into **SQLite** (`data/context.db`), stdlib `sqlite3` + `csv` + `gzip`
  + `urllib`. Tables mirror the domain schema in PORT_PLAN §5. SQLite (not markdown) because
  the context layer is *facts joined across sources by ID*, which regex-over-markdown was the
  MLB app's biggest bug class; the *ledgers* (decisions/outcomes) stay markdown, unchanged.
- **Cadence:** `nfl_data.sh sync` (the `mlb_api.sh` replacement) refreshes per-dataset on its
  natural cadence, keyed off the release asset `updated_at`/ETag — schedules on every run;
  snap_counts/depth_charts/rosters daily; stats_player after game days; pbp/NGS/pfr weekly.
  Each table carries `fetched_at` + source timestamp; every consumer prints the staleness
  stamp (the SP-freshness "date-stamped source" doctrine, generalized).
- **Not committed to git**: the DB rebuilds deterministically from release assets;
  a committed `data/ingest_manifest.json` (per dataset: asset name, upstream `updated_at`,
  row count, sha) makes each run's data provenance auditable — the NFL analog of committing
  `.probables/` snapshots. Small derived per-week context packs (the inputs a build actually
  used) are committed as the audit record.
- **Failure behavior:** a failed refresh **keeps the last-good table** and marks it STALE
  (with age) rather than erroring the run; consumers gate like the MLB freshness gates —
  a leg premised on stale volume/injury data is PENDING, not silently priced. A missing
  *dataset* (injuries-style upstream death) idles its features, never the app.

---

## Layer 3 — LIVE (best-effort enrichment; the app must be fully correct without it)

### 3.1 ESPN `site.api.espn.com` (undocumented)

- Intended uses: live game state (`/apis/site/v2/sports/football/nfl/scoreboard`), in-week
  injury/practice status (`…/teams/{id}/injuries` and event summaries), and the **T-90min
  inactives** (event summary feeds).
- **[VERIFIED — currently BLOCKED]**: from this environment the host **times out through the
  egress proxy** (connection timed out; not reachable today). Two consequences for the plan:
  (a) the environment allowlist needs `site.api.espn.com` (and `sports.core.api.espn.com`)
  added before M3's live layer can even be tested — same one-time env step as `*.mlb.com` was
  for the MLB app; (b) the design must already be what the task demands anyway — *best-effort*:
  every ESPN-derived field is optional, degrades to "UNKNOWN — treat as PENDING/unverified",
  and no gate can *require* ESPN to pass. Being undocumented, shapes can drift without notice:
  parse defensively, selftest with committed fixtures, degrade on shape mismatch.
- Fallback chain for what ESPN would provide: live game state → `schedules` scores (5-min
  cadence; good enough for settlement, no in-progress detail) + kickoff-time-based
  started-game guards (an event whose kickoff has passed is LOCKED regardless of feed);
  injuries/inactives → weekly_rosters status + depth_charts + manual flag in the build.

### 3.2 Open-Meteo (forecast weather) [VERIFIED — working from this environment]

- `api.open-meteo.com/v1/forecast` — no key, tested live: hourly `temperature_2m`,
  `precipitation_probability`, `wind_speed_10m`, `wind_gusts_10m`, °F/mph units, 16-day
  horizon (covers any game from week open). Pull the kickoff-hour ±3h window per outdoor game.
- Requires the **static stadium table** (~32 rows, committed as csv or a table in the store):
  `team, stadium_id, stadium, lat, lon, roof(dome/retractable/outdoor), surface, tz`. Seed
  roof/surface/stadium from `schedules` (verified those columns exist) + lat/lon entered once
  by hand; `schedules.roof` also drives the dome short-circuit (no weather gate for domes —
  the MLB dome-list pattern, but data-driven instead of hardcoded).
- Failure behavior: unreachable → weather adjustments contribute 0 and the gate row shows
  "weather UNVERIFIED" (identical to MLB's pre-game empty weather state).
- `schedules.temp/wind` are historical actuals — backtest calibration for the weather
  adjustments, not forecasts (as the task noted).

---

## Refresh-cadence & fallback summary (one table to rule the runbook)

| Layer / source | Normal cadence | Staleness rule | Primary fallback |
|---|---|---|---|
| Odds featured board | scheduler phases (§1.4) | started-game guard; cache age printed | manual book pull, flagged |
| Odds props | per-event phases (§1.4) | absent = pre-posting (PENDING-PRICE) | manual book pull; leg stays unpriced otherwise |
| Odds historical | on demand (CLV backfill) | paid-tier + ceiling gates | CLV cell stays blank + flagged (never faked) |
| nflverse schedules | every run | >6h old in-season = STALE banner | none needed (also mirrored via git raw) |
| nflverse stats_player | post-gameday | settle blocks on missing week | settle stays TBD → MANUAL proposal |
| nflverse snap_counts / depth_charts / rosters | daily | age-stamped; stale ⇒ volume legs PENDING | prior week's table, flagged |
| nflverse participation | **postseason only** | never current in-season | snap share × target share (doctrine) |
| nflverse injuries | **dead 2025+** | historical only | ESPN best-effort → roster status → UNVERIFIED gate |
| ESPN | opportunistic | any failure = feature absent | schedules scores + kickoff-clock guards |
| Open-Meteo | T-24h and T-2h per outdoor game | forecast age stamped | no weather adjustment + UNVERIFIED flag |
