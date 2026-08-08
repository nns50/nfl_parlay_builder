#!/usr/bin/env python3
"""weather.py — kickoff-window forecasts per outdoor game (Open-Meteo + stadiums.csv).

WHY THIS EXISTS (NFL_REQUIREMENTS §4.5)
    Weather is far more material in NFL than MLB: wind ≥ ~15 mph suppresses deep passing,
    kicking range, and totals; precip leans under; dome is a first-class boolean. MLB read
    weather from the game feed near first pitch; NFL gets real FORECASTS (Open-Meteo,
    verified working, no key) against the static name-keyed stadium table.

HONESTY RULES (ported doctrine)
    • Dome/closed roof → DOME row, no fetch, no weather adjustments apply.
    • Beyond the 16-day forecast horizon → HORIZON row ("re-check inside T-16d"),
      never a fabricated number.
    • Stadium missing from config/stadiums.csv → UNVERIFIED row, loudly.
    • Rows are written to the `weather` table with the forecast timestamp — consumers
      cite forecast age like any staleness stamp.

USAGE
    tools/weather.py week [<season> <week>]     # all games of the week (default: current)
    tools/weather.py probe "<stadium>" <isoZ>   # one venue at one time (any reason)
"""
import csv
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DB = os.environ.get("NFL_DB", os.path.join(REPO, "data", "context.db"))
STADIUMS = os.path.join(REPO, "config", "stadiums.csv")
API = "https://api.open-meteo.com/v1/forecast"
HORIZON_DAYS = 16
WIND_FLAG = 15.0     # mph — the passing/kicking suppression threshold (directional seed)
GUST_FLAG = 25.0
PRECIP_FLAG = 50     # % probability

DDL = """CREATE TABLE IF NOT EXISTS weather (
  game_id TEXT PRIMARY KEY, stadium TEXT, forecast_ts TEXT,
  kickoff_temp_f REAL, wind_mph REAL, gust_mph REAL, precip_prob INT,
  verdict TEXT, source TEXT)"""


# ── pure helpers (selftest-covered) ───────────────────────────────────────────

def load_stadiums(path=STADIUMS):
    out = {}
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out[r["stadium"]] = {"lat": float(r["lat"]), "lon": float(r["lon"]),
                                 "roof": r["roof"], "tz": r["tz"]}
    return out


def is_indoor(game_roof, stadium_roof):
    """Roof resolution. The static table VETOES impossible per-game values: a venue
    with no roof cannot be 'closed' — schedules' roof column follows the home team's
    template at neutral sites (verified: the 2026 Melbourne Cricket Ground game
    carries LA's 'dome'). Otherwise the per-game value wins (retractable open/closed
    state); static is the fallback; unknown retractable counts OUTDOOR (conservative
    — weather may apply)."""
    s = (stadium_roof or "").strip().lower()
    g = (game_roof or "").strip().lower()
    if s == "outdoor":
        return False
    if g in ("dome", "closed"):
        return True
    if g in ("outdoors", "open"):
        return False
    return s == "dome"


def pick_window(times, temp, wind, gust, precip, kickoff_iso, hours=4):
    """From hourly arrays, the kickoff-window read: temp at kickoff hour, MAX wind/
    gust/precip-prob over kickoff..+hours. Times are 'YYYY-MM-DDTHH:MM' UTC."""
    key = kickoff_iso[:13]          # truncate to the hour
    idx = next((i for i, t in enumerate(times) if t[:13] == key), None)
    if idx is None:
        return None
    sl = slice(idx, min(idx + hours, len(times)))
    def mx(arr):
        vals = [v for v in arr[sl] if v is not None]
        return max(vals) if vals else None
    return {"temp_f": temp[idx], "wind_mph": mx(wind), "gust_mph": mx(gust),
            "precip_prob": mx(precip)}


def verdict(w):
    """Human flag line from a window read. '' = benign."""
    flags = []
    if w.get("wind_mph") is not None and w["wind_mph"] >= WIND_FLAG:
        flags.append(f"⚠ WIND {w['wind_mph']:.0f}mph (suppresses pass/kick/totals)")
    if w.get("gust_mph") is not None and w["gust_mph"] >= GUST_FLAG:
        flags.append(f"⚠ GUSTS {w['gust_mph']:.0f}mph")
    if w.get("precip_prob") is not None and w["precip_prob"] >= PRECIP_FLAG:
        flags.append(f"⚠ PRECIP {w['precip_prob']:.0f}%")
    if w.get("temp_f") is not None and w["temp_f"] <= 20:
        flags.append(f"⚠ COLD {w['temp_f']:.0f}°F")
    return "; ".join(flags)


