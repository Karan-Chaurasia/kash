"""End-to-end run: reconcile the books, score against truth, print a report and
write report.json for the dashboard."""
import json
import os

from reconcile import load, reconcile
from score import score

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    result = reconcile(*load())
    result["accuracy"] = score(result["exceptions"])
    json.dump(result, open(os.path.join(HERE, "report.json"), "w"), indent=2)

    s, a = result["stats"], result["accuracy"]
    print(f"reconciled {s['reconciled_pct']}% of value  "
          f"(Rs {s['reconciled_value']:.0f} of {s['settled_value']:.0f})")
    print(f"exceptions raised: {s['exceptions']}")
    print(f"accuracy vs truth -> precision {a['precision']}  recall {a['recall']}  f1 {a['f1']}  "
          f"(fp {a['false_positive']}, fn {a['false_negative']})")
    print("per anomaly type (caught/planted):")
    for t, v in a["per_type"].items():
        print(f"  {t:24s} {v['caught']}/{v['planted']}")


if __name__ == "__main__":
    main()
