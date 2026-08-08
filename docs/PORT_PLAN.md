# PORT PLAN — MLB parlay builder → NFL parlay builder

Phases 3+4 deliverable. Companions: `SOURCE_AUDIT.md` (what exists), `DATA_SOURCES.md`
(verified data landscape), `NFL_REQUIREMENTS.md` (domain deltas). **Plan only — no
implementation exists yet.** The MLB repo is untouched.

**Stack stance (per the rules):** same stack and architectural style as the MLB app — bash +
stdlib-Python CLI tools, markdown ledgers for decisions/outcomes, doctrine in CLAUDE.md,
selftest-guarded parsers, generated static dashboard on Pages, cron-driven Claude runs.
Three deliberate deviations, each with a concrete reason:

1. **SQLite context store** (stdlib `sqlite3`) instead of on-demand API fetch — nflverse is
   release files, not a query API, and the context layer's job is cross-source ID joins,
   which regex-over-markdown demonstrably can't do safely (the MLB selftest is a museum of
   exactly that bug class). Ledgers stay markdown; only *facts* move to SQLite.
2. **Structured leg identity** (a canonical `leg_id`, rendered to text) instead of free-text
   legs parsed by regex — the single biggest MLB bug source (SOURCE_AUDIT §3).
3. **Correlation engine v2** (pairwise ρ matrix + multi-leg joint pricing + SGP-floor +
   blocked-combo awareness) instead of the one-pair/hand-tier model — MLB's model is too
   naive for NFL's correlation structure (NFL_REQUIREMENTS §5; the audit says so explicitly,
   as the task predicted).

---

## 1. Target architecture

```
nfl_parlay_builder/
├── CLAUDE.md                  # NFL doctrine (rewritten; same gate/tier/registry structure)
├── docs/                      # this plan + generated dashboard (index.html)
├── config/
│   ├── markets.conf           # polled market set + tiers + per-phase cadences (decision c)
│   ├── stadiums.csv           # static ~32-row table: lat/lon/roof/surface/tz
│   └── corr_matrix.csv        # leg-family pair → ρ tier (same-game), versioned
├── data/
│   ├── context.db             # SQLite store — NOT committed (rebuilt from sources)
│   ├── ingest_manifest.json   # committed: per-dataset asset id/updated_at/rowcount/sha
│   └── weeks/2026-W01/        # committed per-week audit packs (slate, availability,
│                              #   volume table, weather snapshot — the .probables analog)
├── ledgers/
│   ├── results_log.md         # calibration & CLV ledger (schema ported, week-keyed)
│   ├── fades.md               # fade registry (structure ported, content starts empty)
│   └── bankroll.md            # $10 ladder (weekly cadence)
├── builds/2026-W01.md         # one append-only file per WEEK (was parlays/<date>.md)
├── tools/
│   ├── nfl_data.sh            # context-layer CLI: sync / slate / volume / form / player…
│   ├── ingest.py              # release-asset → SQLite normalizer (csv.gz, stdlib)
│   ├── odds_api.sh            # ported Odds API wrapper (sport-key + week windowing)
│   ├── poll_scheduler.py      # per-kickoff poll planner + credit budgeter (NEW)
│   ├── propquote.py           # kprice.py generalized: any player-prop + alternates
│   ├── devig.sh               # ported as-is
│   ├── implied.py             # spread+total → implied team totals (NEW primitive)
│   ├── truep.py               # ported mechanism; NFL adjustment registry
│   ├── availability.py        # injury/practice/inactives ladder + P(plays) (NEW)
│   ├── weather.py             # Open-Meteo forecast per outdoor game (NEW)
│   ├── corr.py                # correlation engine v2 (matrix + multi-leg joint) (NEW)
│   ├── parlay.py              # thin CLI over corr.py (interface preserved)
│   ├── ticket.py              # construction search, re-engined on corr.py
│   ├── weekcheck.py           # recheck.py generalized: snapshot+diff availability/QB/
│   │                          #   lines/weather; invalidates dependent legs
│   ├── settle.py              # settles all leg types from context.db (proposals)
│   ├── clv_capture.py         # window-close capture (+ backfill via historical API)
│   ├── calib.py / pulse.py    # measurement + exposure governor (ported, re-keyed)
│   ├── generate_dashboard.py  # ported; week-grouped; new availability/corr panels
│   ├── session_start.sh       # NFL digest (selftest→sync→staleness→unsettled→pulse)
│   ├── cron_build.sh          # weekly run skeleton, prompt-only single-source
│   └── selftest.sh            # same contract: fast, offline, quota-free
├── .claude/{settings.json, hooks/session-start.sh}
└── .github/workflows/pages.yml
```

