#!/usr/bin/env bash
#
# odds_api.sh — sportsbook odds via The Odds API (api.the-odds-api.com), NFL edition.
#
# PORTED from mlb_parlay_claude/tools/odds_api.sh (the plan's main reuse target) with the
# NFL adaptations from PORT_PLAN §3: two sport keys (REG + a SEPARATE preseason key —
# verified 2026-08-08), WEEK-scoped bulk pulls via the context store's kickoff windows
# (replaces the MLB ET-calendar-day slate filter), and prop market sets from
# config/markets.conf instead of hardcoded MLB lists. All the bought-with-losses guards
# port intact: started games excluded from best-price output (an in-game price is neither
# shoppable nor a close), empty cache never trusted, deny-reason → actionable allowlist
# message, DEACTIVATED_KEY → user-action message, quota telemetry on every spend.
#
# BUDGET (shared key with the MLB app — user-confirmed): credits = markets × regions per
# request; props bill PER EVENT. `board` (h2h,spreads,totals × us) = 3 credits for the
# whole scope. `events`/`quota` are FREE. Poll cadence/spend discipline lives in
# tools/poll_scheduler.py — this wrapper is the transport.
#
# USAGE
#   tools/odds_api.sh check                       # key + reachability + remaining quota
#   tools/odds_api.sh quota                       # remaining credits (FREE — /sports)
#   tools/odds_api.sh board [reg|pre] [<season> <week>]   # bulk featured pull+cache
#                                                 # reg default: current week via weekof
#   tools/odds_api.sh best <h2h|spreads|totals> [reg|pre] [<season> <week>]
#   tools/odds_api.sh game "<team>" [reg|pre] [<season> <week>]   # book-by-book board
#   tools/odds_api.sh events [reg|pre]            # event ids (FREE; props need them)
#   tools/odds_api.sh props <eventId> <markets|core|kicking|defense|longest>  # SPENDS
#   tools/odds_api.sh raw "<path-and-query>"      # passthrough (apiKey auto-appended)
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

BASE="https://api.the-odds-api.com/v4"
CONF="config/markets.conf"
TIMEOUT=30
CACHE_DIR="data/.cache"
MARKET_LOG="data/market_log.jsonl"   # committed observation log: prop posting times/coverage
mkdir -p "$CACHE_DIR"

die()  { echo "ERROR: $*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
have curl || die "curl not found"
have jq   || die "jq not found"
[[ -f "$CONF" ]] || die "$CONF not found"

conf() { grep "^${1}=" "$CONF" | head -1 | cut -d= -f2-; }
SPORT_REG="$(conf SPORT_KEY_REG)"
SPORT_PRE="$(conf SPORT_KEY_PRE)"
REGIONS="$(conf REGIONS)"
FEATURED="$(conf FEATURED)"

if [[ -z "${ODDS_API_KEY:-}" && -n "${1:-}" && "${1:-}" != "check" ]]; then
  die "ODDS_API_KEY is not set (secret env var — never commit it)."
fi

sport_for() {  # reg|pre -> sport key
  case "${1:-reg}" in
    reg) echo "$SPORT_REG" ;;
    pre) echo "$SPORT_PRE" ;;
    *)   die "scope must be reg or pre (got '$1')" ;;
  esac
}

# GET with apiKey appended; headers land in a fixed per-process file so quota lines
# written inside $(…) subshells stay readable in the parent (MLB bug class, kept fixed).
HDRS_FILE="${TMPDIR:-/tmp}/nfl_odds_hdrs_$$"
api_get() {
  local path="$1" sep
  [[ "$path" == *\?* ]] && sep="&" || sep="?"
  curl -sS -m "$TIMEOUT" -D "$HDRS_FILE" "${BASE}/${path}${sep}apiKey=${ODDS_API_KEY}" 2>/dev/null
}
quota_line() {
  [[ -f "$HDRS_FILE" ]] || return 0
  local rem used
  rem=$(grep -i '^x-requests-remaining:' "$HDRS_FILE" | awk '{print $2}' | tr -d '\r')
  used=$(grep -i '^x-requests-used:'      "$HDRS_FILE" | awk '{print $2}' | tr -d '\r')
  [[ -n "$rem" ]] && echo "  quota: ${rem} credits remaining this month (used ${used:-?})." >&2
}
deny_reason() { [[ -f "$HDRS_FILE" ]] && grep -i '^x-deny-reason:' "$HDRS_FILE" | awk '{print $2}' | tr -d '\r'; }

