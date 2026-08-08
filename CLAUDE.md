# NFL Parlay Builder — doctrine v0

Port of the MLB parlay system (`nns50/mlb_parlay_claude`) to NFL. The plan of record lives in
`docs/PORT_PLAN.md` (+ `SOURCE_AUDIT.md`, `DATA_SOURCES.md`, `NFL_REQUIREMENTS.md`) — all
decisions resolved 2026-08-08. **This doctrine starts deliberately thin: rules get added here
only when the NFL ledger earns them (2-3 sightings for process rules; n≥20-30 for hit-rate
claims). MLB burn history does not port.**

## Build status

- ✅ M0 scaffold + M1 context ingest + M2 market layer + M3 domain gates
  + M4 pricing/construction
- ⬜ M5 ledgers/settle/CLV → M6 measurement → M7 dashboard → M8 ops. See PORT_PLAN §4.

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

## Betting doctrine seed (full framework arrives with M5)

- Minimum-edge gate on the devigged (no-vig) price: **≥ +2pp standalone / ≥ +3-4pp parlay
  anchor**, always vs the best-shopped line. **NO BET is a valid, correct output.**
- TrueP is **pre-registered and derived** (market no-vig baseline + fixed named adjustments,
  `[adj:]`-tagged) — never reconstructed, never vibed.
- Every build presents **three tiers**: best standalone → highest-floor 2-leg → the ~+200
  build with its floor cost explicit. Same-game combined probs are always
  correlation-adjusted; naive products are never shown unlabeled.
- **Supersede, never edit-in-place** in all ledgers; append-only build files per week.
- Never frame a leg as "safe/lock/free money" — win-prob numbers only.

## Git workflow (current phase)

Work on the designated feature branch (`claude/nfl-parlay-port-plan-3ijsrm` for this effort);
commit + push each milestone. **No auto-merge to main** — that authorization is MLB-repo
doctrine and has not been granted here.