Pipeline (unchanged in spirit from MLB):
**sync context → price (scheduler) → gate → derive TrueP → search construction → publish
3 tiers → log → capture CLV → settle → calibrate → govern exposure**.

## 2. Run model (replaces 11/16/18 ET daily)

Weekly skeleton (cron/scheduled Claude sessions; labels cosmetic — windows computed from
kickoff data):

| Run | When | Job |
|---|---|---|
| Week wrap | Tue AM | settle final window, full-week review (the prior-day-review analog), calib+pulse, fades update, dashboard |
| Week build | Wed/Thu | context sync, slate-wide scan (ALL games, every window), initial 3-tier build, bankroll pick — availability legs PENDING |
| Designation update | Fri PM | injury designations in, availability haircuts applied, build revised (supersede protocol) |
| Pre-window locks | T-2h before each window (TNF, Sun-early, Sun-late, SNF, MNF, intl Sat AM) | weekcheck diff, inactives (T-90m) if reachable, final prices, lock legs for THAT window only, CLV close at T-5m |
| Post-window settle | after each window (or folded into next run) | settle that window's legs from `schedules`/`stats_player`, update ledgers |

The per-kickoff **price polling** (DATA_SOURCES §1.4) is `poll_scheduler.py`'s job and runs
inside whichever session is active — runs don't poll on their own clock, they execute the
schedule that's due.

## 3. Port map (file-by-file)

Classification: **PORT** (as-is / trivial rename) · **ADAPT** (same design, targeted changes)
· **REWRITE** (same job, new internals) · **NEW** (no MLB analog) · **DROP**.

