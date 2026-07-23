"""Scanned/raster PDF adapter: no reliable text layer, so we rasterize each
page (via PyMuPDF, no poppler dependency) and recover text + bounding boxes
with Tesseract OCR. Same text -> kind classification as the native adapter,
but every element is tagged source="ocr" and carries Tesseract's own
per-word confidence (averaged per line), which the delta engine later uses
to discount confidence on OCR-derived changes.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytesseract
from PIL import Image

from src.canonical.model import Document, Sheet, Element, stable_id
from src.ingest.base import FormatAdapter
from src.ingest.classify import classify_text
from src.ingest.pdf_native import is_scanned_page
from src.observability.logging import get_logger

log = get_logger("ingest.pdf_scanned")

OCR_DPI = 300
_SCALE = OCR_DPI / 72.0  # PDF points -> pixels at OCR_DPI


class ScannedPdfAdapter(FormatAdapter):
    format_name = "pdf_scanned"

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
            return all(is_scanned_page(p) for p in doc)
        finally:
            doc.close()

    def ingest(self, path: Path, pid: str, revision: str = "") -> Document:
        doc = fitz.open(path)
        sheets: list[Sheet] = []
        try:
            for page_idx, page in enumerate(doc):
                sheet = Sheet(index=page_idx, width=page.rect.width, height=page.rect.height,
                               label=f"Sheet {page_idx + 1}")
                pix = page.get_pixmap(dpi=OCR_DPI)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

                data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
                elements = self._group_words_into_lines(data, pid, page_idx)
                sheet.elements = elements
                sheets.append(sheet)
        finally:
            doc.close()

        log.info(f"ingested scanned PDF {path.name}: {len(sheets)} sheets, "
                  f"{sum(len(s.elements) for s in sheets)} elements (OCR)")
        return Document(pid=pid, format="pdf_scanned", revision=revision,
                         source_path=str(path), sheets=sheets)

    def _group_words_into_lines(self, data: dict, pid: str, page_idx: int) -> list[Element]:
        lines: dict[tuple, list[int]] = {}
        n = len(data["text"])
        for i in range(n):
            word = data["text"][i].strip()
            if not word:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append(i)

        elements: list[Element] = []
        for key, idxs in sorted(lines.items()):
            words = [data["text"][i] for i in idxs]
            line_text = " ".join(words).strip()
            if not line_text:
                continue
            xs0 = [data["left"][i] / _SCALE for i in idxs]
            ys0 = [data["top"][i] / _SCALE for i in idxs]
            xs1 = [(data["left"][i] + data["width"][i]) / _SCALE for i in idxs]
            ys1 = [(data["top"][i] + data["height"][i]) / _SCALE for i in idxs]
            confs = [int(data["conf"][i]) for i in idxs if int(data["conf"][i]) >= 0]
            avg_conf = (sum(confs) / len(confs) / 100.0) if confs else 0.5

            kind = classify_text(line_text)
            x0, y0, x1, y1 = min(xs0), min(ys0), max(xs1), max(ys1)
            elements.append(Element(
                id=stable_id(pid, page_idx, round(x0, 1), round(y0, 1), line_text),
                kind=kind,
                bbox=(round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)),
                text=line_text,
                source="ocr",
                confidence=round(avg_conf, 3),
                meta={"ocr_word_count": len(words)},
            ))
        return elements
