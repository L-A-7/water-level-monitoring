#!/usr/bin/env python3
"""One-time backfill: re-derive distance_cm/distance_std_cm for the
2026-09-09/10 rain-contamination event using a time-series-aware pass over
the raw per-ping samples, instead of sample_filter.py's per-wake-only view.

Background (see conversation / device.md): during that rain event, splash
and multipath echoes inside the tank formed several *stable, recurring*
false clusters (~58/71/84-98/107-120cm) that persisted for hours at a time.
A per-wake filter can at best identify the true cluster when it's a
qualifying minority of that one batch; a naive greedy time-continuity
tracker (accept whichever candidate is nearest the last trusted value)
actively makes things worse here, because it latches onto a false-but-
persistent cluster for hours and never lets go.

What this does instead: for every wake in range, re-derive ALL candidate
clusters from raw_samples_json (or the single device-filtered value for
wakes without raw samples), then find the one path through time -- one
candidate per wake, or "no trustworthy data" -- that never implies a
physically-impossible rate of change and is overall the most internally
consistent, via a global (Viterbi-style) search rather than a step-by-step
greedy one. This lets a correct-but-minority cluster win when it's tight
and time-consistent, without being fooled by a false cluster that merely
persists.

Usage:
    python backfill_storm_correction.py                  # preview + confirm
    python backfill_storm_correction.py --dry-run         # preview only
    python backfill_storm_correction.py --start ISO --end ISO

Nothing is written without an explicit 'yes' confirmation, and the database
is backed up first (this isn't reversible otherwise).
"""
import argparse
import json
import sqlite3
from datetime import datetime, timezone

import sample_filter
from schemas import SENTINEL_NO_ECHO

DB_PATH = "data/water_tank.db"

DEFAULT_START = "2026-09-08T12:00:00+00:00"  # >24h of clean baseline before the storm, for anchoring

# Max plausible rate of distance change. Below SOFT_RATE_CM_PER_H, movement is
# essentially free (normal drift); between SOFT and HARD it's allowed but
# costed, to model "a strong rain event, but still physical"; above
# HARD_RATE_CM_PER_H it's treated as impossible and never selected. Per the
# user: level moves ~10cm/h in practice; HARD_RATE leaves ~4x headroom above
# that for an extreme event before refusing a jump outright.
SOFT_RATE_CM_PER_H = 15.0
HARD_RATE_CM_PER_H = 60.0
K1 = 0.05  # cost per cm of movement within the soft rate
K2 = 0.6   # cost per cm of movement between soft and hard rate

# Emission "cost" for picking a given cluster: rewards tight, larger clusters
# (net negative -> preferred over skipping), penalizes noisy or single-point
# ones (net positive -> only taken if skipping would be worse). Tuned against
# the real 2026-09-09/10 event: with these weights every wake where the true
# cluster is present and >=MIN_RUN_SIZE_FLOOR points gets picked correctly,
# and no coincidental small-n false cluster in that dataset outscored it.
REWARD_BASE = 0.9
STD_WEIGHT = 1.0
SIZE_PENALTY = 1.2

TOLERANCE_CM = 0.5  # ignore diffs smaller than this when deciding whether to write

# Reading IDs manually cross-checked by the user against the raw samples_cm
# (after resolving a UTC/local-time mix-up -- the user was reading the
# dashboard's local time, this script and the earlier analysis work in UTC).
# All 9 are the *sole* survivor of the true water-surface echo in an
# otherwise fully rain-contaminated 30-ping batch, forming a smooth,
# physically plausible decline from the 209.5cm pre-storm baseline toward
# the 196.7cm post-storm plateau. The DP's per-candidate SIZE_PENALTY
# correctly refuses to trust any single such point in isolation (a lone
# point is indistinguishable from a lucky stray echo on its own -- see
# clusters_for_reading()'s docstring), but has no mechanism to credit a
# *chain* of them jointly confirming one smooth trend, which is exactly
# what the user did by eye. Tried generalizing this automatically (e.g.
# "trust whichever cluster is farthest + clearly separated, since splash
# multipath is physically always a shorter apparent path than the true
# surface") -- disproven by reading id 6477's batch, which has an isolated
# far point (158.09cm) that does NOT fit the trend established immediately
# before and after it. So these are pinned as manually-verified anchors
# rather than folded into the general algorithm.
PINNED_READING_IDS = {6388, 6392, 6393, 6409, 6410, 6413, 6418, 6420, 6421, 6422, 6425, 6427}
PIN_REWARD = -50.0  # far more negative than any legitimate emission cost -> always chosen if reachable


