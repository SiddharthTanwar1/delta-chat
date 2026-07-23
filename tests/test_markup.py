from pathlib import Path

import pytest

from src.ingest.base import detect_and_ingest
from src.delta.engine import compute_delta
from src.markup.overlay import markup

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "samples"


def _skip_if_missing(path: Path):
    if not path.exists():
        pytest.skip(f"{path} not generated -- run `make samples` first")


def test_markup_pdf_writes_annotations(tmp_path):
    a, b = SAMPLES / "native_pdf" / "A.pdf", SAMPLES / "native_pdf" / "B.pdf"
    _skip_if_missing(a); _skip_if_missing(b)
    doc_a = detect_and_ingest(a, pid="a", revision="A")
    doc_b = detect_and_ingest(b, pid="b", revision="B")
    items = compute_delta(doc_a, doc_b, match_min=0.35, move_threshold=12.0)
    out = markup(doc_b, items, tmp_path)
    assert out.exists()

    import fitz
    pdf = fitz.open(out)
    n_annots = sum(1 for _ in pdf[0].annots())
    pdf.close()
    assert n_annots == len([i for i in items if (i.bbox_b or i.bbox_a) is not None])


def test_markup_dxf_adds_layer(tmp_path):
    a, b = SAMPLES / "dxf" / "A.dxf", SAMPLES / "dxf" / "B.dxf"
    _skip_if_missing(a); _skip_if_missing(b)
    doc_a = detect_and_ingest(a, pid="a", revision="A")
    doc_b = detect_and_ingest(b, pid="b", revision="B")
    items = compute_delta(doc_a, doc_b, match_min=0.35, move_threshold=12.0)
    out = markup(doc_b, items, tmp_path)
    assert out.exists()

    import ezdxf
    dxf = ezdxf.readfile(out)
    assert "MARKUP" in dxf.layers
    markup_entities = [e for e in dxf.modelspace() if e.dxf.layer == "MARKUP"]
    assert len(markup_entities) > 0
