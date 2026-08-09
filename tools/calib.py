#!/usr/bin/env python3
"""calib.py — recompute calibration / Brier / attribution / ROI from the ledger (READ-ONLY).

PORTED (the MLB measurement stack — the part of that system that proved out):
    §1 calibration bands (played legs, explicit TrueP; reconstructed '%*' rows excluded)
    §1b Brier skill vs the market (TrueP vs logged no-vig ImplP over EVERY decided leg —
        the leg-selection scoreboard; converges far faster than band tables)
    §1c per-adjustment attribution (from the [adj: …] tags truep.py emits)
    §2 record by Type · §2b STANDALONE vs PARLAY split · §3 ticket units/ROI
    §4 recommended-but-not-played would-record (fade/decline calibration)

RE-KEYED FOR NFL: rows are identified by leg_id (tools/legs.py) — dedup of
    reprice/supersede copies is a dict-keep-last on leg_id, not the MLB regex
    forensics. Bucket=BT rows (pipeline-validation) are EXCLUDED from every live
    section and reported separately. Week keys, no date inference, no epoch marker.

If these numbers disagree with the ledger's prose rollup, the prose is stale — fix it.

USAGE
    tools/calib.py [path/to/results_log.md]
"""
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from legs import COL, is_leg_row, parse_leg_id, split_row  # noqa: E402

REPO = os.path.dirname(HERE)
LEDGER = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].endswith(".md") else \
    os.environ.get("NFL_LEDGER", os.path.join(REPO, "ledgers", "results_log.md"))

ADJ_TAG = re.compile(r"\[adj:\s*([^\]]*)\]")


def parse_result(cell):
    """W/L/Push from a Result cell; None for TBD/SUPERSEDED/void/undecided.
    (Ported semantics: SUPERSEDED anywhere in the cell vetoes; the verdict is read
    from the first bold span or the leading token.)"""
    s = cell or ""
    if "superseded" in s.lower():
        return None
    m = re.search(r"\*\*(.+?)\*\*", s)
    seg = (m.group(1) if m else s).strip()
    low = seg.lower()
    if any(t in low for t in ("tbd", "n/a", "void")):
        return None
    if low.startswith("push"):
        return "Push"
    core = re.sub(r"^\s*would-?\s*", "", low)
    if re.match(r"w\b", core):
        return "W"
    if re.match(r"l\b", core):
        return "L"
    return None


def parse_pct(cell):
    """'64.3%' → (64.3, starred=False); '68%*' → (68.0, True); '—' → (None, False).
    Star = literal '%*' after bold-stripping (the ported bold/italics lessons)."""
    s = (cell or "").replace("**", "")
    starred = "%*" in s
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", s)
    return (float(m.group(1)) if m else None), starred


def parse_num(cell):
    s = (cell or "").replace("−", "-").replace("—", "").strip()
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def parse_adj_tags(cell):
    """[adj: a+3, b-2] → ['a','b']; [adj: none] → []; untagged → None."""
    m = ADJ_TAG.search(cell or "")
    if not m:
        return None
    content = m.group(1).strip()
    if content.lower() in ("n/a", "na", "-", "—"):
        return None
    names = []
    for part in content.split(","):
        part = part.strip()
        if not part or part.lower().startswith("none"):
            continue
        g = re.match(r"([A-Za-z][A-Za-z0-9_]*)\s*[+\-−][\d.]", part)
        if g:
            names.append(g.group(1))
        elif re.fullmatch(r"[A-Za-z][A-Za-z0-9_~]*", part):
            names.append(part.lstrip("~"))
    return names


