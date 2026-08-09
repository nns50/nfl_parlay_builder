#!/usr/bin/env python3
"""reconcile_played.py — fold ledgers/played.md into results_log.md (Played=Y + Stake).

WHY THIS EXISTS (2026-08-09)
    Every logged row is a leg the system RECOMMENDED; nothing recorded which ones the
    owner actually took, or for how much. Without that, ROI, the ¼-Kelly staking check
    and the standalone-vs-parlay split are computed from assumption, not fact — the MLB
    doctrine's "log the ACTUAL stake" rule had no home in the NFL schema until the Stake
    column was added alongside this tool.

    played.md is deliberately a plain markdown file: the owner edits it from a phone via
    GitHub's web UI between runs, and the next scheduled run reconciles it. No form, no
    service, no auth.

POSTURE
    Proposals by default; --apply writes ONLY the Played and Stake cells of matched rows.
    Idempotent — an already-applied line is a no-op, so runs never double-count. A
    leg_id that matches nothing, a duplicate leg_id, or a non-numeric stake is an ERROR
    (exit 1), never a silent skip: a typo'd bet that vanishes is worse than a loud stop.

USAGE
    tools/reconcile_played.py            # propose (read-only)
    tools/reconcile_played.py --apply    # write Played/Stake cells
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from legs import COL, cell, is_leg_row, parse_leg_id, set_cell, split_row  # noqa: E402

LEDGER = os.environ.get("NFL_LEDGER", os.path.join(REPO, "ledgers", "results_log.md"))
PLAYED = os.environ.get("NFL_PLAYED", os.path.join(REPO, "ledgers", "played.md"))

LINE_RX = re.compile(r"^\s*([^|#]+?)\s*\|\s*([^|#]+?)\s*(?:#.*)?$")


def parse_played(text):
    """→ (entries, errors). entries = [(leg_id, stake_float, raw_stake)]. Pure."""
    entries, errors, seen, in_bets = [], [], set(), False
    for n, raw in enumerate(text.split("\n"), 1):
        ln = raw.strip()
        if ln.startswith("## "):
            in_bets = ln.lower().startswith("## bets")
            continue
        if not in_bets or not ln or ln.startswith("#") or ln.startswith("<!--"):
            continue
        if ln.startswith("```") or ln.startswith("|"):
            continue
        m = LINE_RX.match(ln)
        if not m:
            errors.append(f"line {n}: cannot parse {ln!r} — want '<leg_id> | <stake>'")
            continue
        leg_id, raw_stake = m.group(1), m.group(2)
        if parse_leg_id(leg_id) is None:
            errors.append(f"line {n}: {leg_id!r} is not a valid leg_id")
            continue
        if leg_id in seen:
            errors.append(f"line {n}: duplicate leg_id {leg_id} — one stake per leg")
            continue
        seen.add(leg_id)
        try:
            stake = float(raw_stake.replace("$", "").replace("u", "").strip())
        except ValueError:
            errors.append(f"line {n}: stake {raw_stake!r} is not a number")
            continue
        if stake <= 0:
            errors.append(f"line {n}: stake {raw_stake!r} must be > 0")
            continue
        entries.append((leg_id, stake, raw_stake.strip()))
    return entries, errors


def main():
    apply_mode = "--apply" in sys.argv
    if not os.path.exists(PLAYED):
        print(f"  (no {os.path.relpath(PLAYED)} — nothing to reconcile)")
        return 0
    entries, errors = parse_played(open(PLAYED, encoding="utf-8").read())

    lines = open(LEDGER, encoding="utf-8").read().split("\n")
    index = {}
    for i, ln in enumerate(lines):
        if is_leg_row(ln):
            index.setdefault(split_row(ln)[COL["leg_id"]], []).append(i)

    print("=" * 70)
    print(f"  PLAYED RECONCILE  ({'APPLY' if apply_mode else 'read-only proposals'})")
    print("=" * 70)
    if not entries and not errors:
        print("  (no bets logged in played.md)")
        return 0

    applied = already = 0
    for leg_id, stake, raw in entries:
        rows = index.get(leg_id)
        if not rows:
            errors.append(f"{leg_id}: no matching row in results_log.md "
                          f"(typo, or the leg was never logged)")
            continue
        for i in rows:
            c = split_row(lines[i])
            if c[COL["played"]].strip().upper() == "Y" and cell(c, "stake") == raw:
                already += 1
                continue
            lines[i] = set_cell(lines[i], COL["played"], "Y")
            lines[i] = set_cell(lines[i], COL["stake"], raw)
            applied += 1
            print(f"  ✅ {leg_id:<52} stake {raw}")
    if already:
        print(f"  (— {already} row(s) already reconciled — idempotent no-op)")

    if errors:
        print("-" * 70)
        for e in errors:
            print(f"  ⛔ {e}")
        print("-" * 70)
        print("  REFUSING to write — fix played.md and re-run "
              "(a typo'd bet that silently vanishes is worse than a stop).")
        return 1

    if apply_mode and applied:
        open(LEDGER, "w", encoding="utf-8").write("\n".join(lines))
        print(f"  ✓ wrote Played/Stake on {applied} row(s)")
    elif not apply_mode and applied:
        print("  → re-run with --apply to write these cells")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
