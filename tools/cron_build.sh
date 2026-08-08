#!/usr/bin/env bash
#
# cron_build.sh — the weekly run skeleton (the MLB 11/16/18 pattern, re-shaped to NFL).
#
# RUN TYPES (PORT_PLAN §2 — labels cosmetic, detection data-driven):
#   wrap         Tue: settle the week, full-week review, calib+pulse, fades update, dashboard
#   build        Wed/Thu: sync, slate-wide scan (ALL games, every window), initial 3 tiers
#   designation  Fri: injury designations land → availability haircuts → revise the build
#   lock         any day, when games kick within T-3h: weekcheck diff, final prices,
#                lock THAT window's legs only, T-5m close is the CLV snapshot
# Detection: imminent games (store kickoffs within 3h) → lock; else Tue→wrap, Fri→
# designation, else build. Notifications: the consolidated four touchpoints (resolved Q3).
#
# USAGE
#   tools/cron_build.sh                    # auto-detect run type
#   tools/cron_build.sh wrap|build|designation|lock [--prompt-only]
#   tools/cron_build.sh --detect-only [--now ISO]   # print the detected type (selftest)
#
# CRONTAB SKETCH (ET; the lock entries fire hourly on game days — the detector no-ops
# when nothing is imminent, so extra firings cost nothing):
#   0 10 * * 2  bash tools/cron_build.sh wrap
#   0 10 * * 4  bash tools/cron_build.sh build
#   0 17 * * 5  bash tools/cron_build.sh designation
#   0 9-21 * * 0,1,4,6  bash tools/cron_build.sh   # auto: lock when windows approach
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

detect() {
  local now="${1:-}"
  python3 - "$now" <<'EOF'
import os, sqlite3, sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
now_s = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else None
now = (datetime.strptime(now_s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
       if now_s else datetime.now(timezone.utc))
db = os.environ.get("NFL_DB", "data/context.db")
imminent = False
try:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    for (k,) in con.execute("SELECT kickoff_utc FROM games WHERE kickoff_utc IS NOT NULL "
                            "AND game_type != 'PRE'"):
        ko = datetime.strptime(k, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if timedelta(0) < ko - now <= timedelta(hours=3):
            imminent = True
            break
except Exception:
    pass
wd = now.astimezone(ZoneInfo("America/New_York")).strftime("%A")
print("lock" if imminent else
      {"Tuesday": "wrap", "Friday": "designation"}.get(wd, "build"))
EOF
}

PROMPT_ONLY=0
BUILD=""
NOW=""
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
  case "${args[$i]}" in
    --prompt-only) PROMPT_ONLY=1 ;;
    --detect-only) BUILD="__detect__" ;;
    --now) NOW="${args[$((i+1))]}" ;;
    wrap|build|designation|lock) [[ -z "$BUILD" ]] && BUILD="${args[$i]}" ;;
  esac
done
if [[ "$BUILD" == "__detect__" ]]; then
  detect "$NOW"
  exit 0
fi
[[ -z "$BUILD" ]] && BUILD="$(detect "$NOW")"

COMMON="The session_start.sh digest is already in your context (injected by hook) — selftest, store sync, quota/ODDS_MODE, unsettled proposals, weekcheck, availability, pulse. Doctrine: CLAUDE.md. Git: commit + push to the designated feature branch (NO auto-merge — not granted for this repo)."

case "$BUILD" in
wrap)
  LABEL="Tuesday wrap — settle the week + measurement"
  PROMPT="Run the NFL Tuesday WRAP per CLAUDE.md. $COMMON Steps:
1. Settle: python3 tools/settle.py <season> <prior-week> --apply (digest shows proposals). MANUAL rows by hand. Update builds/<week>.md '## Results' and ledgers/bankroll.md.
2. CLV holes: any decided row with blank CLV → python3 tools/clv_backfill.py <season> <week> (PLAN first; --apply only if cost ≤ 120 credits and quota is rich).
3. Full-week review into builds/<week>.md: every game vs active reads; validate/miss each fades.md entry touched (dated W/L + tally); promote lessons per the tiered bar (process 2-3 sightings; hit-rate n≥20-30).
4. Run tools/calib.py + tools/pulse.py; reconcile the ledger prose rollup with calib output.
5. Regenerate the dashboard (python3 tools/generate_dashboard.py) and commit it.
6. NOTIFY (touchpoint 1 of 4): push notification + email draft — week record, CLV tally, calib/pulse highlights, bankroll state, Odds API credits remaining."
  ;;
