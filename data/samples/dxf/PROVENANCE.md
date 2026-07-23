# dxf sample pair (DWG surrogate)

Synthesized with `ezdxf` (`scripts/generate_samples.py::gen_dxf_pair`). See README 'DWG -> DXF' for why DXF (not binary DWG) is the real input format for the CAD adapter. Rev B differs from Rev A by 3 edits:

1. Linear dimension value changed: `24.000` -> `30.000`.
2. Piping LINE endpoint moved: `(80, 20)` -> `(80, 32)`.
3. `TEMP LABEL` text removed; a `VALVE_SYM` block instance added near the    equipment.
