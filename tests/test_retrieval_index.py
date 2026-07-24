"""Regression test for a real retrieval miss found while manually testing
chat: the query "dimensions" (plural) wasn't matching indexed "dimension"
(singular) because BM25 has no stemming -- see index.py::_stem."""
from pathlib import Path

import pytest

from src.ingest.base import detect_and_ingest
from src.delta.engine import compute_delta
from src.chat.index import RetrievalIndex

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "samples"


def _skip_if_missing(path: Path):
    if not path.exists():
        pytest.skip(f"{path} not generated -- run `make samples` first")


def test_plural_query_retrieves_singular_dimension_change():
    a, b = SAMPLES / "native_pdf" / "A.pdf", SAMPLES / "native_pdf" / "B.pdf"
    _skip_if_missing(a); _skip_if_missing(b)
    doc_a = detect_and_ingest(a, pid="a", revision="A")
    doc_b = detect_and_ingest(b, pid="b", revision="B")
    items = compute_delta(doc_a, doc_b, match_min=0.35, move_threshold=12.0)
    index = RetrievalIndex(doc_a, doc_b, items)

    results = index.search("Did any dimensions change near the pump?", top_k=5)
    assert any(c.source_id == "D-005" for c in results), \
        "expected the R0.50 -> R0.75 dimension delta to be retrieved for a pluralized query"


def test_bare_table_numbers_are_not_classified_as_dimension():
    a = SAMPLES / "native_pdf" / "A.pdf"
    _skip_if_missing(a)
    doc = detect_and_ingest(a, pid="a", revision="A")
    bare_number_elements = [e for _, e in doc.all_elements() if e.text and e.text.strip() in ("1", "2", "4")]
    assert bare_number_elements, "expected the parts-list qty column to be ingested"
    assert all(e.kind != "dimension" for e in bare_number_elements)