build)
  LABEL="Wed/Thu build — slate-wide scan + initial three tiers"
  PROMPT="Run the NFL weekly BUILD per CLAUDE.md. $COMMON Steps:
1. tools/nfl_data.sh slate <season> <week> — the full board, every window. python3 tools/implied.py --week <season> <week> for implied team totals.
2. Board: tools/odds_api.sh board reg; poll plan: python3 tools/poll_scheduler.py plan <season> <week> (verify within budget).
3. SLATE-WIDE SCAN — ALL games, ≥1 non-ML read per game (totals/team-totals/props once posted). Volume reads: tools/nfl_data.sh volume; availability gate: python3 tools/availability.py gate; weather: python3 tools/weather.py week (HORIZON rows honest).
4. Per leg: best price → devig.sh → truep.py (paste [adj:] tag) → min-edge gate (+2pp standalone / +3-4pp anchor). NO BET is a valid output.
5. Three tiers via tools/ticket.py with EVERY gate-clearing leg (families+teams declared for same-game stacks; heed min-SGP quotes). Tier 1 = best standalone; Tier 2 = best floor; Tier 3 = the band pick with its floor cost explicit.
6. Log EVERY scan candidate to ledgers/results_log.md (leg_id via tools/legs.py; Grade at bet time; Bucket S/P). Availability-uncertain legs = PENDING.
7. Bankroll pick (single safest qualifying favorite, whole board, independent of the parlay).
8. python3 tools/weekcheck.py snap <season> <week> — commit the premises snapshot.
9. Append the run to builds/<season>-W<week>.md; regenerate the dashboard; commit+push.
10. NOTIFY (touchpoint 2 of 4): push + email — the three tiers, bankroll pick, PENDING flags, credits remaining."
  ;;
designation)
  LABEL="Friday designation update — availability haircuts"
  PROMPT="Run the NFL Friday DESIGNATION update per CLAUDE.md. $COMMON Steps:
1. python3 tools/availability.py sync then gate <season> <week> — Friday designations are in. Any QB listing = the whole game repriced.
2. python3 tools/weekcheck.py diff <season> <week> — every finding invalidates its dependent legs: re-derive TrueP (availability haircut = P(plays) multiplier) or drop; SUPERSEDE rows in the ledger, never edit in place.
3. Weather now inside horizon for Sunday: python3 tools/weather.py week — apply wind/precip registry adjustments where flagged.
4. Re-run tools/ticket.py if the leg pool changed; append the revision to builds/<week>.md.
5. Commit+push. NOTIFY (touchpoint 3 of 4): push + email — designation changes, superseded legs, the current build, credits remaining."
  ;;
lock)
  LABEL="Window lock — T-3h gate for the imminent window"
  PROMPT="Run the NFL WINDOW LOCK per CLAUDE.md — games kick within ~3h. $COMMON Steps:
1. python3 tools/weekcheck.py diff <season> <week> — ⚠/⛔ findings CLOSE the gate for affected legs (QB change, availability drop, line moved past basis, wind crossing, started).
2. Availability final: python3 tools/availability.py gate — inactives land ~T-90m (ESPN best-effort; unresolved Q at lock = PENDING, do not lock).
3. Final prices: tools/odds_api.sh board reg (this near kickoff, the pull doubles as the close snapshot); props via the scheduler's due list (python3 tools/poll_scheduler.py due <season> <week> --mark).
4. Lock ONLY this window's legs in builds/<week>.md ('## Locks by window'); the rest of the week stays open.
5. After the window: python3 tools/clv_capture.py <season> <week> --apply (idempotent; EDGE-GONE warnings mean do NOT re-bet).
6. Commit+push. NOTIFY (touchpoint 4 of 4, first lock of the day only): push + email — locked legs, gate closures, EDGE-GONE flags, credits remaining."
  ;;
*)
  echo "ERROR: unknown run type '$BUILD' (wrap|build|designation|lock)" >&2
  exit 1
  ;;
esac

if [[ "$PROMPT_ONLY" == "1" ]]; then
  echo "$PROMPT"
  exit 0
fi

echo "[cron_build.sh] $(TZ=America/New_York date '+%Y-%m-%d %H:%M %Z') — $LABEL"
if command -v claude >/dev/null 2>&1; then
  exec claude -p "$PROMPT"
else
  echo "('claude' CLI not on PATH — prompt below; use --prompt-only for scripting)"
  echo "═══════════════════════════════════════════════════"
  echo "$PROMPT"
fi