| MLB file | Verdict | What changes and why |
|---|---|---|
| `tools/devig.sh` | **PORT** | Sport-agnostic math (devig, edge gate, ¼-Kelly). Only prose touch-ups. |
| `.github/workflows/pages.yml` | **PORT** | Identical mechanism. |
| `.gitignore` | **PORT** | + `data/context.db`, odds cache. |
| `tools/odds_api.sh` | **ADAPT** | Keep: check/quota/caching/best-price jq/started-game guards/deny-reason handling/credit telemetry. Change: `SPORT` becomes config with **two keys** (`americanfootball_nfl`, `americanfootball_nfl_preseason` — verified separate); date-slate filtering (ET-day + post-midnight rule) → **week/window filtering** off `commence_time` + `schedules` join; MLB `PROPS_ALL/CORE` → `config/markets.conf` NFL sets; cache keyed per week+window, freshness phase-dependent. |
| `tools/kprice.py` | **ADAPT → `propquote.py`** | Same design (per-player line table, best price/side/line, no-vig per line, standard-line heuristic, quota guards, started-game refusal). Change: any prop market + `_alternate` (not just Ks); player→event resolution via store IDs (odds event id ↔ game_id join), not probables-snapshot surname match. |
| `tools/truep.py` | **ADAPT** | Mechanism ports untouched (baseline + fixed named adjustments, `[adj:]` ledger tags, ±3 custom cap, mirror `~name`). Registry **content** replaced with NFL entries (script/weather/availability/rest/matchup families per NFL_REQUIREMENTS §4); all magnitudes start [directional] and earn their §1c records like `ace_edge` did. |
| `tools/parlay.py` | **REWRITE (interface preserved)** | `joint2`+Fréchet clamp survives as the 2-leg case inside `corr.py`; the CLI keeps `--leg TrueP:price [--corr tier] [--sgp]` for habit-compat. New internals: ρ from the matrix by leg-family pair (hand tier = override), N-leg same-game joint via Gaussian copula, SGP-vs-independent verdict mandatory for same-game tickets. Reason: NFL_REQUIREMENTS §5 — one-pair/hand-tier is structurally wrong for NFL. |
| `tools/ticket.py` | **ADAPT (re-engined)** | Keep: enumeration, Pareto payout/floor frontier, +180..+260 band ranked by true prob, ¼-Kelly, min-SGP quote, rejected-constructions output, "NO BET is honest" posture. Change: legality rules (same-game combos default-modeled instead of default-forbidden; blocklist table consulted; ≥2 correlated legs priced via corr.py), leg input by structured `leg_id`. |
| `tools/mlb_api.sh` | **REWRITE → `nfl_data.sh` + `ingest.py`** | The *role* (deterministic authoritative facts, check-first, actionable BLOCKED messages) ports; the *architecture* flips from on-demand REST queries to **release-asset ingest into SQLite** (DATA_SOURCES §2.4 — nflverse is files, not an API; verified download path). Subcommand surface mirrors the old one: `check/sync/slate/finals/volume/form/player/depth/avail/weather/raw`. |
| `tools/recheck.py` | **REWRITE → `weekcheck.py`** | Same burn-class defense (the thing you premised a leg on silently changed). Diff domain grows from "probable SP + game status" to: QB/status changes, availability transitions (incl. designation posts + inactives), line moves past thresholds, weather crossings, kickoff/flex changes. Snapshot = the committed week pack. Exit-1-on-findings + fixture selftest pattern ports. |
| `tools/settle.py` | **REWRITE** | Same posture (READ-ONLY proposals; margin-settled spreads; integer-line pushes; DNP→MANUAL/void). Internals: settle from `context.db` (`schedules` finals for ML/spread/totals/TT; `stats_player` weekly rows for props) with `leg_id` joins — the surname-regex/gamelog machinery and DH G-hints disappear. New: kicking-fields verify at M1; tackle props stay MANUAL (press-box vs pbp mismatch). |
| `tools/clv_capture.py` | **ADAPT** | Verdict logic (closing no-vig vs logged no-vig, ±0.5pp dead-band, ⚠ EDGE-GONE, idempotent cell-surgical writes) ports. Change: "the close" is **per window** (T-5m scheduler poll = the close snapshot); per-game stale-cache guard keyed to each kickoff; prop closes via per-event polls already scheduled — mostly bookkeeping, not new spend. |
| `tools/clv_backfill.py` | **ADAPT** | Historical endpoint identical (10×/snapshot pricing). NFL is *cheaper*: kickoffs cluster, one snapshot closes a whole 9-game window. Keep plan-mode default + credit ceiling + paid-tier gate. |
| `tools/calib.py` | **ADAPT** | Bands, Brier-vs-market, per-adjustment attribution, S/P split, ROI — all port (sport-agnostic, and the part of MLB that worked best). Change: dedup by structured `leg_id` (kills `leg_key` regexes), dates → `season+week` keys (kills `ledger-epoch`). |
| `tools/pulse.py` | **ADAPT** | Governor rules (COOL/SUSPEND/MARKET-SHADE/GLOBAL-SHRINK, re-warm) port verbatim — they're the system's best idea. Change: window = last 3 weeks / last 25 decided legs (NFL sample arrives 1/7th as fast — thresholds re-examined at M6); dimensions = NFL bet types, prop families, availability tags, TrueP bands. |
| `tools/session_start.sh` | **ADAPT** | Same digest skeleton: §0 selftest → API checks → **context sync + staleness table** (new) → unsettled windows → fades → auto-CLV inside pre-window phases → pulse. ET-hour window arithmetic → schedule-driven phases. |
| `tools/cron_build.sh` | **REWRITE** | Keep: prompt-only single-source contract (hook delegates; selftest-pinned), missed-run watchdog absorption, credits-remaining reporting, notification/email steps. Change: build taxonomy = weekly skeleton (§2), selected by day/phase not ET hour. |
| `.claude/hooks/session-start.sh` + `settings.json` | **ADAPT** | Mechanism identical (sentinel, digest injection, delegate to cron_build --prompt-only). Phase detection changes with §2. |
| `tools/selftest.sh` | **ADAPT (pattern)** | The contract (fast, offline, quota-free, fixture-pinned regressions, wired into digest §0, red = STOP) ports as-is; the 33 checks are MLB-parser-specific and get rebuilt per milestone as NFL parsers/logic land. |
| `tools/generate_dashboard.py` | **ADAPT** | Section/chart set + parser-guard + calib-reconciliation port. Change: week-grouped views, availability board panel, correlation/stack panel, NRFI panel dropped; parses the NFL ledgers; keep Chart.js CDN (or vendor it — minor decision (h)). |
| `tools/nrfi_settle.py`, `tools/nrfi_digest.py`, `nrfi_tracker.md` | **DROP** | MLB-specific side product. A 1H-total/first-drive analog is possible later but is scope creep before the core loop runs (decision (g)). |
| `CLAUDE.md` | **REWRITE** | Structure ports (doctrine style, gate header, 3-tier contract, min-edge gates, TrueP method, staking, supersede protocol, promoting-lessons bar, git workflow incl. the no-amend rule). Content is MLB-earned and does NOT port: burn tags, K-prop micro-doctrine, fade entries, MLB run cadence. NFL doctrine starts thin and earns its rules the same way. |
| `fades.md` | **ADAPT (template)** | Registry structure + validation protocol + status transitions port; entries start EMPTY (MLB fades are not evidence about NFL). Team-form transitions anchor to point differential (the run-diff rule, renamed). |
| `results_log.md` | **ADAPT (schema)** | Columns port (`…TrueP/ImplP/Edge/Result/Played/CLV/Bucket` + process-grade + `[adj:]`); add `Week` + `leg_id`; log-the-whole-scan and pre-registration doctrine unchanged. |
| `bankroll.md` | **ADAPT** | Ladder rules port; cadence becomes weekly (decision (f)). |
| `parlays/YYYY-MM-DD.md` template | **ADAPT** | → `builds/<season>-W<week>.md`, append-only per RUN within the week, supersede protocol, per-window lock sections, `## Result` per window. |
| `parlays/.probables/*.json` | **REWRITE → `data/weeks/` packs** | Same audit-record idea, wider content (slate, availability states, volume table, weather, line snapshot) — what `weekcheck.py` diffs against. |
| `tools/README.md` | **ADAPT** | Keep the **coverage matrix** discipline (leg-type × pipeline-stage, open-cells-must-be-listed) — rebuilt with NFL rows; it's the best audit artifact in the repo. |
| `docs/index.html` | generated | Regenerated by the adapted generator. |

