#!/usr/bin/env python3
"""ingest.py — nflverse release assets → data/context.db (SQLite, stdlib only).

WHY THIS EXISTS
    The MLB app's context layer was on-demand REST (statsapi.mlb.com). NFL has no such API:
    nflverse publishes datasets as GitHub *release assets* (csv/csv.gz per season). This is
    the pre-computed store the port plan mandates (PORT_PLAN decision (a)): download the
    csv.gz variants (this stack has no pyarrow — verified), normalize into SQLite, and join
    facts across sources BY ID (gsis ↔ pfr ↔ espn via the players table) — the thing the MLB
    app's regex-over-markdown approach demonstrably couldn't do safely.

DESIGN RULES (ported doctrine)
    • Idempotent sync: each dataset is stamped (source Last-Modified + Content-Length) into
      data/ingest_manifest.json (COMMITTED — the provenance/audit record). Unchanged source
      ⇒ skip, 0 downloads. --force overrides.
    • Absence ≠ error: current-season assets (stats/snaps) don't exist until games are
      played — a 404 on an optional season is recorded ABSENT and reported calmly.
    • Missing columns are FLAGGED, not silently dropped: each table declares WANTED columns;
      any not found in the source header land in the manifest + status output (this is how
      the "kicking fields present?" class of assumption stays visible).
    • Staleness is first-class: `status` prints per-dataset age; consumers cite it.
    • READ-ONLY query surface: `sql` opens the DB in ro mode.

USAGE (normally via tools/nfl_data.sh)
    ingest.py sync [dataset] [--force]      ingest.py volume <team> <season> <week>
    ingest.py status                        ingest.py form <team> [n]
    ingest.py slate <season> <week>         ingest.py player "<name>"
    ingest.py finals <season> <week>        ingest.py depth <team>
    ingest.py sql "SELECT …"
"""
import csv
import gzip
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DB = os.environ.get("NFL_DB", os.path.join(REPO, "data", "context.db"))
MANIFEST = os.environ.get("NFL_MANIFEST", os.path.join(REPO, "data", "ingest_manifest.json"))
CACHE = os.path.join(REPO, "data", ".cache")
BASE = "https://github.com/nflverse/nflverse-data/releases/download"
ET = ZoneInfo("America/New_York")

# History window: two full prior seasons (backtest + form) + the current season.
def current_season(today=None):
    """NFL season label: March–December belong to that year's season; Jan/Feb to prior."""
    d = today or datetime.now(timezone.utc)
    return d.year if d.month >= 3 else d.year - 1


HISTORY_SEASONS = 2


def season_list(today=None):
    cur = current_season(today)
    return list(range(cur - HISTORY_SEASONS, cur + 1))


# ── dataset registry ──────────────────────────────────────────────────────────
# url may contain {season}. optional=True → 404 is ABSENT (info), not an error.
DATASETS = {
    "schedules":      {"url": "schedules/games.csv", "per_season": False, "table": "games"},
    "teams":          {"url": "teams/teams_colors_logos.csv", "per_season": False, "table": "teams"},
    "players":        {"url": "players/players.csv.gz", "per_season": False, "table": "players"},
    "stats_player":   {"url": "stats_player/stats_player_week_{season}.csv.gz",
                       "per_season": True, "table": "player_week", "optional": True},
    "snap_counts":    {"url": "snap_counts/snap_counts_{season}.csv.gz",
                       "per_season": True, "table": "snaps", "optional": True},
    # current season only: pre-2025 files use the old week-based schema, and the
    # table's contract is "latest snapshot per team" — history adds nothing here.
    "depth_charts":   {"url": "depth_charts/depth_charts_{season}.csv.gz",
                       "per_season": True, "table": "depth", "optional": True,
                       "current_only": True},
    "weekly_rosters": {"url": "weekly_rosters/roster_weekly_{season}.csv.gz",
                       "per_season": True, "table": "rosters", "optional": True},
}