def read_rows(text):
    """→ (rows, tickets). Each row dict: section, week, leg, leg_id, type, price, truep,
    starred, implp, result, played, clv, bucket. Dedup keep-LAST per leg_id with the
    Played section preferred (walk Recommended first, then Played, then BT last so BT
    can never shadow a live row of the same id)."""
    sections = [("## Recommended but NOT played", "R"), ("## Played legs", "P"),
                ("## Backtest", "BT")]
    tickets = []
    ordered = []
    cur = None
    in_ticket = False
    for ln in text.split("\n"):
        if ln.startswith("## ") or ln.startswith("### "):
            cur = None
            in_ticket = "Played-ticket" in ln
            for h, tag in sections:
                if ln.startswith(h):
                    cur = tag
        if in_ticket and ln.strip().startswith("|"):
            c = [x.strip() for x in ln.split("|")]
            if len(c) >= 8 and c[1] and not set(c[1]) <= set("-: ") and c[1] != "Week":
                tickets.append(c)
            continue
        if cur and is_leg_row(ln):
            c = split_row(ln)
            truep, starred = parse_pct(c[COL["truep"]])
            implp, _ = parse_pct(c[COL["implp"]])
            ordered.append({
                "section": cur, "week": c[COL["week"]], "leg": c[COL["leg"]],
                "leg_id": c[COL["leg_id"]], "type": c[COL["type"]],
                "truep": truep, "starred": starred, "implp": implp,
                "result": parse_result(c[COL["result"]]),
                "played": c[COL["played"]].upper() == "Y",
                "clv": c[COL["clv"]].replace("−", "-"),
                "bucket": c[COL["bucket"]].upper(),
            })
    # dedup keep-last per leg_id, section priority R < P (later wins; BT ids are distinct
    # by construction — different weeks — but guard anyway by keeping BT separate)
    live, bt = {}, {}
    for r in ordered:
        (bt if r["bucket"] == "BT" else live)[r["leg_id"]] = r

    # PARSER GUARD (2026-08-09). Rows are only ingested when they sit under a declared
    # "## " section header; a renamed/removed header leaves cur=None and EVERY row is
    # skipped in silence — calibration then reads 0 and reports nothing wrong. That is
    # the same silent-drop class generate_dashboard.py --selftest already guards. Count
    # well-formed leg rows in the raw file and flag any the sectioniser did not claim.
    orphans = sum(1 for ln in text.split("\n") if is_leg_row(ln)) - len(ordered)
    return list(live.values()), list(bt.values()), tickets, max(orphans, 0)


