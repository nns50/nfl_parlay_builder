#!/usr/bin/env bash
#
# selftest.sh — fast invariant suite for the NFL parlay tooling.
#
# CONTRACT (ported from the MLB repo, verbatim in spirit):
#   • FAST (~seconds), OFFLINE, QUOTA-FREE — fixture tests only, no network, no API spend.
#   • Every silent-bug class we fix gets PINNED here as a regression check.
#   • Exit 0 = all green; exit 1 = at least one failure (details printed).
#   • A red selftest is doctrine-STOP: do not build/settle/trust tool output until fixed.
#
# USAGE
#   tools/selftest.sh            # full offline suite
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

PASS=0; FAIL=0
ok() { PASS=$((PASS+1)); printf "  \033[32m✓\033[0m %s\n" "$1"; }
no() { FAIL=$((FAIL+1)); printf "  \033[31m✗ %s\033[0m\n" "$1"; [[ -n "${2:-}" ]] && printf "%s\n" "$2" | sed 's/^/        /'; }
pyblk() { # pyblk "<desc>" <<'EOF' … EOF   — pass iff the python block exits 0
  local desc="$1" out
  if out=$(python3 2>&1); then ok "$desc"; else no "$desc" "$out"; fi
}

echo "════════ selftest (offline) ════════"

