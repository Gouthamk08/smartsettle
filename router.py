"""
router.py — SmartSettle payment routing optimizer.

CONTRACT COMPLIANCE (Section 3 of problem spec):
  ✓ Transactions only start at or after arrival_time
  ✓ Capacity = concurrent slots [start, start+latency) — exclusive end
  ✓ max_delay is a DEADLINE: transaction must START by arrival_time + max_delay
  ✓ delay = start_time - arrival_time  (NOT settle_time - arrival_time)
  ✓ failure_penalty = 0.5 * amount for any tx not started by deadline
  ✓ submission.json uses {"channel_id": null, "start_time": null, "failed": true}
  ✓ Each tx_id appears exactly once; no duplicates
  ✓ total_system_cost_estimate included in output

Algorithm: Cost-aware greedy
  1. Score & sort (urgency + value + priority) — high-risk first
  2. Per tx: evaluate all 3 channels, find earliest valid slot each
  3. Pick channel with lowest cost = fee + delay_penalty
  4. If best routing cost > failure_penalty → mark failed (explicit check)
  5. If no slot fits within deadline → mark failed
"""

import csv, json, sys, os
from collections import defaultdict

# ── Channel constants (EXACT from spec) ─────────────────────────────────────
CHANNELS    = ["Channel_F", "Channel_S", "Channel_B"]
CHANNEL_FEE = {"Channel_F": 5.0,  "Channel_S": 1.0,  "Channel_B": 0.20}
CHANNEL_LAT = {"Channel_F": 1,    "Channel_S": 3,    "Channel_B": 10}
CHANNEL_CAP = {"Channel_F": 2,    "Channel_S": 4,    "Channel_B": 10}

P = 0.001   # delay penalty factor
F = 0.50    # failure penalty factor


# ── Slot finder ──────────────────────────────────────────────────────────────

def earliest_slot(channel: str, arrival: int, max_delay: int,
                  booked: dict) -> int | None:
    """
    Find the earliest start_time t where:
      t >= arrival                    (cannot start before arrival)
      t <= arrival + max_delay        (DEADLINE: must start by this time)
      concurrent slots at [t, t+lat) < capacity

    Capacity rule (spec §3C-2): a transaction occupies [start, start+latency)
    — the end is EXCLUSIVE. Two txs overlap if their intervals overlap.
    """
    lat      = CHANNEL_LAT[channel]
    cap      = CHANNEL_CAP[channel]
    slots    = booked[channel]
    deadline = arrival + max_delay   # last valid start_time

    t = arrival
    while t <= deadline:
        end = t + lat
        # Find all intervals that overlap [t, end) in one pass
        overlapping_ends = [e for (s, e) in slots if s < end and e > t]
        if len(overlapping_ends) < cap:
            return t
        # Jump past the earliest overlapping slot's end to avoid re-scanning
        t = min(overlapping_ends)

    return None  # no valid slot within deadline


# ── Cost functions ───────────────────────────────────────────────────────────

def tx_routing_cost(channel: str, amount: float,
                    start_time: int, arrival: int) -> float:
    """fee + delay_penalty. delay = start_time - arrival_time (spec §3D)"""
    delay = start_time - arrival   # always >= 0 since start >= arrival
    return CHANNEL_FEE[channel] + P * amount * delay


def tx_failure_cost(amount: float) -> float:
    return F * amount


# ── Priority scorer (sort order — higher = schedule first) ──────────────────

def priority_score(tx: dict) -> float:
    """
    Combines:
      - priority (1-5): business importance
      - urgency (1/max_delay): tight deadlines must be scheduled first
      - value (amount): high amounts have higher penalties — schedule early
    """
    urgency = 1.0 / max(tx["max_delay"], 1)
    value   = tx["amount"] / 20_000          # normalised to [0,1] approx
    return tx["priority"] * 10 + urgency * 8 + value * 2


# ── Main router ──────────────────────────────────────────────────────────────

def route(transactions: list[dict]) -> list[dict]:
    """
    Returns list of assignment dicts for submission.json.
    Each dict is either:
      {"tx_id": ..., "channel_id": ..., "start_time": ...}
    or:
      {"tx_id": ..., "channel_id": null, "start_time": null, "failed": true}
    """
    sorted_txs = sorted(transactions, key=priority_score, reverse=True)

    # channel → list of (start, end) booked intervals (kept sorted)
    booked: dict[str, list] = defaultdict(list)

    total_cost_estimate = 0.0
    assignments = []

    for tx in sorted_txs:
        tx_id   = tx["tx_id"]
        amount  = tx["amount"]
        arrival = tx["arrival_time"]
        max_d   = tx["max_delay"]

        fail_cost = tx_failure_cost(amount)

        best_cost    = float("inf")
        best_channel = None
        best_start   = None

        # Evaluate all channels, pick the cheapest valid one
        for ch in CHANNELS:
            slot = earliest_slot(ch, arrival, max_d, booked)
            if slot is None:
                continue
            cost = tx_routing_cost(ch, amount, slot, arrival)
            if cost < best_cost:
                best_cost    = cost
                best_channel = ch
                best_start   = slot

        # Explicit cost-benefit: failing may be cheaper than routing
        if best_channel is None or fail_cost <= best_cost:
            assignments.append({
                "tx_id":      tx_id,
                "channel_id": None,
                "start_time": None,
                "failed":     True,
            })
            total_cost_estimate += fail_cost
        else:
            # Book the slot
            end = best_start + CHANNEL_LAT[best_channel]
            booked[best_channel].append((best_start, end))
            booked[best_channel].sort()
            assignments.append({
                "tx_id":      tx_id,
                "channel_id": best_channel,
                "start_time": best_start,
            })
            total_cost_estimate += best_cost

    return assignments, round(total_cost_estimate, 4)


# ── I/O ──────────────────────────────────────────────────────────────────────

def load_transactions(path: str) -> list[dict]:
    txs = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            txs.append({
                "tx_id":        row["tx_id"],
                "amount":       float(row["amount"]),
                "arrival_time": int(row["arrival_time"]),
                "max_delay":    int(row["max_delay"]),
                "priority":     int(row["priority"]),
            })
    return txs


def save_submission(assignments: list[dict], cost_estimate: float, path: str):
    submission = {
        "assignments": assignments,
        "total_system_cost_estimate": cost_estimate,
    }
    with open(path, "w") as f:
        json.dump(submission, f, indent=2)
    print(f"[router] Saved {len(assignments)} assignments → {path}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tx_path  = sys.argv[1] if len(sys.argv) > 1 else "data/transactions.csv"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "output/submission.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    txs = load_transactions(tx_path)
    assignments, estimate = route(txs)
    save_submission(assignments, estimate, out_path)