#!/usr/bin/env bash
#
# nfl_data.sh — the context-layer CLI (the mlb_api.sh analog, store-backed).
#
# WHY THIS EXISTS
#   NFL has no statsapi equivalent: facts come from nflverse GitHub release assets,
#   ingested into data/context.db by tools/ingest.py (PORT_PLAN decision (a)). This
#   wrapper gives the routine one stable command surface + a `check` preflight with
#   actionable guidance when egress is blocked — same doctrine as mlb_api.sh/odds_api.sh.
#
# USAGE
#   tools/nfl_data.sh check                       # reachability preflight (exit 0 ok, 2 blocked)
#   tools/nfl_data.sh sync [dataset] [--force]    # release assets → data/context.db (idempotent)
#   tools/nfl_data.sh status                      # per-dataset staleness table
#   tools/nfl_data.sh slate  <season> <week>      # games grouped by kickoff window
#   tools/nfl_data.sh finals <season> <week>      # completed games w/ scores (settle input)
#   tools/nfl_data.sh volume <team> <season> <wk> # per-player snap% + target/carry share
#   tools/nfl_data.sh form   <team> [n]           # last-n results + point differential
#   tools/nfl_data.sh player "<name>"             # resolve player -> ids/team/position
#   tools/nfl_data.sh depth  <team>               # latest depth-chart snapshot
#   tools/nfl_data.sh sql    "<SELECT ...>"       # read-only passthrough
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

PROBE="https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"

die() { echo "ERROR: $*" >&2; exit 1; }
command -v curl >/dev/null 2>&1 || die "curl not found"
command -v python3 >/dev/null 2>&1 || die "python3 not found"

cmd_check() {
  local code
  code=$(curl -sIL -o /dev/null -w '%{http_code}' -m 25 "$PROBE" 2>/dev/null || echo 000)
  if [[ "$code" == "200" ]]; then
    echo "OK: nflverse release assets reachable — context store can sync."
    echo "    Next: tools/nfl_data.sh sync   (idempotent; skips unchanged sources)"
    return 0
  fi
  cat >&2 <<EOF
BLOCKED: cannot reach nflverse release assets (HTTP $code on the schedules probe).
  github.com (and its objects.githubusercontent.com redirect target) must be reachable
  from this environment. If the network policy is an allowlist, add both hosts and start
  a NEW session (policy applies at startup). Until then the store serves its LAST-GOOD
  tables — run 'tools/nfl_data.sh status' to see how stale each dataset is; consumers
  must treat stale-premised legs as PENDING per CLAUDE.md.
EOF
  return 2
}

sub="${1:-}"
case "$sub" in
  check) cmd_check ;;
  sync|status|slate|finals|volume|form|player|depth|sql)
    shift
    exec python3 tools/ingest.py "$sub" "$@" ;;
  ""|-h|--help|help) sed -n '3,23p' "$0" ;;
  *) die "unknown subcommand: $sub (try: check sync status slate finals volume form player depth sql)" ;;
esac
