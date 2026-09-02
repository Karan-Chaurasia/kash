"""Make synthetic books for a payments merchant: orders, payments, refunds,
settlements and a bank statement.

The payout on a settlement is gross - fee - GST - refunds, so the bank credit
won't equal the raw payment total. A truth file records the real links and the
problems we plant so the reconciler can be scored on precision/recall.
"""
import csv
import json
import os
import random
from datetime import date, timedelta

SEED = 20260722
N_ORDERS = 400
N_REFUNDS = 34
FEE_RATE = 0.02
GST = 0.18
START = date(2026, 6, 1)
DAYS = 26

PLANT = {
    "unpaid_order": 20,
    "pending_settlement": 15,
    "fee_mismatch": 8,
    "tax_mismatch": 8,
    "refund_not_deducted": 8,   # refund exists but the payout didn't net it off
    "missing_payout": 4,
    "partial_settlement": 5,    # bank credit smaller than the settlement
    "unexplained_credit": 6,
    "duplicate_bank_entry": 4,
    "chargeback": 6,
    "garbled_ref": 2,           # UTR missing (base fallback test)
    "fuzzy_utr": 5,             # UTR corrupted + date shifted
    "near_miss_amount": 5,      # amount within TOL but not exact
    "noisy_description": 2,     # narration noise
}

CUSTOMERS = [
    "Aarav Textiles", "Meghna Foods", "Kiran Motors", "Sunrise Pharma", "Bharat Steels",
    "Nimbus Cloud", "Verdant Organics", "Coastal Traders", "Peak Logistics", "Zenith Retail",
    "Orchid Interiors", "Falcon Sports", "Lotus Dairy", "Anand Hardware", "Deccan Books",
    "Ivory Apparel", "Grand Spices", "Nova Electronics", "Riya Jewellers", "Metro Cafe",
]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def money(x):
    return round(x + 1e-9, 2)


