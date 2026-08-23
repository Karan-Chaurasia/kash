"""Decide which exceptions are safe to clear automatically and which go to a human.

Nothing is auto-resolved without evidence that fully explains it. A partial payout
is only cleared when its shortfall matches a documented reserve; a variance we
can't account for is escalated rather than guessed at. That "won't pretend"
behaviour is the point of a controller versus a matcher.
"""
import csv
import os

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TOL = 0.05


def _reserves():
    path = os.path.join(DATA, "reserves.csv")
    out = {}
    if os.path.exists(path):
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                out.setdefault(r["settlement_id"], []).append(
                    {"reserve_id": r["reserve_id"], "amount": float(r["amount"]), "reason": r["reason"]})
    return out


def resolve(exceptions):
    reserves = _reserves()
    return [{**e, **_classify(e, reserves)} for e in exceptions]


def _classify(e, reserves):
    t = e["type"]
    if t == "pending_settlement":
        return _ok(0.99, [e["ref"]], "Captured but not yet settled; normal payout timing.")
    if t == "duplicate_bank_entry":
        return _ok(0.99, [e["ref"]], "Exact duplicate of a payout already matched; ignore the copy.")
    if t == "partial_settlement":
        for rv in reserves.get(e["ref"], []):
            if abs(rv["amount"] - e["amount"]) <= TOL:
                return _ok(0.98, [e["ref"], rv["reserve_id"]],
                           f"Shortfall equals a documented reserve ({rv['reason']}, {rv['amount']}).")
        return _escalate(0.42, [e["ref"]], "Payout short with no matching reserve; needs review.")
    reasons = {
        "unpaid_order": "Open receivable; someone must chase or cancel it.",
        "missing_payout": "Payout never arrived; a person must follow up with the bank.",
        "fee_mismatch": "Fee looks wrong; a human should raise the dispute.",
        "tax_mismatch": "GST working looks wrong; needs a human check.",
        "refund_not_deducted": "Refund not netted from the payout; needs a correcting entry.",
        "unexplained_credit": "Unknown money in; identity must be confirmed by a person.",
        "chargeback": "Chargeback needs evidence gathering and representation.",
    }
    return _escalate(0.5, [e["ref"]], reasons.get(t, "Not auto-resolvable without more evidence."))


def _ok(conf, evidence, text):
    return {"status": "resolved", "confidence": conf, "evidence": evidence, "resolution": text}


def _escalate(conf, evidence, text):
    return {"status": "escalate", "confidence": conf, "evidence": evidence, "resolution": text}
