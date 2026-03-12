"""
scorer.py — mirrors the judge's exact cost formula.
Run this locally to validate any submission before uploading.
"""

import json
import csv
import sys

# ── Constants (match judge exactly) ────────────────────────────────────────
CHANNEL_FEE   = {"Channel_F": 5.0,   "Channel_S": 1.0,   "Channel_B": 0.20}
CHANNEL_LAT   = {"Channel_F": 1,     "Channel_S": 3,     "Channel_B": 10}
CHANNEL_CAP   = {"Channel_F": 2,     "Channel_S": 4,     "Channel_B": 10}
DELAY_PENALTY  = 0.001   # P
FAILURE_PENALTY = 0.50   # F  (fraction of amount)


def load_transactions(path: str) -> dict:
    txs = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            txs[row["tx_id"]] = {
                "tx_id":       row["tx_id"],
                "amount":      float(row["amount"]),
                "arrival_time": int(row["arrival_time"]),
                "max_delay":   int(row["max_delay"]),
                "priority":    int(row["priority"]),
            }
    return txs


def score(transactions_path: str, submission_path: str, verbose: bool = True):
    txs = load_transactions(transactions_path)
    with open(submission_path) as f:
        assignments = json.load(f)

    # ── Capacity tracking ───────────────────────────────────────────────────
    # channel → list of (start, end) intervals
    channel_slots: dict[str, list[tuple]] = {ch: [] for ch in CHANNEL_CAP}

    total_cost    = 0.0
    routed_cost   = 0.0
    failure_cost  = 0.0
    violations    = []
    results       = []

    for asgn in assignments:
        tx_id = asgn["tx_id"]
        if tx_id not in txs:
            print(f"[WARN] Unknown tx_id in submission: {tx_id}")
            continue

        tx = txs[tx_id]

        # ── Failed transaction ──────────────────────────────────────────────
        if asgn.get("failed"):
            fp = FAILURE_PENALTY * tx["amount"]
            failure_cost += fp
            total_cost   += fp
            results.append({**tx, "channel": "FAILED", "start_time": None,
                            "settle_time": None, "cost": fp, "status": "failed"})
            continue

        channel    = asgn["channel_id"]
        start_time = int(asgn["start_time"])
        latency    = CHANNEL_LAT[channel]
        settle_time = start_time + latency

        # ── Constraint: must not start before arrival ───────────────────────
        if start_time < tx["arrival_time"]:
            violations.append(f"{tx_id}: starts before arrival "
                              f"({start_time} < {tx['arrival_time']})")

        # ── Constraint: delay must not exceed max_delay ─────────────────────
        actual_delay = settle_time - tx["arrival_time"]
        if actual_delay > tx["max_delay"]:
            violations.append(f"{tx_id}: delay {actual_delay} > max_delay {tx['max_delay']}")

        # ── Constraint: capacity (no more than CAP simultaneous) ───────────
        slots = channel_slots[channel]
        concurrent = sum(
            1 for (s, e) in slots
            if s < settle_time and e > start_time   # overlap
        )
        if concurrent >= CHANNEL_CAP[channel]:
            violations.append(f"{tx_id}: capacity exceeded on {channel} "
                              f"at interval [{start_time},{settle_time})")
        slots.append((start_time, settle_time))

        # ── Cost ────────────────────────────────────────────────────────────
        fee           = CHANNEL_FEE[channel]
        delay_pen     = DELAY_PENALTY * tx["amount"] * actual_delay
        tx_cost       = fee + delay_pen
        routed_cost  += tx_cost
        total_cost   += tx_cost

        results.append({**tx, "channel": channel, "start_time": start_time,
                        "settle_time": settle_time, "delay": actual_delay,
                        "fee": fee, "delay_penalty": delay_pen,
                        "cost": tx_cost, "status": "routed"})

    # ── Unassigned (missing from submission) ───────────────────────────────
    assigned_ids = {a["tx_id"] for a in assignments}
    for tx_id, tx in txs.items():
        if tx_id not in assigned_ids:
            fp = FAILURE_PENALTY * tx["amount"]
            failure_cost += fp
            total_cost   += fp
            violations.append(f"{tx_id}: missing from submission → treated as failed")
            results.append({**tx, "channel": "MISSING", "cost": fp, "status": "missing"})

    # ── Report ─────────────────────────────────────────────────────────────
    if verbose:
        print("=" * 60)
        print("SMARTSETTLE SCORER")
        print("=" * 60)
        print(f"  Transactions  : {len(txs)}")
        print(f"  Routed        : {sum(1 for r in results if r['status']=='routed')}")
        print(f"  Failed        : {sum(1 for r in results if r['status'] in ('failed','missing'))}")
        print(f"  Routed cost   : ₹{routed_cost:,.4f}")
        print(f"  Failure cost  : ₹{failure_cost:,.4f}")
        print(f"  TOTAL COST    : ₹{total_cost:,.4f}  ◄ judge metric")
        print()
        if violations:
            print(f"  ⚠  VIOLATIONS ({len(violations)}) — may result in DQ:")
            for v in violations:
                print(f"     • {v}")
        else:
            print("  ✓  No constraint violations")
        print("=" * 60)

    return {
        "total_cost": total_cost,
        "routed_cost": routed_cost,
        "failure_cost": failure_cost,
        "violations": violations,
        "results": results,
    }


if __name__ == "__main__":
    tx_path  = sys.argv[1] if len(sys.argv) > 1 else "data/transactions.csv"
    sub_path = sys.argv[2] if len(sys.argv) > 2 else "output/submission.json"
    score(tx_path, sub_path)