def clusters_for_reading(distance_cm, distance_std_cm, raw_samples_json):
    """(mean, std, n) for every candidate cluster in a reading -- gap-split the
    same way sample_filter.filter_samples() does, but deliberately WITHOUT its
    MIN_RUN_SIZE_FLOOR pre-filter, down to lone points. sample_filter has to
    pre-filter because it judges a batch in isolation and a lone point is
    indistinguishable from a lucky single stray echo there; the DP below
    doesn't have that blind spot -- SIZE_PENALTY in emit_cost() already
    discounts small-n runs, and it gets to weigh a candidate against the
    surrounding time series, not just against its own batch. Pre-filtering
    here would throw away real minority/lone-point detections (validated
    against the 2026-09-09/10 event -- e.g. a 2-point ~196.6cm cluster that
    is the only trace of the true reading left in that particular wake)
    before the DP ever gets a chance to recognize them as consistent."""
    if raw_samples_json:
        valid = sorted(s for s in json.loads(raw_samples_json) if s != SENTINEL_NO_ECHO)
        if not valid:
            return []
        runs, current = [], [valid[0]]
        for x in valid[1:]:
            if x - current[-1] > sample_filter.GAP_THRESHOLD_CM:
                runs.append(current)
                current = []
            current.append(x)
        runs.append(current)
        out = []
        for run in runs:
            n = len(run)
            mean = sum(run) / n
            std = (sum((x - mean) ** 2 for x in run) / n) ** 0.5 if n > 1 else 0.0
            out.append((mean, std, n))
        return out
    if distance_cm is not None:
        return [(distance_cm, distance_std_cm if distance_std_cm is not None else 0.5, 1)]
    return []


def emit_cost(std, n):
    return STD_WEIGHT * std - REWARD_BASE + SIZE_PENALTY / n


def jump_cost(prev_mean, prev_time, cur_mean, cur_time):
    elapsed_h = max((cur_time - prev_time).total_seconds() / 3600.0, 1e-6)
    d = abs(cur_mean - prev_mean)
    rate = d / elapsed_h
    if rate <= SOFT_RATE_CM_PER_H:
        return K1 * d
    if rate <= HARD_RATE_CM_PER_H:
        return K1 * SOFT_RATE_CM_PER_H * elapsed_h + K2 * (d - SOFT_RATE_CM_PER_H * elapsed_h)
    return float("inf")


def solve(wakes, pinned_ids=frozenset()):
    """wakes: list of (row_id, timestamp, stored_distance_cm, candidates).
    Returns {row_id: (mean, std, n)} for wakes the path trusts.

    pinned_ids: reading ids whose farthest candidate (the physically
    plausible one -- see PINNED_READING_IDS) is forced in via an
    overriding reward, bypassing the normal size-based emission cost."""
    nodes = []  # (wake_idx, mean, std, n, ts, row_id, pinned)
    for wi, (row_id, ts, _stored, cands) in enumerate(wakes):
        if not cands:
            continue
        pin_idx = None
        if row_id in pinned_ids:
            pin_idx = max(range(len(cands)), key=lambda k: cands[k][0])  # farthest = pinned candidate
        for ci, (mean, std, n) in enumerate(cands):
            nodes.append((wi, mean, std, n, ts, row_id, ci == pin_idx))

    def node_emit_cost(std, n, pinned):
        return PIN_REWARD if pinned else emit_cost(std, n)

    n_nodes = len(nodes)
    best = [node_emit_cost(std, n, pinned) for (_wi, _m, std, n, _ts, _rid, pinned) in nodes]
    prev_ptr = [-1] * n_nodes

    for j in range(n_nodes):
        wj, meanj, stdj, nj, tj, _, pinnedj = nodes[j]
        ej = node_emit_cost(stdj, nj, pinnedj)
        bestj, bp = best[j], prev_ptr[j]
        for i in range(j):
            wi_, meani, _stdi, _ni, ti, _, _ = nodes[i]
            if wi_ >= wj:
                continue
            jc = jump_cost(meani, ti, meanj, tj)
            if jc == float("inf"):
                continue
            cost = best[i] + jc + ej
            if cost < bestj:
                bestj, bp = cost, i
        best[j], prev_ptr[j] = bestj, bp

    if not n_nodes:
        return {}
    end_i = min(range(n_nodes), key=lambda i: best[i])
    path = []
    i = end_i
    while i != -1:
        path.append(i)
        i = prev_ptr[i]

    chosen = {}
    for i in path:
        wi, mean, std, n, _ts, row_id, _pinned = nodes[i]
        chosen[row_id] = (round(mean, 2), round(std, 2), n)
    return chosen


