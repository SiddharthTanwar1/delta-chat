"""Native (born-digital) PDF adapter: extracts the text/vector layer directly
via PyMuPDF -- no OCR needed. Classifies each text line into
text/dimension/note via `classify.py`, plus coarse geometry elements from the
page's vector drawing ops (useful for "did geometry move" style deltas even
without full CAD structure).
"""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

from src.canonical.model import Document, Sheet, Element, stable_id
from src.ingest.base import FormatAdapter
from src.ingest.classify import classify_text
from src.observability.logging import get_logger

log = get_logger("ingest.pdf_native")


def is_scanned_page(page: "fitz.Page") -> bool:
    """A page is 'scanned' if it has essentially no extractable text but does
    have a large embedded image -- i.e. it's a photo/scan, not born-digital."""
    text = page.get_text("text").strip()
    if len(text) > 40:
        return False
    images = page.get_images(full=True)
    if not images:
        return False
    rect_area = page.rect.width * page.rect.height
    for img in images:
        xref = img[0]
        try:
            bbox_list = page.get_image_bbox(img)
        except Exception:
            continue
        img_area = bbox_list.width * bbox_list.height
        if rect_area > 0 and img_area / rect_area > 0.6:
            return True
    return False


class NativePdfAdapter(FormatAdapter):
    format_name = "pdf_native"

    def sniff(self, path: Path) -> bool:
        if path.suffix.lower() != ".pdf":
            return False
        try:
            doc = fitz.open(path)
        except Exception:
            return False
        try:
            if doc.page_count == 0:
                return False
            # native iff at least one page has a real text layer
            return any(not is_scanned_page(p) for p in doc)
        finally:
            doc.close()

    def ingest(self, path: Path, pid: str, revision: str = "") -> Document:
        doc = fitz.open(path)
        sheets: list[Sheet] = []
        try:
            for page_idx, page in enumerate(doc):
                sheet = Sheet(index=page_idx, width=page.rect.width, height=page.rect.height,
                               label=f"Sheet {page_idx + 1}")
                elements: list[Element] = []

                text_dict = page.get_text("dict")
                for block in text_dict.get("blocks", []):
                    for line in block.get("lines", []):
                        spans = line.get("spans", [])
                        if not spans:
                            continue
                        line_text = "".join(s.get("text", "") for s in spans).strip()
                        if not line_text:
                            continue
                        x0 = min(s["bbox"][0] for s in spans)
                        y0 = min(s["bbox"][1] for s in spans)
                        x1 = max(s["bbox"][2] for s in spans)
                        y1 = max(s["bbox"][3] for s in spans)
                        kind = classify_text(line_text)
                        elements.append(Element(
                            id=stable_id(pid, page_idx, round(x0, 1), round(y0, 1), line_text),
                            kind=kind,
                            bbox=(round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)),
                            text=line_text,
                            source="vector",
                            confidence=1.0,
                            meta={"font": spans[0].get("font", "")},
                        ))

                for i, drawing in enumerate(page.get_drawings()):
                    rect = drawing.get("rect")
                    if rect is None:
                        continue
                    if rect.width < 1 or rect.height < 1:
                        continue
                    elements.append(Element(
                        id=stable_id(pid, page_idx, "geom", i, round(rect.x0, 1), round(rect.y0, 1)),
                        kind="geometry",
                        bbox=(round(rect.x0, 2), round(rect.y0, 2), round(rect.x1, 2), round(rect.y1, 2)),
                        text=None,
                        source="vector",
                        confidence=1.0,
                        meta={"n_items": len(drawing.get("items", []))},
                    ))

                sheet.elements = elements
                sheets.append(sheet)
        finally:
            doc.close()

        log.info(f"ingested native PDF {path.name}: {len(sheets)} sheets, "
                  f"{sum(len(s.elements) for s in sheets)} elements")
        return Document(pid=pid, format="pdf_native", revision=revision,
                         source_path=str(path), sheets=sheets)
