"""End-to-end run: reconcile the books, score against truth, print a report and
write report.json for the dashboard."""
import json
import os
import time

from reconcile import load, reconcile
from score import score

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    data = load()
    t0 = time.perf_counter()
    result = reconcile(*data)
    elapsed = time.perf_counter() - t0
    result["stats"]["seconds"] = round(elapsed, 3)
    result["accuracy"] = score(result["exceptions"])
    json.dump(result, open(os.path.join(HERE, "report.json"), "w"), indent=2)

    s, a = result["stats"], result["accuracy"]
    print(f"processed {s['records']} records in {s['seconds']}s")
    print(f"reconciled {s['reconciled_pct']}% of value  (Rs {s['reconciled_value']:.0f} of {s['settled_value']:.0f})")
    print(f"exceptions raised: {s['exceptions']}")
    print(f"accuracy vs truth -> precision {a['precision']}  recall {a['recall']}  f1 {a['f1']}  "
          f"(fp {a['false_positive']}, fn {a['false_negative']})")
    print("per anomaly type (caught/planted):")
    for t, v in a["per_type"].items():
        print(f"  {t:24s} {v['caught']}/{v['planted']}")
    if a["false_positives"]:
        print("false positives:", a["false_positives"][:10])
    if a["missed"]:
        print("missed:", a["missed"][:10])


if __name__ == "__main__":
    main()
