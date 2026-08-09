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
# manifest-vs-DB pin (live burn 2026-08-08): fresh manifest + missing/empty TABLE
# must NOT skip — a deleted DB with an intact manifest left the store empty
import os
os.environ["NFL_DB"] = ":memory:"
import importlib, ingest as _ing
importlib.reload(_ing)
con = _ing.connect()
assert not _ing.db_has_rows(con, "games")                 # table absent → no skip
import csv as _csv
rows = list(_csv.DictReader(open("tools/fixtures/games_fixture.csv")))
_ing.load_table(con, "games", iter(rows), list(rows[0].keys()))
assert _ing.db_has_rows(con, "games")                     # populated → skip allowed
assert _ing.db_has_rows(con, "games", 2026) and not _ing.db_has_rows(con, "games", 1999)
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

# ── 15. M4: implied team totals (the pricing primitive) ──────────────────────
pyblk "implied: spread/total → team totals; nflverse sign convention flip" <<'EOF'
import sys; sys.path.insert(0, "tools")
from implied import implied_totals, from_store_line
assert implied_totals(-3.5, 44.5) == (24.0, 20.5)     # home favored by 3.5
assert implied_totals(+3.0, 42.0) == (19.5, 22.5)     # home a 3-point dog
assert from_store_line(3.5) == -3.5                    # store: + = home favored
EOF

# ── 15b. M4: devig math (ported tool still computes the same numbers) ────────
DV=$(bash tools/devig.sh -120 +100 59 2>/dev/null)
echo "$DV" | grep -q "no-vig  52.2%" && echo "$DV" | grep -q "Edge +6.8pp" \
  && ok "devig.sh: -120/+100 → 52.2% no-vig, +6.8pp edge" \
  || no "devig.sh: -120/+100 → 52.2% no-vig, +6.8pp edge" "$DV"

# ── 15c. M4: truep NFL registry + custom cap ─────────────────────────────────
python3 tools/truep.py --list 2>/dev/null | grep -q "script_rush_fav" \
  && ok "truep.py: NFL registry loads" || no "truep.py: NFL registry loads"
if python3 tools/truep.py --base-prob 55 --custom "+5:too big" >/dev/null 2>&1; then
  no "truep.py: --custom ±3 cap enforced"
else ok "truep.py: --custom ±3 cap enforced"; fi
python3 tools/truep.py --base-prob 54.3 --adj wind_under 2>/dev/null \
  | grep -q "\[adj: wind_under+4\]" \
  && ok "truep.py: [adj:] ledger tag emitted" || no "truep.py: [adj:] ledger tag emitted"

# ── 15d. M4: corr engine — copula math + matrix semantics ────────────────────
pyblk "corr: bvn bounds/independence/comonotone; MC deterministic + consistent" <<'EOF'
import sys; sys.path.insert(0, "tools")
from corr import bvn_prob, joint_prob, build_R, pair_rho, blocked, load_matrix, load_blocklist
assert abs(bvn_prob(0.6, 0.55, 0.0) - 0.33) < 1e-6            # independence = product
assert abs(bvn_prob(0.6, 0.55, 0.999) - 0.55) < 0.01          # comonotone → min(p)
assert bvn_prob(0.6, 0.55, 0.45) > 0.33                       # positive ρ lifts joint
assert bvn_prob(0.6, 0.55, -0.45) < 0.33                      # negative ρ cuts it
lo = max(0.0, 0.6 + 0.55 - 1)
assert bvn_prob(0.6, 0.55, -0.999) >= lo - 1e-9               # Fréchet floor respected
# 3-leg MC: deterministic, between bounds, above independent product for +ρ
R = [[1, .4, .3], [.4, 1, .3], [.3, .3, 1]]
a = joint_prob([.6, .55, .5], R); b = joint_prob([.6, .55, .5], R)
assert a == b, "MC not deterministic"
assert .6 * .55 * .5 < a < .5, a
EOF

pyblk "corr: matrix lookup — same-team rows, orientation flips, unknown=None, blocklist" <<'EOF'
import sys; sys.path.insert(0, "tools")
from corr import pair_rho, blocked, load_matrix, load_blocklist
M, B = load_matrix(), load_blocklist()
qb  = {"p":.6, "game":"G1", "team":"BUF", "family":"qb_pass_yds_o"}
wr  = {"p":.55,"game":"G1", "team":"BUF", "family":"wr_rec_yds_o"}
wr2 = {"p":.5, "game":"G1", "team":"BUF", "family":"wr_rec_yds_o"}
oqb = {"p":.5, "game":"G1", "team":"HOU", "family":"qb_pass_yds_o"}
tu  = {"p":.5, "game":"G1", "team":None,  "family":"game_total_u"}
ml  = {"p":.6, "game":"G1", "team":"BUF", "family":"team_ml"}
oml = {"p":.4, "game":"G1", "team":"HOU", "family":"team_ml"}
x   = {"p":.6, "game":"G2", "team":"KC",  "family":"team_ml"}
unk = {"p":.5, "game":"G1", "team":"BUF", "family":"made_up_family"}
# These are MEASURED (corr_backtest.py --reseed, 2015-2025, n=736-2869), not guessed.
# Re-running --reseed may move them; update here WITH the new measurement, never by
# loosening the assertion.
assert pair_rho(qb, wr, M) == 0.44                    # same-team QB→WR (phi +0.293)
assert pair_rho(wr, wr2, M) == 0.02                   # same-team WRs: ~INDEPENDENT.
# The shipped seed said -0.15 ("they compete for one target pool"); measurement over
# n=736 says +0.010. The story was wrong, and it had been BLOCKING legal WR1+WR2 stacks.
assert pair_rho(qb, oqb, M) == 0.17                   # opposing QBs row (backtest)
assert pair_rho(qb, tu, M) == -0.33                   # orientation flip: yds_o × total_u
                                                      # (mirrors the re-seeded +0.33)
