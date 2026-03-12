"""
main.py — SmartSettle end-to-end runner.

Usage:
    python main.py                                  # uses defaults
    python main.py data/transactions.csv            # custom input
    python main.py data/transactions.csv out/sub.json
"""

import sys
import os

def main():
    tx_path  = sys.argv[1] if len(sys.argv) > 1 else "data/transactions.csv"
    sub_path = sys.argv[2] if len(sys.argv) > 2 else "output/submission.json"

    os.makedirs(os.path.dirname(sub_path), exist_ok=True)

    print(f"\n{'='*60}")
    print("  SMARTSETTLE — Payment Routing Optimizer")
    print(f"{'='*60}")
    print(f"  Input  : {tx_path}")
    print(f"  Output : {sub_path}")
    print()

    # ── Step 1: Route ────────────────────────────────────────────────────────
    from router import load_transactions, route, save_submission
    txs         = load_transactions(tx_path)
    print(f"[router] Loaded {len(txs)} transactions")
    assignments = route(txs)
    save_submission(assignments, sub_path)

    routed  = sum(1 for a in assignments if not a.get("failed"))
    failed  = sum(1 for a in assignments if a.get("failed"))
    print(f"[router] Routed: {routed}  |  Failed: {failed}")

    # ── Step 2: Score ────────────────────────────────────────────────────────
    print()
    from scorer import score
    result = score(tx_path, sub_path, verbose=True)

    # ── Step 3: Channel breakdown ────────────────────────────────────────────
    from collections import Counter
    channel_counts = Counter(
        a.get("channel_id", "FAILED") for a in assignments
    )
    print("\n  Channel breakdown:")
    for ch, count in sorted(channel_counts.items()):
        print(f"    {ch:12s}: {count} transactions")

    print()
    return result


if __name__ == "__main__":
    main()
