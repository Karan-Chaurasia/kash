"""Build a synthetic but realistic set of books for a payments merchant:
orders, gateway payments, settlement batches, and a bank statement.

A hidden ground-truth file records the true links and the anomalies we planted,
so the reconciler can be scored on real precision/recall instead of guesswork.
"""
import csv
import json
import os
import random
from datetime import date, timedelta

SEED = 20260722
N_ORDERS = 240
FEE_RATE = 0.02
GST_ON_FEE = 0.18
START = date(2026, 6, 1)
DAYS = 24

# how many of each anomaly to plant
PLANT = {
    "unpaid_order": 14,
    "pending_settlement": 10,
    "fee_mismatch": 6,
    "missing_payout": 3,
    "unexplained_credit": 4,
    "duplicate_bank_entry": 3,
    "refund": 8,
    "chargeback": 4,
}

CUSTOMERS = [
    "Aarav Textiles", "Meghna Foods", "Kiran Motors", "Sunrise Pharma", "Bharat Steels",
    "Nimbus Cloud", "Verdant Organics", "Coastal Traders", "Peak Logistics", "Zenith Retail",
    "Orchid Interiors", "Falcon Sports", "Lotus Dairy", "Anand Hardware", "Deccan Books",
]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def money(x):
    return round(x + 1e-9, 2)


