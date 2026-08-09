# NFL Parlay Builder — doctrine v0

Port of the MLB parlay system (`nns50/mlb_parlay_claude`) to NFL. The plan of record lives in
`docs/PORT_PLAN.md` (+ `SOURCE_AUDIT.md`, `DATA_SOURCES.md`, `NFL_REQUIREMENTS.md`) — all
decisions resolved 2026-08-08. **This doctrine starts deliberately thin: rules get added here
only when the NFL ledger earns them (2-3 sightings for process rules; n≥20-30 for hit-rate
claims). MLB burn history does not port.**

## Build status

- ✅ **ALL MILESTONES COMPLETE** (M0–M8, 2026-08-08): scaffold, context ingest, market
  layer, domain gates, pricing/construction, ledger loop, measurement, dashboard, ops.
  The system is ready for the preseason soak (paper mode) → REG Week 1 (kickoff Wed
  2026-09-09). Remaining before live money: wire the external cron (crontab sketch in
  `tools/cron_build.sh`), merge to main to activate Pages, run 1-2 paper weeks.

## Ops — the weekly rhythm (`session_start.sh` + `cron_build.sh` + the hook)

- `.claude/hooks/session-start.sh` (UserPromptSubmit) injects `tools/session_start.sh`
  (selftest → store sync → quota/ODDS_MODE → unsettled proposals → weekcheck →
  availability → window-phase CLV auto-apply → PULSE) and delegates the run directive to
  `tools/cron_build.sh <type> --prompt-only` — the SINGLE prompt source.
- Run types (data-driven detection — imminent kickoffs → lock; else Tue→wrap,
  Fri→designation, else build): **wrap** (settle + review + calib/pulse + dashboard) →
  **build** (scan → gates → tiers → snapshot) → **designation** (Fri availability
  haircuts, supersede protocol) → **lock** (per window: weekcheck diff, inactives, final
  prices, lock that window only, T-5m close). Notifications at the four touchpoints.
- `tools/clv_backfill.py <S> <W> [--apply]` — historical closes for missed windows
  (30 cr/snapshot; windows cluster; plan-mode default; rich-tier + --max-credits gated;
  ' bf' provenance marker; validated live against real 2025 closes).

## Repo map

- `config/` — `markets.conf` (polled market set + cadences), `stadiums.csv` (weather coords,
  roof, tz — **name-keyed**: schedules' `stadium_id` follows the home team even at neutral
  sites, so the stadium *name* is the venue key).
- `data/` — `context.db` (SQLite store, NOT committed; rebuilt from nflverse release assets),
  `ingest_manifest.json` (committed provenance: per-dataset source stamps + row counts +
  missing-column flags).
- `ledgers/`, `builds/` — arrive with M5.
- `tools/` — the application. Zero non-stdlib dependencies (bash + curl + jq + python3).

## Context layer — `tools/nfl_data.sh` (the mlb_api.sh analog; store-backed, not on-demand)

Run `check` first (reachability preflight, actionable BLOCKED guidance). Then:

```
tools/nfl_data.sh sync [dataset] [--force]   # nflverse release assets → data/context.db
tools/nfl_data.sh status                     # per-dataset staleness table (age-stamped)
tools/nfl_data.sh slate  <season> <week>     # week's games grouped by kickoff window
tools/nfl_data.sh finals <season> <week>     # completed games w/ scores (settle input)
tools/nfl_data.sh volume <team> <season> <wk># snap% + target/carry share per player (ID-joined)
tools/nfl_data.sh form   <team> [n]          # last-n results + point differential
tools/nfl_data.sh player "<name>"            # resolve player → gsis/pfr/espn ids, team, pos
tools/nfl_data.sh depth  <team>              # latest depth chart snapshot
tools/nfl_data.sh sql    "<SELECT …>"        # read-only passthrough
```

Rules that already apply (ported doctrine, sport-agnostic):
- **Selftest gates every session**: `tools/selftest.sh` red = STOP, fix before trusting output.
- **Staleness is first-class**: every consumer of store data shows the source stamp; a leg
  premised on stale data is PENDING, not silently priced.
- **Facts come from the store by ID join** (gsis ↔ pfr ↔ espn via `players`), never by
  re-parsing free text. Name-fallback joins are flagged `~` wherever they occur.
- **Known data limits** (verified, see DATA_SOURCES.md): nflverse `injuries` is dead for
  2025+; route participation is postseason-only → in-season volume = snap share × target
  share × depth role. `stats_player`/`snap_counts` for the current season don't exist until
  games are played — `sync` treats that as ABSENT (info), not an error.

## Market layer — `tools/odds_api.sh` + `tools/poll_scheduler.py` + `tools/propquote.py`

Run `odds_api.sh check` first (key + both sport keys + quota; shared key with the MLB
app — report credits after every spending run). Then:

```
tools/odds_api.sh board [reg|pre] [<season> <week>]  # bulk featured pull (3 cr), week-scoped, cached
tools/odds_api.sh best h2h|spreads|totals [scope]    # best price/side/point from cache (0 cr)
tools/odds_api.sh game "<team>" [scope]              # book-by-book board (0 cr, cached)
tools/odds_api.sh events [reg|pre]                   # event ids (FREE)
tools/odds_api.sh props <eid> <core|kicking|defense|longest|keys>  # per-event, SPENDS
tools/poll_scheduler.py plan <season> <week>         # dry-run the week's polls + credit cost
tools/poll_scheduler.py due  <season> <week> --mark  # what to poll NOW (idempotent state)
tools/propquote.py "<player>" <market>               # every line + alternates, devigged (~2 cr)
```

Market-layer rules: poll cadences/market sets live in `config/markets.conf` (core-8 props;
defense/kicking/longest opt-in); started games are never priced (in-game ≠ shoppable/close);
absence of a prop market is a NORMAL pre-posting state (logged to `data/market_log.jsonl` —
the posting-time observation record), never an error; preseason = featured markets only;
props auto-suppress under `CREDIT_FLOOR_PROPS`. Empty-response prop calls bill 0 credits
(verified 2026-08-08), so absence probes are free.

## Domain gates — `tools/availability.py` + `tools/weather.py` + `tools/weekcheck.py`

```
tools/availability.py sync [--no-espn]     # roster floor + ESPN Q/D/O ladder → store
tools/availability.py gate [S W]           # per-game gate table (QB listings loudest)
tools/availability.py team <ABBR>          # team board: designation, P(plays), detail
tools/weather.py week [S W]                # per-game kickoff-window forecast (Open-Meteo)
tools/weather.py probe "<stadium>" <isoZ>  # one venue, one time
tools/weekcheck.py snap [S W]              # commit the week's premises (data/weeks/…)
tools/weekcheck.py diff [S W]              # live vs snapshot; exit 1 on ⚠/⛔
```

