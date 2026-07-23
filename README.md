# Document Delta & Grounded Chat

Given two revisions of a technical document (native PDF, scanned PDF, or DXF/DWG), this
system ingests both, computes a structured **delta** (added/removed/modified, with
location and confidence), renders a human- and machine-readable **delta report**, and
answers **grounded chat** questions over both revisions and the report — every claim
carries a citation back to a specific document location or delta entry.

Built for the "Applied AI Engineer — Document Delta & Grounded Chat" take-home.

## Quickstart

```bash
make setup                          # venv + deps
cp .env.example .env                # then add your ANTHROPIC_API_KEY
make samples                        # synthesize the 3 sample pairs (already committed, but reproducible)

make run PAIR=native_pdf            # ingest -> delta -> report (no LLM needed)
make chat PAIR=native_pdf           # interactive grounded chat (needs API key)
make eval                           # full scorecard: delta P/R/F1 + chat correctness/groundedness
make eval-no-llm                    # delta metrics only, no API key needed
make metrics                        # observability dashboard from traces/
make markup PAIR=native_pdf         # bonus: annotated delta overlay
make test                           # 24 unit tests, no API key needed
```

Everything above is a single documented command; there is no Docker dependency (see
[Observability](#observability) for why — the short version is it keeps every command
above runnable with nothing but `pip install`, no accounts, no services).

Try `make chat PAIR=native_pdf` and ask: *"Did any dimensions change near the pump?"*
or *"What changed on sheet 1?"*.

## Architecture: the canonical representation

```
data/samples/*.pdf|.dxf --[adapter]--> canonical Document --[delta engine]--> DeltaItem[]
                                              |                                    |
                                              +----------[chat retrieval]----------+
                                                            |
                                                    grounded answer + citations
```

Every format adapter (`src/ingest/pdf_native.py`, `pdf_scanned.py`, `dwg.py`) normalizes
its input into the same `Document → Sheet → Element` shape (`src/canonical/model.py`).
Nothing downstream — the delta engine, the report, the chat retrieval layer — knows or
cares whether the source was a born-digital PDF, a scan, or a DXF. Adding a 4th format
means writing one adapter that emits this shape; nothing else changes. This is the one
design decision everything else in the repo is organized around.

`Element{id, kind, bbox, text, source, confidence, meta}` — `kind` is one of
`text | dimension | note | table_cell | geometry | block`; `source` records how it was
recovered (`vector` = extracted PDF text/geometry, `ocr` = Tesseract, `cad` = DXF
entity), which the delta engine later uses to discount confidence on OCR-derived items.

## The three format adapters

| Format | Library | Notes |
|---|---|---|
| Native PDF | PyMuPDF (`fitz`) | Extracts the real text/vector layer directly; text lines classified into dimension/note/text via regex (`src/ingest/classify.py`); vector drawing ops become coarse `geometry` elements. |
| Scanned PDF | PyMuPDF (rasterize) + Tesseract OCR | Detected by "near-empty text layer + full-page image" heuristic. Rasterizes at 300 DPI (no poppler needed), runs `pytesseract.image_to_data` for word-level boxes, groups into lines, carries per-line OCR confidence into the canonical model. |
| DWG | `ezdxf` via **DXF** | See below — this is the one adapter with a real, documented constraint. |

### DWG → DXF: why, not a shortcut

True binary `.dwg` is a closed Autodesk format. The only ways to read it are Autodesk's
proprietary SDK, or the free **ODA File Converter** — a GUI/CLI binary that requires a
manual download and EULA click-through, and isn't something that can be relied on being
present in an arbitrary environment (it isn't `pip install`-able, and wasn't installed
here). Rather than fake this seam, `src/ingest/dwg.py` is built against **DXF**, the
open, textual CAD interchange format Autodesk itself ships for interoperability, parsed
with `ezdxf` (pure Python). The adapter:

- Accepts `.dxf` directly — this is the real, working, verified path (`data/samples/dxf/`).
- If handed a `.dwg`, it shells out to `ODAFileConverter` if that binary happens to be on
  `PATH` (a real, documented, optional integration point — not hypothetical code, just
  code that needs an external tool this environment doesn't have).
- If neither applies, it raises a clear, actionable error rather than silently failing
  or pretending to support something it can't (`tests/test_ingest_adapters.py::test_unsupported_dwg_without_oda_raises_clear_error`).

This is a deliberate, defensible scope cut, not an oversight — happy to go deeper on the
ODA integration path if useful.

## The delta engine: alignment is the hard part

`src/delta/align.py` builds a cost matrix over **text similarity** (`difflib`) and
**spatial proximity** (bbox center distance, normalized to the sheet diagonal) between
every element of Rev A and Rev B on a matching sheet, with kind-mismatches penalized
(a text line should basically never match a geometry blob). It solves this with
`scipy.optimize.linear_sum_assignment` (the Hungarian algorithm) rather than a greedy
nearest-match, so the result doesn't depend on element ordering.

`src/delta/engine.py` turns the alignment into typed items:
- Matched pairs with identical text and stable position → **unchanged**, no item emitted.
- Matched pairs with identical text but shifted position → **modified / moved**.
- Matched pairs with different text → **modified**, with dimension-typed elements getting
  a parsed numeric old→new comparison (`R0.50 → R0.75`, not just a string diff).
- Unmatched Rev-A elements → **removed**; unmatched Rev-B elements → **added**.
- Confidence = match score × min(source confidence of the two elements) — OCR-sourced
  elements automatically pull confidence down.

**This entire path is deterministic.** The one non-deterministic branch is
`llm_describe`, an optional callback that, if supplied, is invoked *only* for matches
whose alignment score lands in a genuinely ambiguous band (0.40–0.60) to write a
human-readable description — everything outside that band is template-generated. This
is "where the LLM lives" in the delta path, and it's isolated on purpose so the
structural output (what changed, where, how) stays reproducible run-to-run regardless of
LLM sampling variance. It's off by default (`llm_describe=None`); the demo runs the pure
deterministic path.

### Known limitation (found by the eval harness, not hidden)

On the `native_pdf` sample pair, two **unrelated** notes at the same list position
(`NOTE 2: FIELD VERIFY...` in Rev A, `NOTE 3: TORQUE ALL FASTENERS...` in Rev B) score
just above the match threshold on text+spatial similarity alone and get merged into one
false "modified" item instead of a clean removed+added pair
(`tests/test_align_and_delta.py::test_align_borderline_notes_merge_is_a_known_limitation`
reproduces this deliberately). This is a real weakness of a purely lexical+spatial
matcher — it has no notion that two sentences are topically unrelated, only that they're
in the same place and share some characters. The eval scorecard catches this
automatically (see below); the honest fix is incorporating semantic similarity
(embeddings, or routing this specific match into the LLM-assist band) into the cost
function — noted under "What's next."

## Grounded chat

- **Retrieval** (`src/chat/index.py`): BM25 lexical search over three pools — PID A
  elements, PID B elements, delta report entries. Chosen over embeddings deliberately:
  this domain is dense with exact tokens (dimension values, part numbers, note ids)
  where lexical match is a strong, zero-cost, provider-agnostic fit, and it keeps the
  whole system runnable with no embedding API key. Simple query hints boost relevance:
  "sheet N" filters to that sheet, "changed/added/removed" boosts delta-report entries.
  Trade-off: a purely paraphrased query with no shared vocabulary would retrieve worse
  than an embedding index would — see "What's next."
- **LLM client** (`src/chat/llm.py`): a small `LLMClient` interface; `AnthropicClient` is
  the concrete implementation (model, keys, thresholds all come from `.env`/`config.py`,
  never hardcoded — swap providers by writing one more class with the same signature).
  Every call captures model name, input/output token counts, and an estimated cost, and
  is itself a trace span.
- **Grounding** (`src/chat/answer.py`): the prompt requires every claim to end in a
  citation tag copied from the retrieved context (`[PID-A sheet1]`, `[D-014]`). After the
  model responds, every citation it used is **deterministically checked** against the set
  of chunks actually retrieved for that query — this is a real automated groundedness
  check, not the model's self-report. Citations that don't correspond to anything
  retrieved are stripped and logged as a warning rather than trusted.

## Observability

Homegrown tracer + structured logger (`src/observability/`), justified: it needs zero
external accounts or services, works fully offline, and keeps every `make` target in
this README self-contained — no signing up for Langfuse/LangSmith/Phoenix or standing up
Prometheus+Grafana to run the demo. The trade-off is losing their UIs; for a scoped
take-home, a JSON trace file per run plus `make metrics` felt like the better fit than
adding infra dependencies. (OpenTelemetry-compatible instrumentation would be the first
thing to add for a real deployment — see "What's next.")

- **Tracing** (`src/observability/tracing.py`): every top-level request (a delta run, a
  chat turn) gets a `Trace` with nested `Span`s — stage name, duration, input/output
  summaries, status. Written as one JSON file per trace under `traces/` and appended to
  `traces/traces.jsonl` for aggregation. Errors are captured with a stack trace on the
  span and re-raised, never swallowed.
- **Structured logging** (`src/observability/logging.py`): every log line is one JSON
  object carrying `request_id`/`trace_id` — greppable, correlatable to a trace.
- **LLM telemetry**: every `AnthropicClient.complete()` call records model, prompt,
  response, token counts, and estimated cost as a span (see `src/chat/llm.py`).
- **Metrics dashboard** (`make metrics` → `scripts/report_traces.py`): reads
  `traces/traces.jsonl` and prints latency percentiles per request kind, total LLM
  tokens/cost, cumulative delta counts, retrieval hit stats, and any failed spans.

## Evaluation harness

`make eval` runs the full pipeline (ingest → delta → chat) against all 3 labeled sample
pairs and prints a scorecard, writes `eval/results/latest.json`, and diffs against the
previous run so a regression shows up automatically.

- **Delta P/R/F1** (`eval/metrics.py::score_delta`): greedy-matches each ground-truth
  item (authored by hand, alongside the exact edit script that produced each sample pair
  — see `data/samples/*/PROVENANCE.md` — so labels are exact, not guessed after the fact)
  against predicted `DeltaItem`s by kind + sheet + a text-anchor substring check (or
  element type, for anchor-less geometry changes). Unmatched expected items are misses
  (false negatives); unmatched predicted items are unexplained (false positives) — both
  are printed in a **candid failure table**, not hidden.
- **Chat scoring**: a deterministic **citation-validity** check (from `answer.py`,
  described above) plus an **LLM-as-judge correctness** score (0/0.5/1,
  `eval/metrics.py::llm_judge_correctness`) cross-checked against a cheap deterministic
  **keyword-presence** score, so the judge isn't the only signal.

### Delta results (verified, `make eval-no-llm`)

| pair | precision | recall | F1 | tp/fp/fn |
|---|---|---|---|---|
| dxf | 1.00 | 1.00 | 1.00 | 4/0/0 |
| scanned_pdf | 1.00 | 1.00 | 1.00 | 3/0/0 |
| native_pdf | 0.83 | 0.71 | 0.77 | 5/1/2 |

The `native_pdf` miss is exactly the known limitation above, caught by the harness doing
its job.

### Judge validation

*(This section is filled in with real numbers once `make eval` runs with a live
ANTHROPIC_API_KEY — see the note at the top of this README if you're reading this before
that step ran. The judge's 0/0.5/1 scores on the `qa.jsonl` sets are spot-checked by hand
against the `expected_keywords`/`unanswerable` labels in each set.)*

## Repo layout

```
src/canonical/model.py     # the format-agnostic seam (Document/Sheet/Element)
src/ingest/                # FormatAdapter interface + 3 adapters
src/delta/                 # align.py (Hungarian matching), engine.py, report.py
src/chat/                  # index.py (BM25), llm.py (Anthropic), answer.py, cli.py
src/observability/         # tracing.py, logging.py
src/markup/overlay.py      # bonus: delta drawn back onto Rev B
src/pipeline.py            # the one ingest->delta->report code path (CLI + eval share it)
eval/                      # metrics.py, run_eval.py, datasets/<pair>/{expected_delta.json,qa.jsonl}
data/samples/<pair>/       # synthesized A/B pairs + PROVENANCE.md
scripts/                   # generate_samples.py, run_delta.py, report_traces.py
tests/                     # 24 unit tests, no API key needed
```

## What was cut, and why

- **Web UI**: chat is CLI-only. The assignment explicitly allows CLI/API/web ("your
  call"); CLI kept the reproducible-run bar lowest (no server process, no browser) for
  the time budget, at the cost of a less demo-friendly surface than a web UI would be.
- **Embeddings-based retrieval**: BM25 only (see "Grounded chat" above) — right fit for
  this token-dense domain, wrong fit for heavily-paraphrased queries.
- **Full geometry diffing**: PDF vector drawings and DXF geometry are captured as
  bounding boxes (position/size), not full shape comparison — enough to detect "this
  line/shape moved or changed extent," not enough to detect "this circle became a
  hexagon of the same bbox." Full geometric diffing (path-level comparison) was out of
  scope for the time available.
- **Real binary `.dwg` parsing**: see the DWG → DXF section above.
- **Multi-page/multi-sheet cross-references**: each sheet is aligned independently; a
  note that moved from sheet 1 to sheet 2 would show as a removal on sheet 1 and an
  addition on sheet 2, not a single "moved to sheet 2" item.

## What's next, with more time

1. **Semantic matching in the alignment cost function** — the direct fix for the known
   limitation above; would also make BM25 retrieval hybrid-capable with the same
   embedding model.
2. **OpenTelemetry-compatible export** from the existing homegrown tracer, so traces can
   flow into a real backend (Jaeger/Honeycomb/Langfuse) without changing instrumentation
   call sites — the `Span`/`Trace` shape was kept close to OTel's model on purpose.
3. **Full binary DWG support** via a documented ODA File Converter install step (already
   has the integration point in `src/ingest/dwg.py`).
4. **Cost/latency budget analysis** — the telemetry to compute this already exists in
   `traces/traces.jsonl`; a `make budget` report comparing against a target $/query and
   ms/query would be a natural next script.
5. **A minimal served UI** — the CLI's `answer_question()`/`RetrievalIndex` are already
   decoupled from the terminal loop, so a thin FastAPI wrapper is the main missing piece.