# ── wanted columns per table: (source_col, sqlite_type) ───────────────────────
# A wanted column missing from the source header is recorded in the manifest and
# shown by `status` — assumptions about upstream schemas stay visible, never silent.
WANTED = {
    "games": [
        ("game_id", "TEXT"), ("season", "INT"), ("game_type", "TEXT"), ("week", "INT"),
        ("gameday", "TEXT"), ("weekday", "TEXT"), ("gametime", "TEXT"),
        ("away_team", "TEXT"), ("away_score", "INT"), ("home_team", "TEXT"),
        ("home_score", "INT"), ("location", "TEXT"), ("result", "INT"), ("total", "INT"),
        ("overtime", "INT"), ("gsis", "TEXT"), ("pfr", "TEXT"), ("espn", "TEXT"),
        ("ftn", "TEXT"), ("away_rest", "INT"), ("home_rest", "INT"),
        ("away_moneyline", "INT"), ("home_moneyline", "INT"), ("spread_line", "REAL"),
        ("total_line", "REAL"), ("div_game", "INT"), ("roof", "TEXT"), ("surface", "TEXT"),
        ("temp", "INT"), ("wind", "INT"), ("away_qb_id", "TEXT"), ("home_qb_id", "TEXT"),
        ("away_qb_name", "TEXT"), ("home_qb_name", "TEXT"), ("referee", "TEXT"),
        ("stadium_id", "TEXT"), ("stadium", "TEXT"),
    ],
    "teams": [
        ("team_abbr", "TEXT"), ("team_name", "TEXT"), ("team_id", "TEXT"),
        ("team_nick", "TEXT"), ("team_conf", "TEXT"), ("team_division", "TEXT"),
    ],
    "players": [
        ("gsis_id", "TEXT"), ("display_name", "TEXT"), ("football_name", "TEXT"),
        ("position", "TEXT"), ("position_group", "TEXT"), ("latest_team", "TEXT"),
        ("status", "TEXT"), ("espn_id", "TEXT"), ("pfr_id", "TEXT"), ("esb_id", "TEXT"),
        ("rookie_season", "INT"), ("last_season", "INT"),
    ],
    "player_week": [
        ("player_id", "TEXT"), ("player_display_name", "TEXT"), ("position", "TEXT"),
        ("position_group", "TEXT"), ("season", "INT"), ("week", "INT"),
        ("season_type", "TEXT"), ("game_id", "TEXT"), ("team", "TEXT"),
        ("opponent_team", "TEXT"),
        # passing
        ("completions", "INT"), ("attempts", "INT"), ("passing_yards", "REAL"),
        ("passing_tds", "INT"), ("passing_interceptions", "INT"), ("sacks_suffered", "INT"),
        # rushing
        ("carries", "INT"), ("rushing_yards", "REAL"), ("rushing_tds", "INT"),
        # receiving
        ("receptions", "INT"), ("targets", "INT"), ("receiving_yards", "REAL"),
        ("receiving_tds", "INT"), ("target_share", "REAL"), ("air_yards_share", "REAL"),
        # defense (C-tier props settle MANUAL, but the fields inform matchup work)
        ("def_sacks", "REAL"), ("def_interceptions", "REAL"), ("def_tackles_solo", "INT"),
        ("def_tackle_assists", "INT"),
        # kicking (presence VERIFIED 2026-08-08 — kicker props settle from here)
        ("fg_made", "INT"), ("fg_att", "INT"), ("fg_missed", "INT"), ("fg_long", "INT"),
        ("pat_made", "INT"), ("pat_att", "INT"),
    ],
    "snaps": [
        ("game_id", "TEXT"), ("pfr_game_id", "TEXT"), ("season", "INT"),
        ("game_type", "TEXT"), ("week", "INT"), ("player", "TEXT"),
        ("pfr_player_id", "TEXT"), ("position", "TEXT"), ("team", "TEXT"),
        ("opponent", "TEXT"), ("offense_snaps", "INT"), ("offense_pct", "REAL"),
        ("defense_snaps", "INT"), ("defense_pct", "REAL"),
        ("st_snaps", "INT"), ("st_pct", "REAL"),
    ],
    "depth": [
        ("dt", "TEXT"), ("team", "TEXT"), ("player_name", "TEXT"), ("espn_id", "TEXT"),
        ("gsis_id", "TEXT"), ("pos_grp", "TEXT"), ("pos_name", "TEXT"), ("pos_abb", "TEXT"),
        ("pos_slot", "INT"), ("pos_rank", "INT"),
    ],
    "rosters": [
        ("season", "INT"), ("week", "INT"), ("game_type", "TEXT"), ("team", "TEXT"),
        ("position", "TEXT"), ("depth_chart_position", "TEXT"), ("status", "TEXT"),
        ("status_description_abbr", "TEXT"), ("full_name", "TEXT"), ("gsis_id", "TEXT"),
        ("pfr_id", "TEXT"), ("espn_id", "TEXT"),
    ],
}

