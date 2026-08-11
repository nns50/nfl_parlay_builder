# NFL Parlay Builder — doctrine v0

Port of the MLB parlay system (`nns50/mlb_parlay_claude`) to NFL. The plan of record lives in
`docs/PORT_PLAN.md` (+ `SOURCE_AUDIT.md`, `DATA_SOURCES.md`, `NFL_REQUIREMENTS.md`) — all
decisions resolved 2026-08-08. **This doctrine starts deliberately thin: rules get added here
only when the NFL ledger earns them (2-3 sightings for process rules; n≥20-30 for hit-rate
claims). MLB burn history does not port.**

## Build status

- ✅ **ALL MILESTONES COMPLETE** (M0–M8, 2026-08-08): scaffold, context ingest, market
  layer, domain gates, pricing/construction, ledger loop, measurement, dashboard, ops.
- ✅ **Scheduling wired + verified (2026-08-09).** The external cron is the four CCR run
  Routines (Tue/Thu 14:00Z wrap+build · Fri 21:00Z designation · Sun 15:30/19:30/23:30Z
  locks · Mon/Thu 23:00Z TNF+MNF locks) = 8 firings/week. **All four are OWNER-CREATED in
  the web UI (`created_via: http_api`) — that is load-bearing, not cosmetic: it is what lets
  a run draft the Gmail email without a permission dialog. Never replace one with an
  agent-minted Routine.** Each run delivers its own email + push + Slack; there are no mailer
  Routines. Pages is live at https://nns50.github.io/nfl_parlay_builder/ (deploys from `main`).
- ✅ **Ledger loop VALIDATED against real completed games (2026-08-09).** Settlement and
  CLV had never run on finished games — all 83 live rows are future REG W1 — so both were
  proven against real 2025 W18 results, with expected values HAND-COMPUTED from published
  box scores / closing prices rather than derived from the tools themselves:
  - `tools/validate_settle.py` — **29/29 correct**: spreads by MARGIN (a −2.5 favourite
    winning by 2 LOSES), integer pushes on spreads/totals/team-totals/props, AWAY-team
    margins, kicking points (3·FG+PAT), anytime-TD, and the MANUAL classes (defensive,
    longest-play, DNP). Store-gated (SKIPs pre-sync), runs on a temp `NFL_LEDGER`.
  - **CLV closed out** with one 30-credit historical snapshot (2026-01-04T17:58Z, one
    window = 6 games). Six verdicts written and independently re-devigged by hand (ATL
    −198/NO +189 → no-vig 65.76/34.24 → `+`/`−`, matching exactly). The two refusals were
    CORRECT: the closing board no longer quoted the logged total (36.5 vs 43.0) or spread
    rung, and fabricating a comparison there would invent CLV. **`clv_backfill.py` imports
    `verdict_from_close`/`close_novig` FROM `clv_capture.py`, so the LIVE path's verdict
    engine is what got proven** — now pinned offline in selftest at 0 credits.
- ⏳ **Remaining before live money: the numbers themselves.** The plumbing and the ledger
  loop are done and guarded; what is still unearned is calibration — 0 decided legs, pulse
  idle. **nflverse carries NO preseason games in any season**, so nothing can settle before
  REG Week 1 (kickoff Wed 2026-09-09); a "paper week" before then would add runs but zero
  measurement. Calibration genuinely begins at Week 1.

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
- **Dashboard (`tools/generate_dashboard.py` → `docs/index.html`, Pages from `main`).**
  Panels, in page order: **Run health** (last run's selftest / fold / email / Slack / push /
  credits — the alarm, so it sits first), **Pipeline** (legs logged · decided · played ·
  staked · BT, plus the first date anything *can* settle — an empty ledger must read as
  EARLY, not BROKEN), **This week's board** (the newest `## Run` section rendered
  mobile-readable), **Streaks & the $10 ladder**, **Cumulative P/L** (real stakes only),
  **Bankroll ladder**, **Hit rate by edge bucket**, **Bet-type breakdown**, **CLV vs results**, calibration + CLV-per-leg
  charts, recent legs, BT rows, **Parlay tickets**, **Active fades**, **Run timeline**, and
  Builds · Fades · Bankroll. Regenerate it in every run and stage `docs/index.html` in the
  build commit; it only READS the ledgers.
