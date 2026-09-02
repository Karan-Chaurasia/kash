"""Reconciliation engine.

Matches order -> payment -> refund -> settlement -> bank in passes. Exact keys
first (order id, UTR), then a fallback on amount + date when the UTR is missing.
Each settlement is checked against its own components. Whatever doesn't tie out
becomes a typed exception with a reason, and every step is logged.
"""
import csv
import os
from datetime import date

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TOL = 0.05
FEE_RATE = 0.02
GST = 0.18

ACTIONS = {
    "unpaid_order": "Chase the customer or cancel the order.",
    "amount_mismatch": "Payment amount differs from the order; verify capture.",
    "pending_settlement": "Expected in the next payout cycle; escalate if aged.",
    "fee_mismatch": "Raise a fee dispute with the gateway.",
    "tax_mismatch": "GST on the fee looks wrong; check the tax working.",
    "refund_not_deducted": "A refund was not netted from the payout; reconcile the batch.",
    "settlement_total_mismatch": "Batch total doesn't match its components; recompute.",
    "missing_payout": "Payout not received; follow up with the bank/gateway.",
    "partial_settlement": "Payout smaller than the settlement; verify deductions/holds.",
    "payout_amount_mismatch": "Payout larger than the settlement; verify.",
    "unexplained_credit": "Unknown inward credit; identify the source.",
    "duplicate_bank_entry": "Duplicate credit; reverse or ignore the copy.",
    "chargeback": "Chargeback debit; gather evidence and represent.",
    "unmatched_debit": "Outgoing debit with no source; investigate.",
}


def _num(bank_id):
    return int(bank_id.split("-")[1])


def load():
    def read(name):
        with open(os.path.join(DATA, name), newline="") as f:
            return list(csv.DictReader(f))

    orders = {r["order_id"]: {**r, "amount": float(r["amount"])} for r in read("orders.csv")}
    payments = [{**r, "gross": float(r["gross"]), "fee": float(r["fee"]), "tax": float(r["tax"]),
                 "net": float(r["net"])} for r in read("payments.csv")]
    refunds = [{**r, "amount": float(r["amount"])} for r in read("refunds.csv")]
    settlements = {r["settlement_id"]: {**r, "gross_total": float(r["gross_total"]),
                   "fee_total": float(r["fee_total"]), "tax_total": float(r["tax_total"]),
                   "refund_total": float(r["refund_total"]), "net_total": float(r["net_total"]),
                   "payment_count": int(r["payment_count"])} for r in read("settlements.csv")}
    bank = [{**r, "amount": float(r["amount"])} for r in read("bank.csv")]
    return orders, payments, refunds, settlements, bank