KEYS = {  # PRIMARY KEY column lists (INSERT OR REPLACE semantics)
    "games": ["game_id"],
    "teams": ["team_abbr"],
    "players": ["gsis_id"],
    "player_week": ["season", "week", "player_id"],
    "snaps": ["game_id", "pfr_player_id"],
    "depth": [],          # snapshot rows; latest-only filter applied at load
    "rosters": ["season", "week", "gsis_id"],
}

# games gains two computed columns (see load note below)
COMPUTED = {"games": [("kickoff_et", "TEXT"), ("kickoff_utc", "TEXT")]}


# ── small pure helpers (selftest-covered) ─────────────────────────────────────

def coerce(val, typ):
    """'' → None; INT/REAL parsed leniently ('20.0' → 20 for INT); TEXT passthrough."""
    if val is None or val == "" or val == "NA":
        return None
    if typ == "INT":
        try:
            return int(float(val))
        except ValueError:
            return None
    if typ == "REAL":
        try:
            return float(val)
        except ValueError:
            return None
    return val


def kickoff_iso(gameday, gametime):
    """('2026-09-09','20:20') ET → ('2026-09-09 20:20 ET','2026-09-10T00:20:00Z').
    nflverse gametime is Eastern. Missing time → (gameday, None)."""
    if not gameday:
        return None, None
    if not gametime:
        return f"{gameday} ??:?? ET", None
    try:
        dt = datetime.strptime(f"{gameday} {gametime}", "%Y-%m-%d %H:%M").replace(tzinfo=ET)
    except ValueError:
        return f"{gameday} {gametime} ET", None
    return (f"{gameday} {gametime} ET",
            dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))


def latest_depth_rows(rows):
    """Keep only each team's LATEST snapshot (max dt per team) from timestamped
    depth-chart rows (2025+ format: one full chart per team per dt; a season file
    holds hundreds of snapshots — 413K rows → ~3K)."""
    latest = {}
    for r in rows:
        t, dt = r.get("team"), r.get("dt")
        if t and dt and (t not in latest or dt > latest[t]):
            latest[t] = dt
    return [r for r in rows if r.get("dt") == latest.get(r.get("team"))]


def share(part, total):
    return round(part / total, 3) if total else None


def source_unchanged(entry, length, last_modified):
    """Manifest skip rule: same Content-Length + Last-Modified ⇒ source unchanged."""
    return (bool(entry) and entry.get("source_length") == length
            and entry.get("source_last_modified") == last_modified
            and entry.get("rows", 0) > 0)


# ── HTTP via curl (the repo's proven transport; stdlib urllib would need CA fiddling) ──

def curl_head(url):
    """(http_code, content_length, last_modified) following redirects."""
    try:
        out = subprocess.run(
            ["curl", "-sIL", "-m", "40", url], capture_output=True, text=True, timeout=50
        ).stdout
    except Exception:  # noqa: BLE001
        return "000", None, None
    codes = re.findall(r"^HTTP/[\d.]+\s+(\d+)", out, re.M)
    code = codes[-1] if codes else "000"
    blocks = out.split("\r\n\r\n")
    final = blocks[-2] if len(blocks) > 1 and not blocks[-1].strip() else blocks[-1]
    lm = re.search(r"^last-modified:\s*(.+?)\r?$", final, re.M | re.I)
    cl = re.search(r"^content-length:\s*(\d+)", final, re.M | re.I)
    return code, (cl.group(1) if cl else None), (lm.group(1).strip() if lm else None)


