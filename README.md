# Kash

A reconciliation engine for a payments merchant. It follows the money from an
order to its gateway payment, through any refund, into a settlement batch, and
out to the bank credit — and flags whatever doesn't line up.

Finance teams mostly do this by hand in spreadsheets. Kash runs it in one
command, decides which exceptions it can clear on its own, escalates the rest,
and keeps a full audit trail.

## What it checks

- Orders that were never paid
- Payments captured but not yet settled
- Gateway fee or GST that doesn't match the expected working
- Refunds that weren't netted off the payout
- Settlement batches whose payout never reached the bank, or arrived short
- Bank credits with no settlement behind them
- Duplicate payouts and chargebacks

## How it works

Six sources are matched in passes: orders, payments, refunds, settlements,
reserves, and the bank statement. A payout on a settlement is
gross − fee − GST − refunds, so it is checked against its own components before
being tied to a bank credit.

Matching uses exact keys first (order id, UTR). When the bank feed is noisy —
garbled UTR, truncated reference, character substitution like `0`→`O`, or a
date-shifted credit — the engine falls back to fuzzy UTR matching (truncation
and non-digit substitutions only, to avoid false matches on sequential UTRs),
then to amount + date window as a last resort.

Anything that doesn't tie out becomes a typed exception with a reason. Kash then
tries to clear each one, but only with evidence: a payout short by exactly a
documented reserve is cleared; a shortfall it can't account for is escalated to
a human rather than guessed.

The LLM layer (`llm.py`, `ask.py`) is strictly optional and offline by default.
Set `GEMINI_API_KEY`, `GROQ_API_KEY`, or `OPENAI_API_KEY` to enable it. When
active, it only investigates and explains — the engine does all the math
deterministically and the score is identical with or without it.

## Accuracy

The books are synthetic and seeded, and ship with a ground-truth file so the
matcher is scored on real precision and recall — on genuinely hard data:

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

Hard cases in the data: garbled UTRs, near-miss amounts (±₹0.01–0.04),
date-shifted bank credits (+2 days), noisy narrations, and duplicate payouts on
fuzzy-matched entries.

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

## Files

    generate.py    synthetic books + ground truth (hard anomalies seeded)
    reconcile.py   matching engine (exact → fuzzy UTR → amount+date)
    resolve.py     clears safe exceptions, escalates the rest
    score.py       precision / recall against the truth
    run.py         end to end (writes report.json)
    ask.py         answers plain questions about the close
    llm.py         optional LLM helper (Gemini / Groq / OpenAI)
    serve.py       serves the dashboard
    dashboard.html the finance close view

Pure Python, no dependencies.
