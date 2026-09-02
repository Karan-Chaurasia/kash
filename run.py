"""End-to-end run: reconcile the books, resolve what's safe, score against truth.
Writes report.json and prints a summary. ``build`` is reused by the dashboard."""
import json
import os
import time

from reconcile import load, reconcile
from resolve import resolve
from score import score

HERE = os.path.dirname(os.path.abspath(__file__))


def build():
    data = load()
    t0 = time.perf_counter()
    result = reconcile(*data)
    result["exceptions"] = resolve(result["exceptions"])
    result["stats"]["seconds"] = round(time.perf_counter() - t0, 3)
    result["accuracy"] = score(result["exceptions"])

    ex = result["exceptions"]
    resolved = [e for e in ex if e["status"] == "resolved"]
    escalated = [e for e in ex if e["status"] == "escalate"]
    result["resolution"] = {
        "auto_resolved": len(resolved),
        "escalated": len(escalated),
        "auto_resolution_rate": round(100 * len(resolved) / len(ex), 1) if ex else 0.0,
        "resolved_without_evidence": sum(1 for e in resolved if not e["evidence"]),
        "escalated_value": round(sum(e["amount"] for e in escalated), 2),
    }

    acc, st = result["accuracy"], result["stats"]
    population = st["orders"] + st["payments"] + st["settlements"] + st["bank_entries"]
    tp, fp, fn = acc["true_positive"], acc["false_positive"], acc["false_negative"]
    tn = population - (tp + fn) - fp
    result["confusion"] = {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "population": population,
                           "specificity": round(tn / (tn + fp), 4) if (tn + fp) else 1.0}
    return result


def main():
    result = build()
    with open(os.path.join(HERE, "report.json"), "w") as f:
        json.dump(result, f, indent=2)
    s, a, r = result["stats"], result["accuracy"], result["resolution"]
    print(f"processed {s['records']} records in {s['seconds']}s")
    print(f"reconciled {s['reconciled_pct']}% of value  (Rs {s['reconciled_value']:.0f} of {s['settled_value']:.0f})")
    print(f"exceptions {s['exceptions']}  ->  auto-resolved {r['auto_resolved']}  escalated {r['escalated']}  "
          f"({r['auto_resolution_rate']}% auto, {r['resolved_without_evidence']} resolved without evidence)")
    print(f"detection accuracy vs truth -> precision {a['precision']}  recall {a['recall']}  f1 {a['f1']}")
    c = result["confusion"]
    print(f"confusion (over {c['population']} checkable records) -> "
          f"TP {c['tp']}  FP {c['fp']}  FN {c['fn']}  TN {c['tn']}")


if __name__ == "__main__":
    main()
