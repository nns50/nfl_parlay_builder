# SOURCE AUDIT — `nns50/mlb_parlay_claude`

Phase 1 of the NFL port. Audited 2026-08-08 at commit `b279379` ("CLV backfill from historical
snapshots + moved-close hint pin + date-semantics doc"). Every file in the repo was read.

**The most important thing to understand up front:** this is **not a web app**. It is a
**Claude-driven analysis pipeline**: bash/python CLI tools + markdown ledgers + a scheduled
Claude Code session that runs the routine 3×/day, with a generated static HTML dashboard as the
read-only UI. "Component structure" here means the tool pipeline; "state" means the markdown
ledgers; "routes" mean dashboard sections. The port target should preserve exactly this shape.

---

## 1. Stack, build tooling, deps, conventions, state management

| Aspect | What it actually is |
|---|---|
| Languages | Bash (7 scripts) + Python 3.11 **stdlib-only** (12 scripts). Zero pip deps, no requirements.txt, no package.json. |
| External binaries | `curl`, `jq`, `git`, `python3`. That's the whole toolchain. |
| Build tooling | None. No bundler, no compiler. `tools/generate_dashboard.py` is the only "build" (markdown → `docs/index.html`). |
| CI/CD | One GitHub Actions workflow: `.github/workflows/pages.yml` — regenerates the dashboard and deploys `docs/` to GitHub Pages on every push to `main`. |
| Orchestration | `tools/cron_build.sh` (external cron → `claude -p "<build prompt>"`) + `.claude/hooks/session-start.sh` (UserPromptSubmit hook, fires once per session via a `/tmp` sentinel, runs `tools/session_start.sh` and injects the time-appropriate build directive). `cron_build.sh <hour> --prompt-only` is the single source of truth for build prompts; the hook delegates to it. |
| State management | **Markdown files are the database** (see §6). Tools parse them with regexes; several tools write back cell-surgically (`clv_capture.py --apply` rewrites only the CLV cell of matched rows). All other state edits are made by the Claude session itself, by hand, following doctrine. |
| Config | `CLAUDE.md` is the doctrine/config (636 lines: gates, adjustment registry doctrine, run schedule, git workflow). `.claude/settings.json` wires the hook. Secrets via env var (`ODDS_API_KEY`), never committed. |
| Quality gates | `tools/selftest.sh` — 33 offline fixture checks (parser invariants, verdict math, cross-tool agreement, dashboard↔calib reconciliation). Runs in `session_start.sh` §0 with `--quick`; a red selftest is doctrine-STOP for the whole routine. |
| Conventions | Every tool opens with a `WHY THIS EXISTS` header citing the specific "burn" (loss/bug) that motivated it. Read-only analysis tools (calib, settle, pulse) print proposals; write tools are explicit (`--apply`). Fixes are pinned as selftest regressions. Dates in ledgers are `M/D` with a `<!-- ledger-epoch: YYYY -->` season anchor. |

Folder layout:

```
mlb_parlay_claude/
├── CLAUDE.md                 # doctrine (the routine's "program")
├── fades.md                  # active fades registry + W/L validation logs
├── results_log.md            # calibration & CLV ledger (the measurement core)
├── bankroll.md               # $10 rollover-ladder ledger
├── nrfi_tracker.md           # standalone 1st-inning O/U tracker
├── parlays/YYYY-MM-DD.md     # one append-only build file per day
├── parlays/.probables/*.json # committed probables snapshots (recheck.py audit trail)
├── docs/index.html           # generated dashboard (committed; Pages deploys it)
├── tools/                    # the entire application (19 scripts + README)
├── .claude/{settings.json, hooks/session-start.sh}
└── .github/workflows/pages.yml
```

## 2. Data layer

### 2a. `tools/odds_api.sh` — The Odds API wrapper (**the main thing being reused**)

- **Base**: `https://api.the-odds-api.com/v4`, `SPORT="baseball_mlb"` hardcoded at line 43,
  `REGIONS="us"`. Auth = `apiKey` query param from env `ODDS_API_KEY` (checked, never logged).
- **Commands**: `check` (reachability + key + quota), `quota` (free — `/sports` returns quota
  headers at 0 cost), `slate [date]` (bulk `/odds`, `h2h,totals,spreads`, **cached**),
  `best <market> [date]` (best price per side per game across books, from cache),
  `game "<team>"` (full book-by-book board), `events [date]` (free), `props <eventId>
  <markets|all|core>` (per-event `/events/{id}/odds` — quota-spending, warns first),
  `clv <betPrice> <team>` (closing no-vig vs bet), `raw` (passthrough).
- **Cost model** (encoded in comments + guards): credits = markets × regions per call. `slate`
  = 3 credits for the whole board; props = 1 credit/market/event. Curated market lists:
  `PROPS_ALL` (14 MLB markets) / `PROPS_CORE` (7). Tier detection: `session_start.sh` derives
  `ODDS_MODE=low_quota|standard|rich` from remaining credits (rich ≥ 5000 unlocks props tooling).
- **Caching**: `$TMPDIR/odds_cache/slate_<date>.json` per run; `session_start.sh` re-warms only
  if the cache is >90 min old or empty. Every downstream read (best/game/clv_capture/kprice
  event-id resolution) hits the cache, not the API. Quota headers (`x-requests-remaining/used`)
  parsed from response headers into a per-process header file.
- **Response shape** (normalized nowhere — consumed as-is via jq/json): array of events
  `{id, commence_time, home_team, away_team, bookmakers[{title, markets[{key,
  outcomes[{name, point?, price, description?}]}]}]}`. Team identity = **full team name
  strings** matched by substring against nickname maps.
- **Correctness guards** (port these ideas, they were all bought with losses): started games
  excluded from `best`/`clv` (an in-game price is neither shoppable nor a close); slate-date
  bucketing in ET with a post-midnight-ET rule for late west-coast games; empty cache never
  "fresh"; stale-cache gate in CLV (cache warmed after kickoff → MANUAL, never a fake close);
  `DEACTIVATED_KEY` handled with a user-action message; egress-proxy denials (`x-deny-reason:
  host_not_allowed`) produce actionable "allowlist this host" guidance.
- **Historical endpoint** (`clv_backfill.py`): `/historical` board snapshots at 5-min grain,
  10 credits × markets × regions per snapshot timestamp (30cr for the 3-market board); used to
  retro-fill missed CLV closes; plan-mode default, paid-tier gated, `--max-credits` ceiling.

### 2b. `tools/mlb_api.sh` — MLB StatsAPI wrapper (**the layer with no NFL equivalent**)

- Free, no auth, no documented rate limit. 15 subcommands over `statsapi.mlb.com/api/v1`:
  `check` preflight; `slate/status/finals <date>` (schedule + `abstractGameState` — the
  authoritative game-status gate and the settle source); `findpitcher/pitcher/gamelog`
  (SP-freshness gate + K-prop settle source); `lineups` (CONFIRMED/PENDING hitter-leg gate);
  `ump`; `weather` (with a hardcoded dome list); `splits` (team K% vs LHP/RHP); `standings`;
  `teamform` (last-N W-L + run diff — fade transitions); `findteam`; `raw`.
- Consumed by: `settle.py` (finals + boxscores + gamelogs), `recheck.py` (probables snapshots
  + diffs), `nrfi_settle.py` (1st-inning linescores), `session_start.sh` (digest),
  and the Claude routine directly.
- **Everything here is on-demand fetch** — viable because StatsAPI is free/unlimited and the
  slate is daily. This is the architectural assumption the NFL context layer must replace with
  a pre-computed store (nflverse assets are release files, not a query API).

### 2c. Other externals

- **Chart.js 4.4.0 from jsdelivr CDN** — the dashboard's only external asset.
- **Gmail MCP + PushNotification** — build notifications (email draft to the user + push),
  driven by the cron prompts, not by repo code.
- Weather comes from StatsAPI game hydration (near first pitch only) — no forecast source.
  (NFL plan upgrades this to Open-Meteo forecasts; verified reachable from this environment.)

## 3. Domain models (implicit — encoded in regexes, maps, and column layouts)

There are no typed model classes. The de-facto model, reverse-engineered from the parsers:

| Entity | Where it lives | Shape |
|---|---|---|
| Game | StatsAPI schedule JSON + odds-cache event | `gamePk` / odds `event id`; status (`Preview/Live/Final`); teams as names; probables. Never joined across sources by ID — team-name/nickname matching bridges them. |
| Team | `NICK` + `ABBREV` dicts duplicated in `settle.py` + `clv_capture.py` (~30 nicknames, ~30 abbrs + StatsAPI alias map in `nrfi_settle.py`) | abbreviation is the canonical ledger form; nickname is the odds-feed match key. |
| Player (pitcher/hitter) | StatsAPI `personId` resolved by accent-stripped surname search; odds outcomes matched by `description` substring | surname is the ledger key — every tool re-resolves it. |
| Leg | **A free-text markdown cell** parsed by `parse_kprop` / `parse_hprop` / `find_team` / spread & total regexes | e.g. `Gilbert O6.5K`, `BAL -1.5 RL (@ DET)`, `NYY team total Over 4.5`, with optional `[adj: …]` tag, `G1/G2` doubleheader hint, `**bold**` noise. Leg text IS the schema. |
| Leg identity | `calib.leg_key()` | `(date, market-kind, side, line)` — dedups reprice/supersede copies of the same physical bet; shared by calib/pulse/dashboard. |
| Ticket/parlay | `ticket.py` construction dicts + a `×`-joined ledger row | legs, true combined prob, decimal payout, EV, corr-pair note. |
| Odds/price | American int strings everywhere; devig helpers in 4 tools | no-vig prob = raw implied / overround. |
| Bet types (`Type` col) | free text normalized by `pulse.norm_type` | ML-fav/ML-dog, run line, total, K-Over ≥7.5 / ≤6.5, K-Under, hitter/pitcher prop, parlay. |

**Audit finding:** leg-as-free-text is the single biggest source of historical bugs (the selftest
is substantially a museum of leg-parsing regressions). The port should make the leg a structured
record from day one and *render* text, not parse it.

## 4. Business logic

The pipeline, in dependency order:

1. **Price** — `odds_api.sh best/props`, `kprice.py` (per-pitcher K-line table: every posted
   line, best price per side, no-vig per line, standard-line heuristic = most balanced juice).
   Line-shopping across books is doctrine ("free EV larger than most analytical edges").
2. **Devig** — `devig.sh`: two-sided proportional devig (raw implied / overround); one-sided
   props estimated at raw − 2.5pp and flagged. Prints edge + gate verdict + ¼-Kelly stake.
3. **TrueP derivation** — `truep.py`: TrueP = market no-vig baseline + **fixed, named
   adjustments** from a registry (~20 entries, e.g. `ace_edge +3`, `own_sp_hi −5`,
   `wind_out_over +4`), `--custom` hard-capped ±3, `~name` sign-mirror. Emits a
   machine-readable `[adj: …]` tag pasted into the ledger so calibration scores each
   adjustment (`calib.py` §1c). **This is the "model": market-anchored + audited adjustments,
   not a projection system.**
4. **Gates** (doctrine, enforced by checklist + tools): min-edge gate ≥ +2pp standalone /
   +3-4pp parlay-anchor (vs the best-shopped no-vig price); game-not-started; SP-freshness;
   lineup CONFIRMED; fades consulted; calibration + pulse applied; "NO BET" is a valid output.
5. **Correlation** — `parlay.py`: 2-leg joint prob via Gaussian-like covariance
   `p1p2 + ρ√(p1q1p2q2)` clamped to Fréchet bounds; ρ from a 7-tier qualitative ladder
   (±0.15/0.30/0.45). Compares independent-product EV vs an offered SGP quote. **3+ legs are
   treated independent; only one correlated pair per ticket is modeled.**
6. **Construction search** — `ticket.py` (the **target-odds search**): enumerates every legal
   1-3-leg combination from gate-cleared legs (one leg per game unless both declare the same
   corr tier; ≤1 pair; negative pairs auto-rejected), prices pairs via `joint2`, prints the
   payout/floor **Pareto frontier**, the **+180..+260 target band ranked by true combined
   prob** (the ~+200 ask, answered as max-floor-at-the-payout), ¼-Kelly, and the minimum
   acceptable SGP quote for corr pairs. Tier 2 = best-floor pick; Tier 3 = band pick.
7. **Staking** — ¼-Kelly off devigged edge, cap 2u/leg; parlays staked on the ticket's own
   edge; plus the separate $10 full-rollover ladder (`bankroll.md`) picking the single
   safest qualifying favorite per day.
8. **Output contract** — three tiers every build: (1) best standalone (+ non-ML bias +
   variance-diversify rules), (2) highest-floor 2-leg, (3) the +200 build with its floor cost
   made explicit.
9. **Measurement loop** — `settle.py` (proposes W/L for the full leg universe off finals /
   gamelogs / boxscores; margin-settled spreads; pushes; doubleheader G-hints; READ-ONLY),
   `clv_capture.py --apply` (auto-writes closing-line verdicts, ±0.5pp dead-band, ⚠ EDGE-GONE
   warnings; `clv_backfill.py` for missed closes), `calib.py` (calibration bands, **Brier
   skill vs market** — the headline scoreboard, per-adjustment attribution, standalone-vs-
   parlay split, ROI), `pulse.py` (**exposure governor**: recent-window COOL / SUSPEND /
   MARKET-SHADE / GLOBAL-SHRINK actions per dimension; recency governs exposure, the n≥20-30
   bar governs belief), `recheck.py` (probables snapshot + pre-lock scratch diff).
10. **Confidence/EV model** — there is no ML model anywhere. EV = TrueP − no-vig price;
    confidence = calibration + Brier-vs-market + CLV, all vs the market baseline.

## 5. UI — `tools/generate_dashboard.py` → `docs/index.html` (GitHub Pages)

- **"Route map"**: single page, anchor-nav sections — Overview (stat tiles + today's board +
  parlay-tax split) → Bankroll & calibration (bankroll curve; calibration bars vs perfect-cal
  line) → Trends (cumulative win rate; hit-rate by edge bucket) → P&L (cumulative units;
  CLV-vs-results; CLV per leg) → Leg-type table → Fade registry → NRFI tracker → Recent legs →
  Ticket rollup → Parlay history. A scroll-spy highlights the active section.
- **Components**: Chart.js canvases (7 charts) + static HTML tables. **Interactions: click-to-
  sort table headers, chart tooltips, scroll-spy nav — that's all.** No inputs, no filters, no
  client-side data fetching; the page is fully regenerated by the pipeline each run.
- **States**: per-panel empty states (`<p class="no-data">…` fallbacks); a freshness badge
  (`● live` vs `⚠ data may be stale` when the newest parlay file is >1 day old); no loading or
  error states (static site). Dark-theme-only design (GitHub-dark palette).
- **Mobile**: 2 `@media` breakpoints; responsive charts (`maintainAspectRatio:false`), grid
  collapses to one column. Adequate, not elaborate.
- **Parser guard**: `generate_dashboard.py --selftest` asserts each source parses ≥N rows and
  reconciles units-P/L + calibration n against `calib.py` (the source of truth); wired into
  `selftest.sh` §13d.

## 6. Persistence

| Store | Written by | Schema |
|---|---|---|
| `results_log.md` | Claude (rows) + `clv_capture.py`/`clv_backfill.py` (CLV cells, surgical) | Two leg tables — `## Played legs`, `## Recommended but NOT played`: `Date \| Leg \| Type \| Price \| TrueP \| ImplP \| Edge \| Result \| Played \| CLV \| Bucket` (fixed pipe indexes — apply-mode depends on them); `### Played-ticket record` (stake/return/P-L); rollup prose reconciled to `calib.py`; user-angle tables; `<!-- ledger-epoch -->` anchor. Conventions: pre-registered TrueP (legacy `*` rows excluded), no-vig ImplP, supersede-never-edit, S/P bucket tags, `[adj:]` tags. |
| `fades.md` | Claude | Sections A (fade-as-fav) / B (hot dog) / C (K-Over fades) / D (construction fades) / E (data traps); per-entry `ID \| name \| reason \| added \| last-validated \| W/L log \| status` with ACTIVE→NEUTRAL→RETIRED transitions gated on run-diff windows. |
| `bankroll.md` | Claude | Ladder rules + attempts table (`Attempt \| Date \| Roll \| Balance before \| Bet \| True% \| Result \| Balance after \| Note`). |
| `nrfi_tracker.md` | Claude + `nrfi_settle.py --apply` | Doctrine + per-day read rows (`Date \| Matchup \| Pick \| TrueP \| … \| Result`) + running record. |
| `parlays/YYYY-MM-DD.md` | Claude | Append-only per day: `## Daily slate context`, then `## Run HH:MM ET — Build A/B/C` (gate table, PULSE block, slate scan, 3 tiers, per-leg reasoning, rejected legs, run notes, credits-remaining line), then `## Played build` / `## Result`. |
| `parlays/.probables/<date>.json` | `recheck.py snap` | Committed audit snapshots: `[{pk, state, detail, away, away_sp_id, away_sp, home, …}]`. |
| `/tmp/odds_cache/slate_<date>.json` | `odds_api.sh` | Ephemeral per-run odds cache (also carries event ids + commence times for kprice/CLV). |
| `docs/index.html` | `generate_dashboard.py` | Committed build artifact. |

No SQL anywhere. Viable at MLB scale because every fact is re-fetchable on demand from
StatsAPI; the ledgers only persist *decisions and outcomes*.

## 7. MLB-specific assumptions hardcoded or leaking into shared layers

Enumerated so the port map (PORT_PLAN.md §3) can address each:

1. **`SPORT="baseball_mlb"`** in `odds_api.sh` (line 43) — plus MLB-curated `PROPS_ALL/CORE`
   market lists, and MLB dome list inside `mlb_api.sh weather`.
2. **Daily-slate world-model everywhere**: cache keys, ledger `Date` columns, `parlays/` one-
   file-per-day, "yesterday" settles, 3-runs-per-day cadence, 90-min cache freshness, "slate
   date" = ET calendar day (with the post-midnight rule). NFL's unit is the *week* with
   per-game locks spread over 5+ days.
3. **Team dictionaries duplicated in three tools** (`settle.py`, `clv_capture.py`,
   `nrfi_settle.py` alias map, `session_start.sh` TF_MAP) — all MLB names; a port must
   centralize one NFL team table instead of re-duplicating.
4. **Pitcher-centric domain**: SP-freshness gate, K-prop parsing/settling via *gamelog*,
   probables snapshot/recheck (SP scratch), opposing-lineup K% splits, ump zones, NICK-based
   `findpitcher` flows. NFL's analogs (QB status, practice designations, inactives) are
   structurally different mechanics, not renames.
5. **Lineup-posting gate (~2-3h pre-game, binary CONFIRMED/PENDING)** — NFL has a week-long
   injury ladder (Wed/Thu/Fri practice → Fri designation → T-90min inactives).
6. **Doubleheader disambiguation (G1/G2 hints)** throughout settle/CLV/kprice — no NFL analog
   (drop), but replaced by a different identity problem (same-week vs next-week same-matchup
   is impossible in NFL; cross-source game-ID joins are the new need).
7. **Correlation model tuned for MLB's mostly-independent legs**: one modeled pair per ticket,
   3+ legs independent, hand-assigned tiers. NFL same-game legs are pervasively correlated —
   this is flagged in Phase 2/3 as the biggest piece of business logic that must be *rebuilt,
   not ported* (NFL_REQUIREMENTS.md §5).
8. **On-demand fetch against a free stats API** as the context layer's architecture — no NFL
   equivalent exists; nflverse is release-file ingest (pre-computed store required).
9. **Leg text as schema** (§3 finding) — sport-specific regexes (`O6.5K`, `TB` colliding with
   Tampa Bay, accent handling) would all need NFL re-derivation; better to fix structurally.
10. **MLB market micro-doctrine embedded in CLAUDE.md** (K-alt ladders, RL-by-margin, NRFI,
    contact-lineup fades, +200-chase fade, heavy-fav recipes) — the *shape* (registry + fades
    + burns + gates) ports; the *content* is MLB and must be re-earned in NFL terms.
11. **`ledger-epoch` / M-D date ambiguity logic** in pulse assumes a season contained within a
    calendar year; NFL seasons span the new year (Jan playoffs) — week-indexed keys avoid it.
12. **Timezone**: everything is `America/New_York`; NFL adds international 9:30 ET kickoffs
    and a Sunday multi-window day — fine, but window logic must be data-driven (the verified
    2026 schedule opens on a *Wednesday*, and includes neutral-site games).