def curl_get(url, dest):
    r = subprocess.run(["curl", "-sSL", "--fail", "-m", "300", "-o", dest, url],
                       capture_output=True, text=True, timeout=320)
    if r.returncode != 0:
        raise RuntimeError(f"download failed ({r.returncode}): {r.stderr.strip()[:200]}")


def read_csv_rows(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt", encoding="utf-8", newline="") as fh:
        yield from csv.DictReader(fh)


# ── DB plumbing ───────────────────────────────────────────────────────────────

def connect(readonly=False):
    d = os.path.dirname(DB)
    if d:                       # ':memory:' (selftest) has no parent dir
        os.makedirs(d, exist_ok=True)
    if readonly and DB == ":memory:":
        readonly = False
    if readonly:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    else:
        con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def ddl(table):
    cols = [f"{c} {t}" for c, t in WANTED[table]] + \
           [f"{c} {t}" for c, t in COMPUTED.get(table, [])]
    pk = KEYS.get(table) or []
    pk_sql = f", PRIMARY KEY ({', '.join(pk)})" if pk else ""
    return f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(cols)}{pk_sql})"


def load_table(con, table, rows_iter, header_cols, season=None):
    """Generic loader: WANTED-column projection + coercion + per-season replace.
    Returns (rows_loaded, missing_source_columns)."""
    wanted = WANTED[table]
    missing = [c for c, _ in wanted if c not in header_cols]
    present = [(c, t) for c, t in wanted if c in header_cols]
    con.execute(ddl(table))
    if season is not None and ("season", "INT") in wanted:
        con.execute(f"DELETE FROM {table} WHERE season = ?", (season,))
    else:
        con.execute(f"DELETE FROM {table}")

    rows = rows_iter
    if table == "depth":
        rows = latest_depth_rows(list(rows_iter))
    if table == "players":
        rows = (r for r in rows if (r.get("gsis_id") or "").strip())

    cols = [c for c, _ in present] + [c for c, _ in COMPUTED.get(table, [])]
    sql = (f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) "
           f"VALUES ({', '.join('?' * len(cols))})")
    n = 0
    for r in rows:
        vals = [coerce(r.get(c), t) for c, t in present]
        if table == "games":
            et_s, utc_s = kickoff_iso(r.get("gameday"), r.get("gametime"))
            vals += [et_s, utc_s]
        con.execute(sql, vals)
        n += 1
    con.commit()
    return n, missing


# ── manifest ──────────────────────────────────────────────────────────────────