**MLB assumptions that break (transplant checklist)** — each is addressed above; flagging per
the task: daily slate→week+windows; one lock→per-game locks; lineup-post gate→availability
ladder; SP-freshness→QB/volume-input freshness stamps; gamelog/boxscore settle→store settle;
DH G-hints→cross-source ID joins; 9-inning/no-clock margins→key-number spreads; batting
order→snap/target share; low correlation→pervasive correlation (engine v2); on-demand
fetch→pre-computed store; calendar-year season→season+week keys; team nickname dicts ×3→one
`teams` table; leg-text-as-schema→`leg_id`.

## 4. Milestones (sequenced; data-layer risk retired first; each independently runnable)

**No UI work before M1+M2 are proven end to end** (per the task). It's 2026-08-08: preseason
is live now, REG Week 1 kicks off 2026-09-09 — M1–M5 can run against real data immediately,
and preseason weeks are the soak window.

| # | Milestone | Scope | "Done" looks like |
|---|---|---|---|
| M0 | Scaffold | Repo layout, `config/` (markets.conf, stadiums.csv seeded from `schedules` + hand lat/lon), selftest skeleton, CLAUDE.md v0 | `selftest.sh` green; `stadiums.csv` covers all 32 teams incl. roof flags |
| **M1** | **Context ingest proven E2E** (the risk) | `ingest.py` + `nfl_data.sh sync`: schedules, stats_player, snap_counts, depth_charts, weekly_rosters, teams, players → `context.db`; manifest; staleness stamps | One command builds the store from nothing; `nfl_data.sh slate 2026 1` prints the real Week 1 (272-game season verified present); `volume <team> 2025 <wk>` prints snap/target shares for a historical week; kicking fields confirmed or flagged; re-run = no-op (ETag); selftest fixtures for every parser |
| M2 | Market layer | `odds_api.sh` adapt (both sport keys), `poll_scheduler.py` + budget guard, `propquote.py` | Live preseason featured board pulls today; scheduler dry-run for a simulated 16-game week prints the poll plan + credit estimate ≤ budget (DATA_SOURCES table reproduced from code); prop-posting timing observed and logged one real week; credit telemetry line per run |
| M3 | Domain gates | `availability.py` (degraded-mode default), `weather.py` + stadium join, `weekcheck.py` snapshot/diff | Gate table renders for a real week with store data; ESPN absent ⇒ visibly degraded (PENDING-AVAILABILITY), never wrong; weather populated for outdoor games at T-24h; weekcheck catches an injected QB/status/line change (fixtures) |
| M4 | Pricing + construction | `devig.sh`, `implied.py`, `truep.py` NFL registry, `corr.py` v2, `parlay.py`/`ticket.py` re-engined | A full historical week (2025) prices end-to-end: scan table → gate-cleared legs → 3 tiers with corr-adjusted floors + min-SGP quotes; corr matrix seeded and sanity-backtested against joint outcomes from `stats_player` history; blocklist consulted |
| M5 | Ledger loop | `results_log.md` NFL schema, `settle.py`, `clv_capture.py`+backfill, `builds/` template, bankroll | A live paper week (preseason featured markets now, or REG Wk1) is built, logged, CLV-closed per window, and auto-settle proposals match hand-checked results; CLV cells fill or say MANUAL — never fake |
| M6 | Measurement + governor | `calib.py`, `pulse.py`, selftest reconciliation checks | calib runs on the paper ledger and reconciles with the file prose; pulse produces (empty-window) output; dashboard-parser reconciliation checks wired |
| M7 | Dashboard | `generate_dashboard.py` adapt + Pages | Site deploys from `main`; week-grouped panels render the paper data; `--selftest` reconciles with calib |
| M8 | Ops | `cron_build.sh` weekly skeleton, hook, notifications, watchdogs | One fully unattended real week (target: REG Week 1, Sep 9–14) produces builds, locks, CLV, settles, dashboard, push+email — with the audit trail complete and selftest green throughout |