assert pair_rho(qb, x, M) == 0.0                      # different game = independent
assert pair_rho(qb, unk, M) is None                   # unknown same-game pair
assert blocked(ml, oml, B) is not None                # opposite MLs blocked
assert blocked(ml, wr, B) is None
EOF

# ── 15e. M4: ticket.py — blocked/negative/unknown rejected; stack priced ─────
pyblk "ticket.py: legality + copula stack pricing + band search (CLI, offline)" <<'EOF'
import subprocess
r = subprocess.run(["python3", "tools/ticket.py",
  "--leg", "60:-140:G1:BUF ML:team_ml:BUF",
  "--leg", "58:+105:G1:Allen O249.5:qb_pass_yds_o:BUF",
  "--leg", "45:+240:G1:HOU ML:team_ml:HOU",
  "--leg", "55:-110:G1:Shakir rec yds:wr_rec_yds_o:BUF",
  "--leg", "56:-105:G1:Coleman rec yds:wr_rec_yds_o:BUF",
  # TrueP must beat breakeven (+120 → 45.5%) or the leg is dropped as thin BEFORE the
  # correlation check ever sees it — which is how this test first failed.
  "--leg", "53:+120:G1:HOU team total O21.5:team_total_o:HOU",
  "--leg", "57:-110:G2:Total U44.5:game_total_u",
  "--leg", "52:-102:G1:Mystery:made_up_fam:BUF",
  ], capture_output=True, text=True, timeout=120)
out = r.stdout
assert "BLOCKED — opposite sides" in out, "opposing MLs not blocked"
# BUF ML x HOU team-total-over is measured -0.58 — a genuinely negative pair.
assert "negatively-correlated pair" in out, "negative ML x opposing-TT pair not rejected"
assert "unknown same-game correlation" in out, "unknown pair not rejected"
assert "joint" in out and "stack" in out, "no copula-priced stack in output"
assert "TARGET BAND" in out and "RECOMMENDED" in out, "band search missing"
assert "worth taking only if the quote beats" in out, "min-SGP quote missing"
EOF

# ── 15f. M4: parlay.py CLI-compat (tier joint via copula, deterministic) ─────
pyblk "parlay.py: moderate-tier pair sits between product and min(p)" <<'EOF'
import subprocess, re
r = subprocess.run(["python3", "tools/parlay.py", "--leg", "60:-130",
                    "--leg", "55:+110", "--corr", "moderate"],
                   capture_output=True, text=True, timeout=60)
m = re.search(r"true combined .*?:\s+([\d.]+)%", r.stdout)
assert m, r.stdout
v = float(m.group(1))
assert 33.0 < v < 55.0 and v > 33.1, v      # above the 33.0% naive product, below min(p)
EOF

# ── 15g. M4: corr matrix + blocklist CSVs parse and stay symmetric ───────────
pyblk "corr_matrix.csv / blocked_combos.csv: parse, ρ in range, families well-formed" <<'EOF'
import csv
fams = set()
for row in csv.DictReader(open("config/corr_matrix.csv")):
    rho = float(row["rho"]); assert -1 < rho < 1, row
    assert row["same_team"] in ("Y", "N", "any"), row
    fams |= {row["family_a"], row["family_b"]}
assert "qb_pass_yds_o" in fams and "team_ml" in fams
for row in csv.DictReader(open("config/blocked_combos.csv")):
    assert row["reason"].strip(), row
EOF

# ── 16. M5: leg_id codec + verdict math + cell surgery ───────────────────────
pyblk "legs.py: leg_id round-trip; verdict fns (margin/push/flag); set_cell surgical" <<'EOF'
import sys; sys.path.insert(0, "tools")
from legs import (format_leg_id, parse_leg_id, ou_verdict, spread_verdict,
                  flag_verdict, set_cell, is_leg_row, COL)
lid = format_leg_id(2026, 1, "2026_01_BUF_HOU", "player_pass_yds", "Over", 249.5, "00-0034857")
assert lid == "2026-W01:2026_01_BUF_HOU:player_pass_yds:Over:249.5:00-0034857"
p = parse_leg_id(lid)
assert p["season"] == 2026 and p["week"] == 1 and p["point"] == 249.5
assert p["gsis_id"] == "00-0034857" and p["market"] == "player_pass_yds"
h = parse_leg_id("2026-W01:2026_01_NE_SEA:h2h:SEA::")
assert h["point"] is None and h["gsis_id"] is None
sp = parse_leg_id(format_leg_id(2026, 1, "G", "spreads", "NE", 3.5))
assert sp["point"] == 3.5
assert parse_leg_id("**2026-W01:G:h2h:SEA::**") is not None    # markdown noise stripped
assert parse_leg_id("not a leg id") is None
assert ou_verdict("Over", 44.0, 44) == "Push"                  # integer push
assert ou_verdict("Under", 44.5, 44) == "W" and ou_verdict("Over", 44.5, 45) == "W"
assert spread_verdict(24, 20, -4.5) == "L"                     # won by 4, laid 4.5 — the margin rule
assert spread_verdict(24, 20, -3.5) == "W" and spread_verdict(20, 24, +4.5) == "W"
assert spread_verdict(24, 21, -3.0) == "Push"
assert flag_verdict("Yes", 2) == "W" and flag_verdict("Yes", 0) == "L" and flag_verdict("No", 0) == "W"
row = "| 2026-W01 | x | 2026-W01:G:h2h:SEA:: | ML | -190 | B | 64% | 64% | +0 | scan | TBD | N | — | S |"
assert is_leg_row(row)
out = set_cell(row, COL["result"], "**W** (SEA 24-20)")
assert "**W** (SEA 24-20)" in out and out.count("|") == row.count("|")
assert "TBD" not in out and "-190" in out                      # only the one cell changed
EOF

# ── 16b. M5: settle_leg on fixtures — every market family ────────────────────
pyblk "settle.py: game/prop/kicking/ATD/DNP/not-final verdicts from fixture rows" <<'EOF'
import sys; sys.path.insert(0, "tools")
from settle import settle_leg, team_total_verdict
game = {"game_id": "G", "home_team": "MIA", "away_team": "BUF",
        "home_score": 30, "away_score": 13}
