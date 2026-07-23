# scanned_pdf sample pair

Synthesized with reportlab + PyMuPDF + Pillow (`scripts/generate_samples.py::gen_scanned_pair`). A clean PDF is built with reportlab, then rasterized at 200 DPI, given a 0.6deg rotation, a light Gaussian blur, and ~0.2% salt noise, then re-saved as an image-only PDF page (no text layer) -- so the scanned-PDF adapter (OCR path) is exercised for real, not stubbed. Rev B differs from Rev A by 2 edits:

1. `TORQUE SPEC: 45 FT-LB` -> `TORQUE SPEC: 60 FT-LB`.
2. Gasket-replacement date note: `2024-03-01` -> `2025-01-15`.