def days_out(kickoff_iso, now=None):
    ko = datetime.strptime(kickoff_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (ko - now).total_seconds() / 86400.0


# ── fetch ─────────────────────────────────────────────────────────────────────

def fetch_forecast(lat, lon):
    url = (f"{API}?latitude={lat}&longitude={lon}"
           f"&hourly=temperature_2m,precipitation_probability,wind_speed_10m,wind_gusts_10m"
           f"&wind_speed_unit=mph&temperature_unit=fahrenheit"
           f"&forecast_days={HORIZON_DAYS}&timezone=UTC")
    # Open-Meteo is intermittently slow through this egress path (observed 2026-08-08:
    # one request timed out at 25s, the next returned instantly) — one retry, then
    # degrade to UNVERIFIED rather than block the run.
    for attempt in (1, 2):
        r = subprocess.run(["curl", "-sS", "--fail", "-m", "25", url],
                           capture_output=True, text=True, timeout=35)
        if r.returncode == 0:
            try:
                return json.loads(r.stdout)
            except json.JSONDecodeError:
                return None
    return None


def cmd_week(season, week, fetch=fetch_forecast, now=None):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute(DDL)
    games = con.execute(
        "SELECT * FROM games WHERE season=? AND week=? ORDER BY kickoff_utc",
        (season, week)).fetchall()
    if not games:
        sys.exit(f"no games for {season} W{week}")
    stads = load_stadiums()
    ts = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"═══ weather — {season} W{week} (forecast {ts}; flags: wind≥{WIND_FLAG:.0f} "
          f"gust≥{GUST_FLAG:.0f} precip≥{PRECIP_FLAG}%) ═══")
    fc_cache = {}
    for g in games:
        label = f"{g['away_team']:>3} @ {g['home_team']:<3} {g['kickoff_et']:<22}"
        st = stads.get(g["stadium"])
        if is_indoor(g["roof"], st["roof"] if st else None):
            row = (g["game_id"], g["stadium"], ts, None, None, None, None, "DOME", "static")
            print(f"  {label} DOME — weather N/A ({g['stadium']})")
        elif st is None:
            row = (g["game_id"], g["stadium"], ts, None, None, None, None,
                   "UNVERIFIED", "missing-stadium")
            print(f"  {label} ⚠ UNVERIFIED — '{g['stadium']}' not in config/stadiums.csv "
                  f"(add coords); weather adjustments must not apply")
        elif days_out(g["kickoff_utc"], now) > HORIZON_DAYS - 0.5:
            row = (g["game_id"], g["stadium"], ts, None, None, None, None,
                   "HORIZON", "open-meteo")
            print(f"  {label} HORIZON — kickoff {days_out(g['kickoff_utc'], now):.0f}d out "
                  f"(> {HORIZON_DAYS}d forecast) — re-check inside T-16d")
        else:
            key = (st["lat"], st["lon"])
            if key not in fc_cache:
                fc_cache[key] = fetch(st["lat"], st["lon"])
            fc = fc_cache[key]
            w = None
            if fc and "hourly" in fc:
                h = fc["hourly"]
                w = pick_window(h["time"], h["temperature_2m"], h["wind_speed_10m"],
                                h["wind_gusts_10m"], h["precipitation_probability"],
                                g["kickoff_utc"])
            if w is None:
                row = (g["game_id"], g["stadium"], ts, None, None, None, None,
                       "UNVERIFIED", "fetch-failed")
                print(f"  {label} ⚠ UNVERIFIED — forecast fetch failed; no weather adjustment")
            else:
                v = verdict(w) or "ok"
                row = (g["game_id"], g["stadium"], ts, w["temp_f"], w["wind_mph"],
                       w["gust_mph"], w["precip_prob"], v, "open-meteo")
                print(f"  {label} {w['temp_f']:.0f}°F wind {w['wind_mph']:.0f} "
                      f"gust {w['gust_mph']:.0f} precip {w['precip_prob'] or 0:.0f}%"
                      f"  {v if v != 'ok' else '✓'}")
        con.execute("INSERT OR REPLACE INTO weather VALUES (?,?,?,?,?,?,?,?,?)", row)
    con.commit()
    con.close()


def cmd_probe(stadium, iso):
    stads = load_stadiums()
    st = stads.get(stadium)
    if st is None:
        near = [s for s in stads if stadium.lower() in s.lower()]
        if len(near) == 1:
            stadium, st = near[0], stads[near[0]]
        else:
            sys.exit(f"stadium {stadium!r} not found (candidates: {near or 'none'})")
    if st["roof"] == "dome":
        print(f"{stadium}: DOME — weather N/A")
        return
    fc = fetch_forecast(st["lat"], st["lon"])
    if not fc or "hourly" not in fc:
        sys.exit("forecast fetch failed")
    h = fc["hourly"]
    w = pick_window(h["time"], h["temperature_2m"], h["wind_speed_10m"],
                    h["wind_gusts_10m"], h["precipitation_probability"], iso)
    if w is None:
        sys.exit(f"{iso} outside the returned forecast range")
    v = verdict(w) or "✓ benign"
    print(f"{stadium} @ {iso}: {w['temp_f']:.0f}°F, wind {w['wind_mph']:.0f} mph, "
          f"gusts {w['gust_mph']:.0f} mph, precip {w['precip_prob'] or 0:.0f}%   {v}")


def main():
    args = sys.argv[1:]
    if args and args[0] == "week":
        if len(args) >= 3:
            cmd_week(int(args[1]), int(args[2]))
        else:
            out = subprocess.run(["python3", os.path.join(HERE, "ingest.py"), "weekof"],
                                 capture_output=True, text=True, timeout=30).stdout.split()
            cmd_week(int(out[0]), int(out[1]))
    elif args and args[0] == "probe" and len(args) >= 3:
        cmd_probe(args[1], args[2])
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
