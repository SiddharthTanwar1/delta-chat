# native_pdf sample pair

Synthesized with reportlab (`scripts/generate_samples.py::gen_native_pair`).
Both A.pdf and B.pdf are born-digital (real text/vector layer) so the native PDF adapter applies. Rev B differs from Rev A by exactly 4 edits:

1. Dimension near the pump changed: `R0.50` -> `R0.75`.
2. `NOTE 2: FIELD VERIFY ALL DIMENSIONS PRIOR TO FABRICATION` removed.
3. `NOTE 3: TORQUE ALL FASTENERS TO 45 FT-LB` added.
4. `VALVE V-12` label moved (x shifted 300 -> 340 pt).