live = dict(game, home_score=None, away_score=None)
stat = {"player_display_name": "Josh Fixture", "passing_yards": 306.0, "passing_tds": 2,
        "attempts": 41, "completions": 29, "passing_interceptions": 1, "carries": 9,
        "rushing_yards": 44.0, "rushing_tds": 1, "receptions": 0, "targets": 0,
        "receiving_yards": 0.0, "receiving_tds": 0, "fg_made": 3, "pat_made": 4}
L = lambda m, s, pt=None, g="00-1": {"season":2025,"week":10,"game_id":"G","market":m,
                                     "side":s,"point":pt,"gsis_id":g}
assert settle_leg(L("h2h","BUF"), game, None)[0] == "L"
assert settle_leg(L("h2h","MIA"), game, None)[0] == "W"
assert settle_leg(L("spreads","MIA",-16.5), game, None)[0] == "W"   # won by 17
assert settle_leg(L("spreads","MIA",-17.0), game, None)[0] == "Push"
assert settle_leg(L("totals","Over",43.5), game, None)[0] == "L"    # total 43
assert settle_leg(L("player_pass_yds","Over",249.5), game, stat)[0] == "W"
assert settle_leg(L("player_kicking_points","Over",12.5), game, stat)[0] == "W"  # 13
assert settle_leg(L("player_anytime_td","Yes"), game, stat)[0] == "W"
assert settle_leg(L("player_pass_yds","Over",249.5), game, None)[0] == "MANUAL"  # DNP
assert settle_leg(L("player_sacks","Over",0.5), game, stat)[0] == "MANUAL"       # C-tier
assert settle_leg(L("h2h","BUF"), live, None)[0] is None                          # not final
assert team_total_verdict(L("team_total","MIA_Over",20.5), game)[0] == "W"
assert team_total_verdict(L("team_total","BUF_Under",21.5), game)[0] == "W"
EOF

# ── 16c. M5: clv close math — side resolution, moved number, dead-band, edge-gone ─
pyblk "clv_capture: close_novig fixtures + verdict dead-band + EDGE GONE + stale gate" <<'EOF'
import sys; sys.path.insert(0, "tools")
from clv_capture import (close_novig, verdict_from_close, edge_warning,
                         cache_is_stale_for)
names = {"SEA": "Seattle Seahawks", "NE": "New England Patriots"}
ev = {"bookmakers": [
  {"title": "A", "markets": [
    {"key": "h2h", "outcomes": [
      {"name": "Seattle Seahawks", "price": -200},
      {"name": "New England Patriots", "price": 170}]},
    {"key": "totals", "outcomes": [
      {"name": "Over", "point": 43.5, "price": -110},
      {"name": "Under", "point": 43.5, "price": -110}]}]},
  {"title": "B", "markets": [
    {"key": "h2h", "outcomes": [
      {"name": "Seattle Seahawks", "price": -195},
      {"name": "New England Patriots", "price": 175}]}]}]}
got, err = close_novig(ev, "h2h", "SEA", None, names)
assert err is None and abs(got[0] - 0.6425) < 0.01              # best -195/+175 devig
got2, err2 = close_novig(ev, "totals", "Under", 44.0, names)
assert got2 is None and "NUMBER moved" in err2                   # 44.0 no longer quoted
got3, err3 = close_novig(ev, "totals", "Under", 43.5, names)
assert err3 is None and abs(got3[0] - 0.5) < 1e-6
assert verdict_from_close(55.0, 52.0).startswith("+")
assert verdict_from_close(52.3, 52.0).startswith("=")            # ±0.5pp dead-band
assert verdict_from_close(48.0, 52.0).startswith("−")
assert "EDGE GONE" in edge_warning(65.0, 64.0)
assert edge_warning(50.0, 60.0) is None
assert cache_is_stale_for("2026-09-10T01:00:00Z", "2026-09-10T00:15:00Z") is True
assert cache_is_stale_for("2026-09-09T12:00:00Z", "2026-09-10T00:15:00Z") is False
EOF

# ── 17. M6: calib parses the live ledger; BT rows excluded; result semantics ─
pyblk "calib: ledger parse + BT isolation + result/star semantics" <<'EOF'
import sys; sys.path.insert(0, "tools")
from calib import parse_result, parse_pct, parse_adj_tags, read_rows
assert parse_result("**W** (CHI 24-20)") == "W"
assert parse_result("**L** (JAX 29-36)") == "L"
assert parse_result("**Push** (44 on the nose)") == "Push"
assert parse_result("TBD") is None
assert parse_result("SUPERSEDED → see run 2 **W**") is None       # supersede veto
assert parse_result("would-W (declined)") == "W"
assert parse_pct("68%*") == (68.0, True)                          # starred legacy
assert parse_pct("**64.3%**") == (64.3, False)                    # bold ≠ star
assert parse_adj_tags("SEA ML [adj: none]") == []
assert parse_adj_tags("x [adj: wind_under+4, rest_edge+2]") == ["wind_under", "rest_edge"]
assert parse_adj_tags("no tag here") is None
live, bt, tickets, _orphans = read_rows(open("ledgers/results_log.md").read())
assert len(bt) == 7, f"expected 7 BT rows, got {len(bt)}"
assert all(r["bucket"] == "BT" for r in bt)
# Live rows GROW every build (the log-the-whole-scan doctrine), so assert structure,
# never a count — a fixed count here goes red on the first build that logs a scan.
assert len(live) >= 2, f"expected at least the seeded live rows, got {len(live)}"
assert all(r["bucket"] != "BT" for r in live)                      # BT never leaks into live
assert all(r["leg_id"] for r in live)                              # every live row is JOIN-able
assert len({r["leg_id"] for r in live}) == len(live), "duplicate leg_id in live rows"
assert sum(r["result"] == "W" for r in bt) == 5 and sum(r["result"] == "L" for r in bt) == 2
EOF

