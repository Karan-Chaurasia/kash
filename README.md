# Kosh

Automated reconciliation for a payments merchant. It follows the money from an
order to its gateway payment, into a settlement batch, and finally to the bank
credit, and flags anything that doesn't line up.

Most finance teams still do this by hand in spreadsheets. Kosh does it in one
command, explains every exception, and keeps an audit trail behind it.

## What it catches

- Orders that were never paid
- Payments captured but not yet settled
- Gateway fees that don't match the expected rate
- Settlement batches whose payout never reached the bank
- Bank credits with no settlement behind them
- Duplicate payouts
- Refunds and chargebacks

## How it works

Four sources are matched in passes: orders, gateway payments, settlements, and
the bank statement. Exact keys go first (order id, UTR reference); when a
payout's reference is missing, it falls back to matching by amount and date.
Whatever can't be tied out becomes a typed exception with a reason and a
suggested next step.

The books here are synthetic and seeded, and they ship with a ground-truth file,
so the matcher is scored on real precision and recall rather than a demo that
only looks right.

## Run it

    python generate.py    # build the books (writes data/)
    python run.py         # reconcile, score, write report.json

Sample output:

    reconciled 83.33% of value  (Rs 13,38,909 of 16,06,755)
    exceptions raised: 52
    accuracy vs truth -> precision 1.0  recall 1.0  f1 1.0

## Files

    generate.py   synthetic books + ground truth
    reconcile.py  the matching engine
    score.py      precision / recall against the truth
    run.py        end to end

Pure Python, no dependencies.