# Week window from the context store: "<season> <week> <type> <fromZ> <toZ>".
# Explicit season+week override; else weekof (the current/next REG-POST week).
week_window() {
  local season="${1:-}" week="${2:-}"
  if [[ -n "$season" && -n "$week" ]]; then
    python3 - "$season" "$week" <<'EOF'
import sqlite3, sys
con = sqlite3.connect("file:data/context.db?mode=ro", uri=True)
r = con.execute("SELECT MIN(kickoff_utc), MAX(kickoff_utc), game_type FROM games "
                "WHERE season=? AND week=?", (int(sys.argv[1]), int(sys.argv[2]))).fetchone()
if not r or not r[0]:
    sys.exit(f"no games for season {sys.argv[1]} week {sys.argv[2]} (run nfl_data.sh sync)")
print(sys.argv[1], sys.argv[2], r[2], r[0], r[1])
EOF
  else
    python3 tools/ingest.py weekof
  fi
}

cmd_check() {
  [[ -n "${ODDS_API_KEY:-}" ]] || { echo "NO KEY: set ODDS_API_KEY." >&2; exit 3; }
  local body
  body="$(api_get "sports?all=true")"
  if [[ -n "$(deny_reason)" ]]; then
    echo "BLOCKED: api.the-odds-api.com denied at the egress proxy (x-deny-reason: $(deny_reason))." >&2
    echo "  Add 'api.the-odds-api.com' to the environment allowlist, then start a NEW session." >&2
    rm -f "$HDRS_FILE"; exit 2
  fi
  if echo "$body" | jq -e 'type=="array"' >/dev/null 2>&1; then
    local reg pre
    reg=$(echo "$body" | jq -r --arg k "$SPORT_REG" '[.[]|select(.key==$k)][0].active // "MISSING"')
    pre=$(echo "$body" | jq -r --arg k "$SPORT_PRE" '[.[]|select(.key==$k)][0].active // "MISSING"')
    echo "OK: The Odds API reachable, key valid. $SPORT_REG active=$reg; $SPORT_PRE active=$pre."
    quota_line
    rm -f "$HDRS_FILE"; return 0
  fi
  if echo "$body" | grep -q 'DEACTIVATED_KEY'; then
    echo "DEACTIVATED: the Odds API key is deactivated (billing) — only the account owner can fix this at the-odds-api.com." >&2
    rm -f "$HDRS_FILE"; exit 4
  fi
  echo "BLOCKED/ERROR: unexpected response:" >&2
  echo "$body" | head -c 300 >&2; echo >&2
  rm -f "$HDRS_FILE"; exit 2
}

cmd_quota() {
  local body rem used
  body="$(api_get "sports?all=true" 2>/dev/null)"
  rem=$(grep -i '^x-requests-remaining:' "$HDRS_FILE" 2>/dev/null | awk '{print $2}' | tr -d '\r')
  used=$(grep -i '^x-requests-used:'      "$HDRS_FILE" 2>/dev/null | awk '{print $2}' | tr -d '\r')
  rm -f "$HDRS_FILE"
  if [[ -n "$rem" ]]; then
    echo "Odds API credits remaining: ${rem} (used ${used:-?} this month)   (as of $(TZ=America/New_York date '+%Y-%m-%d %H:%M ET'))"
  elif echo "$body" | grep -q 'DEACTIVATED_KEY'; then
    echo "Odds API credits remaining: UNAVAILABLE (key DEACTIVATED)"; return 1
  else
    echo "Odds API credits remaining: UNAVAILABLE (no key or host blocked)"; return 1
  fi
}

cache_file() { echo "$CACHE_DIR/board_${1}_${2}.json"; }   # sportkey, scopetag