# ── 17b. M6: pulse governor actions fire on synthetic windows ────────────────
pyblk "pulse: COOL/SUSPEND/MARKET-SHADE/GLOBAL-SHRINK/RE-WARM on fixtures" <<'EOF'
import sys; sys.path.insert(0, "tools")
from pulse import actions_for, market_family, window_rows
def row(res, truep=65, clv="—", week="2026-W01", market="h2h", implp=None):
    return {"result": res, "truep": truep, "starred": False, "implp": implp,
            "week": week, "leg": "x [adj: none]",
            "leg_id": f"2026-W01:2026_01_NE_SEA:{market}:SEA::", "clv": clv}
assert market_family("2026-W01:G:player_pass_yds:Over:249.5:00-1") == "prop:pass_yds"
assert market_family("2026-W01:G:h2h:SEA::") == "ML"
# COOL: 1-4 (20%) vs claimed 65 → gap 45 ≥ 15, n=5
_, acts = actions_for([row("W")] + [row("L")] * 4)
assert any("COOL" in a[0] for a in acts), acts
# SUSPEND: 0-6 vs claimed 65
_, acts = actions_for([row("L")] * 6)
assert any("SUSPEND" in a[0] for a in acts), acts
# RE-WARM: 3 of last 5 won suppresses COOL/SUSPEND even after a cold start
rows = [row("L")] * 5 + [row("W"), row("W"), row("L"), row("W"), row("W")]
_, acts = actions_for(rows)
assert not any("SUSPEND" in a[0] or "COOL" in a[0] for a in acts), acts
# MARKET-SHADE: CLV 0+/4−
_, acts = actions_for([row("W", clv="− 60%cl"), row("W", clv="- 61%cl"),
                       row("L", clv="− 59%cl"), row("W", clv="− 62%cl")])
assert any("MARKET-SHADE" in a[0] for a in acts), acts
# GLOBAL SHRINK: TrueP consistently worse than market over n≥10
bad = [row("L", truep=70, implp=50) for _ in range(10)]
_, acts = actions_for(bad)
assert any("GLOBAL SHRINK" in a[0] for a in acts), acts
# window: last 3 distinct weeks only
rows = ([row("W", week="2026-W01")] * 6 + [row("L", week="2026-W02")] * 6
        + [row("W", week="2026-W03")] * 6 + [row("L", week="2026-W04")] * 6)
recent = window_rows(rows)
assert {r["week"] for r in recent} == {"2026-W02", "2026-W03", "2026-W04"}
EOF

# ── 18. M7: dashboard parser invariants + calib reconciliation ───────────────
if python3 tools/generate_dashboard.py --selftest >/dev/null 2>&1; then
  ok "generate_dashboard --selftest (parses ledgers, BT isolation, render sane)"
else
  no "generate_dashboard --selftest" "$(python3 tools/generate_dashboard.py --selftest 2>&1 | tail -8)"
fi

# ── 19. M8: cron run-type detection (data-driven) + prompt single-source ─────
pyblk "cron_build: detect lock/wrap/designation/build from fixture kickoffs + weekday" <<'EOF'
import os, subprocess, sys, tempfile, csv
td = tempfile.mkdtemp()
os.environ["NFL_DB"] = os.path.join(td, "t.db")
sys.path.insert(0, "tools")
import ingest
con = ingest.connect()
rows = list(csv.DictReader(open("tools/fixtures/games_fixture.csv")))
ingest.load_table(con, "games", iter(rows), list(rows[0].keys())); con.close()
env = dict(os.environ)
def det(now):
    return subprocess.run(["bash", "tools/cron_build.sh", "--detect-only", "--now", now],
                          capture_output=True, text=True, env=env, timeout=30).stdout.strip()
assert det("2026-09-09T23:00:00Z") == "lock",        det("2026-09-09T23:00:00Z")  # T-80m to the Wed opener
assert det("2026-09-08T14:00:00Z") == "wrap",        det("2026-09-08T14:00:00Z")  # Tuesday, nothing imminent
assert det("2026-09-04T14:00:00Z") == "designation", det("2026-09-04T14:00:00Z")  # Friday
assert det("2026-09-02T14:00:00Z") == "build",       det("2026-09-02T14:00:00Z")  # Wednesday, no games near
EOF
for t in wrap build designation lock; do
  if bash tools/cron_build.sh "$t" --prompt-only 2>/dev/null | grep -q "per CLAUDE.md"; then
    ok "cron_build.sh $t --prompt-only prints its prompt"
  else no "cron_build.sh $t --prompt-only prints its prompt"; fi
done
grep -q -- "--prompt-only" .claude/hooks/session-start.sh \
  && ok "hook delegates to cron_build --prompt-only (single prompt source)" \
  || no "hook delegates to cron_build --prompt-only"

# ── 19b. M8: clv_backfill pure planning (snapshot clustering + row selection) ─
pyblk "clv_backfill: window-clustered snapshots; only blank-CLV backfillable rows" <<'EOF'
import sys; sys.path.insert(0, "tools")
from clv_backfill import snapshot_ts, plan_rows
assert snapshot_ts("2026-09-13T17:00:00Z") == "2026-09-13T16:58:00Z"
games = {"G1": {"kickoff_utc": "2026-09-13T17:00:00Z"},
         "G2": {"kickoff_utc": "2026-09-13T17:00:00Z"},
         "G3": {"kickoff_utc": "2026-09-14T00:20:00Z"}}
mk = lambda gid, mkt, clv: (f"| 2026-W01 | x | 2026-W01:{gid}:{mkt}:SEA:: | ML | -110 "
                            f"| B | 60% | 58% | +2 | ok | TBD | N | {clv} | S |")
lines = [mk("G1", "h2h", "—"), mk("G2", "totals", "—"), mk("G3", "h2h", "—"),
         mk("G1", "player_pass_yds", "—"),     # prop → not backfillable
         mk("G2", "h2h", "+ 60%cl")]           # already filled → skip
rows = plan_rows(lines, 2026, 1, games)
assert len(rows) == 3, rows
stamps = {snapshot_ts(k) for _, _, k in rows}
assert len(stamps) == 2, stamps                # G1+G2 share one window snapshot
EOF