- **Ported from the MLB dashboard (2026-08-09), adapted not copied.** The measurement
  panels came across because they test *this* system's thesis: **hit-rate-by-edge-bucket is
  the +2pp gate's own scoreboard** (the ≥2pp buckets must out-hit the <2pp ones or the gate
  is not earning its keep) and **CLV-vs-results** tests whether beating the close predicts
  winning. **`--selftest` now reconciles the page against `calib.py`** — live/BT row counts,
  the orphan guard, and cumulative P/L — because a dashboard that merely agrees with
  ITSELF can still disagree with the source of truth, and the page is what the owner
  actually reads. Verified to FAIL on injected drift, not just to pass when healthy.
  **Deliberately NOT ported: NRFI/YRFI** (`nrfi_tracker.md`, `nrfi_digest.py`,
  `nrfi_settle.py`) — it is a first-inning baseball market with no NFL equivalent, and
  inventing a "first drive" analog would manufacture doctrine this ledger has not earned.
  `kprice.py` is already covered by `propquote.py`, and `recheck.py` (SP-scratch snapshot →
  diff) by `weekcheck.py snap/diff`.
- **The exposure governor is LIVE FROM WEEK 1 (2026-08-09).** `pulse.py` previously
  required 15 *decided* legs before any rule could fire, so it idled through roughly the
  first three weeks of a season — exactly when the adjustments are least proven. But
  **MARKET-SHADE is a pure CLV rule**, and CLV is known at the CLOSE, weeks before any
  W/L. `clv_window_rows()` now feeds it CLV-bearing legs **decided or not**, so the
  governor can shade a dimension to market no-vig from the very first week. Hit-rate rules
  (COOL / SUSPEND / GLOBAL SHRINK) still require decisions, because those genuinely need
  results.
- **Streaks are a RULE TRIGGER, not decoration.** `streaks()` reports the current run
  (signed), longest win run and longest losing run over decided legs — a Push breaks
  nothing, since it is not a loss. `ladder_state()` computes the $10 ladder's live state
  and raises **STOP** at **4 consecutive wins within the current attempt**, which is the
  ledger's own withdraw rule; a loss resets the count and a finished attempt never carries
  over. It prints in `session_start.sh §6b` so a run sees it BEFORE picking the week's roll,
  and shouts on the dashboard.
- **Notifications are DIFF-FIRST**: open with what changed since the prior run section and
  say "no material change vs <run>" outright when nothing moved — runs 6-8 matched to the
  hundredth of a point, and an unscannable wall of repeated tables is how a real change
  gets missed.

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
- **EARNED RULE (4 sightings, runs 9-12; promoted at the run-13 wrap 2026-08-11) — the
  VENUE-TYPE AUTHORITY IS `weather.py`, NOT the schedules row, and not the run's own prose.**
  A neutral-site game inherits the *home team's* roof template, so `schedules` says
  `roof='dome'` for **SF@LA at the Melbourne Cricket Ground — which is open-air**. The code
  has always been right (`stadiums.csv` marks it `outdoor`, `is_dome()` vetoes on
  static-outdoor, `weather.py week` prints it HORIZON, `selftest.sh:330` asserts the veto).
  The *prose* regressed: run 4 wrote "4 domes + the MCG", **run 5 caught and corrected it**,
  and runs 9-12 each re-added it and listed `SF@LA Over` as a `dome_pass_over` candidate —
  an unearned **+2pp** on an outdoor game. It never reached a leg (all 92 rows are
  `[adj: none]`, `grep -c dome_pass_over ledgers/results_log.md` = 0) only because nothing
  was near the gate. **Before writing ANY weather-family adjustment, read the venue off
  `weather.py week` — a DOME row is the only licence for `dome_pass_over`.** The general
  lesson, which is why this is in doctrine and not just a build file: **a correction written
  only into `builds/` does not survive — it has to reach CLAUDE.md or it will regress.**

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
`config/corr_matrix.csv` keyed by leg FAMILY + same-team flag. **19 of 21 rows are now
MEASURED over 2015-2025 (n=736-2869/pair) via `corr_backtest.py --reseed`**, which writes
ρ = sin(π·φ/2) back into the CSV; the only 2 left structural are the opposite-side pairs
that are blocked anyway. **This mattered more than expected: structural guesses ran up to
2× off IN BOTH DIRECTIONS and got two SIGNS wrong** — same-team WR1×WR2 was seeded −0.15
("they compete for one target pool") but measures **+0.02, i.e. ~independent**, and that
wrong sign had been silently REJECTING legal WR1+WR2 stacks as negatively correlated;
`rb_rush_yds_o × game_total_u` was seeded +0.15 and measures ~0. Biggest magnitude moves:
`team_ml × OPPOSING team_total_o` −0.20 → **−0.58**, `team_spread × team_ml` (same team)
0.75 → **0.93** (a spread+ML stack is nearly ONE leg, not two), `kicker_pts × team_total_o`
0.30 → 0.49. For a single leg a bad ρ is invisible; in a parlay it compounds straight into
the floor, which is the number the whole ticket rests on. Re-run `--reseed` as seasons
accrue, and update selftest WITH the new measurement rather than loosening the assertion; same-game groups price
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

