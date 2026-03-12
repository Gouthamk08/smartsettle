# SmartSettle — Payment Routing & Settlement Optimizer

**Track:** Fintech / Payments | **Algorithm:** Priority-Score Greedy | **Complexity:** O(n log n)

---

## Quick Start

```bash
# 1. Install dependencies
pip install flask

# 2. Run the server
python app.py

# 3. Open browser
open http://localhost:5000
```

## CLI Usage (no server needed)

```bash
# Optimize a CSV file directly
python optimizer.py transactions.csv

# Custom output path
python optimizer.py transactions.csv my_submission.json
```

## Project Structure

```
smartsettle/
├── app.py              ← Flask API server
├── optimizer.py        ← Core routing engine
├── transactions.csv    ← Sample input
├── submission.json     ← Output (generated)
├── static/
│   └── index.html      ← Frontend UI
└── README.md
```

## API Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| POST | `/api/optimize` | Optimize CSV (JSON body: `{"csv": "..."}`) |
| GET  | `/api/sample`   | Get sample CSV data |
| GET  | `/api/health`   | Health check |
| GET  | `/`             | Frontend UI |

## Algorithm

**Scoring:** `score = priority × 1000 + amount ÷ max_delay`

**Routing logic:**
1. Sort transactions by score (descending)
2. For each tx, find earliest available slot on cheapest feasible channel
3. If `failure_penalty < best_channel_cost` → mark as failed (intentional)
4. Respect all capacity constraints per minute

## Cost Formula

```
total_cost = Σ(fee + 0.001 × amount × delay)   # successful tx
           + Σ(0.5 × amount)                    # failed tx
```

## Channels

| Channel | Fee | Latency | Capacity |
|---------|-----|---------|----------|
| Channel_F (FAST) | ₹5.00 | 1 min | 2 |
| Channel_S (STANDARD) | ₹1.00 | 3 min | 4 |
| Channel_B (BULK) | ₹0.20 | 10 min | 10 |