# ── 20. CLI contract ─────────────────────────────────────────────────────────
if bash tools/nfl_data.sh definitely-not-a-command >/dev/null 2>&1; then
  no "nfl_data.sh rejects unknown subcommand"
else ok "nfl_data.sh rejects unknown subcommand"; fi
if bash tools/nfl_data.sh --help 2>/dev/null | grep -q "sync \[dataset\]"; then
  ok "nfl_data.sh --help prints usage"
else no "nfl_data.sh --help prints usage"; fi
if python3 tools/ingest.py sync not-a-dataset >/dev/null 2>&1; then
  no "ingest.py sync rejects unknown dataset"
else ok "ingest.py sync rejects unknown dataset"; fi

# ── notify_slack.sh — webhook notifier degrades gracefully, payload is valid ─
OUT="$(env -u SLACK_WEBHOOK_URL bash tools/notify_slack.sh "test" 2>&1)"
if [[ $? -eq 0 && "$OUT" == *SKIP* ]]; then
  ok "notify_slack.sh SKIPs (exit 0) when SLACK_WEBHOOK_URL is unset"
else no "notify_slack.sh SKIPs (exit 0) when SLACK_WEBHOOK_URL is unset" "$OUT"; fi
DRY="$(bash tools/notify_slack.sh --dry-run 'line1
"quoted" & <chars>' 2>&1)"
if jq -e '.text | contains("quoted")' <<<"$DRY" >/dev/null 2>&1; then
  ok "notify_slack.sh --dry-run emits valid JSON with escaped content"
else no "notify_slack.sh --dry-run emits valid JSON with escaped content" "$DRY"; fi

# ── cron_build.sh is the SINGLE prompt source — a syntax break kills EVERY run.
# (2026-08-09: raw double quotes were once injected into the double-quoted COMMON
#  string, breaking the whole script. bash -n catches that class instantly.)
if bash -n tools/cron_build.sh 2>/dev/null; then
  ok "cron_build.sh parses (bash -n) — the prompt source is not broken"
else no "cron_build.sh parses (bash -n) — the prompt source is not broken" "$(bash -n tools/cron_build.sh 2>&1 | head -3)"; fi
MISSING=""
for RT in wrap build designation lock; do
  P="$(bash tools/cron_build.sh "$RT" --prompt-only 2>/dev/null)"
  [[ "$P" == *mcp__Gmail__create_draft* ]] || MISSING="$MISSING $RT:email"
  [[ "$P" == *notify_slack.sh* ]] || MISSING="$MISSING $RT:slack"
  [[ "$P" == *realityremixed125@gmail.com* ]] || MISSING="$MISSING $RT:to"
done
if [[ -z "$MISSING" ]]; then
  ok "every run type (wrap/build/designation/lock) carries the Gmail draft + Slack"
else no "every run type (wrap/build/designation/lock) carries the Gmail draft + Slack" "missing:$MISSING"; fi

# ── settle.py vs REAL 2025 W18 finals — 29 hand-computed verdicts ────────────
# Settlement is what money depends on and had never run against completed games.
# Expected verdicts are literals derived from the published box scores, so this
# catches a WRONG settle, not merely an inconsistent one. Store-gated: SKIPs on a
# pre-sync environment instead of failing. Uses a temp ledger (NFL_LEDGER).
SV="$(python3 tools/validate_settle.py --quiet 2>&1)"
if [[ "$SV" == SKIP:* ]]; then
  ok "settle.py verdicts vs real 2025 W18 finals — SKIPPED (store not synced)"
elif [[ "$SV" == *"29/29 correct"* ]]; then
  ok "settle.py settles all 29 real 2025 W18 cases correctly (margin/push/prop/MANUAL)"
else no "settle.py settles all 29 real 2025 W18 cases correctly (margin/push/prop/MANUAL)" "$SV"; fi

# ── calib.py parser guard — orphaned rows must SCREAM, not read as zero ──────
# A renamed "## " section silently drops every row and calibration reports 0 without
# complaint. Feed it a ledger whose header was renamed and assert the guard fires.
GUARD_TMP="$(mktemp -d)"
{ echo "# ledger"; echo; echo "## (header renamed by a reformat)"; echo;
  grep -E "^\| (Week|-|2026-W)" ledgers/results_log.md | head -20; } > "$GUARD_TMP/led.md"
GOUT="$(NFL_LEDGER="$GUARD_TMP/led.md" python3 tools/calib.py 2>&1 | head -6)"
if [[ "$GOUT" == *"PARSER GUARD"* ]]; then
  ok "calib.py parser guard flags leg rows orphaned outside a '## ' section"
else no "calib.py parser guard flags leg rows orphaned outside a '## ' section" "$GOUT"; fi
CLEAN="$(python3 tools/calib.py 2>&1 | head -6)"
if [[ "$CLEAN" != *"PARSER GUARD"* ]]; then
  ok "calib.py parser guard stays silent on the healthy live ledger"
else no "calib.py parser guard stays silent on the healthy live ledger" "$CLEAN"; fi
rm -rf "$GUARD_TMP"

# ── CLV verdict engine — pinned against REAL 2025 W18 closes (0 credits) ────
# The 2026-01-04 17:58Z historical snapshot (30 cr, spent once) returned these actual
# closing prices; the devig + sign + dead-band are re-derived here offline forever.
# clv_backfill.py imports verdict_from_close/close_novig FROM clv_capture.py, so this
# pins the LIVE capture path too, not a parallel copy.
pyblk "clv verdict engine: real 2025 W18 closes → correct +/−/= and dead band" <<'EOF'
import sys; sys.path.insert(0, "tools")
from clv_capture import verdict_from_close

def sign(closing, logged):          # cell is "+ 66%cl" — the verdict is its first char
    return verdict_from_close(closing, logged).split()[0]

