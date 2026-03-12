"""
main.py — SmartSettle end-to-end runner.

Usage:
    python main.py
    python main.py data/transactions.csv
    python main.py data/transactions.csv output/submission.json
"""

import sys, os
from collections import Counter

def main():
    tx_path  = sys.argv[1] if len(sys.argv) > 1 else "data/transactions.csv"
    sub_path = sys.argv[2] if len(sys.argv) > 2 else "output/submission.json"
    os.makedirs(os.path.dirname(sub_path), exist_ok=True)

    print(f"\n{'='*62}")
    print("  SMARTSETTLE — Payment Routing Optimizer")
    print(f"{'='*62}")
    print(f"  Input  : {tx_path}")
    print(f"  Output : {sub_path}")
    print()

    from router import load_transactions, route, save_submission
    txs = load_transactions(tx_path)
    print(f"[router] Loaded {len(txs)} transactions")

    assignments, estimate = route(txs)
    save_submission(assignments, estimate, sub_path)

    routed = sum(1 for a in assignments if not a.get("failed"))
    failed = sum(1 for a in assignments if a.get("failed"))
    print(f"[router] Routed: {routed}  |  Failed: {failed}")
    print(f"[router] Estimated cost: ₹{estimate:,.4f}")

    print()
    from scorer import score
    score(tx_path, sub_path, verbose=True)

    counts = Counter(a.get("channel_id") or "FAILED" for a in assignments)
    print("\n  Channel breakdown:")
    for ch in ["Channel_F", "Channel_S", "Channel_B", "FAILED"]:
        if counts[ch]:
            print(f"    {ch:12s}: {counts[ch]} transactions")
    print()

if __name__ == "__main__":
    main()