def reconcile(orders, payments, refunds, settlements, bank):
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
        elif abs(p["gross"] - o["amount"]) > TOL:
            flag("amount_mismatch", p["payment_id"], p["gross"],
                 f"Payment gross {p['gross']} != order amount {o['amount']}.")
        else:
            links.append(("order->payment", oid, p["payment_id"]))
    note("order-payment", f"{len(links)} orders matched to a payment")

    # payment: fee + GST sanity, and settlement membership
    for p in payments:
        exp_fee = round(p["gross"] * FEE_RATE + 1e-9, 2)
        if abs(p["fee"] - exp_fee) > 0.5:
            flag("fee_mismatch", p["payment_id"], p["fee"], f"Fee {p['fee']} != expected {exp_fee}.")
        exp_tax = round(p["fee"] * GST + 1e-9, 2)
        if abs(p["tax"] - exp_tax) > 0.5:
            flag("tax_mismatch", p["payment_id"], p["tax"], f"GST {p['tax']} != expected {exp_tax} on fee.")
        if not p["settlement_id"]:
            flag("pending_settlement", p["payment_id"], p["net"],
                 f"Payment {p['payment_id']} captured but not settled.")

    # settlement <-> its components and refunds
    pay_by_settle, ref_by_settle = {}, {}
    for p in payments:
        pay_by_settle.setdefault(p["settlement_id"], []).append(p)
    for r in refunds:
        ref_by_settle.setdefault(r["settlement_id"], []).append(r)

    for sid, s in settlements.items():
        members = pay_by_settle.get(sid, [])
        comp = round(sum(m["gross"] for m in members) - sum(m["fee"] for m in members)
                     - sum(m["tax"] for m in members) - s["refund_total"] + 1e-9, 2)
        if abs(comp - s["net_total"]) > TOL:
            flag("settlement_total_mismatch", sid, s["net_total"],
                 f"Components come to {comp}, settlement says {s['net_total']}.")
        seen_refunds = round(sum(r["amount"] for r in ref_by_settle.get(sid, [])) + 1e-9, 2)
        if abs(seen_refunds - s["refund_total"]) > TOL:
            flag("refund_not_deducted", sid, round(seen_refunds - s["refund_total"], 2),
                 f"Refunds total {seen_refunds} but only {s['refund_total']} netted from the payout.")

    # settlement <-> bank
    credits = [b for b in bank if b["type"] == "credit"]
    debits = [b for b in bank if b["type"] == "debit"]
    by_ref = {}
    for b in credits:
        if b["ref"]:
            by_ref.setdefault(b["ref"], []).append(b)

    used, settle_utrs, reconciled_value = set(), {s["utr"] for s in settlements.values()}, 0.0
    # track which bank_id was matched to which settlement (for duplicate detection on fuzzy matches)
    matched_ref_to_sid = {}  # bank ref -> sid that claimed it
    for sid, s in settlements.items():
        group = sorted(by_ref.get(s["utr"], []), key=lambda b: _num(b["bank_id"]))
        primary = group[0] if group else _match_fuzzy_utr(s, credits, used) or _match_by_amount_date(s, credits, used)
        if primary and abs(primary["amount"] - s["net_total"]) <= TOL:
            used.add(primary["bank_id"])
            links.append(("settlement->bank", sid, primary["bank_id"]))
            reconciled_value += s["net_total"]
            if primary["ref"]:
                matched_ref_to_sid[primary["ref"]] = sid
        elif primary and primary["amount"] < s["net_total"] - TOL:
            flag("partial_settlement", sid, round(s["net_total"] - primary["amount"], 2),
                 f"Payout {primary['amount']} is short of settlement {s['net_total']}.")
            used.add(primary["bank_id"])
            reconciled_value += primary["amount"]
            if primary["ref"]:
                matched_ref_to_sid[primary["ref"]] = sid
        elif primary:
            flag("payout_amount_mismatch", sid, primary["amount"],
                 f"Payout {primary['amount']} exceeds settlement {s['net_total']}.")
            used.add(primary["bank_id"])
        else:
            flag("missing_payout", sid, s["net_total"], f"No bank credit for settlement {sid}.")
        for extra in group[1:]:
            flag("duplicate_bank_entry", extra["bank_id"], extra["amount"], f"Duplicate credit for {s['utr']}.")
            used.add(extra["bank_id"])
        # catch duplicates of fuzzy-matched primary immediately
        if primary and primary["ref"] and primary["ref"] not in settle_utrs:
            for dup in credits:
                if dup["bank_id"] not in used and dup["ref"] == primary["ref"]:
                    flag("duplicate_bank_entry", dup["bank_id"], dup["amount"],
                         f"Duplicate credit for {primary['ref']} (already matched to {sid}).")
                    used.add(dup["bank_id"])

    for b in credits:
        if b["bank_id"] in used:
            continue
        if b["ref"] not in settle_utrs:
            flag("unexplained_credit", b["bank_id"], b["amount"], f"Credit {b['bank_id']} has no matching settlement.")

    for b in debits:
        if b["ref"] in orders:
            flag("chargeback", b["bank_id"], b["amount"], f"Chargeback on {b['ref']}.")
        else:
            flag("unmatched_debit", b["bank_id"], b["amount"], f"Debit {b['bank_id']} has no source.")

    note("settlement-bank", f"{int(reconciled_value)} reconciled to bank")
    total = sum(s["net_total"] for s in settlements.values())
    stats = {"orders": len(orders), "payments": len(payments), "refunds": len(refunds),
             "settlements": len(settlements), "bank_entries": len(bank),
             "records": len(orders) + len(payments) + len(refunds) + len(settlements) + len(bank),
             "links": len(links), "exceptions": len(exceptions),
             "reconciled_value": round(reconciled_value, 2), "settled_value": round(total, 2),
             "reconciled_pct": round(100 * reconciled_value / total, 2) if total else 0.0}
    return {"exceptions": exceptions, "audit": audit, "links": links, "stats": stats}


def _fuzzy_utr(a, b):
    """True when b looks like a corrupted version of a: truncated by 1 char,
    or has exactly one non-digit character substitution (e.g. 0->O, 1->I).
    Digit-only substitutions are excluded to avoid false matches on sequential UTRs.
    """
    if a == b:
        return True
    # truncation: b is a with last char removed
    if len(a) == len(b) + 1 and a[:-1] == b:
        return True
    if len(b) == len(a) + 1 and b[:-1] == a:
        return True
    # single non-digit substitution (e.g. 0->O, 1->l)
    if len(a) == len(b):
        diffs = [(x, y) for x, y in zip(a, b) if x != y]
        if len(diffs) == 1:
            x, y = diffs[0]
            # only accept if at least one side is non-digit (genuine corruption, not sequential)
            if not (x.isdigit() and y.isdigit()):
                return True
    return False


def _match_fuzzy_utr(s, credits, used):
    """Match by fuzzy UTR similarity when exact UTR lookup fails.
    When multiple fuzzy hits exist, narrow by amount to avoid cross-settlement collisions.
    Among ties, prefer the lowest bank_id (original over duplicate).
    """
    utr = s.get("utr", "")
    if not utr:
        return None
    hits = [b for b in credits if b["bank_id"] not in used and b["ref"] and _fuzzy_utr(utr, b["ref"])]
    if len(hits) == 1:
        return hits[0]
    # tiebreak by amount proximity, then lowest bank_id
    amount_hits = sorted(
        [b for b in hits if abs(b["amount"] - s["net_total"]) <= TOL],
        key=lambda b: _num(b["bank_id"])
    )
    return amount_hits[0] if amount_hits else None


def _match_by_amount_date(s, credits, used, window=3):
    target, sd = s["net_total"], date.fromisoformat(s["settled_at"])
    hits = [b for b in credits if b["bank_id"] not in used and abs(b["amount"] - target) <= TOL
            and abs((date.fromisoformat(b["date"]) - sd).days) <= window]
    return hits[0] if len(hits) == 1 else None