## 5. NFL domain model — type/schema definitions (implementation-free)

`context.db` tables (SQLite; names = nflverse fields where they exist):

```
teams(team TEXT PK, full_name, conference, division, stadium_id)
stadiums(stadium_id TEXT PK, name, lat REAL, lon REAL, roof TEXT, surface TEXT, tz TEXT)
games(game_id TEXT PK,                -- nflverse '2026_01_NE_SEA'
      season INT, week INT, game_type TEXT,      -- PRE/REG/POST
      kickoff_utc TEXT, window_id TEXT,          -- computed by clustering
      away TEXT, home TEXT, neutral INT,
      away_rest INT, home_rest INT, div_game INT,
      roof TEXT, surface TEXT, stadium_id TEXT, referee TEXT,
      away_score INT, home_score INT, status TEXT,
      odds_event_id TEXT, espn_id TEXT, pfr_id TEXT,   -- cross-source joins
      close_spread REAL, close_total REAL, close_ml_home INT)  -- from schedules (backtest/CLV ref)
players(gsis_id TEXT PK, name, position, team, espn_id, pfr_id, status, updated_at)
depth(season INT, week INT, team, position, depth_rank INT, gsis_id, source_ts)
snaps(season INT, week INT, gsis_id, team, off_snaps INT, off_pct REAL, def_snaps INT, def_pct REAL)
player_week(season INT, week INT, gsis_id, team, opponent,
      completions, attempts, passing_yards, passing_tds, passing_interceptions,
      carries, rushing_yards, rushing_tds, targets, receptions, receiving_yards,
      receiving_tds, sacks_suffered, fg_made, fg_att, pat_made, def_sacks, def_tackles, …)
availability(season INT, week INT, gsis_id,
      practice_wed TEXT, practice_thu TEXT, practice_fri TEXT,   -- DNP/LP/FP/NULL
      designation TEXT,          -- OUT/DOUBTFUL/QUESTIONABLE/NULL
      active INT,                -- from inactives; NULL until T-90m known
      p_plays REAL, source TEXT, updated_at TEXT)
weather(game_id, forecast_ts, kickoff_temp_f, wind_mph, gust_mph, precip_prob, source)
odds_close(event_id, market, outcome, point REAL, price INT, book, captured_ts)  -- window closes
```