# board [reg|pre] [season week] — bulk featured pull, week-scoped for reg via the store.
cmd_board() {
  local scope="${1:-reg}" season="${2:-}" week="${3:-}" sport win from to tag cf raw url
  sport="$(sport_for "$scope")"
  if [[ "$scope" == "reg" ]]; then
    win="$(week_window "$season" "$week")" || die "week window unresolved: $win"
    read -r season week _ from to <<<"$win"
    tag="${season}-W${week}"
    # pad the window: −2h before first kickoff, +5h after last (game length)
    from=$(python3 -c "from datetime import datetime,timedelta,timezone;print((datetime.strptime('$from','%Y-%m-%dT%H:%M:%SZ')-timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%SZ'))")
    to=$(python3 -c "from datetime import datetime,timedelta,timezone;print((datetime.strptime('$to','%Y-%m-%dT%H:%M:%SZ')+timedelta(hours=5)).strftime('%Y-%m-%dT%H:%M:%SZ'))")
    url="sports/${sport}/odds?regions=${REGIONS}&markets=${FEATURED}&oddsFormat=american&dateFormat=iso&commenceTimeFrom=${from}&commenceTimeTo=${to}"
  else
    tag="upcoming"
    url="sports/${sport}/odds?regions=${REGIONS}&markets=${FEATURED}&oddsFormat=american&dateFormat=iso"
  fi
  cf="$(cache_file "$sport" "$tag")"
  raw="$(api_get "$url")"
  if ! echo "$raw" | jq -e 'type=="array"' >/dev/null 2>&1; then
    echo "ERROR pulling odds: $(echo "$raw" | head -c 300)" >&2; quota_line; rm -f "$HDRS_FILE"; exit 2
  fi
  echo "$raw" > "$cf"
  quota_line; rm -f "$HDRS_FILE"
  local n; n=$(jq 'length' "$cf")
  echo "════ best h2h — ${sport} ${tag} (${n} events, cached → $cf) ════"
  [[ "$n" -eq 0 ]] && { echo "(no events in scope — lines may not be posted yet)"; return 0; }
  jq -r --arg now "$(date -u +%FT%TZ)" "$(best_jq h2h)" "$cf"
  echo "  (spreads/totals cached too → tools/odds_api.sh best spreads|totals $scope $season $week)"
}

# Best price per outcome across books; STARTED events excluded (in-game ≠ shoppable/close).
best_jq() {
  cat <<JQ
def sign(p): if p>0 then "+" else "" end;
( [ .[] | select(.commence_time <= \$now) ] | length ) as \$started
| ( if \$started > 0 then "⛔ \(\$started) event(s) already started — excluded (in-game prices)" else empty end ),
( .[] | select(.commence_time > \$now) | . as \$g
| "── \(\$g.away_team) @ \(\$g.home_team)  (\(\$g.commence_time))"
, ( [ \$g.bookmakers[] | {bk:.title, o:(.markets[]?|select(.key=="$1").outcomes[]?) } ]
    | group_by(.o.name + (.o.point|tostring))[]
    | max_by(.o.price) as \$b
    | "   \(\$b.o.name)\(if \$b.o.point != null then " "+(\$b.o.point|tostring) else "" end): \(sign(\$b.o.price))\(\$b.o.price)  @\(\$b.bk)" ) )
JQ
}

ensure_cache() {  # scope season week -> cache path (warm if missing)
  local scope="$1" season="${2:-}" week="${3:-}" sport tag cf
  sport="$(sport_for "$scope")"
  if [[ "$scope" == "reg" ]]; then
    if [[ -z "$season" || -z "$week" ]]; then
      read -r season week _ _ _ <<<"$(week_window)" || die "cannot resolve current week"
    fi
    tag="${season}-W${week}"
  else
    tag="upcoming"
  fi
  cf="$(cache_file "$sport" "$tag")"
  if [[ ! -s "$cf" || "$(jq 'length' "$cf" 2>/dev/null || echo 0)" -eq 0 ]]; then
    cmd_board "$scope" "$season" "$week" >/dev/null
  fi
  echo "$cf"
}

cmd_best() {
  local mk="${1:?market: h2h|spreads|totals}" scope="${2:-reg}" cf
  case "$mk" in h2h|spreads|totals) ;; *) die "market must be h2h, spreads, or totals" ;; esac
  cf="$(ensure_cache "$scope" "${3:-}" "${4:-}")"
  jq -r --arg now "$(date -u +%FT%TZ)" "$(best_jq "$mk")" "$cf"
}