### Real stakes — `ledgers/played.md` → `tools/reconcile_played.py` (M9, 2026-08-09)

Every logged row is a leg the system **recommended**; nothing recorded which ones were
actually taken. The schema now carries a **`Stake` column** (appended at index 15 so no
earlier index shifted; `legs.cell()`/`parse_stake()` read it, and a row WITHOUT the cell
still parses — requiring it would silently drop legacy rows, the exact failure the parser
guard exists to catch).

**The loop:** the owner appends `<leg_id> | <stake>` lines to `ledgers/played.md` from a
phone via GitHub's web UI between runs; **every run starts by running
`reconcile_played.py --apply`**, which sets `Played=Y` + `Stake` on the matching rows.
Idempotent, so re-running never double-counts. A leg_id that matches nothing, a duplicate,
or a non-numeric stake is a **hard error that refuses to write** — a typo'd bet that
silently vanishes is worse than a stop. `calib.py §3b` then reports **real-stake single-leg
ROI**; legs without a stake are excluded and counted, never imputed at a flat 1u (assumed
ROI is precisely the fake number this replaces).

### Run health — `ledgers/run_health.jsonl` → `tools/run_health.py`

Run 6 delivered no Slack message and reported success: `notify_slack.sh` hit its
"secret unset → SKIP, exit 0" branch and nothing recorded it, so the failure stayed
invisible for a day. Every run now ends with `run_health.py record` — selftest N/N, fold
SHA, per-channel `ok|SKIP|FAILED|n/a`, credits, verdict — appended as one JSON line and
rendered as the dashboard's health strip. **`SKIP` (never wired) and `FAILED` (wired,
errored) are different problems; keep them apart.**

`session_start.sh` §2 also projects **credit runway** (burn/run measured from
`run_health.jsonl` once it has ≥3 runs, else the 3-6 cr featured baseline × 8 runs/week),
and warns when the headroom is under ~22 weeks — the key is shared with the MLB app and
props raise burn sharply once markets post.

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
- **EVERY RUN OWNS ITS WHOLE TOUCHPOINT — the Gmail draft included** (owner-directed
  2026-08-09). There are NO separate mailer routines; the run that produces the report is
  the run that mails it. Four parts, in this order, after the fold (so the draft carries the
  real SHA): **(a)** `mcp__Gmail__create_draft` (ToolSearch it) → realityremixed125@gmail.com,
  subject `NFL Parlay — <season> W<week> <run type>`, body = the full report; **(b)**
  `PushNotification`; **(c)** `bash tools/notify_slack.sh` with the condensed report
  (incoming-webhook curl, promptless; reads `SLACK_WEBHOOK_URL` like `ODDS_API_KEY`; SKIPs
  gracefully where unset); **(d)** the complete report as the run's FINAL session message.