def band(p):
    lo = int(p // 5 * 5)
    return f"{lo}-{lo + 4}"


def main():
    with open(LEDGER, encoding="utf-8") as fh:
        text = fh.read()
    live, bt, tickets, orphans = read_rows(text)

    print("=" * 64)
    print(f"  CALIBRATION / ROI RECOMPUTE (read-only) — {os.path.relpath(LEDGER)}")
    print(f"  live rows: {len(live)} (deduped by leg_id)   BT validation rows: {len(bt)}")
    if orphans:
        print(f"  ⛔ PARSER GUARD: {orphans} well-formed leg row(s) sit OUTSIDE any "
              f"'## ' section")
        print("     and were NOT counted. Every number below is computed from a partial "
              "ledger.")
        print("     Fix the section headers (## Recommended but NOT played / ## Played "
              "legs / ## Backtest)")
        print("     before trusting or acting on this output.")
    print("=" * 64)

    # §1 calibration bands — played, explicit TrueP, decided
    buckets = defaultdict(lambda: [0, 0, 0])
    excl = 0
    for r in live:
        if not r["played"] or r["truep"] is None:
            continue
        if r["starred"]:
            excl += 1
            continue
        if r["result"] not in ("W", "L"):
            continue
        b = buckets[band(r["truep"])]
        b[0] += 1
        b[1 if r["result"] == "W" else 2] += 1
    print(f"\n-- 1. Calibration bands (played, explicit TrueP; {excl} starred excluded) --")
    if not buckets:
        print("   (no decided played legs yet)")
    for b in sorted(buckets, key=lambda x: int(x.split("-")[0])):
        n, w, l = buckets[b]
        dec = w + l
        hit = w / dec * 100 if dec else 0
        mid = int(b.split("-")[0]) + 2.5
        flag = ""
        if dec >= 3:
            flag = ("  ⚠ under" if hit < mid - 7 else
                    "  ▲ over" if hit > mid + 7 else "")
        print(f"   {b:<8} n={n}  {w}-{l}  {hit:.0f}%  (mid {mid:.1f}){flag}")

    # §1b Brier vs market — every decided live leg with TrueP + ImplP
    pool = [r for r in live if r["result"] in ("W", "L") and not r["starred"]
            and r["truep"] is not None and r["implp"] is not None]
    print("\n-- 1b. Brier skill vs market (every decided leg) --")
    if len(pool) >= 10:
        bm = sum((r["truep"] / 100 - (r["result"] == "W")) ** 2 for r in pool) / len(pool)
        bk = sum((r["implp"] / 100 - (r["result"] == "W")) ** 2 for r in pool) / len(pool)
        skill = bk - bm
        verdict = ("TrueP BEATS the logged price — adjustments add signal" if skill > 0
                   else "TrueP does NOT beat the price — shrink toward the baseline")
        print(f"   n={len(pool)}  Brier(TrueP) {bm:.4f}  Brier(market) {bk:.4f}  "
              f"skill {skill:+.4f} → {verdict}")
        if len(pool) < 40:
            print("   ⚠ n<40 — directional only; don't resize adjustments off this.")
    else:
        print(f"   (only {len(pool)} scorable live legs — need ≥10)")

    # §1c per-adjustment attribution
    per = defaultdict(lambda: [0, 0, 0.0, 0.0])
    for r in pool:
        tags = parse_adj_tags(r["leg"])
        if tags is None:
            continue
        y = 1.0 if r["result"] == "W" else 0.0
        for t in (tags or ["(none — market-anchored)"]):
            e = per[t]
            e[0] += 1
            e[1] += int(y)
            e[2] += (r["truep"] / 100 - y) ** 2
            e[3] += (r["implp"] / 100 - y) ** 2
    print("\n-- 1c. Per-adjustment attribution ([adj:] tags) --")
    if not per:
        print("   (no tagged decided rows yet — judge nothing before n≥20 per tag)")
    for t in sorted(per, key=lambda x: -per[x][0]):
        n, w, bm_, bk_ = per[t]
        flag = "" if n >= 20 else "  (n<20 — directional)"
        print(f"   {t:<26} n={n:<3} {w}-{n-w}  skill/leg {(bk_-bm_)/n:+.4f}{flag}")

    # §2 by type + §2b S/P split (played)
    by_type = defaultdict(lambda: [0, 0, 0])
    by_bucket = defaultdict(lambda: [0, 0, 0])
    for r in live:
        if not r["played"] or r["result"] is None:
            continue
        idx = {"W": 0, "L": 1, "Push": 2}[r["result"]]
        by_type[r["type"]][idx] += 1
        bkt = {"S": "STANDALONE", "P": "PARLAY"}.get(r["bucket"], "untagged")
        by_bucket[bkt][idx] += 1
    print("\n-- 2. Record by type (played) --")
    for t, (w, l, p) in sorted(by_type.items(), key=lambda kv: -sum(kv[1])):
        print(f"   {t:<14} {w}-{l}{f' +{p}P' if p else ''}")
    if not by_type:
        print("   (none)")
    print("\n-- 2b. STANDALONE vs PARLAY (played — the parlay-tax test) --")
    for bkt in ("STANDALONE", "PARLAY", "untagged"):
        if bkt in by_bucket:
            w, l, p = by_bucket[bkt]
            print(f"   {bkt:<11} {w}-{l}{f' +{p}P' if p else ''}")
    if not by_bucket:
        print("   (none)")

    # §3 ticket units/ROI
    stake = ret = pl = 0.0
    wins = losses = parsed = 0
    for c in tickets:
        if len(c) < 8 or "tbd" in (c[7] or "").lower():
            continue
        s, r_, p_ = parse_num(c[4]), parse_num(c[5]), parse_num(c[6])
        if s is None:
            continue
        parsed += 1
        stake += s
        ret += r_ or 0.0
        pl += p_ if p_ is not None else ((r_ or 0.0) - s)
        wins += (r_ or 0) > s
        losses += (r_ or 0) <= s
    print("\n-- 3. Played PARLAY-ticket units/ROI --")
    if parsed:
        print(f"   tickets {parsed}  {wins}-{losses}  staked {stake:.2f}u  "
              f"P/L {pl:+.2f}u  ROI {pl/stake*100 if stake else 0:+.1f}%")
    else:
        print("   (no decided ticket rows)")

    # §4 recommended-not-played
    rec = [r for r in live if r["section"] == "R" and not r["played"]
           and r["result"] in ("W", "L")]
    w = sum(r["result"] == "W" for r in rec)
    print("\n-- 4. Recommended-not-played (decline calibration) --")
    print(f"   {w}-{len(rec)-w} would-record" if rec else "   (none decided)")

    # BT validation readout (never mixed into the live sections)
    dec_bt = [r for r in bt if r["result"] in ("W", "L", "Push")]
    print(f"\n-- BT pipeline-validation rows: {len(dec_bt)}/{len(bt)} settled "
          f"({sum(r['result']=='W' for r in dec_bt)}W "
          f"{sum(r['result']=='L' for r in dec_bt)}L "
          f"{sum(r['result']=='Push' for r in dec_bt)}P) — excluded from all live stats --")
    print("\n" + "=" * 64)
    print("  If these differ from the ledger's prose rollup, the prose is stale.")
    print("=" * 64)


if __name__ == "__main__":
    main()
