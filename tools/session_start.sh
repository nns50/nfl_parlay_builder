#!/usr/bin/env bash
#
# session_start.sh — one-shot session-open digest (the ported MLB pattern, NFL rhythm).
#
# Composes the mechanical session open so no step is silently skipped:
#   0. selftest (red = STOP — do not build/settle/trust tool output)
#   1. context store: reachability + sync + staleness table
#   2. odds API: key/quota → ODDS_MODE
#   3. current week + unsettled-legs proposals (read-only counts)
#   4. weekcheck diff vs the committed snapshot (the pre-lock gate)
#   5. availability sync (ESPN best-effort; degraded mode announces itself)
#   6. CLV auto-apply — ONLY inside a window phase (any game kicking within 2h or
#      kicked within the last 6h); idempotent, never spends on the featured close
#   7. PULSE — the exposure governor (any build THIS session must apply its actions)
#
# READ-MOSTLY: writes are the idempotent store/ledger refreshes (sync, availability,
# CLV apply) — judgment steps (settle apply, builds, locks) belong to the run prompts.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

rule() { printf '%s\n' "────────────────────────────────────────────────────────"; }
hdr()  { echo; rule; echo " $*"; rule; }

echo "════════════════════════════════════════════════════════"
echo "  NFL SESSION-START DIGEST   $(TZ=America/New_York date '+%Y-%m-%d %H:%M ET')"
echo "════════════════════════════════════════════════════════"

hdr "0. Tooling selftest"
if ST="$(bash tools/selftest.sh 2>&1)"; then
  echo "  ✓ $(grep -oE 'ALL [0-9]+ CHECKS PASSED' <<<"$ST" || echo 'all checks passed')"
else
  echo "  ⛔ SELFTEST FAILED — a tool is broken; do NOT trust build output until fixed:"
  grep -E '✗|FAILED' <<<"$ST" | head -6 | sed 's/^/     /'
fi

hdr "1. Context store (nflverse)"
if bash tools/nfl_data.sh check >/dev/null 2>&1; then
  bash tools/nfl_data.sh sync 2>&1 | sed 's/^/  /'
else
  echo "  ⚠ BLOCKED — serving last-good tables; consumers must treat stale premises as PENDING."
fi
bash tools/nfl_data.sh status 2>/dev/null | head -8 | sed 's/^/  /'

hdr "2. Odds API (shared key — report credits every run)"
bash tools/odds_api.sh check 2>&1 | sed 's/^/  /'
QUOTA_LINE="$(bash tools/odds_api.sh quota 2>/dev/null)" || true
echo "  $QUOTA_LINE"
REM="$(grep -oE '[0-9]+' <<<"$QUOTA_LINE" | head -1)"; REM="${REM:-0}"
if   (( REM < 20 ));   then echo "  ODDS_MODE=low_quota — no API spends this session."
elif (( REM >= 5000 )); then echo "  ODDS_MODE=rich — props tooling unlocked."
else echo "  ODDS_MODE=standard — featured markets only; hand-price props."
fi

hdr "2b. Notification channels (this session can only deliver what is wired HERE)"
if [[ -n "${SLACK_WEBHOOK_URL:-}" ]]; then
  echo "  ✓ SLACK_WEBHOOK_URL present — tools/notify_slack.sh will POST."
else
  echo "  ⛔ SLACK_WEBHOOK_URL UNSET in THIS environment — notify_slack.sh will SKIP and"
  echo "     NO Slack message will reach the owner. This is an ENVIRONMENT config gap, not"
  echo "     a code bug: add the secret to the environment this session runs in. You MUST"
  echo "     say 'Slack: SKIPPED (webhook unset)' in the run's notification + final message."
fi
if [[ -n "${GMAIL_WEBHOOK_URL:-}" ]]; then
  echo "  ✓ GMAIL_WEBHOOK_URL present — tools/notify_email.sh will POST."
else
  echo "  ⛔ GMAIL_WEBHOOK_URL UNSET in THIS environment — notify_email.sh will SKIP and NO"
  echo "     email will reach realityremixed125@gmail.com. Setup: docs/NOTIFY_EMAIL_SETUP.md."
  echo "     You MUST say 'Email: SKIPPED (webhook unset)' in the run's final message."
fi
echo "  ⛔ NEVER call mcp__Gmail__create_draft from a scheduled run — it prompts and STALLS."

hdr "3. Current week + unsettled legs"
WK="$(bash tools/nfl_data.sh weekof 2>/dev/null)" || WK=""
echo "  weekof: ${WK:-unresolved (sync the store)}"
if [[ -n "$WK" ]]; then
  read -r S W _ <<<"$WK"
  for wk in "$W" "$((W-1))"; do
    (( wk >= 1 )) || continue
    N=$(python3 tools/settle.py "$S" "$wk" 2>/dev/null | grep -cE "✅|❌|➖" || true)
    [[ "$N" -gt 0 ]] && echo "  ⚠ $S W$wk has $N settle proposal(s) → python3 tools/settle.py $S $wk --apply"
  done
fi

hdr "4. Weekcheck (pre-lock premises diff)"
if [[ -n "${WK:-}" ]]; then
  read -r S W _ <<<"$WK"
  python3 tools/weekcheck.py diff "$S" "$W" 2>/dev/null | sed 's/^/  /' \
    || echo "  ⚠ findings above invalidate dependent legs until re-verified"
fi

hdr "5. Availability (ESPN best-effort over the roster floor)"
python3 tools/availability.py sync 2>&1 | sed 's/^/  /'

# 6. CLV auto-apply — window phase only (a pre-game capture hours early is premature;
#    the T-5m scheduler poll is the real close. This catches the batch after each window.)
if [[ -n "${WK:-}" ]]; then
  read -r S W _ <<<"$WK"
  PHASE=$(python3 - "$S" "$W" <<'EOF'
import os, sqlite3, sys
from datetime import datetime, timedelta, timezone
db = os.environ.get("NFL_DB", "data/context.db")
try:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    now = datetime.now(timezone.utc)
    for (k,) in con.execute("SELECT kickoff_utc FROM games WHERE season=? AND week=? "
                            "AND kickoff_utc IS NOT NULL", (int(sys.argv[1]), int(sys.argv[2]))):
        ko = datetime.strptime(k, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if -timedelta(hours=6) <= ko - now <= timedelta(hours=2):
            print("WINDOW"); break
except Exception:
    pass
EOF
)
  if [[ "$PHASE" == "WINDOW" ]]; then
    hdr "6. CLV capture — window phase detected (auto-apply, idempotent)"
    python3 tools/clv_capture.py "$S" "$W" --apply 2>&1 | tail -6 | sed 's/^/  /'
  fi
fi

hdr "7. PULSE — exposure governor (APPLY its actions in any build this session)"
python3 tools/pulse.py 2>/dev/null | sed 's/^/  /' || echo "  (pulse failed — run manually)"

echo
echo "════════════════════════════════════════════════════════"
echo "  NEXT (judgment — not automated): settle --apply any proposals above;"
echo "  read ledgers/fades.md + results_log.md; scan → gate → tiers per CLAUDE.md;"
echo "  weekcheck snap after building; lock only inside each window's T-2h phase."
echo "════════════════════════════════════════════════════════"