- **✅ RESOLVED — the Slack env gap is CLOSED (confirmed by the run-13 wrap, 2026-08-11).**
  Historical record, kept because the diagnosis is what made it fixable: the run Routines
  fire in `env_016czcjdFNb2qPStdfxfkxay` (**nfl-parlay-builder**) while the orchestrating
  interactive session and the MLB daily routine live in `env_01BbCZZcyZK6n1zUkrvn5qHY`
  (**parlay-test**). `SLACK_WEBHOOK_URL` was set in parlay-test ONLY, so `notify_slack.sh`
  hit its "secret unset → SKIP, exit 0" branch in every scheduled run — that is why run 6
  (2026-08-09 15:40Z) delivered no Slack message and reported success. It was an env-config
  gap, never a code bug. **The variable is now present in nfl-parlay-builder**: run 13's
  `session_start.sh §2b` printed `✓ SLACK_WEBHOOK_URL present` and its `notify_slack.sh`
  POSTed 2,207 chars from a scheduled session. §2b keeps printing the channel state every
  run, so a regression here can never be silent again.
- **⚠ THE ROOT CAUSE WAS WHO CREATED THE ROUTINE — not NFL, not the environment, not the
  repo settings.** A Routine minted by an agent over MCP (`created_via: meta_mcp`) does NOT
  carry the owner's connector authority: its sessions are tagged `routine:agent-minted`, and
  every `mcp__Gmail__create_draft` call falls back to an "Allow once / Deny" dialog on the
  owner's phone that **STALLS the run** (runs 1-4; re-proven run 7 with a screenshot).
  A Routine the owner creates in the web UI (`created_via: http_api`) carries that authority
  and drafts silently — which is why the MLB daily routine has always worked with one plain
  line and needed no machinery at all.
- **FIX (2026-08-09): the four agent-minted NFL Routines were DELETED and recreated by the
  owner in the web UI.** The runs call `mcp__Gmail__create_draft` directly, exactly like MLB.
  Diagnostics that led here, so they are not re-run: attaching the connector and allowlisting
  the tool in `.claude/settings.json` do NOT suppress the dialog (connector *attachment* is
  not *auto-approval*); `create_trigger`'s `connectors` grant is **disabled for this org**;
  SMTP 587/465 and IMAP 993 are **blocked** from the container.
- **Do not rebuild a webhook/Apps-Script email path.** One was built and then removed the
  same day — it was scaffolding around an agent-minted Routine, not a real limitation. If a
  draft ever prompts again, the Routine is agent-minted: **recreate it in the web UI**, do
  not engineer around it.
- **EVERY NFL Routine carries the touchpoint by construction.** All four run Routines execute
  `cron_build.sh <type> --prompt-only`, so the single COMMON block reaches wrap, build,
  designation and lock alike — selftest asserts all four carry the Gmail draft (addressed to
  realityremixed125@gmail.com) plus Slack, and that `cron_build.sh` still parses (a raw-quote
  injection once broke the whole prompt source; `bash -n` now guards it).
- A run that cannot deliver a channel must SAY SO in its final message — never silently
  skip, never retry in a loop.

## Git workflow (current phase)

Work on the designated feature branch (`claude/nfl-parlay-port-plan-3ijsrm`) in interactive
sessions; commit + push each unit of work and keep `main` in step (`git push origin HEAD:main`).

**STANDING AUTHORIZATION (user-granted 2026-08-09): fold run output into `main` automatically.**
Scheduled (trigger-fired) runs push to per-run outcome branches (each Routine has its OWN
randomly-named `claude/<adjective>-<name>` branch — never hardcode the pattern)
AND can push `main` directly — both proven 2026-08-09 (run 3 folded to main with no extra
grant; the claude-code-remote MCP server, and thus `add_repo`, does not exist in trigger
sessions). Every run therefore ends with the FOLD: (1) commit; (2) `git push` (lands on the
outcome branch); (3) `git push origin HEAD:main` — on a non-fast-forward rejection,
`git fetch origin main`, merge (a `docs/index.html` conflict is generated output — resolve
by re-running `tools/generate_dashboard.py`, never by hand), re-run selftest, push again.
If the fold still fails, say so in the notification with the branch + SHA — an interactive
check-in completes the fold and deletes the leftover outcome branch. At run START, fetch + merge ANY `origin/claude/*` tip not
already contained in `origin/main` (append-only ledgers merge clean) so no predecessor run is
lost — test containment with `git merge-base --is-ancestor`, do not match on branch name. `main` drives the Pages dashboard — an unfolded run is
invisible until folded.