def load_manifest():
    if os.path.exists(MANIFEST):
        with open(MANIFEST, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def save_manifest(m):
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(m, fh, indent=1, sort_keys=True)
        fh.write("\n")


# ── sync ──────────────────────────────────────────────────────────────────────

def sync(only=None, force=False, today=None):
    man = load_manifest()
    con = connect()
    os.makedirs(CACHE, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    seasons = season_list(today)
    any_fail = False

    for name, ds in DATASETS.items():
        if only and name != only:
            continue
        if not ds["per_season"]:
            season_iter = [None]
        elif ds.get("current_only"):
            season_iter = seasons[-1:]
        else:
            season_iter = seasons
        for season in season_iter:
            url = f"{BASE}/{ds['url'].format(season=season)}"
            key = f"{name}:{season}" if season else name
            code, length, lastmod = curl_head(url)
            if code == "404" and ds.get("optional") and season == seasons[-1]:
                man[key] = {"status": "ABSENT", "checked_at": now, "url": url,
                            "note": "current-season asset not published yet (no games played)"}
                print(f"  ∅ {key:<24} ABSENT upstream (expected pre-season) ")
                continue
            if code != "200":
                any_fail = True
                print(f"  ✗ {key:<24} HTTP {code} — keeping last-good table; see check")
                man.setdefault(key, {})["last_error"] = f"HTTP {code} @ {now}"
                continue
            if not force and source_unchanged(man.get(key), length, lastmod):
                print(f"  ✓ {key:<24} fresh (source unchanged; {man[key]['rows']} rows)")
                continue
            dest = os.path.join(CACHE, os.path.basename(url))
            try:
                curl_get(url, dest)
                rows = read_csv_rows(dest)
                first = next(rows, None)
                if first is None:
                    raise RuntimeError("empty file")
                header = list(first.keys())

                def chain():
                    yield first
                    yield from rows
                n, missing = load_table(con, ds["table"], chain(), header, season)
                man[key] = {"status": "OK", "url": url, "rows": n,
                            "source_length": length, "source_last_modified": lastmod,
                            "fetched_at": now, "missing_cols": missing}
                miss = f"  ⚠ missing cols: {missing}" if missing else ""
                print(f"  ⬇ {key:<24} {n} rows loaded{miss}")
            except Exception as e:  # noqa: BLE001
                any_fail = True
                print(f"  ✗ {key:<24} {e} — keeping last-good table")
                man.setdefault(key, {})["last_error"] = f"{e} @ {now}"
            finally:
                if os.path.exists(dest):
                    os.remove(dest)
    save_manifest(man)
    con.close()
    return 1 if any_fail else 0


# ── status ────────────────────────────────────────────────────────────────────

def status():
    man = load_manifest()
    if not man:
        print("  (no manifest — run: tools/nfl_data.sh sync)")
        return
    now = datetime.now(timezone.utc)
    print(f"  {'dataset':<26} {'rows':>7}  {'source last-modified':<31} {'age':<8} notes")
    for key in sorted(man):
        e = man[key]
        if e.get("status") == "ABSENT":
            print(f"  {key:<26} {'—':>7}  {'—':<31} {'—':<8} ABSENT (pre-season, expected)")
            continue
        age = "?"
        if e.get("fetched_at"):
            try:
                dt = datetime.strptime(e["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                h = (now - dt).total_seconds() / 3600
                age = f"{h:.0f}h" if h < 48 else f"{h/24:.0f}d"
            except ValueError:
                pass
        notes = []
        if e.get("missing_cols"):
            notes.append(f"⚠ missing cols: {','.join(e['missing_cols'])}")
        if e.get("last_error"):
            notes.append(f"last_error: {e['last_error']}")
        print(f"  {key:<26} {e.get('rows', 0):>7}  {str(e.get('source_last_modified')):<31} "
              f"{age:<8} {'; '.join(notes)}")


# ── query commands ────────────────────────────────────────────────────────────

def window_label(row):
    """Cosmetic window tag from data (never hardcoded schedule assumptions)."""
    wd, gt = row["weekday"] or "?", row["gametime"] or ""
    hour = int(gt.split(":")[0]) if ":" in gt else None
    if wd == "Sunday" and hour is not None:
        if hour < 12:
            return "Sun-intl/early-AM"
        if hour < 16:
            return "Sun-early"
        if hour < 19:
            return "Sun-late"
        return "SNF"
    return {"Thursday": "TNF", "Monday": "MNF", "Saturday": "Sat", "Friday": "Fri",
            "Wednesday": "Wed", "Tuesday": "Tue"}.get(wd, wd)


def slate(season, week):
    con = connect(readonly=True)
    rows = con.execute(
        "SELECT * FROM games WHERE season=? AND week=? ORDER BY kickoff_utc, game_id",
        (season, week)).fetchall()
    if not rows:
        print(f"  (no games for season {season} week {week} — run sync?)")
        return
    gt = rows[0]["game_type"]
    print(f"═══ {season} week {week} ({gt}) — {len(rows)} games ═══")
    last_win = None
    for r in rows:
        win = f"{r['gameday']} {window_label(r)}"
        if win != last_win:
            print(f"\n── {win} ──")
            last_win = win
        env = "dome" if (r["roof"] or "") in ("dome", "closed") else (r["roof"] or "?")
        score = ""
        if r["home_score"] is not None:
            score = f"  FINAL {r['away_score']}-{r['home_score']}"
        neutral = "  [NEUTRAL]" if (r["location"] or "") == "Neutral" else ""
        line = ""
        if r["spread_line"] is not None:
            line = f"  (spread {r['spread_line']:+g} home, total {r['total_line'] or '?'})"
        print(f"  {r['away_team']:>3} @ {r['home_team']:<3}  {r['kickoff_et']}"
              f"  [{env}, {r['stadium'] or '?'}]{neutral}"
              f"  rest {r['away_rest']}/{r['home_rest']}{line}{score}")
    con.close()


def finals(season, week):
    con = connect(readonly=True)
    rows = con.execute(
        "SELECT * FROM games WHERE season=? AND week=? AND home_score IS NOT NULL "
        "ORDER BY kickoff_utc", (season, week)).fetchall()
    if not rows:
        print(f"  (no completed games for season {season} week {week})")
        return
    for r in rows:
        ot = " [OT]" if r["overtime"] else ""
        print(f"  {r['away_team']} {r['away_score']} - {r['home_team']} {r['home_score']}{ot}"
              f"   ({r['gameday']})")
    con.close()


def volume(team, season, week):
    """Snap share × target/carry share per player — the in-season volume model's
    ground truth (participation is postseason-only; DATA_SOURCES §2.3). Joins
    snaps (pfr ids) → players (id bridge) → player_week (gsis ids); a row that
    had to fall back to a NAME join is flagged '~' per doctrine."""
    con = connect(readonly=True)
    team = team.upper()
    snaps = con.execute(
        "SELECT * FROM snaps WHERE team=? AND season=? AND week=? AND offense_snaps>0 "
        "ORDER BY offense_pct DESC", (team, season, week)).fetchall()
    if not snaps:
        print(f"  (no offensive snap rows for {team} {season} wk{week} — "
              f"check team code / season sync)")
        return
    stats = {r["player_id"]: r for r in con.execute(
        "SELECT * FROM player_week WHERE team=? AND season=? AND week=?",
        (team, season, week)).fetchall()}
    bridge = {r["pfr_id"]: r["gsis_id"] for r in
              con.execute("SELECT pfr_id, gsis_id FROM players WHERE pfr_id IS NOT NULL")}
    by_name = {re.sub(r"[^a-z]", "", (r["player_display_name"] or "").lower()): r
               for r in stats.values()}
    team_targets = sum(r["targets"] or 0 for r in stats.values())
    team_carries = sum(r["carries"] or 0 for r in stats.values())
    game = snaps[0]["game_id"]
    print(f"═══ {team} volume — {season} wk{week} ({game}) — "
          f"team targets {team_targets}, carries {team_carries} ═══")
    print(f"  {'player':<24} {'pos':<4} {'snap%':>6} {'tgt':>4} {'tgt%':>6} "
          f"{'car':>4} {'car%':>6} {'rec':>4} {'rec_yd':>7} {'rush_yd':>8}")
    def cell(v, width):
        return f"{'—' if v is None else v:>{width}}"

    for s in snaps:
        gsis = bridge.get(s["pfr_player_id"])
        st = stats.get(gsis)
        flag = " "
        if st is None:
            st = by_name.get(re.sub(r"[^a-z]", "", (s["player"] or "").lower()))
            flag = "~" if st is not None else " "
        tgt = st["targets"] if st else None
        car = st["carries"] if st else None
        rec = st["receptions"] if st else None
        ryd = st["receiving_yards"] if st else None
        rush = st["rushing_yards"] if st else None
        print(f" {flag}{s['player']:<24} {s['position'] or '?':<4} "
              f"{(s['offense_pct'] or 0)*100:>5.0f}% "
              f"{cell(tgt, 4)} {format_share(share(tgt or 0, team_targets)):>6} "
              f"{cell(car, 4)} {format_share(share(car or 0, team_carries)):>6} "
              f"{cell(rec, 4)} {cell(ryd, 7)} {cell(rush, 8)}")
    print("  ('~' = name-fallback join, no pfr↔gsis id bridge for that player)")
    con.close()


def format_share(x):
    return f"{x*100:.0f}%" if x is not None else "—"


def form(team, n=10):
    con = connect(readonly=True)
    team = team.upper()
    rows = con.execute(
        "SELECT * FROM games WHERE (home_team=? OR away_team=?) AND home_score IS NOT NULL "
        "AND game_type != 'PRE' ORDER BY kickoff_utc DESC LIMIT ?", (team, team, n)).fetchall()
    if not rows:
        print(f"  (no completed games for {team})")
        return
    w = 0
    diff = 0
    lines = []
    for r in reversed(rows):
        home = r["home_team"] == team
        own = r["home_score"] if home else r["away_score"]
        opp = r["away_score"] if home else r["home_score"]
        opp_t = r["away_team"] if home else r["home_team"]
        res = "W" if own > opp else ("L" if own < opp else "T")
        w += res == "W"
        diff += own - opp
        lines.append(f"  {r['gameday']}  {'vs' if home else ' @'} {opp_t:<3} "
                     f"{res} {own}-{opp}")
    print(f"{team} last {len(rows)}: {w}-{len(rows)-w}   point diff "
          f"{'+' if diff >= 0 else ''}{diff}")
    print("\n".join(lines))
    con.close()


def player(namefrag):
    con = connect(readonly=True)
    rows = con.execute(
        "SELECT gsis_id, display_name, position, latest_team, status, espn_id, pfr_id, "
        "last_season FROM players WHERE display_name LIKE ? ORDER BY last_season DESC "
        "LIMIT 15", (f"%{namefrag}%",)).fetchall()
    if not rows:
        print(f"  (no player matching {namefrag!r})")
        return
    for r in rows:
        print(f"  {r['gsis_id']}  {r['display_name']:<26} {r['position'] or '?':<4} "
              f"{r['latest_team'] or '—':<4} {r['status'] or '?':<6} "
              f"espn:{r['espn_id'] or '—'} pfr:{r['pfr_id'] or '—'} "
              f"(last {r['last_season']})")
    con.close()


def depth(team):
    con = connect(readonly=True)
    team = team.upper()
    rows = con.execute(
        "SELECT * FROM depth WHERE team=? ORDER BY pos_grp, pos_abb, pos_slot, pos_rank",
        (team,)).fetchall()
    if not rows:
        print(f"  (no depth rows for {team})")
        return
    print(f"═══ {team} depth chart — snapshot {rows[0]['dt']} ═══")
    grp = None
    for r in rows:
        if r["pos_grp"] != grp:
            grp = r["pos_grp"]
            print(f"── {grp} ──")
        print(f"  {r['pos_abb'] or '?':<5} #{r['pos_rank'] or '?'}  {r['player_name']}"
              f"  (gsis {r['gsis_id'] or '—'})")
    con.close()


def run_sql(q):
    con = connect(readonly=True)
    try:
        rows = con.execute(q).fetchall()
    except sqlite3.OperationalError as e:
        sys.exit(f"sql error: {e}")
    for r in rows[:200]:
        print("  " + " | ".join(str(r[k]) for k in r.keys()))
    if len(rows) > 200:
        print(f"  … {len(rows) - 200} more rows")
    con.close()


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd, rest = args[0], args[1:]
    force = "--force" in rest
    rest = [a for a in rest if a != "--force"]
    if cmd == "sync":
        only = rest[0] if rest else None
        if only and only not in DATASETS:
            sys.exit(f"unknown dataset {only!r} (choose from {', '.join(DATASETS)})")
        sys.exit(sync(only, force))
    elif cmd == "status":
        status()
    elif cmd == "slate" and len(rest) >= 2:
        slate(int(rest[0]), int(rest[1]))
    elif cmd == "finals" and len(rest) >= 2:
        finals(int(rest[0]), int(rest[1]))
    elif cmd == "volume" and len(rest) >= 3:
        volume(rest[0], int(rest[1]), int(rest[2]))
    elif cmd == "form" and rest:
        form(rest[0], int(rest[1]) if len(rest) > 1 else 10)
    elif cmd == "player" and rest:
        player(rest[0])
    elif cmd == "depth" and rest:
        depth(rest[0])
    elif cmd == "sql" and rest:
        run_sql(rest[0])
    else:
        sys.exit(f"bad usage: {cmd} {rest} — see header docstring")


if __name__ == "__main__":
    main()
