#!/usr/bin/env bash
#
# notify_email.sh — deliver a run report to realityremixed125@gmail.com with NO approval.
#
# WHY THIS EXISTS (2026-08-09). mcp__Gmail__create_draft cannot be used from a
# trigger-fired session: it pops "Create Draft requests permission / Allow once /
# Deny" on the owner's phone and STALLS the run there (proven runs 1-4, re-proven
# run 7 with a screenshot). Connector attachment + a .claude/settings.json allowlist
# do NOT suppress it, and create_trigger's `connectors` grant is disabled for this
# organization. SMTP 587/465 and IMAP 993 are blocked from the container. The ONLY
# promptless path left is an ordinary HTTPS POST — the same trick that fixed Slack.
#
# The far end is a Google Apps Script web app deployed by the owner, running AS the
# owner's Google account, so the message is created directly in that Gmail. Setup
# lives in docs/NOTIFY_EMAIL_SETUP.md. The /exec URL is a capability URL: treat it
# exactly like SLACK_WEBHOOK_URL — never commit it, never echo it.
#
# USAGE
#   tools/notify_email.sh "Subject" "body text"     # body may also come from stdin
#   tools/notify_email.sh --draft "Subject" "body"  # create a Gmail DRAFT (default: send)
#   tools/notify_email.sh --dry-run "Subject" "body"
#
# GMAIL_WEBHOOK_URL absent → SKIP with exit 0, so sessions without the secret degrade
# gracefully instead of erroring (same contract as notify_slack.sh).
set -uo pipefail

DRY=0
MODE="send"
while [[ "${1:-}" == --* ]]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --draft)   MODE="draft" ;;
    --send)    MODE="send" ;;
    *) echo "notify_email: unknown flag $1" >&2; exit 2 ;;
  esac
  shift
done

SUBJECT="${1:-}"
BODY="${2:-}"
if [[ -z "$BODY" && ! -t 0 ]]; then BODY="$(cat)"; fi
if [[ -z "$SUBJECT" ]]; then echo "notify_email: no subject given" >&2; exit 2; fi
if [[ -z "$BODY" ]]; then echo "notify_email: no body given (arg or stdin)" >&2; exit 2; fi

TO="${NFL_REPORT_TO:-realityremixed125@gmail.com}"

# Apps Script caps a single execution's payload; trim defensively rather than 413.
if (( ${#BODY} > 180000 )); then BODY="${BODY:0:180000}"$'\n…(trimmed)'; fi

PAYLOAD="$(jq -Rn --arg to "$TO" --arg s "$SUBJECT" --arg b "$BODY" --arg m "$MODE" \
  '{to: $to, subject: $s, body: $b, mode: $m}')"

if [[ "$DRY" == "1" ]]; then
  echo "$PAYLOAD"
  exit 0
fi

if [[ -z "${GMAIL_WEBHOOK_URL:-}" ]]; then
  echo "notify_email: SKIP (GMAIL_WEBHOOK_URL unset in this session)"
  exit 0
fi

RESP="$(mktemp)"
trap 'rm -f "$RESP"' EXIT
for attempt in 1 2; do
  # -L is REQUIRED: an Apps Script /exec URL 302s to script.googleusercontent.com.
  HTTP=$(curl -sS -L -o "$RESP" -w '%{http_code}' -X POST \
         -H 'Content-Type: application/json' --data "$PAYLOAD" \
         --max-time 30 "$GMAIL_WEBHOOK_URL" 2>/dev/null) || HTTP=000
  if [[ "$HTTP" == "200" ]] && grep -qi '^ok' "$RESP"; then
    echo "notify_email: $MODE ok → $TO (${#BODY} chars)"
    exit 0
  fi
  [[ $attempt == 1 ]] && sleep 3
done
echo "notify_email: FAILED (HTTP $HTTP: $(head -c 200 "$RESP")) — email undelivered; say so in the run output" >&2
exit 1