def main():
    rng = random.Random(SEED)
    os.makedirs(OUT, exist_ok=True)
    orders, payments, refunds, settlements, bank, reserves = [], [], [], [], [], []
    truth = {"order_payment": {}, "payment_settlement": {}, "settlement_bank": {}, "anomalies": []}

    def anomaly(kind, ref):
        truth["anomalies"].append({"type": kind, "ref": ref})

    unpaid = set(rng.sample(range(N_ORDERS), PLANT["unpaid_order"]))
    for i in range(N_ORDERS):
        oid = f"ORD-{i + 1:05d}"
        amount = money(rng.choice([499, 999, 1499, 2499, 4999, 7999, 12999, 24999]) + rng.randint(0, 95))
        created = START + timedelta(days=rng.randint(0, DAYS - 5))
        paid = i not in unpaid
        orders.append({"order_id": oid, "customer": rng.choice(CUSTOMERS), "amount": amount,
                       "created_at": created.isoformat(), "status": "paid" if paid else "unpaid"})
        if not paid:
            anomaly("unpaid_order", oid)

    paid_orders = [o for o in orders if o["status"] == "paid"]
    idx = list(range(len(paid_orders)))
    pending = set(rng.sample(idx, PLANT["pending_settlement"]))
    fee_bad = set(rng.sample(idx, PLANT["fee_mismatch"]))
    tax_bad = set(rng.sample(idx, PLANT["tax_mismatch"]))

    for j, o in enumerate(paid_orders):
        pid = f"PAY-{j + 1:05d}"
        fee = money(o["amount"] * FEE_RATE)
        if j in fee_bad:
            fee = money(fee + rng.choice([4.0, 6.5, 9.0, -5.0]))
            anomaly("fee_mismatch", pid)
        tax = money(fee * GST)
        if j in tax_bad:
            tax = money(tax + rng.choice([3.0, 5.5, -2.5, 7.0]))
            anomaly("tax_mismatch", pid)
        net = money(o["amount"] - fee - tax)
        cap = date.fromisoformat(o["created_at"]) + timedelta(days=rng.randint(0, 1))
        payments.append({"payment_id": pid, "order_id": o["order_id"], "gross": o["amount"],
                         "fee": fee, "tax": tax, "net": net, "settlement_id": "", "captured_at": cap.isoformat()})
        truth["order_payment"][pid] = o["order_id"]
        if j in pending:
            anomaly("pending_settlement", pid)

    settleable = [p for k, p in enumerate(payments) if k not in pending]

    # refunds on settled payments; some deliberately not netted off in the payout
    refunded = rng.sample(settleable, min(N_REFUNDS, len(settleable)))
    not_deducted = set()
    for k, p in enumerate(refunded):
        rid = f"RFN-{k + 1:05d}"
        amt = money(p["gross"] * rng.choice([0.3, 0.5, 1.0]))
        rd = date.fromisoformat(p["captured_at"]) + timedelta(days=rng.randint(1, 3))
        refunds.append({"refund_id": rid, "payment_id": p["payment_id"], "amount": amt,
                        "created_at": rd.isoformat(), "settlement_id": ""})
        if k < PLANT["refund_not_deducted"]:
            not_deducted.add(rid)
    bad_ids = {r["refund_id"] for r in refunds if r["refund_id"] in not_deducted}
    ref_by_payment = {}
    for r in refunds:
        ref_by_payment.setdefault(r["payment_id"], []).append(r)

    # settle by capture day
    by_day = {}
    for p in settleable:
        by_day.setdefault(p["captured_at"], []).append(p)

    utr_seq = 1
    for i, (day, group) in enumerate(sorted(by_day.items())):
        sid = f"STL-{i + 1:05d}"
        group_refunds = [r for p in group for r in ref_by_payment.get(p["payment_id"], [])]
        gross_total = money(sum(p["gross"] for p in group))
        fee_total = money(sum(p["fee"] for p in group))
        tax_total = money(sum(p["tax"] for p in group))
        deducted = [r for r in group_refunds if r["refund_id"] not in bad_ids]
        refund_total = money(sum(r["amount"] for r in deducted))
        net_total = money(gross_total - fee_total - tax_total - refund_total)
        utr = f"UTR{utr_seq:08d}"
        utr_seq += 1
        for p in group:
            p["settlement_id"] = sid
            truth["payment_settlement"][p["payment_id"]] = sid
        for r in group_refunds:
            r["settlement_id"] = sid
        settlements.append({"settlement_id": sid, "settled_at": (date.fromisoformat(day) + timedelta(days=1)).isoformat(),
                            "gross_total": gross_total, "fee_total": fee_total, "tax_total": tax_total,
                            "refund_total": refund_total, "net_total": net_total,
                            "payment_count": len(group), "utr": utr})
        if any(r["refund_id"] in bad_ids for r in group_refunds):
            anomaly("refund_not_deducted", sid)

    # bank credits for settlements, with a few missing / partial / garbled-reference payouts
    n = len(settlements)
    pool = list(range(n))
    rng.shuffle(pool)
    m = PLANT["missing_payout"]
    partial_list = pool[m:m + PLANT["partial_settlement"]]
    missing, partial = set(pool[:m]), set(partial_list)
    reserve_backed = set(partial_list[:3])  # these shortfalls have a documented reserve behind them
    g0 = m + PLANT["partial_settlement"]
    garbled = set(pool[g0:g0 + PLANT["garbled_ref"]])
    fuzzy = set(pool[g0 + PLANT["garbled_ref"]:g0 + PLANT["garbled_ref"] + PLANT["fuzzy_utr"]])
    near_miss = set(pool[g0 + PLANT["garbled_ref"] + PLANT["fuzzy_utr"]:g0 + PLANT["garbled_ref"] + PLANT["fuzzy_utr"] + PLANT["near_miss_amount"]])
    noisy = set(pool[g0 + PLANT["garbled_ref"] + PLANT["fuzzy_utr"] + PLANT["near_miss_amount"]:g0 + PLANT["garbled_ref"] + PLANT["fuzzy_utr"] + PLANT["near_miss_amount"] + PLANT["noisy_description"]])


    bank_seq = 1
    for i, s in enumerate(settlements):
        if i in missing:
            anomaly("missing_payout", s["settlement_id"])
            continue
        bid = f"BNK-{bank_seq:05d}"
        bank_seq += 1
        # defaults
        amount = s["net_total"]
        ref = s["utr"]
        narr = f"NEFT PAYOUT {s['utr']} RAZORPAY"
        bank_date = s["settled_at"]
        if i in partial:
            shortfall = rng.choice([500, 1200, 2500, 4000])
            amount = money(s["net_total"] - shortfall)
            anomaly("partial_settlement", s["settlement_id"])
            if i in reserve_backed:
                reserves.append({"reserve_id": f"RSV-{len(reserves) + 1:05d}", "settlement_id": s["settlement_id"],
                                 "amount": money(shortfall), "date": s["settled_at"],
                                 "reason": rng.choice(["Rolling reserve hold", "Dispute reserve", "Risk hold"])})
        elif i in garbled:
            ref, narr = "", "NEFT INWARD SETTLEMENT"
        elif i in fuzzy:
            corruptions = [
                s["utr"][:-1],
                s["utr"][:-2] + s["utr"][-1],
                s["utr"][:4] + ("0" if s["utr"][4] != "0" else "O") + s["utr"][5:],
            ]
            ref = rng.choice(corruptions)
            narr = f"NEFT PAYOUT {ref} RAZORPAY"
            bank_date = (date.fromisoformat(s["settled_at"]) + timedelta(days=2)).isoformat()
        elif i in near_miss:
            delta = rng.choice([0.01, 0.02, 0.03, 0.04, -0.01, -0.02])
            amount = money(s["net_total"] + delta)
        elif i in noisy:
            narr = rng.choice([
                f"NEFT PAYOUT {s['utr']} RAZORPAY XXXX",
                f"NEFT PAYOUT {s['utr']} RAZORPAY - SETTLEMENT",
                f"NEFT PAYOUT {s['utr']} RAZORPAY / INWARD",
            ])
        bank.append({"bank_id": bid, "date": bank_date, "amount": amount,
                     "type": "credit", "ref": ref, "narration": narr})
        truth["settlement_bank"][s["settlement_id"]] = bid

    credits = [b for b in bank if b["type"] == "credit" and b["ref"]]
    for b in rng.sample(credits, min(PLANT["duplicate_bank_entry"], len(credits))):
        dup = dict(b)
        dup["bank_id"] = f"BNK-{bank_seq:05d}"
        bank_seq += 1
        bank.append(dup)
        anomaly("duplicate_bank_entry", dup["bank_id"])

    for _ in range(PLANT["unexplained_credit"]):
        bid = f"BNK-{bank_seq:05d}"
        bank_seq += 1
        d = START + timedelta(days=rng.randint(2, DAYS))
        bank.append({"bank_id": bid, "date": d.isoformat(), "amount": money(rng.randint(2000, 60000) + rng.random()),
                     "type": "credit", "ref": f"IMPS{rng.randint(10**9, 10**10):d}", "narration": "IMPS INWARD"})
        anomaly("unexplained_credit", bid)

    for o in rng.sample(paid_orders, PLANT["chargeback"]):
        bid = f"BNK-{bank_seq:05d}"
        bank_seq += 1
        d = date.fromisoformat(o["created_at"]) + timedelta(days=rng.randint(3, 8))
        bank.append({"bank_id": bid, "date": d.isoformat(), "amount": o["amount"], "type": "debit",
                     "ref": o["order_id"], "narration": f"CHARGEBACK {o['order_id']}"})
        anomaly("chargeback", bid)

    rng.shuffle(bank)
    _write("orders.csv", orders, ["order_id", "customer", "amount", "created_at", "status"])
    _write("payments.csv", payments, ["payment_id", "order_id", "gross", "fee", "tax", "net", "settlement_id", "captured_at"])
    _write("refunds.csv", refunds, ["refund_id", "payment_id", "amount", "created_at", "settlement_id"])
    _write("settlements.csv", settlements, ["settlement_id", "settled_at", "gross_total", "fee_total", "tax_total",
                                            "refund_total", "net_total", "payment_count", "utr"])
    _write("reserves.csv", reserves, ["reserve_id", "settlement_id", "amount", "reason", "date"])
    _write("bank.csv", bank, ["bank_id", "date", "amount", "type", "ref", "narration"])
    json.dump(truth, open(os.path.join(OUT, "truth.json"), "w"), indent=2)

    print(f"orders {len(orders)}  payments {len(payments)}  refunds {len(refunds)}  "
          f"settlements {len(settlements)}  bank {len(bank)}")
    print(f"planted anomalies: {len(truth['anomalies'])}  ->", OUT)


def _write(name, rows, cols):
    with open(os.path.join(OUT, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
