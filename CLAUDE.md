# NFL Parlay Builder — doctrine v0

Port of the MLB parlay system (`nns50/mlb_parlay_claude`) to NFL. The plan of record lives in
`docs/PORT_PLAN.md` (+ `SOURCE_AUDIT.md`, `DATA_SOURCES.md`, `NFL_REQUIREMENTS.md`) — all
decisions resolved 2026-08-08. **This doctrine starts deliberately thin: rules get added here
only when the NFL ledger earns them (2-3 sightings for process rules; n≥20-30 for hit-rate
claims). MLB burn history does not port.**

## Build status

- ✅ M0 scaffold + M1 context ingest (this file's tooling section)
- ⬜ M2 market layer (odds wrapper + poll scheduler) → M3 gates → M4 pricing/construction
  → M5 ledgers/settle/CLV → M6 measurement → M7 dashboard → M8 ops. See PORT_PLAN §4.

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

## Betting doctrine seed (full framework arrives with M4/M5)

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