Gate rules: **availability is a ladder, not a boolean** — P(plays) seeds O/IR=0,
D=0.25, Q=0.75, DTD=0.85 (directional; calibration will own them). ESPN is best-effort:
absent ⇒ the board says DEGRADED and only roster hard-OUTs are marked — designations are
never invented. Weather: dome short-circuit (static-outdoor VETOES per-game roof values —
neutral-site rows inherit the home team's roof template); beyond the 16-day horizon ⇒
HORIZON, never a fabricated number; fetch failure ⇒ UNVERIFIED, no weather adjustment.
`weekcheck.py diff` is the pre-lock gate: QB change / availability drop / spread ≥1.5 /
total ≥2.0 / wind crossing 15mph / kickoff moved / started — any finding invalidates the
dependent legs until re-verified.

## Pricing + construction — the M4 chain (run it in THIS order per leg/build)

```
tools/odds_api.sh best … / propquote.py       # 1. BEST-shopped real price (never estimate)
tools/devig.sh <A> <B> [TrueP%]               # 2. no-vig baseline + min-edge gate + ¼-Kelly
tools/implied.py --game <id> | --week S W     # 2b. implied team totals (team-level reads)
tools/truep.py --base-prob <novig> --adj …    # 3. TrueP = baseline + NAMED adjustments
                                              #    (NFL registry — ALL directional seeds;
                                              #    paste the [adj:] tag into the ledger)
tools/parlay.py --leg … [--corr tier] [--sgp] # 4a. price ONE ticket (habit tool)
tools/ticket.py --leg TrueP:price:game[:label[:famOrTier[:team]]] …
                                              # 4b. THE SEARCH: frontier + band + stacks
tools/corr_backtest.py                        # matrix sanity vs history (re-seed evidence)
```

Correlation doctrine (v2 — supersedes the MLB one-pair model): ρ lives in
`config/corr_matrix.csv` keyed by leg FAMILY + same-team flag (5 rows already re-seeded
from a 2024-25 backtest, n=388-856/pair, signs all confirmed); same-game groups price
jointly via a Gaussian copula; blocked combos (`config/blocked_combos.csv`) and
negative-ρ pairs are rejected; an UNKNOWN same-game pair is rejected (one leg per game)
— never silently assumed independent. Every band pick containing a stack prints its
MIN ACCEPTABLE SGP QUOTE — below that number, bet the legs separately.

## Ledger loop — `ledgers/` + `tools/legs.py` + `settle.py` + `clv_capture.py`

- **`ledgers/results_log.md`** — every recommended leg gets a row with a structured
  **`leg_id`** (`{season}-W{week}:{game_id}:{market}:{side}:{point}:{gsis}` — codec in
  `tools/legs.py`). Tools JOIN on leg_id, never on label text (the MLB regex bug class is
  designed out). Columns add `Grade` (process grade at bet time) + `Bucket` S/P/BT
  (BT = backtest-validation rows, excluded from live calibration).
- **`tools/settle.py <S> <W> [--apply]`** — settles TBD rows from the store: h2h by score,
  spreads by MARGIN (integer pushes), totals/team totals off finals, props off
  `player_week` (anytime TD = rush+rec TDs; kicking points = 3·FG+PAT; DNP → MANUAL/void;
  defense/longest MANUAL by doctrine). Proposals by default; --apply writes Result cells.
- **`tools/clv_capture.py <S> <W> [--apply]`** — CLV verdicts (`+/−/= N%cl`, ±0.5pp
  dead-band) from the window's cached close board; ⚠ EDGE GONE warnings; stale-cache and
  moved-number guards; idempotent. Props close via the scheduler's T-5m per-event poll.
  (`clv_backfill.py` via the historical endpoint arrives with M8 ops if live capture
  actually drops windows — NFL kickoffs cluster, so one snapshot covers a whole window.)
- **`builds/<season>-W<week>.md`** — append-only per-run build file (gates → scan → tiers →
  locks by window → results). `ledgers/bankroll.md` — the $10 ladder, one roll per week.

## Betting doctrine seed

- Minimum-edge gate on the devigged (no-vig) price: **≥ +2pp standalone / ≥ +3-4pp parlay
  anchor**, always vs the best-shopped line. **NO BET is a valid, correct output.**
- TrueP is **pre-registered and derived** (market no-vig baseline + fixed named adjustments,
  `[adj:]`-tagged) — never reconstructed, never vibed.
- Every build presents **three tiers**: best standalone → highest-floor 2-leg → the ~+200
  build with its floor cost explicit. Same-game combined probs are always
  correlation-adjusted; naive products are never shown unlabeled.
- **Supersede, never edit-in-place** in all ledgers; append-only build files per week.
- Never frame a leg as "safe/lock/free money" — win-prob numbers only.

## Notifications & email

- Consolidated four-touchpoint cadence (resolved decision Q3): wrap → build →
  designation → first lock of each game day. Body: prose under ~250 words + the run's key
  tables; ALWAYS include `Odds API credits remaining: <N>` (shared key — the burn must
  stay visible).
- **Scheduled runs (owner-directed 2026-08-09): NO connector writes.** Every
  `mcp__Gmail__create_draft` call pops a manual 'Allow once' dialog on the owner's phone
  that no settings allowlist suppresses (confirmed runs 1-4). A scheduled run's touchpoint
  = `PushNotification` (core tool, promptless) + **Slack via `tools/notify_slack.sh`**
  (incoming-webhook POST to the owner's NFL-Parlay workspace — plain curl, promptless;
  reads secret `SLACK_WEBHOOK_URL` from the environment like `ODDS_API_KEY`; SKIPs
  gracefully where unset) + the complete report as the run's FINAL session message —
  the routine-level completion email/push/Slack deliver that message.
- **Per-run Gmail drafts to realityremixed125@gmail.com come from the MAILER routines**
  (wired 2026-08-09): five self-bound triggers on the orchestrating interactive session —
  where connector writes are proven dialog-free — fire ~35-40min after each run slot
  (Tue/Thu 14:40Z; Fri 21:40Z; Sun 16:10/20:10Z; Mon 00:10Z; Mon/Thu 23:40Z), read the
  newest `## Run` section from `builds/` on origin/main, and create the Gmail draft.
  They also sweep-fold any outcome branch that failed to reach main. No new run → silent
  no-op. (Their earlier connector-Slack-DM step is retired — the webhook in the runs
  supersedes it.)

## Git workflow (current phase)

Work on the designated feature branch (`claude/nfl-parlay-port-plan-3ijsrm`) in interactive
sessions; commit + push each unit of work and keep `main` in step (`git push origin HEAD:main`).

**STANDING AUTHORIZATION (user-granted 2026-08-09): fold run output into `main` automatically.**
Scheduled (trigger-fired) runs push to per-run outcome branches (`claude/admiring-johnson-*`)
AND can push `main` directly — both proven 2026-08-09 (run 3 folded to main with no extra
grant; the claude-code-remote MCP server, and thus `add_repo`, does not exist in trigger
sessions). Every run therefore ends with the FOLD: (1) commit; (2) `git push` (lands on the
outcome branch); (3) `git push origin HEAD:main` — on a non-fast-forward rejection,
`git fetch origin main`, merge (a `docs/index.html` conflict is generated output — resolve
by re-running `tools/generate_dashboard.py`, never by hand), re-run selftest, push again.
If the fold still fails, say so in the notification with the branch + SHA — an interactive
check-in completes the fold and deletes the leftover outcome branch. At run START, fetch +
merge any `claude/admiring-johnson-*` tip ahead of the clone base (append-only ledgers merge
clean) so no predecessor run is lost. `main` drives the Pages dashboard — an unfolded run is
invisible until folded.
