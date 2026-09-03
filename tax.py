"""Tax-line matcher.

For every settlement period, computes the expected GST (18% on the 2% gateway
fee) from the payment-level data and compares it against what was actually
charged. Produces a per-settlement tax reconciliation with variance, cumulative
drift, and a flag on any line where the absolute variance exceeds the tolerance.
"""
import csv
import os
from collections import defaultdict

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FEE_RATE = 0.02
GST_RATE = 0.18
TOL = 1.00          # flag if variance on a settlement exceeds ₹1


def tax_reconcile():
    payments = list(csv.DictReader(open(os.path.join(DATA, "payments.csv"))))
    settlements = {r["settlement_id"]: r for r in csv.DictReader(open(os.path.join(DATA, "settlements.csv")))}

    # group payments by settlement
    by_stl = defaultdict(list)
    for p in payments:
        if p["settlement_id"]:
            by_stl[p["settlement_id"]].append(p)

    lines = []
    cumulative_variance = 0.0
    total_expected = 0.0
    total_charged = 0.0

    for sid in sorted(by_stl):
        group = by_stl[sid]
        s = settlements.get(sid, {})

        expected_fee = round(sum(float(p["gross"]) * FEE_RATE for p in group), 2)
        expected_gst = round(expected_fee * GST_RATE, 2)
        charged_fee = round(sum(float(p["fee"]) for p in group), 2)
        charged_gst = round(sum(float(p["tax"]) for p in group), 2)
        fee_variance = round(charged_fee - expected_fee, 2)
        gst_variance = round(charged_gst - expected_gst, 2)
        cumulative_variance = round(cumulative_variance + gst_variance, 2)

        total_expected += expected_gst
        total_charged += charged_gst

        lines.append({
            "settlement_id": sid,
            "settled_at": s.get("settled_at", ""),
            "payments": len(group),
            "expected_fee": expected_fee,
            "charged_fee": charged_fee,
            "fee_variance": fee_variance,
            "expected_gst": expected_gst,
            "charged_gst": charged_gst,
            "gst_variance": gst_variance,
            "cumulative_gst_variance": cumulative_variance,
            "flag": abs(gst_variance) > TOL,
        })

    flagged = [l for l in lines if l["flag"]]
    summary = {
        "settlements_checked": len(lines),
        "total_expected_gst": round(total_expected, 2),
        "total_charged_gst": round(total_charged, 2),
        "total_gst_variance": round(total_charged - total_expected, 2),
        "flagged_lines": len(flagged),
        "tolerance": TOL,
    }
    return {"lines": lines, "summary": summary}
