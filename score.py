"""Score the engine against the planted ground truth: precision / recall on the
anomalies it was supposed to catch."""
import json
import os

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PLANTED_TYPES = {"unpaid_order", "pending_settlement", "fee_mismatch", "tax_mismatch",
                 "refund_not_deducted", "missing_payout", "partial_settlement",
                 "unexplained_credit", "duplicate_bank_entry", "chargeback"}


def score(exceptions):
    with open(os.path.join(DATA, "truth.json")) as f:
        truth = json.load(f)
    planted = {(a["type"], a["ref"]) for a in truth["anomalies"]}
    found = {(e["type"], e["ref"]) for e in exceptions if e["type"] in PLANTED_TYPES}

    tp = planted & found
    fp = found - planted
    fn = planted - found
    precision = len(tp) / len(found) if found else 1.0
    recall = len(tp) / len(planted) if planted else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    per_type = {}
    for t in sorted(PLANTED_TYPES):
        p = {r for (ty, r) in planted if ty == t}
        f = {r for (ty, r) in found if ty == t}
        per_type[t] = {"planted": len(p), "caught": len(p & f)}

    return {
        "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
        "true_positive": len(tp), "false_positive": len(fp), "false_negative": len(fn),
        "false_positives": sorted(fp), "missed": sorted(fn), "per_type": per_type,
    }
