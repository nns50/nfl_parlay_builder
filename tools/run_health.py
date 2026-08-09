#!/usr/bin/env python3
"""run_health.py — one durable line per run: did every channel and gate actually work?

WHY THIS EXISTS (2026-08-09)
    Run 6 delivered no Slack message and said nothing about it: notify_slack.sh hit its
    "secret unset -> SKIP, exit 0" branch and the run reported success. The failure was
    invisible for a full day and cost a long forensic session. Nothing recorded, per run,
    whether selftest was green, whether the fold landed, or whether each channel actually
    delivered — so "it ran" and "it worked" were indistinguishable after the fact.

    This is the record. Append-only JSONL, one object per run, read by the dashboard's
    health strip. A channel that silently skips now leaves a permanent mark.

USAGE
    tools/run_health.py record --run-type build --selftest 84/84 --fold abc1234 \\
        --email ok --slack SKIP --push ok --credits 19392 --verdict "NO BET" \\
        [--season 2026 --week 1 --note "..."]
    tools/run_health.py show [N]        # last N runs (default 10)

CHANNEL VALUES
    ok | SKIP | FAILED | n/a   — SKIP means the channel was not wired (missing secret),
    FAILED means it was wired and errored. They are different problems; keep them apart.
"""
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
HEALTH = os.environ.get("NFL_HEALTH", os.path.join(REPO, "ledgers", "run_health.jsonl"))

CHANNELS = ("email", "slack", "push")
VALID = ("ok", "SKIP", "FAILED", "n/a")


def parse_args(argv):
    """--key value pairs → dict. No argparse ceremony; unknown keys are an error."""
    known = {"run-type", "selftest", "fold", "email", "slack", "push", "credits",
             "verdict", "season", "week", "note", "at"}
    out, i = {}, 0
    while i < len(argv):
        a = argv[i]
        if not a.startswith("--"):
            raise SystemExit(f"run_health: unexpected argument {a!r}")
        k = a[2:]
        if k not in known:
            raise SystemExit(f"run_health: unknown flag --{k} (known: {sorted(known)})")
        if i + 1 >= len(argv):
            raise SystemExit(f"run_health: --{k} needs a value")
        out[k.replace("-", "_")] = argv[i + 1]
        i += 2
    return out


def record(argv):
    a = parse_args(argv)
    for ch in CHANNELS:
        v = a.get(ch)
        if v is not None and v not in VALID:
            raise SystemExit(f"run_health: --{ch} must be one of {VALID}, got {v!r}")
    # selftest "84/84" → green iff both halves match and neither is 0
    st = a.get("selftest", "")
    green = None
    if "/" in st:
        try:
            p, t = (int(x) for x in st.split("/", 1))
            green = (p == t and t > 0)
        except ValueError:
            green = None
    entry = {
        "at": a.get("at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_type": a.get("run_type", "?"),
        "season": a.get("season"), "week": a.get("week"),
        "verdict": a.get("verdict"),
        "selftest": st or None, "selftest_green": green,
        "fold": a.get("fold"),
        "email": a.get("email", "n/a"), "slack": a.get("slack", "n/a"),
        "push": a.get("push", "n/a"),
        "credits": int(a["credits"]) if str(a.get("credits", "")).isdigit() else None,
        "note": a.get("note"),
    }
    os.makedirs(os.path.dirname(HEALTH), exist_ok=True)
    with open(HEALTH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, separators=(",", ":")) + "\n")
    bad = [c for c in CHANNELS if entry[c] in ("SKIP", "FAILED")]
    print(f"  run_health: recorded {entry['run_type']} @ {entry['at']}"
          + (f"  ⚠ {', '.join(f'{c}={entry[c]}' for c in bad)}" if bad else "  ✓ all channels ok"))
    return 0


def load(limit=None):
    if not os.path.exists(HEALTH):
        return []
    rows = []
    for ln in open(HEALTH, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            continue          # a corrupt line must not blind the whole record
    return rows[-limit:] if limit else rows


def show(argv):
    n = int(argv[0]) if argv and argv[0].isdigit() else 10
    rows = load(n)
    if not rows:
        print("  (no runs recorded yet)")
        return 0
    print(f"  {'when':18} {'type':12} {'self':7} {'fold':9} "
          f"{'email':7} {'slack':7} {'push':6} {'credits':8} verdict")
    print("  " + "-" * 96)
    for r in reversed(rows):
        st = ("✓" if r.get("selftest_green") else "⛔") + " " + (r.get("selftest") or "?")
        print(f"  {r['at'][:16]:18} {(r.get('run_type') or '?'):12} {st:7} "
              f"{(r.get('fold') or '—')[:8]:9} {(r.get('email') or '—'):7} "
              f"{(r.get('slack') or '—'):7} {(r.get('push') or '—'):6} "
              f"{str(r.get('credits') or '—'):8} {(r.get('verdict') or '')[:28]}")
    return 0


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("record", "show"):
        print(__doc__)
        return 2
    return record(sys.argv[2:]) if sys.argv[1] == "record" else show(sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())
