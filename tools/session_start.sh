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
# RUNWAY (2026-08-09). The key is SHARED with the MLB app and props get expensive once
# markets post, so "credits remaining" alone hides the wall. Project it: burn/run comes
# from run_health.jsonl when it has history, else the observed 3-6 cr featured baseline.
python3 - "$REM" <<'PYRUN' | sed 's/^/  /'
import json, os, sys
rem = int(sys.argv[1] or 0)
hist = os.path.join("ledgers", "run_health.jsonl")
per, src = 5.0, "baseline (featured board ~3-6 cr/run)"
try:
    cr = [json.loads(l)["credits"] for l in open(hist) if l.strip()]
    cr = [c for c in cr if isinstance(c, int)]
    drops = [a - b for a, b in zip(cr, cr[1:]) if 0 < a - b < 2000]
    if len(drops) >= 3:
        per, src = sum(drops) / len(drops), f"measured over {len(drops)} runs"
except Exception:
    pass
RUNS_WK = 8                       # 4 Routines, 8 firings/week
wk = rem / (per * RUNS_WK) if per else 0
print(f"RUNWAY: ~{per:.1f} cr/run ({src}) x {RUNS_WK} runs/wk "
      f"= ~{per*RUNS_WK:.0f} cr/wk -> ~{wk:.0f} weeks of headroom")
if wk < 22:
    print(f"  ! a full REG season is 18 weeks + playoffs; {wk:.0f} weeks is TIGHT — "
          "props will raise burn, so plan the quota before Week 1")
PYRUN

hdr "2b. Notification channels (this session can only deliver what is wired HERE)"
if [[ -n "${SLACK_WEBHOOK_URL:-}" ]]; then
  echo "  ✓ SLACK_WEBHOOK_URL present — tools/notify_slack.sh will POST."
else
  echo "  ⛔ SLACK_WEBHOOK_URL UNSET in THIS environment — notify_slack.sh will SKIP and"
  echo "     NO Slack message will reach the owner. This is an ENVIRONMENT config gap, not"
  echo "     a code bug: add the secret to the environment this session runs in. You MUST"
  echo "     say 'Slack: SKIPPED (webhook unset)' in the run's notification + final message."
fi
echo "  ✓ Email: mcp__Gmail__create_draft → realityremixed125@gmail.com (user-created Routine;"
echo "    promptless). A permission dialog here means the Routine was agent-minted — report it."

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

# ORDER IS LOAD-BEARING: the availability sync MUST run BEFORE the weekcheck diff.
# Runs 24 and 25 both printed "premises stand" here and then, re-running the very same
# command after the sync had written fresh ESPN listings, got exit 1 with 15 and 43
# findings respectively. Neither reading was wrong — they diff against different store
# states — but a PRE-SYNC gate reading is a stale one, and the digest is what a run reads
# first. Diffing against a store the run has not yet refreshed is how a fired gate reads
# clean. Do not reorder these two blocks.
hdr "4. Availability (ESPN best-effort over the roster floor)"
python3 tools/availability.py sync 2>&1 | sed 's/^/  /'

hdr "5. Weekcheck (pre-lock premises diff — POST-sync, so this is the run's real verdict)"
if [[ -n "${WK:-}" ]]; then
  read -r S W _ <<<"$WK"
  python3 tools/weekcheck.py diff "$S" "$W" 2>/dev/null | sed 's/^/  /' \
    || echo "  ⚠ findings above invalidate dependent legs until re-verified"
fi

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

hdr '6b. Streaks + the $10 ladder (the 4-win STOP rule is doctrine, not a suggestion)'
python3 - <<'PYSTREAK' | sed 's/^/  /'
import sys
sys.path.insert(0, "tools")
try:
    import generate_dashboard as gd
    live, bt, tickets, builds, fades, rolls, health = gd.load()
    s, ld = gd.streaks(live), gd.ladder_state(rolls)
    if s["last"] is None:
        print("legs: no decided legs yet — streaks begin at Week 1")
    else:
        c = s["current"]
        print(f"legs: current {'W' if c > 0 else 'L'}{abs(c)} · "
              f"longest win run {s['best_w']} · longest losing run {s['best_l']}")
    print(f"ladder: attempt {ld['attempt'] or '—'} · consecutive wins {ld['wins']}/4 · "
          f"balance ${ld['balance']:.2f}")
    if ld["stop"]:
        print("*** 4 CONSECUTIVE WINS — STOP & WITHDRAW. Do NOT roll again this week; "
              "the next attempt restarts at $10. ***")
except Exception as e:
    print(f"(streaks unavailable: {e})")
PYSTREAK

hdr "7. PULSE — exposure governor (APPLY its actions in any build this session)"
python3 tools/pulse.py 2>/dev/null | sed 's/^/  /' || echo "  (pulse failed — run manually)"

echo
echo "════════════════════════════════════════════════════════"
echo "  NEXT (judgment — not automated): settle --apply any proposals above;"
echo "  read ledgers/fades.md + results_log.md; scan → gate → tiers per CLAUDE.md;"
echo "  weekcheck snap after building; lock only inside each window's T-2h phase."
echo "════════════════════════════════════════════════════════"
