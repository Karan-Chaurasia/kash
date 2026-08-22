"""Reconciliation engine.

Walks the money trail order -> payment -> settlement -> bank across four sources
and matches each hop with deterministic rules. Anything that doesn't tie out is
raised as a typed exception with a reason and a suggested action, and every
decision is written to an audit trail.
"""
import csv
import os
from datetime import date

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TOL = 0.05
FEE_RATE = 0.02
GST_ON_FEE = 0.18

ACTIONS = {
    "unpaid_order": "Chase the customer or cancel the order.",
    "pending_settlement": "Expected in the next payout cycle; escalate if aged.",
    "fee_mismatch": "Raise a fee dispute with the gateway.",
    "settlement_total_mismatch": "Recompute the batch; a payment net looks wrong.",
    "missing_payout": "Payout not received; follow up with the bank/gateway.",
    "payout_amount_mismatch": "Partial or adjusted payout; verify deductions.",
    "unexplained_credit": "Unknown inward credit; identify the source.",
    "duplicate_bank_entry": "Duplicate credit; reverse or ignore the copy.",
    "refund": "Refund debit matched to its order.",
    "chargeback": "Chargeback debit; gather evidence and represent.",
    "unmatched_debit": "Outgoing debit with no source; investigate.",
}


def _num(bid):
    return int(bid.split("-")[1])


def _expected_fee(gross):
    return round(gross * FEE_RATE * (1 + GST_ON_FEE) + 1e-9, 2)


def load():
    def read(name):
        with open(os.path.join(DATA, name), newline="") as f:
            return list(csv.DictReader(f))

    orders = {r["order_id"]: {**r, "amount": float(r["amount"])} for r in read("orders.csv")}
    payments = [{**r, "gross": float(r["gross"]), "fee": float(r["fee"]), "net": float(r["net"])}
                for r in read("payments.csv")]
    settlements = {r["settlement_id"]: {**r, "net_total": float(r["net_total"]),
                                        "payment_count": int(r["payment_count"])} for r in read("settlements.csv")}
    bank = [{**r, "amount": float(r["amount"])} for r in read("bank.csv")]
    return orders, payments, settlements, bank


def reconcile(orders, payments, settlements, bank):
    exceptions, audit, links = [], [], []

    def flag(kind, ref, amount, reason):
        exceptions.append({"type": kind, "ref": ref, "amount": round(amount, 2),
                           "reason": reason, "action": ACTIONS.get(kind, "Review.")})

    def note(step, detail):
        audit.append({"step": step, "detail": detail})

    pay_by_order = {p["order_id"]: p for p in payments}

    # order <-> payment
    for oid, o in orders.items():
        p = pay_by_order.get(oid)
        if not p:
            flag("unpaid_order", oid, o["amount"], f"Order {oid} has no payment.")
            continue
        if abs(p["gross"] - o["amount"]) > TOL:
            flag("amount_mismatch", p["payment_id"], p["gross"],
                 f"Payment gross {p['gross']} != order amount {o['amount']}.")
        else:
            links.append(("order->payment", oid, p["payment_id"]))
    note("order-payment", f"{len(links)} orders matched to a payment")

    # payment <-> settlement, plus fee sanity
    settled_nets = {}
    for p in payments:
        exp = _expected_fee(p["gross"])
        if abs(p["fee"] - exp) > 0.5:
            flag("fee_mismatch", p["payment_id"], p["fee"],
                 f"Fee {p['fee']} differs from expected {exp}.")
        sid = p["settlement_id"]
        if not sid:
            flag("pending_settlement", p["payment_id"], p["net"],
                 f"Payment {p['payment_id']} captured but not settled.")
        else:
            settled_nets.setdefault(sid, 0.0)
            settled_nets[sid] += p["net"]
            links.append(("payment->settlement", p["payment_id"], sid))

    for sid, s in settlements.items():
        if abs(settled_nets.get(sid, 0.0) - s["net_total"]) > TOL:
            flag("settlement_total_mismatch", sid, s["net_total"],
                 f"Sum of payment nets != settlement total for {sid}.")

    # settlement <-> bank
    credits = [b for b in bank if b["type"] == "credit"]
    debits = [b for b in bank if b["type"] == "debit"]

    by_ref = {}
    for b in credits:
        by_ref.setdefault(b["ref"], []).append(b)

    used_credit = set()
    settle_utrs = {s["utr"] for s in settlements.values()}
    reconciled_value = 0.0

    for sid, s in settlements.items():
        group = sorted(by_ref.get(s["utr"], []), key=lambda b: _num(b["bank_id"]))
        primary = group[0] if group else None
        if primary is None:
            primary = _match_by_amount_date(s, credits, used_credit)  # fallback for a garbled ref
        if primary and abs(primary["amount"] - s["net_total"]) <= TOL:
            used_credit.add(primary["bank_id"])
            links.append(("settlement->bank", sid, primary["bank_id"]))
            reconciled_value += s["net_total"]
        elif primary:
            flag("payout_amount_mismatch", sid, s["net_total"],
                 f"Payout {primary['amount']} != settlement {s['net_total']}.")
            used_credit.add(primary["bank_id"])
        else:
            flag("missing_payout", sid, s["net_total"], f"No bank credit for settlement {sid}.")
        for extra in group[1:]:
            flag("duplicate_bank_entry", extra["bank_id"], extra["amount"],
                 f"Duplicate credit for {s['utr']}.")
            used_credit.add(extra["bank_id"])

    for b in credits:
        if b["ref"] not in settle_utrs and b["bank_id"] not in used_credit:
            flag("unexplained_credit", b["bank_id"], b["amount"],
                 f"Credit {b['bank_id']} has no matching settlement.")

    # bank debits (refunds / chargebacks)
    for b in debits:
        o = orders.get(b["ref"])
        if o and "CHARGEBACK" in b["narration"].upper():
            flag("chargeback", b["bank_id"], b["amount"], f"Chargeback on {b['ref']}.")
        elif o:
            flag("refund", b["bank_id"], b["amount"], f"Refund on {b['ref']}.")
        else:
            flag("unmatched_debit", b["bank_id"], b["amount"], f"Debit {b['bank_id']} has no source.")

    note("settlement-bank", f"{int(reconciled_value)} reconciled to bank")
    total = sum(s["net_total"] for s in settlements.values())
    stats = {
        "orders": len(orders), "payments": len(payments), "settlements": len(settlements),
        "bank_entries": len(bank), "links": len(links), "exceptions": len(exceptions),
        "reconciled_value": round(reconciled_value, 2), "settled_value": round(total, 2),
        "reconciled_pct": round(100 * reconciled_value / total, 2) if total else 0.0,
    }
    return {"exceptions": exceptions, "audit": audit, "links": links, "stats": stats}


def _match_by_amount_date(s, credits, used, window=1):
    target, sd = s["net_total"], date.fromisoformat(s["settled_at"])
    hits = [b for b in credits if b["bank_id"] not in used
            and abs(b["amount"] - target) <= TOL
            and abs((date.fromisoformat(b["date"]) - sd).days) <= window]
    return hits[0] if len(hits) == 1 else None