# ATL closed -198 vs NO +189 → no-vig ATL 65.76% / NO 34.24% (hand-devigged).
assert sign(65.76, 55.0) == "+", "line moved TO our side must read +"
assert sign(34.24, 45.0) == "−", "line moved AWAY must read −"
# the cell also carries the rounded closing prob, which the dashboard renders
assert verdict_from_close(65.76, 55.0) == "+ 66%cl", verdict_from_close(65.76, 55.0)
# dead band: |Δ| ≤ 0.5pp is a wash, just past it is not
assert sign(55.4, 55.0) == "=", "+0.4pp inside the dead band"
assert sign(54.6, 55.0) == "=", "-0.4pp inside the dead band"
assert sign(55.6, 55.0) == "+", "+0.6pp clears the dead band"
assert sign(54.4, 55.0) == "−", "-0.6pp clears the dead band"
# the other real closes from that same snapshot
for close, logged in ((79.1, 50.0), (81.4, 60.0), (85.0, 66.0), (84.3, 40.0)):
    assert sign(close, logged) == "+", (close, logged)
# missing inputs never fabricate a verdict
assert verdict_from_close(None, 55.0) is None and verdict_from_close(65.0, None) is None
EOF

# ── M9: Stake column, played reconcile, run health ──────────────────────────
pyblk "legs.cell()/parse_stake: legacy rows without a Stake cell still parse" <<'EOF'
import sys; sys.path.insert(0, "tools")
from legs import cell, is_leg_row, parse_stake, split_row
new = "| 2026-W01 | x | 2026-W01:2026_01_NE_SEA:h2h:SEA:: | ML | -190 | B | 64.3% | 64.3% | +0.0 | scan | TBD | Y | = | S | 25 |"
old = "| 2026-W01 | x | 2026-W01:2026_01_NE_SEA:h2h:SEA:: | ML | -190 | B | 64.3% | 64.3% | +0.0 | scan | TBD | N | = | S |"
assert is_leg_row(new) and is_leg_row(old), "BOTH shapes must parse — requiring Stake would silently drop legacy rows"
assert cell(split_row(new), "stake") == "25" and parse_stake(split_row(new)) == 25.0
assert cell(split_row(old), "stake") == "" and parse_stake(split_row(old)) is None
assert cell(split_row(new), "bucket") == "S", "adding Stake must not shift earlier indexes"
for raw, want in (("$25", 25.0), ("2u", 2.0), ("", None), ("—", None), ("abc", None)):
    row = new.replace("| 25 |", f"| {raw} |")
    assert parse_stake(split_row(row)) == want, (raw, want)
EOF

pyblk "reconcile_played: parses bets, rejects bad leg_id / dupes / non-numeric stakes" <<'EOF'
import sys; sys.path.insert(0, "tools")
from reconcile_played import parse_played
good = """## Bets
2026-W01:2026_01_NE_SEA:h2h:SEA:: | 25
2026-W01:2026_01_NE_SEA:totals:Under:44.5: | $10   # comment ignored
"""
e, err = parse_played(good)
assert not err and len(e) == 2 and e[0][1] == 25.0 and e[1][1] == 10.0, (e, err)
# lines OUTSIDE '## Bets' must be ignored (the file's own docs contain examples)
assert parse_played("2026-W01:2026_01_NE_SEA:h2h:SEA:: | 25")[0] == []
for bad in ("## Bets\nnot-a-leg-id | 25\n",
            "## Bets\n2026-W01:2026_01_NE_SEA:h2h:SEA:: | abc\n",
            "## Bets\n2026-W01:2026_01_NE_SEA:h2h:SEA:: | -5\n",
            "## Bets\n2026-W01:2026_01_NE_SEA:h2h:SEA:: | 5\n2026-W01:2026_01_NE_SEA:h2h:SEA:: | 7\n"):
    assert parse_played(bad)[1], f"must ERROR, not silently skip: {bad!r}"
EOF

pyblk "run_health: records, validates channels, survives a corrupt line" <<'EOF'
import os, subprocess, sys, tempfile
sys.path.insert(0, "tools")
d = tempfile.mkdtemp(); hp = os.path.join(d, "h.jsonl")
env = dict(os.environ, NFL_HEALTH=hp)
r = subprocess.run([sys.executable, "tools/run_health.py", "record", "--run-type", "build",
                    "--selftest", "84/84", "--fold", "abc1234", "--email", "ok",
                    "--slack", "SKIP", "--push", "ok", "--credits", "19392"],
                   capture_output=True, text=True, env=env)
assert r.returncode == 0 and "slack=SKIP" in r.stdout, r.stdout + r.stderr
bad = subprocess.run([sys.executable, "tools/run_health.py", "record", "--slack", "maybe"],
                     capture_output=True, text=True, env=env)
assert bad.returncode != 0, "an invalid channel value must fail loudly"
open(hp, "a").write("{ not json\n")          # a corrupt line must not blind the record
import run_health
run_health.HEALTH = hp
rows = run_health.load()
assert len(rows) == 1 and rows[0]["selftest_green"] is True and rows[0]["slack"] == "SKIP"
EOF

pyblk "calib §3b: real-stake ROI arithmetic (W pays the price, L loses stake, Push flat)" <<'EOF'
import subprocess, sys, tempfile, os
hdr = ("## Played legs\n\n| Week | Leg | leg_id | Type | Price | Book | TrueP | ImplP "
       "| Edge | Grade | Result | Played | CLV | Bucket | Stake |\n"
       "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
def row(gid, price, res, stake):
    return (f"| 2025-W18 | x | 2025-W18:{gid}:h2h:ATL:: | ML | {price} | B | 50.0% "
            f"| 50.0% | +0.0 | g | **{res}** | Y | = | S | {stake} |\n")
# +100 win on 10 → +10 ; -200 loss of 20 → -20 ; push on 50 → 0. Staked 80, P/L -10.
led = hdr + row("g1", "+100", "W", 10) + row("g2", "-200", "L", 20) + row("g3", "-110", "Push", 50)
f = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False); f.write(led); f.close()
out = subprocess.run([sys.executable, "tools/calib.py"], capture_output=True, text=True,
                     env=dict(os.environ, NFL_LEDGER=f.name)).stdout
