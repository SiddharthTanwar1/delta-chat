"""Synthesizes the 3 sample document pairs used for the demo and the eval
harness. Because we author both the Rev A -> Rev B edits AND the resulting
ground-truth delta labels here, in the same place, the eval labels are exact
-- not guessed after the fact. Run with `make samples`.

Writes:
  data/samples/<pair>/{A,B}.<ext>  + PROVENANCE.md
  eval/datasets/<pair>/expected_delta.json + qa.jsonl
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

import ezdxf
import fitz
from PIL import Image, ImageFilter
from reportlab.lib.pagesizes import landscape
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "samples"
DATASETS = ROOT / "eval" / "datasets"
PAGE = landscape((792, 612))  # 11x8.5in


def _ensure_dirs(pair: str) -> tuple[Path, Path]:
    sdir = SAMPLES / pair
    ddir = DATASETS / pair
    sdir.mkdir(parents=True, exist_ok=True)
    ddir.mkdir(parents=True, exist_ok=True)
    return sdir, ddir


# ---------------------------------------------------------------- native PDF
def _draw_titleblock(c: canvas.Canvas, rev: str):
    w, h = PAGE
    c.setFont("Helvetica-Bold", 14)
    c.drawString(30, h - 30, "PUMP STATION P-101 -- PIPING ARRANGEMENT")
    c.setFont("Helvetica", 10)
    c.drawString(30, h - 46, f"DWG NO. PS-101-01   REV {rev}   SCALE 1:50")
    c.rect(w - 160, 20, 140, 50, stroke=1, fill=0)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(w - 150, 55, "TITLE BLOCK")
    c.setFont("Helvetica", 9)
    c.drawString(w - 150, 40, f"REVISION: {rev}")
    c.drawString(w - 150, 28, "DRAWN BY: J. OKAFOR")


def gen_native_pair():
    pair = "native_pdf"
    sdir, ddir = _ensure_dirs(pair)
    w, h = PAGE

    def build(path: Path, rev: str, radius_label: str, notes: list[str], valve_x: float):
        c = canvas.Canvas(str(path), pagesize=PAGE)
        _draw_titleblock(c, rev)

        # schematic: pump circle + pipe line + valve label
        c.circle(180, h - 220, 30, stroke=1, fill=0)
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(180, h - 224, "P-101")
        c.line(210, h - 220, 420, h - 220)
        c.setFont("Helvetica", 9)
        c.drawString(230, h - 210, radius_label)  # dimension near the pump
        c.drawString(valve_x, h - 245, "VALVE V-12")
        c.circle(valve_x - 8, h - 232, 6, stroke=1, fill=0)

        # dimension callouts
        c.setFont("Helvetica", 9)
        c.drawString(450, h - 220, "12'-6\"")
        c.drawString(450, h - 240, "Ø2.25")
        c.drawString(450, h - 260, "±0.010")

        # notes block
        c.setFont("Helvetica-Bold", 9)
        c.drawString(30, 160, "GENERAL NOTES:")
        c.setFont("Helvetica", 8)
        y = 145
        for n in notes:
            c.drawString(30, y, n)
            y -= 14

        # small parts table
        c.setFont("Helvetica-Bold", 8)
        table_x, table_y = 450, 160
        headers = ["ITEM", "QTY", "DESC"]
        rows = [["1", "1", "PUMP CENTRIFUGAL"], ["2", "2", "VALVE GATE 2IN"], ["3", "4", "FLANGE ANSI 150"]]
        for i, hcell in enumerate(headers):
            c.drawString(table_x + i * 80, table_y, hcell)
        c.setFont("Helvetica", 8)
        for r, row in enumerate(rows):
            for i, cell in enumerate(row):
                c.drawString(table_x + i * 80, table_y - 14 * (r + 1), cell)

        c.showPage()
        c.save()

    build(sdir / "A.pdf", "A", "R0.50",
          ["NOTE 1: ALL DIMENSIONS IN INCHES UNLESS NOTED",
           "NOTE 2: FIELD VERIFY ALL DIMENSIONS PRIOR TO FABRICATION"],
          valve_x=300)
    build(sdir / "B.pdf", "B", "R0.75",
          ["NOTE 1: ALL DIMENSIONS IN INCHES UNLESS NOTED",
           "NOTE 3: TORQUE ALL FASTENERS TO 45 FT-LB"],
          valve_x=340)

    (sdir / "PROVENANCE.md").write_text(
        "# native_pdf sample pair\n\n"
        "Synthesized with reportlab (`scripts/generate_samples.py::gen_native_pair`).\n"
        "Both A.pdf and B.pdf are born-digital (real text/vector layer) so the native "
        "PDF adapter applies. Rev B differs from Rev A by exactly 4 edits:\n\n"
        "1. Dimension near the pump changed: `R0.50` -> `R0.75`.\n"
        "2. `NOTE 2: FIELD VERIFY ALL DIMENSIONS PRIOR TO FABRICATION` removed.\n"
        "3. `NOTE 3: TORQUE ALL FASTENERS TO 45 FT-LB` added.\n"
        "4. `VALVE V-12` label moved (x shifted 300 -> 340 pt).\n"
    )

    expected_delta = [
        {"kind": "modified", "type": "dimension", "sheet": 0, "text_anchor": "R0.50",
         "expected_new_text": "R0.75", "description": "Radius near the pump changed from R0.50 to R0.75"},
        {"kind": "removed", "type": "note", "sheet": 0,
         "text_anchor": "NOTE 2: FIELD VERIFY ALL DIMENSIONS PRIOR TO FABRICATION"},
        {"kind": "added", "type": "note", "sheet": 0,
         "text_anchor": "NOTE 3: TORQUE ALL FASTENERS TO 45 FT-LB"},
        {"kind": "modified", "type": "moved", "sheet": 0, "text_anchor": "VALVE V-12",
         "description": "Valve V-12 label moved"},
    ]
    (ddir / "expected_delta.json").write_text(json.dumps(expected_delta, indent=2))

    qa = [
        {"question": "What changed on sheet 1?", "expects_delta_refs": True,
         "expected_keywords": ["R0.50", "R0.75", "NOTE 2", "NOTE 3", "VALVE V-12"]},
        {"question": "Did any dimensions change near the pump?", "expects_delta_refs": True,
         "expected_keywords": ["R0.50", "R0.75"]},
        {"question": "Was anything removed between the two revisions?", "expects_delta_refs": True,
         "expected_keywords": ["NOTE 2"]},
        {"question": "What does note 1 say?", "expects_delta_refs": False,
         "expected_keywords": ["ALL DIMENSIONS IN INCHES"]},
        {"question": "What changed on sheet 5?", "expects_delta_refs": False,
         "expected_keywords": ["not", "no"], "unanswerable": True},
    ]
    with (ddir / "qa.jsonl").open("w") as f:
        for row in qa:
            f.write(json.dumps(row) + "\n")

    print(f"[native_pdf] wrote {sdir}/A.pdf, B.pdf + ground truth")


# --------------------------------------------------------------- scanned PDF
def gen_scanned_pair():
    pair = "scanned_pdf"
    sdir, ddir = _ensure_dirs(pair)
    w, h = PAGE

    def build_clean_pdf(tmp_path: Path, rev: str, torque_val: str, note: str):
        c = canvas.Canvas(str(tmp_path), pagesize=PAGE)
        c.setFont("Helvetica-Bold", 22)
        c.drawString(40, h - 60, "AS-BUILT FIELD SHEET -- VALVE STATION V-9")
        c.setFont("Helvetica", 16)
        c.drawString(40, h - 100, f"REVISION {rev}")
        c.setFont("Helvetica", 16)
        c.drawString(40, h - 160, f"TORQUE SPEC: {torque_val} FT-LB")
        c.setFont("Helvetica", 16)
        c.drawString(40, h - 200, note)
        c.setFont("Helvetica", 16)
        c.drawString(40, h - 240, "INSPECTED BY: R. TANAKA")
        c.showPage()
        c.save()

    def rasterize_as_scan(tmp_pdf: Path, out_pdf: Path, seed: int):
        src = fitz.open(tmp_pdf)
        page = src[0]
        pix = page.get_pixmap(dpi=200)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        img = img.rotate(0.6, expand=False, fillcolor=(255, 255, 255))
        img = img.filter(ImageFilter.GaussianBlur(radius=0.6))
        random.seed(seed)
        pixels = img.load()
        for _ in range(int(img.width * img.height * 0.002)):
            x = random.randrange(img.width)
            y = random.randrange(img.height)
            pixels[x, y] = (random.randint(150, 210),) * 3
        src.close()

        out = fitz.open()
        page = out.new_page(width=pix.width, height=pix.height)
        img_path = out_pdf.with_suffix(".tmp.png")
        img.save(img_path)
        page.insert_image(page.rect, filename=str(img_path))
        out.save(out_pdf)
        out.close()
        img_path.unlink()

    tmp_a = sdir / "_clean_A.pdf"
    tmp_b = sdir / "_clean_B.pdf"
    build_clean_pdf(tmp_a, "A", "45", "NOTE: FLANGE GASKET REPLACED 2024-03-01")
    build_clean_pdf(tmp_b, "B", "60", "NOTE: FLANGE GASKET REPLACED 2025-01-15")
    rasterize_as_scan(tmp_a, sdir / "A.pdf", seed=1)
    rasterize_as_scan(tmp_b, sdir / "B.pdf", seed=2)
    tmp_a.unlink()
    tmp_b.unlink()

    (sdir / "PROVENANCE.md").write_text(
        "# scanned_pdf sample pair\n\n"
        "Synthesized with reportlab + PyMuPDF + Pillow "
        "(`scripts/generate_samples.py::gen_scanned_pair`). A clean PDF is built with "
        "reportlab, then rasterized at 200 DPI, given a 0.6deg rotation, a light "
        "Gaussian blur, and ~0.2% salt noise, then re-saved as an image-only PDF page "
        "(no text layer) -- so the scanned-PDF adapter (OCR path) is exercised for "
        "real, not stubbed. Rev B differs from Rev A by 2 edits:\n\n"
        "1. `TORQUE SPEC: 45 FT-LB` -> `TORQUE SPEC: 60 FT-LB`.\n"
        "2. Gasket-replacement date note: `2024-03-01` -> `2025-01-15`.\n"
    )

    expected_delta = [
        {"kind": "modified", "type": "dimension", "sheet": 0, "text_anchor": "TORQUE SPEC",
         "expected_new_text": "60", "description": "Torque spec changed from 45 to 60 ft-lb"},
        {"kind": "modified", "type": "note", "sheet": 0, "text_anchor": "FLANGE GASKET REPLACED",
         "expected_new_text": "2025-01-15", "description": "Gasket replacement date updated"},
    ]
    (ddir / "expected_delta.json").write_text(json.dumps(expected_delta, indent=2))

    qa = [
        {"question": "What is the torque spec on the valve station sheet?", "expects_delta_refs": False,
         "expected_keywords": ["60"]},
        {"question": "Did the torque spec change between revisions?", "expects_delta_refs": True,
         "expected_keywords": ["45", "60"]},
        {"question": "When was the flange gasket replaced according to the latest revision?",
         "expects_delta_refs": False, "expected_keywords": ["2025"]},
    ]
    with (ddir / "qa.jsonl").open("w") as f:
        for row in qa:
            f.write(json.dumps(row) + "\n")

    print(f"[scanned_pdf] wrote {sdir}/A.pdf, B.pdf + ground truth")


# --------------------------------------------------------------------- DXF
def gen_dxf_pair():
    pair = "dxf"
    sdir, ddir = _ensure_dirs(pair)

    def build(path: Path, dim_value: float, line_end_y: float, add_block: bool, remove_label: bool):
        doc = ezdxf.new("R2018")
        msp = doc.modelspace()
        msp.add_text("PUMP P-201", dxfattribs={"height": 5, "layer": "TEXT"}).set_placement((0, 40))
        msp.add_mtext("GENERAL NOTES: SEE SPEC 4471 FOR MATERIAL", dxfattribs={"char_height": 3}).set_location((0, 60))
        msp.add_circle((20, 20), radius=8, dxfattribs={"layer": "EQUIPMENT"})
        msp.add_line((30, 20), (80, line_end_y), dxfattribs={"layer": "PIPING"})
        if not remove_label:
            msp.add_text("TEMP LABEL", dxfattribs={"height": 3, "layer": "TEXT"}).set_placement((85, 5))

        # p2 is placed so the dimension's real geometric measurement equals
        # dim_value exactly -- get_measurement() reads geometry, not text,
        # so the ground-truth value must live in the points themselves.
        dim = msp.add_linear_dim(
            base=(30, 30), p1=(30, 20), p2=(30 + dim_value, 20),
            dxfattribs={"layer": "DIMENSIONS"},
        )
        dim.render()

        if add_block:
            block = doc.blocks.new(name="VALVE_SYM")
            block.add_circle((0, 0), radius=2)
            msp.add_blockref("VALVE_SYM", (55, 25), dxfattribs={"layer": "EQUIPMENT"})

        doc.saveas(path)

    build(sdir / "A.dxf", dim_value=24.000, line_end_y=20, add_block=False, remove_label=False)
    build(sdir / "B.dxf", dim_value=30.000, line_end_y=50, add_block=True, remove_label=True)

    (sdir / "PROVENANCE.md").write_text(
        "# dxf sample pair (DWG surrogate)\n\n"
        "Synthesized with `ezdxf` (`scripts/generate_samples.py::gen_dxf_pair`). See "
        "README 'DWG -> DXF' for why DXF (not binary DWG) is the real input format for "
        "the CAD adapter. Rev B differs from Rev A by 3 edits:\n\n"
        "1. Linear dimension value changed: `24.000` -> `30.000`.\n"
        "2. Piping LINE endpoint moved: `(80, 20)` -> `(80, 32)`.\n"
        "3. `TEMP LABEL` text removed; a `VALVE_SYM` block instance added near the "
        "   equipment.\n"
    )

    expected_delta = [
        {"kind": "modified", "type": "dimension", "sheet": 0, "text_anchor": "24.000",
         "expected_new_text": "30.000", "description": "Linear dimension changed from 24.000 to 30.000"},
        {"kind": "modified", "type": "moved", "sheet": 0, "text_anchor": "LINE",
         "description": "Piping line endpoint moved"},
        {"kind": "removed", "type": "text", "sheet": 0, "text_anchor": "TEMP LABEL"},
        {"kind": "added", "type": "block", "sheet": 0, "text_anchor": "VALVE_SYM"},
    ]
    (ddir / "expected_delta.json").write_text(json.dumps(expected_delta, indent=2))

    qa = [
        {"question": "What is the current value of the linear dimension?", "expects_delta_refs": False,
         "expected_keywords": ["30"]},
        {"question": "Did the dimension value change between revisions?", "expects_delta_refs": True,
         "expected_keywords": ["24", "30"]},
        {"question": "Was any equipment block added in the latest revision?", "expects_delta_refs": True,
         "expected_keywords": ["VALVE_SYM", "added"]},
    ]
    with (ddir / "qa.jsonl").open("w") as f:
        for row in qa:
            f.write(json.dumps(row) + "\n")

    print(f"[dxf] wrote {sdir}/A.dxf, B.dxf + ground truth")


if __name__ == "__main__":
    gen_native_pair()
    gen_scanned_pair()
    gen_dxf_pair()
    print("All sample pairs generated.")
