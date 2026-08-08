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

# ── 12. M2: markets.conf budget/floor keys ───────────────────────────────────
grep -Eq '^BUDGET_WEEKLY_SOFT=[0-9]+$' config/markets.conf \
  && ok "markets.conf BUDGET_WEEKLY_SOFT present" || no "markets.conf BUDGET_WEEKLY_SOFT present"
grep -Eq '^CREDIT_FLOOR_PROPS=[0-9]+$' config/markets.conf \
  && ok "markets.conf CREDIT_FLOOR_PROPS present" || no "markets.conf CREDIT_FLOOR_PROPS present"

# ── 13. M2: scheduler phase math (bracket model, close semantics, started) ───
pyblk "poll_scheduler: interval_for bracket logic (baseline/aggressive/close/started)" <<'EOF'
import sys; sys.path.insert(0, "tools")
from poll_scheduler import parse_cadence, interval_for
ph = parse_cadence("99999:720,4320:480,1440:360,120:15,5:0")
assert ph[0] == (99999, 720) and ph[-1] == (5, 0)
assert interval_for(6000, ph) == 720     # week-open baseline
assert interval_for(2000, ph) == 480     # T-72h..T-24h
assert interval_for(600,  ph) == 360     # T-24h..T-2h
assert interval_for(60,   ph) == 15      # aggressive window
assert interval_for(3,    ph) == 0       # close bracket
assert interval_for(0,    ph) is None    # kickoff — stop
assert interval_for(-10,  ph) is None    # started — stop
EOF

# ── 13b. M2: whole-week simulation reproduces the budget model ───────────────
pyblk "poll_scheduler: simulated 16-game week lands within budget; preseason props=0" <<'EOF'
import sys; sys.path.insert(0, "tools")
from datetime import datetime, timezone, timedelta
from poll_scheduler import parse_cadence, simulate_week
ff = parse_cadence("99999:720,4320:480,1440:360,120:15,5:0")
pp = parse_cadence("4320:1440,1440:360,120:30,5:0")
base = datetime(2026, 9, 13, 17, 0, tzinfo=timezone.utc)
kicks = ([datetime(2026, 9, 10, 0, 20, tzinfo=timezone.utc)]      # Thu-style opener
         + [base] * 9                                             # Sun early
         + [base + timedelta(hours=3, minutes=25)] * 4            # Sun late
         + [base + timedelta(hours=7, minutes=20)]                # SNF
         + [base + timedelta(days=1, hours=3, minutes=15)])       # MNF
res = simulate_week(kicks, ff, pp, 8)
assert res["props_polls"] > 0 and res["featured_polls"] > 0
assert res["total_credits"] <= 2500, f"blows the soft budget: {res}"
# floor pins the per-EVENT identity fix: keying props state by kickoff datetime
# collapsed simultaneous-window games and undercounted the week 3x (656 vs ~1600)
assert res["total_credits"] >= 1200, f"implausibly cheap (event-collapse regression?): {res}"
pre = simulate_week(kicks, ff, pp, 8, props_enabled=False)
assert pre["props_credits"] == 0 and pre["featured_polls"] > 0
EOF

# ── 13c. M2: due-state idempotence (marked poll not re-due inside interval) ──
pyblk "poll_scheduler: due --mark is idempotent within an interval" <<'EOF'
import os, sys, io, tempfile, contextlib
td = tempfile.mkdtemp()
os.environ["NFL_DB"] = os.path.join(td, "t.db")
os.environ["NFL_POLL_STATE"] = os.path.join(td, "state.json")
sys.path.insert(0, "tools")
import csv, ingest, importlib
import poll_scheduler as ps
importlib.reload(ps)                       # pick up the env-var paths
con = ingest.connect()
rows = list(csv.DictReader(open("tools/fixtures/games_fixture.csv")))
ingest.load_table(con, "games", iter(rows), list(rows[0].keys())); con.close()
def run(now):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ps.cmd_due(2026, 1, now=now, mark=True, skip_quota=True)
    return buf.getvalue()
first = run("2026-09-07T12:00:00Z")        # T-2.3d: featured+props due (never polled)
assert "FEATURED" in first and "PROPS" in first, first
second = run("2026-09-07T12:05:00Z")       # 5 min later, inside every interval
assert "FEATURED" not in second and "PROPS" not in second, second
EOF

# ── 13d. M2: propquote pure pricing (best-per-side, alternates, ambiguity) ───
pyblk "propquote: best_by_point picks best book incl. _alternate; ambiguity refused" <<'EOF'
import sys; sys.path.insert(0, "tools")
from propquote import best_by_point, novig_at_point
ev = {"bookmakers": [
 {"title": "BookA", "markets": [
   {"key": "player_pass_yds", "outcomes": [
     {"description": "Josh Allen", "name": "Over", "point": 249.5, "price": -115},
     {"description": "Josh Allen", "name": "Under", "point": 249.5, "price": -105}]},
   {"key": "player_pass_yds_alternate", "outcomes": [
     {"description": "Josh Allen", "name": "Over", "point": 274.5, "price": 130}]}]},
 {"title": "BookB", "markets": [
   {"key": "player_pass_yds", "outcomes": [
     {"description": "Josh Allen", "name": "Over", "point": 249.5, "price": -110},
     {"description": "Josh Allen", "name": "Under", "point": 249.5, "price": -110}]}]}]}