cmd_game() {
  local team="${1:?team name fragment}" scope="${2:-reg}" cf
  cf="$(ensure_cache "$scope" "${3:-}" "${4:-}")"
  jq -r --arg t "$team" --arg now "$(date -u +%FT%TZ)" '
    .[] | select((.home_team+" "+.away_team)|ascii_downcase|contains($t|ascii_downcase))
    | "════ \(.away_team) @ \(.home_team)  (\(.commence_time)) ════",
      ( if .commence_time <= $now
        then "⛔ STARTED — cached prices are IN-GAME at cache time, NOT shoppable/closing lines"
        else empty end ),
      ( .bookmakers[] | "── \(.title)",
        ( .markets[] | "   [\(.key)] " + ([.outcomes[] | "\(.name)\(if .point then " "+(.point|tostring) else "" end) \(if .price>0 then "+" else "" end)\(.price)"]|join("  ")) ) )
  ' "$cf"
}

cmd_events() {
  local scope="${1:-reg}" sport raw
  sport="$(sport_for "$scope")"
  raw="$(api_get "sports/${sport}/events?dateFormat=iso")"
  rm -f "$HDRS_FILE"
  echo "$raw" | jq -r '.[] | "\(.id)  \(.commence_time)  \(.away_team) @ \(.home_team)"'
}

# props <eventId> <markets|core|kicking|defense|longest> — PER-EVENT, SPENDS CREDITS.
# Every successful pull appends coverage rows to data/market_log.jsonl — the committed
# observation record for "when do books actually post NFL props" (M2 acceptance).
cmd_props() {
  local eid="${1:?eventId (from events)}" markets="${2:?markets, or core|kicking|defense|longest}"
  local scope="${3:-reg}" sport
  sport="$(sport_for "$scope")"
  case "$markets" in
    core)    markets="$(conf PROPS_CORE)" ;;
    kicking) markets="$(conf PROPS_OPTIN_KICKING)" ;;
    defense) markets="$(conf PROPS_OPTIN_DEFENSE)" ;;
    longest) markets="$(conf PROPS_OPTIN_LONGEST)" ;;
  esac
  local ncred; ncred=$(( $(tr ',' '\n' <<<"$markets" | grep -c .) ))
  echo "ℹ PER-EVENT prop call — ~${ncred} credit(s). Markets: $markets" >&2
  local raw; raw="$(api_get "sports/${sport}/events/${eid}/odds?regions=${REGIONS}&markets=${markets}&oddsFormat=american&dateFormat=iso")"
  quota_line
  # observation log: one line per requested market with books-offering count
  if echo "$raw" | jq -e 'has("bookmakers")' >/dev/null 2>&1; then
    local ts; ts="$(date -u +%FT%TZ)"
    for m in $(tr ',' ' ' <<<"$markets"); do
      echo "$raw" | jq -c --arg ts "$ts" --arg m "$m" --arg eid "$eid" \
        '{ts:$ts, event:$eid, market:$m,
          books:([.bookmakers[]? | select(any(.markets[]?; .key==$m)) | .title] | length),
          commence:.commence_time, matchup:(.away_team+" @ "+.home_team)}' >> "$MARKET_LOG"
    done
  fi
  echo "$raw" | jq -r '
    "════ \(.away_team) @ \(.home_team)  (\(.commence_time)) ════",
    ( if (.bookmakers | length) == 0
      then "  (no prop markets posted for this event yet — normal outside game week / preseason)"
      else ( .bookmakers[] | "── \(.title)",
        ( .markets[] | "   [\(.key)]",
          ( .outcomes[] | "      \(.description // .name) \(.name) \(.point // "") \(if .price>0 then "+" else "" end)\(.price)" ) ) )
      end )
  ' 2>/dev/null || { echo "no prop data:"; echo "$raw" | head -c 300; }
  rm -f "$HDRS_FILE"
}

cmd_raw() { local p="${1:?path}"; api_get "$p"; rm -f "$HDRS_FILE"; echo; }

case "${1:-}" in
  check)   cmd_check ;;
  quota)   cmd_quota ;;
  board)   shift; cmd_board "$@" ;;
  best)    shift; cmd_best "$@" ;;
  game)    shift; cmd_game "$@" ;;
  events)  shift; cmd_events "$@" ;;
  props)   shift; cmd_props "$@" ;;
  raw)     shift; cmd_raw "$@" ;;
  *) sed -n '3,29p' "$0"; exit 1 ;;
esac