Leg / ticket records (ledger-side; rendered to markdown, identified structurally):

```
leg_id  = "{season}-W{week}:{game_id}:{market}:{side}:{point?}:{gsis_id?}"
          e.g. 2026-W01:2026_01_BUF_HOU:player_pass_yds:Over:249.5:00-0034857
Leg     = {leg_id, label, tier(A/B/C market tier), price:int, book,
           truep_pct, implp_novig_pct, edge_pp, adj_tags[], avail_state,
           bucket(S/P), process_grade, result(W/L/Push/Void/TBD), clv}
Ticket  = {legs[leg_id], same_game_groups[], rho_source(matrix|override),
           true_combined_pct, decimal, payout_american, ev_pct, floor_note,
           min_sgp_quote?, blocked_warnings[]}
CorrEntry = {family_a, family_b, same_game:bool, rho_tier, rho, basis(structural|backtest),
             notes}   -- families like QB_pass_yds, WR1_rec_yds, RB_rush_yds, team_ml,
                      -- team_total_over, game_total_over, anytime_td, kicker_pts
```

## 6. Decisions for you (each with my recommended default — "go with your defaults" works)

| # | Decision | Options | **Recommended default** + why |
|---|---|---|---|
| (a) | Context layer: pre-computed weekly store vs on-demand fetch | store / on-demand / hybrid | **Pre-computed SQLite store, rebuilt per session from release assets, manifest + per-week packs committed, DB not committed.** nflverse is files (verified); on-demand would re-download per question; committing the DB bloats git ~3×/wk. Manifest keeps provenance auditable in the MLB `.probables` spirit. |
| (b) | How correlation surfaces in the UI/output | suggest stacks / warn only / adjust payouts / all | **All three**: builds list the top positive same-game stacks with floor-gain + min-SGP quote; the optimizer warns on negative pairs and book-blocked combos (never recommends them); every displayed combined prob/payout is correlation-adjusted — the naive product is never shown unlabeled. Dashboard gets a stack-performance panel once data accrues. |
| (c) | Default polled prop markets | minimal(4) / **core(8)** / broad(14+) | **Core 8**: pass_yds, pass_tds, pass_interceptions, rush_yds, rush_attempts, receptions, reception_yds, anytime_td (~1,750 cr/wk incl. board+closes+backfill, ~62% headroom on 20K/mo). Alternates pulled per shortlisted leg; kicking/defense/period/longest opt-in (thin, settle-fragile). |
| (d) | Injury/practice source | ESPN best-effort / paid API / manual-only | **ESPN best-effort on top of a degraded-mode default** (rosters+depth floor). Requires you to allowlist `site.api.espn.com` + `sports.core.api.espn.com` in the environment (verified blocked today); until then the app runs degraded-correct. No paid data. |
| (e) | Preseason posture (it's August) | ignore / paper-builds / full builds | **Paper-builds on featured markets only**, clearly labeled, no ladder, no props (separate sport key verified; props assumed absent) — used to soak M2/M5 plumbing before Week 1. |
| (f) | Bankroll ladder cadence | per-window / weekly | **One roll per week** (safest qualifying favorite across the whole week, placed at its own window lock). 4-win target ≈ a month horizon, matching NFL rhythm; per-window rolls would triple exposure without new edge. |
| (g) | NRFI-analog side tracker | port as 1H-total tracker / drop | **Drop at launch.** Re-propose a 1H-total/first-drive tracker only after the core loop has a few settled weeks (it was a late MLB addition too). |
| (h) | Odds API key | share the MLB key / second key | **Share** (verified: 19,556 remaining; combined burn fits with headroom). The credits-remaining-every-run doctrine already guards it; split later only if MLB+NFL overlap (Sept/Oct) squeezes. |
| (i) | Dashboard chart lib | keep Chart.js CDN / vendor it | **Keep the CDN** (matches MLB; zero build step). Vendor only if offline viewing matters to you. |

## 7. Open questions & assumptions register

Assumptions I had to make (all flagged inline where used):

1. **Prop posting timing + preseason prop absence** — [ASSUMPTION], verified by observation in
   M2's real-week log. Scheduler already treats absence as normal.
2. **Kicking fields present in `stats_player`** — likely (145 vars) but unverified; M1 checks,
   else kicker props settle MANUAL.
3. **Availability haircuts (Q≈0.75 etc.) and the 15 mph wind threshold** — directional seeds;
   each gets its own calibration/attribution dimension rather than being trusted.
4. **Correlation ρ seeds** — structural reasoning first, backtest against historical joint
   outcomes at M4; the matrix is data so re-seeding doesn't touch code.
5. **Book blocklist contents** — assembled empirically during paper weeks (no public spec).
6. **ESPN endpoint shapes** — undocumented; fixture-pinned parsers + degrade-on-drift.
7. **Pulse window sizing for weekly cadence** (3 weeks / 25 legs) — re-examined at M6 once
   real decided-leg volume per week is known.
8. **The Wednesday opener quirk**: the odds feed and nflverse agree Week 1 opens Wed 9/9 —
   treated as confirmation that windows must be data-driven, but worth a glance at flex/PPD
   handling when the first schedule change of the season lands.

Questions for you (non-blocking — defaults above let me proceed):

- Q1: Is the Odds API key intended to be shared across both apps long-term (decision h)?
- Q2: Will you allowlist the two ESPN hosts in this environment (decision d), or should the
  injury layer plan on degraded mode indefinitely?
- Q3: Weekly notification cadence: same push+email per run as MLB, or consolidated (build /
  Friday update / Sunday locks / Tuesday wrap)? Default: consolidated at those four points.
- Q4: Any appetite cap on defensive/kicker props even as C-tier scan-only rows? Default:
  scan-log them, never tier them, MANUAL settle.

---

*End of plan. Stopping here per the task — no implementation until you review. The natural
first increment after sign-off is M0+M1 (scaffold + context ingest), which can be proven
against live 2026 schedules and 2025 historical data immediately.*