def main():
    rng = random.Random(SEED)
    os.makedirs(OUT, exist_ok=True)

    orders, payments, settlements, bank = [], [], [], []
    truth = {"order_payment": {}, "payment_settlement": {}, "settlement_bank": {}, "anomalies": []}

    unpaid = set(rng.sample(range(N_ORDERS), PLANT["unpaid_order"]))

    # orders
    for i in range(N_ORDERS):
        oid = f"ORD-{i + 1:05d}"
        amount = money(rng.choice([499, 999, 1499, 2499, 4999, 7999, 12999, 24999]) + rng.randint(0, 90))
        created = START + timedelta(days=rng.randint(0, DAYS - 4))
        paid = i not in unpaid
        orders.append({
            "order_id": oid, "customer": rng.choice(CUSTOMERS), "amount": amount,
            "created_at": created.isoformat(), "status": "paid" if paid else "unpaid",
        })
        if not paid:
            truth["anomalies"].append({"type": "unpaid_order", "ref": oid})

    # payments for paid orders
    paid_orders = [o for o in orders if o["status"] == "paid"]
    pending = set(rng.sample(range(len(paid_orders)), PLANT["pending_settlement"]))
    fee_bad = set(rng.sample(range(len(paid_orders)), PLANT["fee_mismatch"]))
    for j, o in enumerate(paid_orders):
        pid = f"PAY-{j + 1:05d}"
        fee = money(o["amount"] * FEE_RATE * (1 + GST_ON_FEE))
        if j in fee_bad:
            fee = money(fee + rng.choice([3.5, 5.0, 8.25, -4.0]))  # wrong fee -> net won't tie out
            truth["anomalies"].append({"type": "fee_mismatch", "ref": pid})
        net = money(o["amount"] - fee)
        cap = date.fromisoformat(o["created_at"]) + timedelta(days=rng.randint(0, 1))
        payments.append({
            "payment_id": pid, "order_id": o["order_id"], "gross": o["amount"],
            "fee": fee, "net": net, "settlement_id": "", "captured_at": cap.isoformat(),
        })
        truth["order_payment"][pid] = o["order_id"]
        if j in pending:
            truth["anomalies"].append({"type": "pending_settlement", "ref": pid})

    # settle everything not marked pending, grouped by capture day
    settleable = [p for k, p in enumerate(payments) if k not in pending]
    by_day = {}
    for p in settleable:
        by_day.setdefault(p["captured_at"], []).append(p)

    utr_seq = 1
    for i, (day, group) in enumerate(sorted(by_day.items())):
        sid = f"STL-{i + 1:05d}"
        net_total = money(sum(p["net"] for p in group))
        settled = date.fromisoformat(day) + timedelta(days=1)
        utr = f"UTR{utr_seq:08d}"
        utr_seq += 1
        for p in group:
            p["settlement_id"] = sid
            truth["payment_settlement"][p["payment_id"]] = sid
        settlements.append({
            "settlement_id": sid, "settled_at": settled.isoformat(),
            "payment_count": len(group), "net_total": net_total, "utr": utr,
        })

    # bank credits for settlements, minus a few "missing payouts"
    missing = set(rng.sample(range(len(settlements)), min(PLANT["missing_payout"], len(settlements))))
    bank_seq = 1
    for i, s in enumerate(settlements):
        if i in missing:
            truth["anomalies"].append({"type": "missing_payout", "ref": s["settlement_id"]})
            continue
        bid = f"BNK-{bank_seq:05d}"
        bank_seq += 1
        bank.append({
            "bank_id": bid, "date": s["settled_at"], "amount": s["net_total"], "type": "credit",
            "ref": s["utr"], "narration": f"NEFT PAYOUT {s['utr']} RAZORPAY",
        })
        truth["settlement_bank"][s["settlement_id"]] = bid

    # duplicate bank entries (double credit for the same payout)
    credits = [b for b in bank if b["type"] == "credit"]
    for b in rng.sample(credits, min(PLANT["duplicate_bank_entry"], len(credits))):
        dup = dict(b)
        dup["bank_id"] = f"BNK-{bank_seq:05d}"
        bank_seq += 1
        bank.append(dup)
        truth["anomalies"].append({"type": "duplicate_bank_entry", "ref": dup["bank_id"]})

    # unexplained credits (money in with no settlement behind it)
    for _ in range(PLANT["unexplained_credit"]):
        bid = f"BNK-{bank_seq:05d}"
        bank_seq += 1
        d = START + timedelta(days=rng.randint(2, DAYS))
        bank.append({
            "bank_id": bid, "date": d.isoformat(), "amount": money(rng.randint(2000, 60000) + rng.random()),
            "type": "credit", "ref": f"IMPS{rng.randint(10**9, 10**10):d}", "narration": "IMPS INWARD",
        })
        truth["anomalies"].append({"type": "unexplained_credit", "ref": bid})

    # refunds and chargebacks: money out, tied to a real paid order
    debit_orders = rng.sample(paid_orders, PLANT["refund"] + PLANT["chargeback"])
    for k, o in enumerate(debit_orders):
        kind = "refund" if k < PLANT["refund"] else "chargeback"
        bid = f"BNK-{bank_seq:05d}"
        bank_seq += 1
        d = date.fromisoformat(o["created_at"]) + timedelta(days=rng.randint(2, 6))
        bank.append({
            "bank_id": bid, "date": d.isoformat(), "amount": o["amount"], "type": "debit",
            "ref": o["order_id"], "narration": f"{kind.upper()} {o['order_id']}",
        })
        truth["anomalies"].append({"type": kind, "ref": bid})

    rng.shuffle(bank)
    _write("orders.csv", orders, ["order_id", "customer", "amount", "created_at", "status"])
    _write("payments.csv", payments, ["payment_id", "order_id", "gross", "fee", "net", "settlement_id", "captured_at"])
    _write("settlements.csv", settlements, ["settlement_id", "settled_at", "payment_count", "net_total", "utr"])
    _write("bank.csv", bank, ["bank_id", "date", "amount", "type", "ref", "narration"])
    json.dump(truth, open(os.path.join(OUT, "truth.json"), "w"), indent=2)

    print(f"orders {len(orders)}  payments {len(payments)}  settlements {len(settlements)}  bank {len(bank)}")
    print(f"planted anomalies: {len(truth['anomalies'])}  ->", OUT)


def _write(name, rows, cols):
    with open(os.path.join(OUT, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
