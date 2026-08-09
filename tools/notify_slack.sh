#!/usr/bin/env bash
#
# notify_slack.sh — post a run notification to Slack via an incoming webhook.
#
# The webhook path deliberately AVOIDS the Slack MCP connector: connector writes
# from scheduled sessions pop a manual 'Allow once' dialog on the owner's phone
# (proven runs 1-4, 2026-08-09), while a webhook is a plain HTTPS POST — promptless
# everywhere, and it lands in whatever workspace/channel the webhook was created
# for (owner's NFL-Parlay workspace).
#
# USAGE
#   tools/notify_slack.sh "message text"          # or pipe the message on stdin
#   tools/notify_slack.sh --dry-run "message"     # print the JSON payload, no POST
#
# SLACK_WEBHOOK_URL comes from the environment (nfl-parlay-builder env config —
# same secret-handling pattern as ODDS_API_KEY; never commit it, never echo it).
# Absent → SKIP with exit 0, so sessions without the secret (interactive, mailer)
# degrade gracefully instead of erroring.
set -uo pipefail

DRY=0
if [[ "${1:-}" == "--dry-run" ]]; then DRY=1; shift; fi
MSG="${1:-}"
if [[ -z "$MSG" && ! -t 0 ]]; then MSG="$(cat)"; fi
if [[ -z "$MSG" ]]; then
  echo "notify_slack: no message given (arg or stdin)" >&2
  exit 2
fi

# Slack hard-caps text elements; trim defensively rather than get a 400 back.
if (( ${#MSG} > 4900 )); then MSG="${MSG:0:4900}…(trimmed)"; fi

PAYLOAD="$(jq -Rn --arg t "$MSG" '{text: $t}')"
if [[ "$DRY" == "1" ]]; then
  echo "$PAYLOAD"
  exit 0
fi

if [[ -z "${SLACK_WEBHOOK_URL:-}" ]]; then
  echo "notify_slack: SKIP (SLACK_WEBHOOK_URL unset in this session)"
  exit 0
fi

RESP="$(mktemp)"
trap 'rm -f "$RESP"' EXIT
for attempt in 1 2; do
  HTTP=$(curl -sS -o "$RESP" -w '%{http_code}' -X POST \
         -H 'Content-type: application/json' --data "$PAYLOAD" \
         "$SLACK_WEBHOOK_URL" 2>/dev/null) || HTTP=000
  if [[ "$HTTP" == "200" && "$(cat "$RESP")" == "ok" ]]; then
    echo "notify_slack: sent (${#MSG} chars)"
    exit 0
  fi
  [[ $attempt == 1 ]] && sleep 2
done
echo "notify_slack: FAILED (HTTP $HTTP: $(head -c 200 "$RESP")) — Slack report undelivered; note it in the run output" >&2
exit 1