os.unlink(f.name)
line = [l for l in out.split("\n") if "staked" in l and "ROI" in l and "legs" in l]
assert line, out
assert "staked 80.00" in line[0] and "P/L -10.00" in line[0] and "-12.5%" in line[0], line[0]
EOF

pyblk "dashboard: health strip / pipeline / week board / timeline all render" <<'EOF'
import sys; sys.path.insert(0, "tools")
import generate_dashboard as gd
page = gd.render()
for needle in ("Run health", "Pipeline", "This week's board", "Run timeline"):
    assert needle in page, needle
# an empty health record must degrade to a note, never crash the page
assert "no runs recorded yet" in gd.health_strip([])
assert "none yet" in gd.health_timeline([])
EOF

# ── ported-from-MLB dashboard panels: correct math + graceful empty ─────────
pyblk "dashboard ports: edge buckets / type split / P-L curve / CLV-vs-result" <<'EOF'
import sys; sys.path.insert(0, "tools")
import generate_dashboard as gd

def leg(**k):
    d = dict(section="P", week="2025-W18", leg="x", leg_id="i", type="ML", price="-110",
             stake=None, truep=50.0, starred=False, implp=50.0, result=None,
             played=True, clv="", bucket="S", edge=None)
    d.update(k); return d

# edge buckets bin on the EDGE column and only count decided legs
b = {x["label"]: x for x in gd.edge_buckets([
    leg(edge=-1.0, result="L"), leg(edge=1.0, result="W"), leg(edge=3.0, result="W"),
    leg(edge=3.5, result="L"), leg(edge=7.0, result="W"), leg(edge=5.0, result=None)])}
assert b["< 0pp"]["n"] == 1 and b["< 0pp"]["hit"] == 0
assert b["0–2pp"]["n"] == 1 and b["0–2pp"]["hit"] == 100
assert b["2–4pp"]["n"] == 2 and b["2–4pp"]["hit"] == 50
assert b["4–6pp"]["n"] == 0 and b["4–6pp"]["hit"] is None, "undecided legs must not count"
assert b["6pp+"]["n"] == 1

# type breakdown separates Push from W/L
t = {x["type"]: x for x in gd.type_breakdown([
    leg(type="ML", result="W"), leg(type="ML", result="L"), leg(type="TOT", result="Push")])}
assert t["ML"]["w"] == 1 and t["ML"]["l"] == 1 and t["ML"]["hit"] == 50
assert t["TOT"]["p"] == 1 and t["TOT"]["hit"] is None

# P/L curve: +100 win on 10 -> +10 ; -200 loss of 20 -> -10 ; Push flat
c = gd.pl_curve([leg(price="+100", stake=10, result="W", leg_id="a"),
                 leg(price="-200", stake=20, result="L", leg_id="b"),
                 leg(price="-110", stake=50, result="Push", leg_id="c")])
assert c["vals"] == [10.0, -10.0, -10.0], c["vals"]
# an UNSTAKED leg must never enter the curve (no imputed flat 1u)
assert gd.pl_curve([leg(price="+100", stake=None, result="W")])["vals"] == []

# CLV vs result
v = {x["k"]: x for x in gd.clv_vs_result([
    leg(clv="+ 66%cl", result="W"), leg(clv="+ 70%cl", result="L"),
    leg(clv="− 30%cl", result="L"), leg(clv="= 50%cl", result="W")])}
assert v["+"]["w"] == 1 and v["+"]["l"] == 1 and v["+"]["hit"] == 50
assert v["-"]["l"] == 1 and v["="]["w"] == 1

# every panel degrades to prose on empty input rather than crashing
for fn in (gd.edge_buckets, gd.type_breakdown, gd.pl_curve, gd.clv_vs_result):
    fn([])
assert "no decided legs" in gd._table(["a"], [], "no decided legs yet")
EOF

# ── streaks + the $10 ladder STOP rule ──────────────────────────────────────
pyblk "streaks: current/longest runs; ladder computes the 4-win STOP trigger" <<'EOF'
import sys; sys.path.insert(0, "tools")
import generate_dashboard as gd

def leg(res, i):
    return dict(section="P", week="2026-W01", leg="x", leg_id=f"{i:03}", type="ML",
                price="-110", stake=None, truep=50.0, starred=False, implp=50.0,
                result=res, played=True, clv="", bucket="S", edge=None)

# W W L W W W  → current +3, longest W 3, longest L 1
s = gd.streaks([leg(r, i) for i, r in enumerate("WWLWWW")])
assert (s["current"], s["best_w"], s["best_l"], s["last"]) == (3, 3, 1, "W"), s
# trailing losses report a NEGATIVE current
s2 = gd.streaks([leg(r, i) for i, r in enumerate("WWLL")])
assert s2["current"] == -2 and s2["best_w"] == 2, s2
# Push must not break a run (it is not a loss)
s3 = gd.streaks([leg(r, i) for i, r in enumerate(["W", "Push", "W"])])
assert s3["current"] == 2, s3
assert gd.streaks([])["last"] is None                       # empty degrades, no crash

# ladder: rows are | Attempt | Week | Roll | before | bet | TrueP | Result | after | note |
def roll(att, n, res, after):
    return [str(att), "2026-W0%d" % n, str(n), "10", "x", "60%", res, str(after), ""]
ld = gd.ladder_state([roll(1, 1, "W", 18), roll(1, 2, "W", 33)])
assert ld["wins"] == 2 and ld["balance"] == 33.0 and not ld["stop"], ld
# FOUR consecutive wins must raise the STOP flag — this is doctrine, not decoration
ld4 = gd.ladder_state([roll(1, i, "W", 10 * (i + 1)) for i in range(1, 5)])
assert ld4["wins"] == 4 and ld4["stop"] is True, ld4
# a loss resets the count inside the attempt
ldl = gd.ladder_state([roll(2, 1, "W", 18), roll(2, 2, "L", 0), roll(2, 3, "W", 19)])
assert ldl["wins"] == 1 and not ldl["stop"], ldl
# only the CURRENT attempt counts — a finished 4-win attempt must not stick
ldp = gd.ladder_state([roll(1, i, "W", 20) for i in range(1, 5)] + [roll(2, 5, "W", 18)])
assert ldp["attempt"] == "2" and ldp["wins"] == 1 and not ldp["stop"], ldp
assert gd.ladder_state([])["balance"] == 10.0
EOF