t = best_by_point(ev, "Josh Allen", "player_pass_yds")
assert t[249.5]["Over"] == (-110, "BookB") and t[249.5]["Under"] == (-105, "BookA")
assert t[274.5]["Over"] == (130, "BookA")          # _alternate folded in
nv = novig_at_point(t[249.5]); assert abs(nv[0] + nv[1] - 1) < 1e-9
assert novig_at_point(t[274.5]) is None            # one-sided
amb = {"bookmakers": [{"title": "A", "markets": [{"key": "player_rush_yds", "outcomes": [
  {"description": "J. Smith", "name": "Over", "point": 50.5, "price": -110},
  {"description": "K. Smith", "name": "Over", "point": 40.5, "price": -110}]}]}]}
assert best_by_point(amb, "Smith", "player_rush_yds") == {}   # two players — refuse
EOF

# ── 13e. M2: weekof resolves the coming week from the store ──────────────────
pyblk "ingest.weekof: resolves 2026 W1 from fixture games" <<'EOF'
import os, sys, io, tempfile, contextlib
td = tempfile.mkdtemp()
os.environ["NFL_DB"] = os.path.join(td, "t.db")
sys.path.insert(0, "tools")
import csv, ingest
con = ingest.connect()
rows = list(csv.DictReader(open("tools/fixtures/games_fixture.csv")))
ingest.load_table(con, "games", iter(rows), list(rows[0].keys())); con.close()
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    ingest.weekof("2026-09-01T00:00:00Z")
out = buf.getvalue().split()
assert out[0] == "2026" and out[1] == "1" and out[2] == "REG", out
EOF

# ── 14. M3: availability ladder (p_plays seeds, status map, espn-id extraction) ─
pyblk "availability: p_plays ladder + roster hard-OUTs + espn id from links" <<'EOF'
import sys; sys.path.insert(0, "tools")
from availability import p_plays, map_status, espn_id_from_links
assert map_status("Out") == "OUT" and map_status("Questionable") == "QUESTIONABLE"
assert map_status("Injured Reserve") == "IR" and map_status("Day-To-Day") == "DTD"
assert map_status("Active") is None                 # news note, not a listing
assert p_plays("OUT") == 0.0 and p_plays("IR") == 0.0
assert p_plays("DOUBTFUL") == 0.25 and p_plays("QUESTIONABLE") == 0.75
assert p_plays(None) is None                        # no signal ≠ certainty
assert p_plays(None, roster_status="RES") == 0.0    # roster floor wins
assert p_plays("QUESTIONABLE", roster_status="PUP") == 0.0
ath = {"links": [{"href": "https://www.espn.com/nfl/player/_/id/4709695/karson-sharar"}]}
assert espn_id_from_links(ath) == "4709695"
assert espn_id_from_links({"links": []}) is None
EOF

# ── 14b. M3: weather pure logic (dome short-circuit, window pick, flags) ─────
pyblk "weather: is_indoor precedence; pick_window maxes; verdict thresholds" <<'EOF'
import sys; sys.path.insert(0, "tools")
from weather import is_indoor, pick_window, verdict, days_out
assert is_indoor("closed", "retractable") is True      # per-game closed wins
assert is_indoor("outdoors", "dome") is False          # per-game open wins
assert is_indoor("", "dome") is True                   # static fallback
assert is_indoor(None, "retractable") is False         # unknown retractable = outdoor
# static-outdoor VETO: neutral-site rows inherit the home team's roof template
# (real case: 2026 MCG game carries LA's 'dome' — a roofless venue can't close)
assert is_indoor("dome", "outdoor") is False
times = [f"2026-09-13T{h:02d}:00" for h in range(12, 24)]
temp = list(range(60, 72)); wind = [5]*5 + [18, 12, 9] + [4]*4
gust = [10]*12; precip = [0]*6 + [60] + [0]*5
w = pick_window(times, temp, wind, gust, precip, "2026-09-13T17:00:00Z", hours=4)
assert w["temp_f"] == 65 and w["wind_mph"] == 18 and w["precip_prob"] == 60
v = verdict(w); assert "WIND 18" in v and "PRECIP 60" in v
assert verdict({"temp_f": 70, "wind_mph": 6, "gust_mph": 10, "precip_prob": 0}) == ""
assert pick_window(times, temp, wind, gust, precip, "2026-09-14T05:00:00Z") is None
from datetime import datetime, timezone
assert 31 < days_out("2026-09-10T00:20:00Z", datetime(2026,8,8,12,0,tzinfo=timezone.utc)) < 33
EOF

# ── 14c. M3: weekcheck diff fixtures (every finding class fires; clean = silent) ─
if python3 tools/weekcheck.py --selftest >/dev/null 2>&1; then
  ok "weekcheck --selftest (QB/line/avail/wind/flex/started/gone fixtures)"
else
  no "weekcheck --selftest (QB/line/avail/wind/flex/started/gone fixtures)" \
     "$(python3 tools/weekcheck.py --selftest 2>&1 | tail -12)"
fi

# ── 15. CLI contract ─────────────────────────────────────────────────────────
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
