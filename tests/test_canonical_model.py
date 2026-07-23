from src.canonical.model import Document, Sheet, Element, stable_id


def test_stable_id_deterministic():
    assert stable_id("a", 1, "x") == stable_id("a", 1, "x")
    assert stable_id("a", 1, "x") != stable_id("a", 1, "y")


def test_element_center():
    e = Element(id="1", kind="text", bbox=(0, 0, 10, 20), text="hi", source="vector")
    assert e.center == (5, 10)


def test_document_roundtrip(tmp_path):
    doc = Document(pid="p1", format="pdf_native", revision="A", source_path="x.pdf", sheets=[
        Sheet(index=0, width=100, height=200, label="Sheet 1", elements=[
            Element(id="e1", kind="dimension", bbox=(1, 2, 3, 4), text="R0.5", source="vector", confidence=0.9),
        ])
    ])
    path = tmp_path / "doc.json"
    doc.save(path)
    loaded = Document.load(path)
    assert loaded.pid == doc.pid
    assert loaded.sheets[0].elements[0].text == "R0.5"
    assert loaded.element_count() == 1