# ── 1. Syntax: every script parses ───────────────────────────────────────────
for f in tools/*.sh; do
  if bash -n "$f" 2>/dev/null; then ok "bash -n $f"; else no "bash -n $f"; fi
done
for f in tools/*.py; do
  if python3 -m py_compile "$f" 2>/dev/null; then ok "py_compile $f"; else no "py_compile $f"; fi
done

# ── 2. markets.conf invariants (decision (c): the core-8 prop set) ───────────
CORE_N=$(grep '^PROPS_CORE=' config/markets.conf | cut -d= -f2 | tr ',' '\n' | grep -c .)
[[ "$CORE_N" == "8" ]] && ok "markets.conf PROPS_CORE has 8 markets" \
                       || no "markets.conf PROPS_CORE has 8 markets" "got $CORE_N"
grep -q '^SPORT_KEY_REG=americanfootball_nfl$' config/markets.conf \
  && ok "markets.conf REG sport key" || no "markets.conf REG sport key"
grep -q '^SPORT_KEY_PRE=americanfootball_nfl_preseason$' config/markets.conf \
  && ok "markets.conf PRE sport key (verified separate key)" || no "markets.conf PRE sport key"
grep -Eq '^CADENCE_FEATURED=([0-9]+:[0-9]+,)*[0-9]+:[0-9]+$' config/markets.conf \
  && ok "markets.conf cadence lines parse" || no "markets.conf cadence lines parse"

# ── 3. stadiums.csv — every 2026 venue resolvable, sane coords/enums ─────────
pyblk "stadiums.csv: coords/roof/tz sane + every 2026 venue name resolves" <<'EOF'
import csv, sys
rows = list(csv.DictReader(open("config/stadiums.csv")))
assert rows, "empty stadiums.csv"
names = set()
for r in rows:
    lat, lon = float(r["lat"]), float(r["lon"])
    assert -90 <= lat <= 90 and -180 <= lon <= 180, f"bad coords: {r['stadium']}"
    assert r["roof"] in ("dome", "retractable", "outdoor"), f"bad roof: {r['stadium']}"
    assert r["tz"].strip(), f"missing tz: {r['stadium']}"
    names.add(r["stadium"])
# every stadium name appearing in the REAL 2025-2026 schedules (verified extract
# 2026-08-08) must resolve — internationals included. A new season adds names here.
need = ["State Farm Stadium","Mercedes-Benz Stadium","M&T Bank Stadium","Highmark Stadium",
 "New Era Field","Bank of America Stadium","Soldier Field","Paycor Stadium",
 "Huntington Bank Field","FirstEnergy Stadium","AT&T Stadium","Empower Field at Mile High",
 "Ford Field","Lambeau Field","NRG Stadium","Reliant Stadium","Lucas Oil Stadium",
 "EverBank Stadium","TIAA Bank Stadium","GEHA Field at Arrowhead Stadium","SoFi Stadium",
 "Allegiant Stadium","Hard Rock Stadium","U.S. Bank Stadium","Gillette Stadium",
 "Caesars Superdome","Mercedes-Benz Superdome","MetLife Stadium","Lincoln Financial Field",
 "Acrisure Stadium","Lumen Field","Levi's Stadium","Raymond James Stadium","Nissan Stadium",
 "Northwest Stadium","FedExField","Tottenham Hotspur Stadium","Wembley Stadium",
 "FC Bayern Munich Stadium","Bernabeu","Stade de France","Maracana Stadium",
 "Estadio Banorte","Melbourne Cricket Ground"]
missing = [n for n in need if n not in names]
assert not missing, f"unresolvable venues: {missing}"
from zoneinfo import ZoneInfo
for r in rows: ZoneInfo(r["tz"])   # every tz must be a real IANA zone
EOF

# ── 4. ingest kickoff math — ET→UTC incl. EDT/EST boundary ───────────────────
pyblk "kickoff_iso: EDT (-4) and EST (-5) conversions correct" <<'EOF'
import sys; sys.path.insert(0, "tools")
from ingest import kickoff_iso
assert kickoff_iso("2026-09-09","20:20") == ("2026-09-09 20:20 ET","2026-09-10T00:20:00Z")
assert kickoff_iso("2027-01-10","13:00") == ("2027-01-10 13:00 ET","2027-01-10T18:00:00Z")
assert kickoff_iso("2026-09-09","")[1] is None      # missing time degrades, not crashes
EOF

# ── 5. games loader on fixture: typing, computed kickoff, extra-col ignored ──
pyblk "games loader: 3 fixture rows load; scores typed; kickoff_utc computed" <<'EOF'
import os, sys; os.environ["NFL_DB"] = ":memory:"; sys.path.insert(0, "tools")
import csv, ingest
con = ingest.connect()
rows = list(csv.DictReader(open("tools/fixtures/games_fixture.csv")))
n, missing = ingest.load_table(con, "games", iter(rows), list(rows[0].keys()))
assert n == 3 and not missing, (n, missing)
r = con.execute("SELECT * FROM games WHERE game_id='2026_01_NE_SEA'").fetchone()
assert r["kickoff_utc"] == "2026-09-10T00:20:00Z", r["kickoff_utc"]
assert r["home_score"] is None
done = con.execute("SELECT * FROM games WHERE game_id='2025_18_BUF_NE'").fetchone()
assert done["away_score"] == 23 and isinstance(done["away_score"], int)
neut = con.execute("SELECT location FROM games WHERE game_id='2026_01_SF_LA'").fetchone()
assert neut["location"] == "Neutral"
EOF

# ── 6. stats loader: kicking + defense fields land; missing cols FLAGGED ─────
pyblk "stats loader: fg_made/pat_made/def_sacks land; crippled header flags missing" <<'EOF'
import os, sys; os.environ["NFL_DB"] = ":memory:"; sys.path.insert(0, "tools")
import csv, ingest
con = ingest.connect()
rows = list(csv.DictReader(open("tools/fixtures/stats_fixture.csv")))
n, missing = ingest.load_table(con, "player_week", iter(rows), list(rows[0].keys()), season=2025)
assert n == 3 and not missing, (n, missing)
k = con.execute("SELECT * FROM player_week WHERE position='K'").fetchone()
assert k["fg_made"] == 3 and k["fg_att"] == 4 and k["pat_made"] == 4 and k["fg_long"] == 52
wr = con.execute("SELECT * FROM player_week WHERE position='WR'").fetchone()
assert wr["targets"] == 11 and abs(wr["target_share"] - 0.324) < 1e-9
# crippled source (no kicking cols) must FLAG, not silently drop
rows2 = list(csv.DictReader(open("tools/fixtures/stats_missing_fixture.csv")))
_, missing2 = ingest.load_table(con, "player_week", iter(rows2), list(rows2[0].keys()), season=2025)
assert "fg_made" in missing2 and "pat_made" in missing2, missing2
EOF

# ── 7. snaps loader + volume share math ──────────────────────────────────────
pyblk "snaps loader: pct floats; share(): sums + zero-total guard" <<'EOF'
import os, sys; os.environ["NFL_DB"] = ":memory:"; sys.path.insert(0, "tools")
import csv, ingest
con = ingest.connect()
rows = list(csv.DictReader(open("tools/fixtures/snaps_fixture.csv")))
n, missing = ingest.load_table(con, "snaps", iter(rows), list(rows[0].keys()), season=2025)
assert n == 3 and not missing
r = con.execute("SELECT * FROM snaps WHERE pfr_player_id='DiggSt00'").fetchone()
assert abs(r["offense_pct"] - 0.897) < 1e-9
assert ingest.share(11, 33) == 0.333 and ingest.share(5, 0) is None
EOF

# ── 8. depth latest-only filter (timestamped 2025+ format) ───────────────────
pyblk "depth loader: keeps only each team's latest snapshot" <<'EOF'
import os, sys; os.environ["NFL_DB"] = ":memory:"; sys.path.insert(0, "tools")
import csv, ingest
con = ingest.connect()
rows = list(csv.DictReader(open("tools/fixtures/depth_fixture.csv")))
n, missing = ingest.load_table(con, "depth", iter(rows), list(rows[0].keys()), season=2026)
assert n == 3 and not missing, (n, missing)          # 2 BUF@latest + 1 MIA; Old Starter dropped
names = {r["player_name"] for r in con.execute("SELECT player_name FROM depth")}
assert names == {"New Starter", "New Backup", "Other Team QB"}, names
EOF

# ── 9. manifest skip rule (idempotent sync) ──────────────────────────────────
pyblk "source_unchanged: skips only on same length+mtime AND loaded rows" <<'EOF'
import sys; sys.path.insert(0, "tools")
from ingest import source_unchanged
e = {"source_length": "123", "source_last_modified": "Mon, 01 Jan 2026 00:00:00 GMT", "rows": 10}
assert source_unchanged(e, "123", "Mon, 01 Jan 2026 00:00:00 GMT")
assert not source_unchanged(e, "999", "Mon, 01 Jan 2026 00:00:00 GMT")   # length changed
assert not source_unchanged({}, "123", "x")                              # never synced
assert not source_unchanged(dict(e, rows=0), "123", "Mon, 01 Jan 2026 00:00:00 GMT")  # empty load
EOF

# ── 10. window labels are data-driven cosmetics ──────────────────────────────
pyblk "window_label: Sun-early / SNF / TNF / intl-AM from kickoff data" <<'EOF'
import sys; sys.path.insert(0, "tools")
from ingest import window_label
lbl = lambda wd, gt: window_label({"weekday": wd, "gametime": gt})
assert lbl("Sunday", "13:00") == "Sun-early"
assert lbl("Sunday", "16:25") == "Sun-late"
assert lbl("Sunday", "20:20") == "SNF"
assert lbl("Sunday", "09:30") == "Sun-intl/early-AM"
assert lbl("Thursday", "20:15") == "TNF"
assert lbl("Wednesday", "20:20") == "Wed"     # the real 2026 opener
EOF

# ── 11. current_season boundary (season spans the new year — no epoch hack) ──
pyblk "current_season: Jan/Feb belong to the prior season" <<'EOF'
import sys; sys.path.insert(0, "tools")
from datetime import datetime, timezone
from ingest import current_season
assert current_season(datetime(2026, 8, 8, tzinfo=timezone.utc)) == 2026
assert current_season(datetime(2027, 1, 15, tzinfo=timezone.utc)) == 2026
assert current_season(datetime(2027, 3, 2, tzinfo=timezone.utc)) == 2027
EOF

# ── 12. CLI contract ─────────────────────────────────────────────────────────
if bash tools/nfl_data.sh definitely-not-a-command >/dev/null 2>&1; then
  no "nfl_data.sh rejects unknown subcommand"
else ok "nfl_data.sh rejects unknown subcommand"; fi
if bash tools/nfl_data.sh --help 2>/dev/null | grep -q "sync \[dataset\]"; then
  ok "nfl_data.sh --help prints usage"
else no "nfl_data.sh --help prints usage"; fi
if python3 tools/ingest.py sync not-a-dataset >/dev/null 2>&1; then
  no "ingest.py sync rejects unknown dataset"
else ok "ingest.py sync rejects unknown dataset"; fi

# ── summary ──────────────────────────────────────────────────────────────────
echo "────────────────────────────────────"
if [[ "$FAIL" -eq 0 ]]; then
  echo "✓ ALL $PASS CHECKS PASSED"
else
  echo "⛔ SELFTEST FAILED — $FAIL of $((PASS+FAIL)) checks failed. Fix before trusting any tool."
  exit 1
fi
