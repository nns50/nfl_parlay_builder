#!/bin/bash
#
# .claude/hooks/session-start.sh — UserPromptSubmit hook (ported mechanism).
#
# Fires on the FIRST message of each session: injects the session_start.sh digest,
# detects the run type from live data, and delegates the directive to
# `cron_build.sh <type> --prompt-only` — the SINGLE SOURCE of run prompts (the MLB
# hook/cron drift bug class, kept fixed). Sentinel prevents re-running per message.
set -uo pipefail

SESSION_SENTINEL="/tmp/nfl_session_init_${CLAUDE_SESSION_ID:-$$}"
[[ -f "$SESSION_SENTINEL" ]] && exit 0
touch "$SESSION_SENTINEL"

# Resolve the repo root from this script's own location (.claude/hooks/ → two up).
# The 2026-08-08 test firing proved trigger-fired sessions clone to a different path
# with no CLAUDE_PROJECT_DIR — the old hardcoded fallback cd failed and the hook
# exited silently. BASH_SOURCE works from any clone path.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." 2>/dev/null && pwd)"
cd "${REPO_ROOT:-${CLAUDE_PROJECT_DIR:-/home/user/nfl_parlay_builder}}" || exit 0

echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║  AUTO SESSION-START — tools/session_start.sh injected by hook   ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
bash tools/session_start.sh 2>&1 || true
echo ""

RUN_TYPE="$(bash tools/cron_build.sh --detect-only 2>/dev/null || echo build)"
DIRECTIVE="$(bash tools/cron_build.sh "$RUN_TYPE" --prompt-only 2>/dev/null)"

echo "════════════════════════════════════════════════════════"
echo "  RUN DIRECTIVE — $RUN_TYPE  ($(TZ=America/New_York date '+%a %H:%M ET'))"
echo "════════════════════════════════════════════════════════"
echo ""
echo "CLAUDE: execute the following run per CLAUDE.md. The digest above is your"
echo "live context. Begin now:"
echo ""
echo "$DIRECTIVE"
