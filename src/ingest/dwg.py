"""DWG/CAD adapter.

Engineering call (documented in README): true binary .dwg is a closed
Autodesk format with no reliable pure-Python parser. The only real options
are Autodesk's proprietary SDK, or the free ODA File Converter -- a GUI/CLI
binary requiring a manual download + EULA click-through, not something we
can rely on being present in an arbitrary environment. Rather than fake this
seam, we build against DXF: the open, textual CAD interchange format
Autodesk itself publishes for interop, parsed with `ezdxf` (pure Python).

If handed a real .dwg, this adapter will shell out to `ODAFileConverter` if
it happens to be on PATH (a real, documented, optional integration point);
otherwise it raises a clear, actionable error rather than pretending to
support something it can't.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import ezdxf
from ezdxf import bbox as ezdxf_bbox

from src.canonical.model import Document, Sheet, Element, stable_id
from src.ingest.base import FormatAdapter
from src.observability.logging import get_logger

log = get_logger("ingest.dwg")

_GEOMETRY_TYPES = {"LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC", "SPLINE", "ELLIPSE"}


def _convert_dwg_to_dxf(dwg_path: Path) -> Path:
    converter = shutil.which("ODAFileConverter")
    if not converter:
        raise ValueError(
            f"Cannot ingest {dwg_path}: no pure-Python DWG parser exists (closed binary "
            "format) and ODAFileConverter is not on PATH. Install ODA File Converter "
            "(https://www.opendesign.com/guestfiles/oda_file_converter) or supply a .dxf "
            "export of this drawing instead -- see README 'DWG -> DXF' for why this is a "
            "deliberate scope cut, not a bug."
        )
        # If ODAFileConverter is available, it's a real CLI batch converter:
        # ODAFileConverter <in_dir> <out_dir> <out_ver> DXF 0 1 <filter>
    out_dir = Path(tempfile.mkdtemp())
    subprocess.run(
        [converter, str(dwg_path.parent), str(out_dir), "ACAD2018", "DXF", "0", "1", dwg_path.name],
        check=True, capture_output=True,
    )
    dxf_path = out_dir / (dwg_path.stem + ".dxf")
    if not dxf_path.exists():
        raise ValueError(f"ODAFileConverter ran but produced no output for {dwg_path}")
    return dxf_path


def _entity_bbox(entity) -> tuple[float, float, float, float] | None:
    try:
        box = ezdxf_bbox.extents([entity], fast=True)
    except Exception:
        return None
    if box is None or not box.has_data:
        return None
    return (round(box.extmin.x, 3), round(box.extmin.y, 3),
            round(box.extmax.x, 3), round(box.extmax.y, 3))


def _union(bboxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    xs0 = [b[0] for b in bboxes]; ys0 = [b[1] for b in bboxes]
    xs1 = [b[2] for b in bboxes]; ys1 = [b[3] for b in bboxes]
    return (min(xs0), min(ys0), max(xs1), max(ys1))


class DwgAdapter(FormatAdapter):
    format_name = "dwg"

    def sniff(self, path: Path) -> bool:
        return path.suffix.lower() in (".dxf", ".dwg")

    def ingest(self, path: Path, pid: str, revision: str = "") -> Document:
        if path.suffix.lower() == ".dwg":
            log.info(f"{path.name} is binary DWG; attempting ODAFileConverter -> DXF")
            path = _convert_dwg_to_dxf(path)

        dxf_doc = ezdxf.readfile(path)
        sheets: list[Sheet] = []

        layout_names = ["Model"] + [
            n for n in dxf_doc.layout_names_in_taborder() if n not in ("Model",)
        ]
        for sheet_idx, layout_name in enumerate(layout_names):
            try:
                layout = dxf_doc.modelspace() if layout_name == "Model" else dxf_doc.layout(layout_name)
            except Exception:
                continue
            elements = self._extract_elements(layout, pid, sheet_idx)
            if not elements:
                continue  # skip empty layouts (e.g. an untouched default paper-space tab)
            bboxes = [e.bbox for e in elements]
            x0, y0, x1, y1 = _union(bboxes)
            sheets.append(Sheet(index=len(sheets), width=round(x1 - x0, 2) or 100.0,
                                 height=round(y1 - y0, 2) or 100.0,
                                 label=layout_name, elements=elements))

        if not sheets:
            sheets = [Sheet(index=0, width=100.0, height=100.0, label="Model", elements=[])]

        log.info(f"ingested DXF {path.name}: {len(sheets)} sheets, "
                 f"{sum(len(s.elements) for s in sheets)} elements")
        return Document(pid=pid, format="dwg", revision=revision,
                         source_path=str(path), sheets=sheets)

    def _extract_elements(self, layout, pid: str, sheet_idx: int) -> list[Element]:
        elements: list[Element] = []
        for i, entity in enumerate(layout):
            etype = entity.dxftype()
            bbox = _entity_bbox(entity)
            if bbox is None:
                continue

            if etype == "TEXT":
                text = entity.dxf.text
                elements.append(Element(
                    id=stable_id(pid, sheet_idx, "text", i, text), kind="text", bbox=bbox,
                    text=text, source="cad", confidence=1.0,
                    meta={"layer": entity.dxf.layer, "entity": etype},
                ))
            elif etype == "MTEXT":
                text = entity.plain_text()
                elements.append(Element(
                    id=stable_id(pid, sheet_idx, "mtext", i, text), kind="note", bbox=bbox,
                    text=text, source="cad", confidence=1.0,
                    meta={"layer": entity.dxf.layer, "entity": etype},
                ))
            elif etype == "DIMENSION":
                try:
                    value = entity.get_measurement()
                except Exception:
                    value = None
                text = f"{value:.3f}" if isinstance(value, (int, float)) else (entity.dxf.text or "")
                elements.append(Element(
                    id=stable_id(pid, sheet_idx, "dim", i, text), kind="dimension", bbox=bbox,
                    text=text, source="cad", confidence=1.0,
                    meta={"layer": entity.dxf.layer, "entity": etype, "value": value},
                ))
            elif etype == "INSERT":
                elements.append(Element(
                    id=stable_id(pid, sheet_idx, "block", i, entity.dxf.name), kind="block", bbox=bbox,
                    text=entity.dxf.name, source="cad", confidence=1.0,
                    meta={"layer": entity.dxf.layer, "entity": etype, "block_name": entity.dxf.name},
                ))
            elif etype in _GEOMETRY_TYPES:
                elements.append(Element(
                    id=stable_id(pid, sheet_idx, "geom", i, etype, bbox), kind="geometry", bbox=bbox,
                    text=None, source="cad", confidence=1.0,
                    meta={"layer": entity.dxf.layer, "entity": etype},
                ))
        return elements
