"""Smoke tests against the real synthesized sample data (data/samples/) --
verifies each adapter round-trips actual files, not just mocks."""
from pathlib import Path

import pytest

from src.ingest.base import detect_and_ingest

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "samples"


def _skip_if_missing(path: Path):
    if not path.exists():
        pytest.skip(f"{path} not generated -- run `make samples` first")


def test_native_pdf_adapter():
    path = SAMPLES / "native_pdf" / "A.pdf"
    _skip_if_missing(path)
    doc = detect_and_ingest(path, pid="t", revision="A")
    assert doc.format == "pdf_native"
    assert doc.element_count() > 10
    assert any(e.kind == "dimension" for _, e in doc.all_elements())


def test_scanned_pdf_adapter():
    path = SAMPLES / "scanned_pdf" / "A.pdf"
    _skip_if_missing(path)
    doc = detect_and_ingest(path, pid="t", revision="A")
    assert doc.format == "pdf_scanned"
    assert all(e.source == "ocr" for _, e in doc.all_elements())
    texts = " ".join(e.text or "" for _, e in doc.all_elements())
    assert "TORQUE" in texts.upper()


def test_dxf_adapter():
    path = SAMPLES / "dxf" / "A.dxf"
    _skip_if_missing(path)
    doc = detect_and_ingest(path, pid="t", revision="A")
    assert doc.format == "dwg"
    assert any(e.kind == "dimension" for _, e in doc.all_elements())
    assert any(e.kind == "geometry" for _, e in doc.all_elements())


def test_unsupported_dwg_without_oda_raises_clear_error(tmp_path):
    fake_dwg = tmp_path / "fake.dwg"
    fake_dwg.write_bytes(b"not a real dwg")
    with pytest.raises(ValueError, match="ODAFileConverter|DWG"):
        detect_and_ingest(fake_dwg, pid="t", revision="A")
