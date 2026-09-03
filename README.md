# Kash

A finance controller for a payments merchant. It closes the full reconciliation
loop, forecasts the cash position, and reconciles every tax line — all
deterministically, in under 2ms, with measured accuracy.

## What it does

**Multi-source reconciliation** — follows money from order → payment → refund →
settlement → bank credit across 6 sources. Flags every discrepancy as a typed
exception with a reason and recommended action. Auto-resolves what it can prove,
escalates the rest.

**Forward cash forecaster** — builds the actual daily cash position from the bank
statement, projects the next 7 days using a weighted average of recent inflows,
incorporates pending settlements as known future credits, and flags any day where
the projected balance drops below the low-cash threshold.

**Tax-line matcher** — for every settlement period, computes expected GST (18% on
the 2% gateway fee) from payment-level data, matches against what was actually
charged, tracks cumulative drift, and flags any line where the variance exceeds
tolerance.

## Accuracy

Scored against a planted ground-truth file on genuinely hard data:

| Anomaly type | Planted | Caught |
|---|---|---|
| unpaid\_order | 20 | 20 |
| pending\_settlement | 15 | 15 |
| fee\_mismatch | 8 | 8 |
| tax\_mismatch | 8 | 8 |
| refund\_not\_deducted | 8 | 8 |
| missing\_payout | 4 | 4 |
| partial\_settlement | 5 | 5 |
| unexplained\_credit | 6 | 6 |
| duplicate\_bank\_entry | 4 | 4 |
| chargeback | 6 | 6 |
| **Total** | **84** | **84** |

    precision 1.0  ·  recall 1.0  ·  f1 1.0  (838 checkable records, 0 false positives)

Hard cases: garbled UTRs, near-miss amounts (±₹0.01–0.04), date-shifted bank
credits (+2 days), noisy narrations, duplicate payouts on fuzzy-matched entries.

## Run it

    python serve.py       # dashboard at http://localhost:8000

or on the command line:

    python generate.py    # build the books (writes data/)
    python run.py         # reconcile, resolve, score, write report.json

Sample output:

    processed 872 records in 0.002s
    reconciled 81.19% of value  (Rs 2149167 of 2647203)
    exceptions 84  ->  auto-resolved 22  escalated 62  (26.2% auto)
    detection accuracy vs truth -> precision 1.0  recall 1.0  f1 1.0
    confusion (over 838 checkable records) -> TP 84  FP 0  FN 0  TN 754

## Architecture

    generate.py    synthetic books + ground truth (hard anomalies seeded)
    reconcile.py   matching engine (exact UTR → fuzzy UTR → amount+date)
    resolve.py     clears safe exceptions with evidence, escalates the rest
    score.py       precision / recall against the truth file
    run.py         end-to-end pipeline (writes report.json)
    forecast.py    daily cash position + 7-day weighted projection
    tax.py         per-settlement GST reconciliation with variance tracking
    ask.py         plain-English Q&A over the close (deterministic + optional LLM)
    llm.py         optional LLM helper (Gemini / Groq / OpenAI) — off by default
    serve.py       HTTP server — /report.json · /forecast · /tax · /ask
    dashboard.html reconciliation · cash forecast · tax matcher tabs

The LLM layer is strictly optional and offline by default. Set `GEMINI_API_KEY`,
`GROQ_API_KEY`, or `OPENAI_API_KEY` to enable it. It only investigates and
explains — the engine does all the math deterministically and the score is
identical with or without it.

Pure Python, no dependencies.
