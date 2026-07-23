"""Shared text -> element-kind classification, used by both PDF adapters
(native and scanned) so the same heuristics apply regardless of how the text
was recovered (vector extraction vs. OCR).
"""
from __future__ import annotations

import re

_DIM_PATTERNS = [
    r"\d+(\.\d+)?\s*(mm|cm|m|in|ft)\b",       # 12.5 mm, 3 in
    r"\d+'-\d+(\.\d+)?\"?",                    # 12'-6"
    r"[⌀Ø]\s*\d+(\.\d+)?",                     # diameter callouts
    r"\bR\s*\d+(\.\d+)?\b",                    # radius callouts
    r"±\s*\d+(\.\d+)?",                        # tolerances
    r"\d+(\.\d+)?\s*°",                        # angles
    r"^\d+(\.\d+)?\"?$",                       # bare number, optionally with "
]
_DIM_RE = re.compile("|".join(f"(?:{p})" for p in _DIM_PATTERNS), re.IGNORECASE)

_NOTE_RE = re.compile(r"^\s*note\b", re.IGNORECASE)


def classify_text(text: str) -> str:
    """Return one of: dimension | note | text."""
    t = (text or "").strip()
    if not t:
        return "text"
    if _NOTE_RE.match(t):
        return "note"
    if _DIM_RE.search(t):
        return "dimension"
    word_count = len(t.split())
    if word_count >= 6:
        return "note"
    return "text"


_NUMERIC_RE = re.compile(r"-?\d+(?:\.\d+)?")


def extract_numeric_value(text: str) -> float | None:
    """Pull the first numeric value out of a dimension string, e.g.
    "12.50 mm" -> 12.5, for delta engine's dimension-value comparison."""
    m = _NUMERIC_RE.search(text or "")
    return float(m.group()) if m else None