# ── shell lint: an unescaped $<digit> in an EXPANDED double-quoted string ───
# session_start.sh once printed a header containing "$10"; bash expanded it as $1
# followed by "0" and `set -u` aborted the whole digest at runtime. bash -n cannot see
# this (it is valid syntax). The check must skip QUOTED heredoc bodies (<<'EOF'), whose
# contents bash never expands — a naive grep flags those and is worse than no lint.
pyblk "no unescaped \$NN currency in expanded double-quoted shell strings (\$10 trap)" <<'PYEOF_LINT'
import glob, re, sys
bad = []
for path in sorted(glob.glob("tools/*.sh")):
    delim = None
    for n, line in enumerate(open(path, encoding="utf-8"), 1):
        if delim is not None:                       # inside a heredoc body
            if line.strip() == delim:
                delim = None
            continue
        m = re.search(r"<<-?\s*'([A-Za-z_][A-Za-z0-9_]*)'", line)
        if m:                                       # QUOTED heredoc → bash won't expand
            delim = m.group(1)
            continue
        code = line.split("#", 1)[0] if not line.lstrip().startswith("#") else ""
        for lit in re.findall(r'"((?:[^"\\]|\\.)*)"', code):
            # TWO+ digits only: bash cannot read $10 as a positional parameter (that
            # needs ${10}), so it is currency ~always. Bare $1-$9 are legitimate params.
            if re.search(r"(?<!\\)\$[0-9]{2,}", lit):
                bad.append(f"{path}:{n}: {lit[:70]}")
assert not bad, "unescaped $<digit> in an expanded string:\n  " + "\n  ".join(bad)
PYEOF_LINT

# ── pulse: MARKET-SHADE must fire on CLV ALONE (governor live from Week 1) ──
pyblk "pulse: CLV-only window fires MARKET-SHADE with ZERO decided legs" <<'EOF'
import os, subprocess, sys, tempfile
hdr = ("## Recommended but NOT played\n\n| Week | Leg | leg_id | Type | Price | Book "
       "| TrueP | ImplP | Edge | Grade | Result | Played | CLV | Bucket | Stake |\n"
       "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
def row(i, clv, result="TBD"):
    return (f"| 2026-W01 | leg{i} [adj: none] | 2026-W01:2026_01_NE_SEA:h2h:T{i}:: | ML "
            f"| -110 | B | 60.0% | 55.0% | +5.0 | scan | {result} | N | {clv} | S |  |\n")
def run(body):
    f = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    f.write(hdr + body); f.close()
    out = subprocess.run([sys.executable, "tools/pulse.py"], capture_output=True,
                         text=True, env=dict(os.environ, NFL_LEDGER=f.name)).stdout
    os.unlink(f.name); return out

# 6 UNDECIDED legs, all negative CLV → the shade must fire anyway
out = run("".join(row(i, "− 5%cl") for i in range(6)))
assert "MARKET-SHADE" in out, "CLV-only shade did not fire:\n" + out
assert "0 decided legs" in out, out
# positive CLV must NOT trigger a shade
out2 = run("".join(row(i, "+ 5%cl") for i in range(6)))
assert "MARKET-SHADE" not in out2, "shade fired on POSITIVE CLV:\n" + out2
# hit-rate rules still need decisions — they must not fire (or divide by zero) here
assert "COOL" not in out and "SUSPEND" not in out, out
EOF

# ── correlation matrix: measured coverage + the re-seeded values in use ─────
pyblk "corr matrix: measured coverage, re-seeded signs, coverage panel" <<'EOF'
import csv, sys
sys.path.insert(0, "tools")
import generate_dashboard as gd
from corr import load_matrix, pair_rho

rows = list(csv.DictReader(open("config/corr_matrix.csv")))
meas = [r for r in rows if (r["basis"] or "").startswith("backtest")]
assert len(meas) >= 19, f"expected >=19 measured rows, got {len(meas)}"
for r in rows:                       # every rho stays a legal correlation
    assert -1.0 <= float(r["rho"]) <= 1.0, r

# the two SIGN CORRECTIONS the 2015-2025 measurement forced — pin them so a careless
# re-seed or hand-edit cannot quietly restore the wrong structural story.
M = load_matrix()
wr = {"p": .5, "game": "G", "team": "BUF", "family": "wr_rec_yds_o"}
wr2 = {"p": .5, "game": "G", "team": "BUF", "family": "wr_rec_yds_o"}
assert pair_rho(wr, wr2, M) >= 0, "same-team WRs measured ~independent (+0.02), not -0.15"
rb = {"p": .5, "game": "G", "team": "BUF", "family": "rb_rush_yds_o"}
tu = {"p": .5, "game": "G", "team": None, "family": "game_total_u"}
assert pair_rho(rb, tu, M) <= 0.05, "rb rush yds x game total UNDER measured ~0, not +0.15"

cov, tally = gd.corr_coverage()
assert tally["measured"] >= 19 and len(cov) == len(rows)
# the only rows allowed to remain guesses are ones that are BLOCKED anyway
guessed = [(r["a"], r["b"]) for r in cov if not r["meas"]]
assert all(a == b for a, b in guessed), f"unmeasured non-blocked pair: {guessed}"
EOF

# ── summary ──────────────────────────────────────────────────────────────────
echo "────────────────────────────────────"
if [[ "$FAIL" -eq 0 ]]; then
  echo "✓ ALL $PASS CHECKS PASSED"
else
  echo "⛔ SELFTEST FAILED — $FAIL of $((PASS+FAIL)) checks failed. Fix before trusting any tool."
  exit 1
fi
