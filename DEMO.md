# Demo walkthrough

Run these two commands from the repo root (after `make setup` and adding a real
`ANTHROPIC_API_KEY` to `.env`).

## 1. Delta

```
$ make run PAIR=native_pdf
```

Produces `reports/native_pdf/delta.json` + `delta.md`. Six real changes detected between
`data/samples/native_pdf/A.pdf` and `B.pdf`:

```
[D-001] Note changed: 'DWG NO. PS-101-01   REV A   SCALE 1:50' → '...REV B...'
[D-002] Text 'VALVE V-12' moved
[D-003] Geometry '(unlabeled element)' moved
[D-004] Text changed: 'REVISION: A' → 'REVISION: B'
[D-005] Dimension changed: R0.50 → R0.75
[D-006] Note changed: 'NOTE 2: FIELD VERIFY...' → 'NOTE 3: TORQUE ALL FASTENERS...'
```

(D-006 is the documented aligner limitation described in the README — the eval harness
catches it and scores it as a miss + an unexplained item, rather than the system
silently getting it wrong unnoticed.)

Bonus markup: `make markup PAIR=native_pdf` draws these six changes back onto Rev B as
colored boxes (`reports/native_pdf/markup_B.pdf`).

## 2. Grounded chat

```
$ make chat PAIR=native_pdf
Ingesting A.pdf + B.pdf and computing delta...
Delta report: reports/native_pdf/delta.md (6 changes)
Grounded chat ready. Ask about either revision or what changed. Ctrl-D to exit.

> Did any dimensions change near the pump?
```

*(Filled in with the real model output once run live with an API key — see README
"Judge validation" note.)*

## 3. Eval scorecard

```
$ make eval
```

*(Filled in with real scorecard output alongside the README once run live with an API
key. `make eval-no-llm` output — delta metrics only — is already captured in the README
"Delta results" table.)*
