# Kash

A reconciliation tool for a payments merchant. It follows the money from an order
to its gateway payment, through any refund, into a settlement batch, and out to
the bank credit, and flags whatever doesn't line up.

Finance teams mostly do this by hand in spreadsheets. Kash runs it in one command,
decides which exceptions it can clear on its own, escalates the rest, and keeps an
audit trail.

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
reserves and the bank statement. A payout on a settlement is
gross - fee - GST - refunds, so it is checked against its own components before
being tied to a bank credit. Matching uses exact keys first (order id, UTR); when
the UTR is missing from the bank feed it falls back to amount and date.

Anything that doesn't tie out becomes a typed exception with a reason. Kash then
tries to clear each one, but only with evidence: a payout short by exactly a
documented reserve is cleared, while a shortfall it can't account for is escalated
to a human rather than guessed.

The books are synthetic and seeded, and ship with a ground-truth file, so the
matcher is scored on real precision and recall.

## Run it

    python serve.py       # dashboard at http://localhost:8000 (builds the books if needed)

or on the command line:

    python generate.py    # build the books (writes data/)
    python run.py         # reconcile, resolve, score, write report.json

Sample output:

    processed 872 records in 0.01s
    reconciled 81.47% of value  (Rs 21,56,667 of 26,47,203)
    exceptions 84  ->  auto-resolved 22  escalated 62
    detection accuracy -> precision 1.0  recall 1.0  f1 1.0

## Files

    generate.py   synthetic books + ground truth
    reconcile.py  the matching engine
    resolve.py    clears safe exceptions, escalates the rest
    score.py      precision / recall against the truth
    run.py         end to end (writes report.json)
    ask.py         answers plain questions about the close
    serve.py       serves the dashboard
    dashboard.html the finance close view

Pure Python, no dependencies.
