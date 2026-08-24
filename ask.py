"""Answer plain questions about the close, straight from the report.

Deterministic and offline. If a question names a record (ORD-, PAY-, STL-, BNK-)
it explains that item; otherwise it matches a few intents (what needs review,
unresolved value, a specific exception type, or an overall summary).
"""
import re

TYPE_WORDS = {
    "fee": "fee_mismatch", "tax": "tax_mismatch", "gst": "tax_mismatch",
    "refund": "refund_not_deducted", "chargeback": "chargeback",
    "duplicate": "duplicate_bank_entry", "unpaid": "unpaid_order",
    "missing": "missing_payout", "partial": "partial_settlement",
    "pending": "pending_settlement", "unexplained": "unexplained_credit",
}


def answer(q, report):
    ql = q.lower().strip()
    ex, s, r = report["exceptions"], report["stats"], report["resolution"]

    m = re.search(r"\b((?:ord|pay|stl|bnk|rfn|rsv)-\d+)\b", q, re.I)
    if m:
        ref = m.group(1).upper()
        hits = [e for e in ex if e["ref"] == ref]
        if not hits:
            return f"{ref} reconciled cleanly, no exception was raised against it."
        out = []
        for e in hits:
            verb = "auto-resolved" if e["status"] == "resolved" else "escalated for review"
            out.append(f"{ref} ({e['type']}, Rs {e['amount']:.0f}) was {verb}. "
                       f"{e.get('resolution') or e['reason']} "
                       f"Evidence: {', '.join(e['evidence']) or '-'}.")
        return " ".join(out)

    if any(w in ql for w in ("how much", "value", "unresolved", "at risk")):
        return (f"Rs {s['reconciled_value']:.0f} of Rs {s['settled_value']:.0f} is reconciled "
                f"({s['reconciled_pct']}%). Rs {r['escalated_value']:.0f} sits in {r['escalated']} "
                f"escalated exceptions that still need a human.")

    if any(w in ql for w in ("escalat", "review", "attention", "human")):
        top = sorted((e for e in ex if e["status"] == "escalate"), key=lambda e: -e["amount"])[:5]
        body = "; ".join(f"{e['ref']} {e['type']} Rs {e['amount']:.0f}" for e in top)
        return f"{r['escalated']} exceptions need review (Rs {r['escalated_value']:.0f}). Largest: {body}."

    if "resolved" in ql or "auto" in ql:
        return (f"{r['auto_resolved']} of {s['exceptions']} exceptions were auto-resolved "
                f"({r['auto_resolution_rate']}%), each with evidence. "
                f"{r['resolved_without_evidence']} were resolved without evidence.")

    for word, kind in TYPE_WORDS.items():
        if word in ql:
            hits = [e for e in ex if e["type"] == kind]
            if not hits:
                return f"No {kind.replace('_', ' ')} exceptions in this close."
            shown = "; ".join(f"{e['ref']} Rs {e['amount']:.0f} ({e['status']})" for e in hits[:8])
            more = f" (+{len(hits) - 8} more)" if len(hits) > 8 else ""
            return f"{len(hits)} {kind.replace('_', ' ')}: {shown}{more}."

    if any(w in ql for w in ("summary", "close", "overall")) or not ql:
        a = report["accuracy"]
        return (f"Processed {s['records']} records and reconciled {s['reconciled_pct']}% of value. "
                f"{s['exceptions']} exceptions: {r['auto_resolved']} auto-resolved, {r['escalated']} escalated. "
                f"Detection precision {a['precision']}, recall {a['recall']}.")

    return ("Try a record id (e.g. STL-00007), 'what needs review', 'unresolved value', "
            "'fee mismatches', or 'summary'.")
