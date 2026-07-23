"""The canonical representation: the format-agnostic seam.

Every ingestion adapter (native PDF, scanned PDF, DXF) normalizes into a
`Document`. Everything downstream -- the delta engine, the report, the chat
retrieval layer -- only ever sees `Document` / `Sheet` / `Element`. Adding a
4th format means writing one adapter that emits this shape; nothing else
changes.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Literal, Optional

ElementKind = Literal["text", "dimension", "note", "table_cell", "geometry", "block"]
ElementSource = Literal["vector", "ocr", "cad"]
DocFormat = Literal["pdf_native", "pdf_scanned", "dwg"]

BBox = tuple[float, float, float, float]  # x0, y0, x1, y1 in sheet-local units


def stable_id(*parts: Any) -> str:
    """Deterministic short id from content, so re-ingesting the same file
    yields the same element ids (needed for reproducible deltas/citations)."""
    h = hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return h[:12]


@dataclass
class Element:
    id: str
    kind: ElementKind
    bbox: BBox
    text: Optional[str]
    source: ElementSource
    confidence: float = 1.0
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Element":
        return Element(
            id=d["id"], kind=d["kind"], bbox=tuple(d["bbox"]), text=d.get("text"),
            source=d["source"], confidence=d.get("confidence", 1.0), meta=d.get("meta", {}),
        )

    @property
    def center(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self.bbox
        return ((x0 + x1) / 2, (y0 + y1) / 2)


@dataclass
class Sheet:
    index: int
    width: float
    height: float
    elements: list[Element] = field(default_factory=list)
    label: str = ""  # e.g. "Sheet 1", "Model Space", "Layout1"

    def to_dict(self) -> dict:
        return {
            "index": self.index, "width": self.width, "height": self.height,
            "label": self.label, "elements": [e.to_dict() for e in self.elements],
        }

    @staticmethod
    def from_dict(d: dict) -> "Sheet":
        return Sheet(
            index=d["index"], width=d["width"], height=d["height"],
            label=d.get("label", ""), elements=[Element.from_dict(e) for e in d["elements"]],
        )


@dataclass
class Document:
    pid: str
    format: DocFormat
    revision: str
    source_path: str
    sheets: list[Sheet] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "pid": self.pid, "format": self.format, "revision": self.revision,
            "source_path": self.source_path, "sheets": [s.to_dict() for s in self.sheets],
        }

    @staticmethod
    def from_dict(d: dict) -> "Document":
        return Document(
            pid=d["pid"], format=d["format"], revision=d["revision"],
            source_path=d["source_path"], sheets=[Sheet.from_dict(s) for s in d["sheets"]],
        )

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2))

    @staticmethod
    def load(path: Path) -> "Document":
        return Document.from_dict(json.loads(Path(path).read_text()))

    def element_count(self) -> int:
        return sum(len(s.elements) for s in self.sheets)

    def all_elements(self):
        for sheet in self.sheets:
            for el in sheet.elements:
                yield sheet, el
