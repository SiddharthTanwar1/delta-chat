PYTHON := .venv/bin/python
PIP := .venv/bin/pip
PAIR ?= native_pdf
export PYTHONPATH := .

.PHONY: setup samples run chat eval eval-no-llm metrics markup test clean

setup:
	python3 -m venv .venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r requirements.txt
	@echo "Now copy .env.example to .env and add your ANTHROPIC_API_KEY."

samples:
	$(PYTHON) scripts/generate_samples.py

## Ingest + delta + report only, no LLM/chat. PAIR=native_pdf|scanned_pdf|dxf
run:
	$(PYTHON) scripts/run_delta.py --pair $(PAIR)

## Interactive grounded chat over PAIR (needs ANTHROPIC_API_KEY in .env)
chat:
	$(PYTHON) -m src.chat.cli --pair $(PAIR)

## Full eval harness: delta P/R/F1 + chat correctness/groundedness scorecard
eval:
	$(PYTHON) eval/run_eval.py

## Delta-only eval, no API key needed
eval-no-llm:
	$(PYTHON) eval/run_eval.py --no-llm

## Observability dashboard: latency, LLM cost, delta counts, retrieval hit rate
metrics:
	$(PYTHON) scripts/report_traces.py

## Bonus: delta markup overlay. PAIR=native_pdf|dxf
markup:
	$(PYTHON) -m src.markup.overlay --pair $(PAIR)

test:
	$(PYTHON) -m pytest -q

clean:
	rm -rf reports eval/results/reports traces/*.json traces/*.jsonl
