"""Forward cash forecaster.

Builds the actual daily cash position from bank credits and debits, then
projects the next 7 days using a weighted average of recent daily inflows.
Flags any projected day where the running balance is expected to drop below
the low-cash threshold.
"""
import csv
import os
from datetime import date, timedelta
from collections import defaultdict

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
LOW_CASH_THRESHOLD = 50_000
FORECAST_DAYS = 7
WEIGHT_RECENT = 3   # last N days get 2x weight in the average


def forecast():
    bank = list(csv.DictReader(open(os.path.join(DATA, "bank.csv"))))
    settlements = list(csv.DictReader(open(os.path.join(DATA, "settlements.csv"))))

    # actual daily net cash from bank statement
    daily = defaultdict(float)
    for b in bank:
        amt = float(b["amount"])
        daily[b["date"]] += amt if b["type"] == "credit" else -amt

    # pending settlements not yet in bank (expected future inflows)
    settled_utrs = set()
    for b in bank:
        if b["ref"]:
            settled_utrs.add(b["ref"])
    pending_inflows = defaultdict(float)
    for s in settlements:
        if s["utr"] not in settled_utrs:
            # expected 1 day after settled_at
            exp_date = (date.fromisoformat(s["settled_at"]) + timedelta(days=1)).isoformat()
            pending_inflows[exp_date] += float(s["net_total"])

    # build sorted history
    all_dates = sorted(daily.keys())
    if not all_dates:
        return {"history": [], "forecast": [], "summary": {}}

    # running balance over history
    balance = 0.0
    history = []
    for d in all_dates:
        balance += daily[d]
        history.append({"date": d, "net": round(daily[d], 2), "balance": round(balance, 2)})

    # weighted average daily inflow for projection
    recent = [h["net"] for h in history[-WEIGHT_RECENT:]]
    older = [h["net"] for h in history[:-WEIGHT_RECENT]] if len(history) > WEIGHT_RECENT else []
    weights = [2] * len(recent) + [1] * len(older)
    values = recent + older
    avg_daily = sum(v * w for v, w in zip(values, weights)) / sum(weights) if weights else 0.0

    # project forward
    last_date = date.fromisoformat(all_dates[-1])
    proj_balance = balance
    projection = []
    for i in range(1, FORECAST_DAYS + 1):
        d = (last_date + timedelta(days=i)).isoformat()
        expected = pending_inflows.get(d, avg_daily)
        proj_balance += expected
        projection.append({
            "date": d,
            "expected_inflow": round(expected, 2),
            "projected_balance": round(proj_balance, 2),
            "low_cash": proj_balance < LOW_CASH_THRESHOLD,
        })

    low_days = [p for p in projection if p["low_cash"]]
    summary = {
        "closing_balance": round(balance, 2),
        "avg_daily_inflow": round(avg_daily, 2),
        "pending_inflow": round(sum(pending_inflows.values()), 2),
        "low_cash_days": len(low_days),
        "threshold": LOW_CASH_THRESHOLD,
        "forecast_days": FORECAST_DAYS,
    }
    return {"history": history, "forecast": projection, "summary": summary}
