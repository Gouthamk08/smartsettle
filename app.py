"""
app.py — SmartSettle Flask API

Endpoints:
  POST /api/optimize   → body: {transactions: [...]}  → returns assignments + score
  GET  /api/health     → sanity check
  GET  /               → serves the HTML frontend
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, json, tempfile, traceback, csv

from router import route
from scorer import score as compute_score

app = Flask(__name__, static_folder=".")
CORS(app)

CHANNEL_LAT = {"Channel_F": 1,   "Channel_S": 3,   "Channel_B": 10}
CHANNEL_FEE = {"Channel_F": 5.0, "Channel_S": 1.0, "Channel_B": 0.20}
DELAY_PENALTY = 0.001

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "service": "SmartSettle Optimizer"})

@app.route("/api/optimize", methods=["POST"])
def optimize():
    try:
        body = request.get_json(force=True)
        transactions = body.get("transactions", [])
        if not transactions:
            return jsonify({"error": "No transactions provided"}), 400

        cleaned = []
        for tx in transactions:
            cleaned.append({
                "tx_id":        str(tx["tx_id"]),
                "amount":       float(tx["amount"]),
                "arrival_time": int(tx["arrival_time"]),
                "max_delay":    int(tx["max_delay"]),
                "priority":     int(tx["priority"]),
            })

        assignments = route(cleaned)

        with tempfile.TemporaryDirectory() as tmpdir:
            tx_path  = os.path.join(tmpdir, "transactions.csv")
            sub_path = os.path.join(tmpdir, "submission.json")
            with open(tx_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["tx_id","amount","arrival_time","max_delay","priority"])
                writer.writeheader()
                writer.writerows(cleaned)
            with open(sub_path, "w") as f:
                json.dump(assignments, f)
            result = compute_score(tx_path, sub_path, verbose=False)

        tx_map = {tx["tx_id"]: tx for tx in cleaned}
        detail = []
        for asgn in assignments:
            tx = tx_map[asgn["tx_id"]]
            if asgn.get("failed"):
                detail.append({**tx, "channel": "FAILED", "start_time": None,
                                "settle_time": None, "delay": None,
                                "cost": round(0.50 * tx["amount"], 4), "status": "failed"})
            else:
                ch     = asgn["channel_id"]
                start  = asgn["start_time"]
                settle = start + CHANNEL_LAT[ch]
                delay  = settle - tx["arrival_time"]
                cost   = CHANNEL_FEE[ch] + DELAY_PENALTY * tx["amount"] * delay
                detail.append({**tx, "channel": ch, "start_time": start,
                                "settle_time": settle, "delay": delay,
                                "cost": round(cost, 4), "status": "routed"})

        return jsonify({
            "assignments":  assignments,
            "detail":       detail,
            "total_cost":   round(result["total_cost"], 4),
            "routed_cost":  round(result["routed_cost"], 4),
            "failure_cost": round(result["failure_cost"], 4),
            "violations":   result["violations"],
            "summary": {
                "total":  len(cleaned),
                "routed": sum(1 for a in assignments if not a.get("failed")),
                "failed": sum(1 for a in assignments if a.get("failed")),
            }
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/")
def index():
    html_path = os.path.join(os.path.dirname(__file__), "smartsettle.html")
    if os.path.exists(html_path):
        return send_from_directory(os.path.dirname(__file__), "smartsettle.html")
    return "<h2>SmartSettle API running. Add smartsettle.html here for the frontend.</h2>"

if __name__ == "__main__":
    print("\n SmartSettle API starting...")
    print("   Frontend : http://localhost:5000")
    print("   Health   : http://localhost:5000/api/health")
    print("   Optimize : POST http://localhost:5000/api/optimize\n")
    app.run(debug=True, port=5001)