def backup_db(db_path):
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = f"{db_path}.backup-{ts}"
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(backup_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    print(f"backed up {db_path} -> {backup_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default=DEFAULT_START, help="ISO start of the window to re-derive (needs clean baseline before the event for anchoring)")
    parser.add_argument("--end", default=None, help="ISO end of the window (default: latest reading in the DB)")
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--dry-run", action="store_true", help="print the plan, don't touch the database")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    end = args.end or conn.execute("SELECT MAX(reading_time) FROM readings").fetchone()[0]

    rows = conn.execute(
        """
        SELECT id, reading_time, distance_cm, distance_std_cm, raw_samples_json
        FROM readings WHERE reading_time BETWEEN ? AND ? ORDER BY reading_time
        """,
        (args.start, end),
    ).fetchall()

    wakes = []
    for row_id, t, d, std, raw in rows:
        ts = datetime.fromisoformat(t)
        wakes.append((row_id, ts, d, clusters_for_reading(d, std, raw)))

    chosen = solve(wakes, pinned_ids=PINNED_READING_IDS)

    to_update = []  # (row_id, new_distance_cm, new_distance_std_cm, old_distance_cm, ts)
    to_clear = []   # (row_id, old_distance_cm, ts)
    for row_id, ts, stored, _cands in wakes:
        if row_id in chosen:
            mean, std, _n = chosen[row_id]
            if stored is None or abs(mean - stored) > TOLERANCE_CM:
                to_update.append((row_id, mean, std, stored, ts))
        else:
            if stored is not None:
                to_clear.append((row_id, stored, ts))

    print(f"Window: {args.start} -> {end}  ({len(wakes)} wakes)")
    print(f"Would correct {len(to_update)} reading(s) to a recovered value:")
    for row_id, mean, std, stored, ts in to_update[:15]:
        print(f"  id={row_id} {ts}  {stored} -> {mean} (std={std})")
    if len(to_update) > 15:
        print(f"  ... and {len(to_update) - 15} more")

    print(f"\nWould clear {len(to_clear)} reading(s) as untrustworthy (no consistent candidate found):")
    for row_id, stored, ts in to_clear[:15]:
        print(f"  id={row_id} {ts}  {stored} -> NULL")
    if len(to_clear) > 15:
        print(f"  ... and {len(to_clear) - 15} more")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return

    if not to_update and not to_clear:
        print("\nNothing to change.")
        return

    confirm = input(f"\nType 'yes' to apply {len(to_update)} correction(s) and {len(to_clear)} clear(s): ").strip()
    if confirm != "yes":
        print("Aborted, nothing changed.")
        return

    backup_db(args.db)
    for row_id, mean, std, _stored, _ts in to_update:
        conn.execute("UPDATE readings SET distance_cm = ?, distance_std_cm = ? WHERE id = ?", (mean, std, row_id))
    for row_id, _stored, _ts in to_clear:
        conn.execute("UPDATE readings SET distance_cm = NULL, distance_std_cm = NULL WHERE id = ?", (row_id,))
    conn.commit()
    print(f"Applied {len(to_update)} correction(s) and {len(to_clear)} clear(s).")


if __name__ == "__main__":
    main()
