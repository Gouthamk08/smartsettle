"""
scorer.py — Mirrors the judge's EXACT cost formula (spec §3D).

Key contract points:
  delay       = start_time - arrival_time          (NOT settle_time)
  deadline    = arrival_time + max_delay           (tx must START by this)
  failure     = tx started after deadline OR marked failed OR missing
  capacity    = concurrent [start, start+latency)  (exclusive end)
"""

import json, csv, sys

CHANNEL_FEE = {"Channel_F": 5.0,  "Channel_S": 1.0,  "Channel_B": 0.20}
CHANNEL_LAT = {"Channel_F": 1,    "Channel_S": 3,    "Channel_B": 10}
CHANNEL_CAP = {"Channel_F": 2,    "Channel_S": 4,    "Channel_B": 10}
P = 0.001   # delay penalty factor
F = 0.50    # failure penalty factor


def load_transactions(path: str) -> dict:
    txs = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            txs[row["tx_id"]] = {
                "tx_id":        row["tx_id"],
                "amount":       float(row["amount"]),
                "arrival_time": int(row["arrival_time"]),
                "max_delay":    int(row["max_delay"]),
                "priority":     int(row["priority"]),
            }
    return txs


def score(transactions_path: str, submission_path: str, verbose: bool = True):
    txs = load_transactions(transactions_path)

    with open(submission_path) as f:
        raw = json.load(f)

    # Support both flat list and {"assignments": [...]} format
    if isinstance(raw, list):
        assignments = raw
    else:
        assignments = raw.get("assignments", [])

    channel_slots: dict[str, list] = {ch: [] for ch in CHANNEL_CAP}
    violations    = []
    results       = []
    total_cost    = 0.0
    routed_cost   = 0.0
    failure_cost  = 0.0

    seen_ids = set()

    for asgn in assignments:
        tx_id = asgn["tx_id"]

        # Duplicate check
        if tx_id in seen_ids:
            violations.append(f"{tx_id}: duplicate assignment — DQ")
            continue
        seen_ids.add(tx_id)

        if tx_id not in txs:
            violations.append(f"{tx_id}: unknown tx_id")
            continue

        tx = txs[tx_id]

        # ── Failed transaction ──────────────────────────────────────────────
        if asgn.get("failed") or asgn.get("channel_id") is None:
            fp = F * tx["amount"]
            failure_cost += fp
            total_cost   += fp
            results.append({**tx, "channel": "FAILED", "cost": fp, "status": "failed"})
            continue

        channel    = asgn["channel_id"]
        start_time = int(asgn["start_time"])

        # ── Validate channel ────────────────────────────────────────────────
        if channel not in CHANNEL_CAP:
            violations.append(f"{tx_id}: invalid channel_id '{channel}' — DQ")
            continue

        # ── Must not start before arrival (DQ condition) ────────────────────
        if start_time < tx["arrival_time"]:
            violations.append(
                f"{tx_id}: starts at {start_time} before arrival {tx['arrival_time']} — DQ")

        # ── Deadline check: must START by arrival + max_delay ───────────────
        deadline = tx["arrival_time"] + tx["max_delay"]
        if start_time > deadline:
            # Treat as failure — started too late
            fp = F * tx["amount"]
            failure_cost += fp
            total_cost   += fp
            violations.append(
                f"{tx_id}: start_time {start_time} > deadline {deadline} → treated as failed")
            results.append({**tx, "channel": channel, "cost": fp, "status": "late-failed"})
            continue

        # ── Capacity check ──────────────────────────────────────────────────
        lat  = CHANNEL_LAT[channel]
        end  = start_time + lat
        slots = channel_slots[channel]
        concurrent = sum(1 for (s, e) in slots if s < end and e > start_time)
        if concurrent >= CHANNEL_CAP[channel]:
            violations.append(
                f"{tx_id}: capacity exceeded on {channel} at [{start_time},{end}) — DQ")
        slots.append((start_time, end))
        slots.sort()

        # ── Cost: delay = start_time - arrival_time (spec §3D) ─────────────
        delay      = start_time - tx["arrival_time"]   # always >= 0
        fee        = CHANNEL_FEE[channel]
        delay_pen  = P * tx["amount"] * delay
        tx_cost    = fee + delay_pen
        routed_cost += tx_cost
        total_cost  += tx_cost

        results.append({
            **tx,
            "channel":       channel,
            "start_time":    start_time,
            "settle_time":   end,
            "delay":         delay,
            "fee":           fee,
            "delay_penalty": round(delay_pen, 4),
            "cost":          round(tx_cost, 4),
            "status":        "routed",
        })

    # ── Missing transactions (not in submission) ────────────────────────────
    for tx_id, tx in txs.items():
        if tx_id not in seen_ids:
            fp = F * tx["amount"]
            failure_cost += fp
            total_cost   += fp
            violations.append(f"{tx_id}: missing from submission → failed")
            results.append({**tx, "channel": "MISSING", "cost": fp, "status": "missing"})

    # ── Report ──────────────────────────────────────────────────────────────
    if verbose:
        print("=" * 62)
        print("  SMARTSETTLE SCORER  (mirrors judge formula exactly)")
        print("=" * 62)
        print(f"  Transactions  : {len(txs)}")
        print(f"  Routed        : {sum(1 for r in results if r['status']=='routed')}")
        print(f"  Failed/Late   : {sum(1 for r in results if r['status'] not in ('routed',))}")
        print(f"  Routed cost   : ₹{routed_cost:,.4f}")
        print(f"  Failure cost  : ₹{failure_cost:,.4f}")
        print(f"  TOTAL COST    : ₹{total_cost:,.4f}  ◄ judge metric")
        print()
        if violations:
            print(f"  ⚠  VIOLATIONS ({len(violations)}):")
            for v in violations:
                print(f"     • {v}")
        else:
            print("  ✓  No constraint violations")
        print("=" * 62)

    return {
        "total_cost":   total_cost,
        "routed_cost":  routed_cost,
        "failure_cost": failure_cost,
        "violations":   violations,
        "results":      results,
    }


if __name__ == "__main__":
    tx_path  = sys.argv[1] if len(sys.argv) > 1 else "data/transactions.csv"
    sub_path = sys.argv[2] if len(sys.argv) > 2 else "output/submission.json"
    score(tx_path, sub_path)