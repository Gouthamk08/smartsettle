"""
router.py — SmartSettle payment routing optimizer.

Algorithm: Priority-score greedy with cost-aware channel selection.
  1. Score & sort transactions (high-priority / tight-deadline first).
  2. For each tx, evaluate every channel and pick the one with lowest
     total cost (fee + delay_penalty), subject to capacity.
  3. If cheapest valid routing costs MORE than the failure penalty,
     mark transaction as failed (explicit cost-benefit check).
  4. If no slot is available within max_delay, mark as failed.
"""

import csv
import json
import heapq
import sys
from collections import defaultdict

# ── Channel constants ───────────────────────────────────────────────────────
CHANNELS = ["Channel_F", "Channel_S", "Channel_B"]

CHANNEL_FEE = {"Channel_F": 5.0,  "Channel_S": 1.0,  "Channel_B": 0.20}
CHANNEL_LAT = {"Channel_F": 1,    "Channel_S": 3,    "Channel_B": 10}
CHANNEL_CAP = {"Channel_F": 2,    "Channel_S": 4,    "Channel_B": 10}

DELAY_PENALTY   = 0.001   # P  — per unit amount per unit time
FAILURE_PENALTY = 0.50    # F  — fraction of amount


# ── Slot finder ─────────────────────────────────────────────────────────────

def earliest_slot(channel: str, not_before: int, deadline: int,
                  booked: dict) -> int | None:
    """
    Return the earliest start_time t such that:
      • t >= not_before  (can't start before tx arrives)
      • t + latency <= arrival + max_delay  (must settle within deadline)
      • fewer than CAP transactions overlap [t, t+latency)

    Uses a timeline scan — O(capacity * intervals) but fast in practice.
    """
    latency  = CHANNEL_LAT[channel]
    cap      = CHANNEL_CAP[channel]
    slots    = booked[channel]          # sorted list of (start, end)

    t = not_before
    max_start = deadline - latency      # latest allowable start

    if max_start < not_before:
        return None                     # impossible regardless of capacity

    while t <= max_start:
        # Count how many booked intervals overlap [t, t+latency)
        end = t + latency
        concurrent = sum(1 for (s, e) in slots if s < end and e > t)
        if concurrent < cap:
            return t
        # Jump to the end of the earliest overlapping interval to skip
        overlapping_ends = [e for (s, e) in slots if s < end and e > t]
        t = min(overlapping_ends)       # try right after earliest slot ends

    return None


# ── Cost helpers ─────────────────────────────────────────────────────────────

def routing_cost(channel: str, amount: float,
                 start_time: int, arrival_time: int) -> float:
    settle_time  = start_time + CHANNEL_LAT[channel]
    actual_delay = settle_time - arrival_time
    return CHANNEL_FEE[channel] + DELAY_PENALTY * amount * actual_delay


def failure_cost(amount: float) -> float:
    return FAILURE_PENALTY * amount


# ── Main router ──────────────────────────────────────────────────────────────

def route(transactions: list[dict]) -> list[dict]:
    """
    Returns list of assignment dicts ready for submission.json.
    """

    # Priority score: higher = schedule first
    # Combines urgency (tight deadline), amount (high value → high penalty),
    # and explicit priority field.
    def tx_score(tx):
        urgency = 1.0 / max(tx["max_delay"], 1)          # tight deadline → high score
        value   = tx["amount"] / 10_000                   # normalised amount
        return tx["priority"] * 10 + urgency * 5 + value

    sorted_txs = sorted(transactions, key=tx_score, reverse=True)

    # channel → sorted list of (start, end) booked intervals
    booked: dict[str, list] = defaultdict(list)

    assignments = []

    for tx in sorted_txs:
        tx_id        = tx["tx_id"]
        amount       = tx["amount"]
        arrival      = tx["arrival_time"]
        max_delay    = tx["max_delay"]
        deadline     = arrival + max_delay     # settle must complete by this time

        fail_cost = failure_cost(amount)

        best_cost    = float("inf")
        best_channel = None
        best_start   = None

        # Evaluate all channels, pick cheapest valid option
        for ch in CHANNELS:
            slot = earliest_slot(ch, arrival, deadline, booked)
            if slot is None:
                continue
            cost = routing_cost(ch, amount, slot, arrival)
            if cost < best_cost:
                best_cost    = cost
                best_channel = ch
                best_start   = slot

        # Explicit failure check: is it cheaper to fail than to route?
        if best_channel is None or fail_cost < best_cost:
            assignments.append({"tx_id": tx_id, "failed": True})
        else:
            # Book the slot
            end = best_start + CHANNEL_LAT[best_channel]
            booked[best_channel].append((best_start, end))
            booked[best_channel].sort()           # keep sorted for jump logic
            assignments.append({
                "tx_id":      tx_id,
                "channel_id": best_channel,
                "start_time": best_start,
            })

    return assignments


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


def save_submission(assignments: list[dict], path: str):
    with open(path, "w") as f:
        json.dump(assignments, f, indent=2)
    print(f"[router] Saved {len(assignments)} assignments → {path}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tx_path  = sys.argv[1] if len(sys.argv) > 1 else "data/transactions.csv"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "output/submission.json"

    import os
    os.makedirs("output", exist_ok=True)

    txs         = load_transactions(tx_path)
    assignments = route(txs)
    save_submission(assignments, out_path)
