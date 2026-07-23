"""Delta engine: turns an alignment into typed, located, confidence-scored
delta items. Deterministic end-to-end -- classification and confidence are
pure functions of the alignment, so the same two documents always produce
the same delta (required for reproducibility and for the eval harness to be
meaningful). The one optional non-deterministic branch is `llm_describe`,
used only for genuinely ambiguous (borderline-similarity) matches, and only
if a caller supplies an LLM client -- see README "Where the LLM lives".
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional

from src.canonical.model import Document, Element, Sheet
from src.delta.align import align_sheet, Match
from src.ingest.classify import extract_numeric_value
from src.observability.logging import get_logger
from src.observability.tracing import Trace

log = get_logger("delta.engine")

DeltaKind = str  # "added" | "removed" | "modified"

# Match scores in this band are genuinely ambiguous -- not a clean same/
# different call. Only these are eligible for LLM assist.
BORDERLINE_LOW = 0.40
BORDERLINE_HIGH = 0.60


@dataclass
class DeltaItem:
    id: str
    kind: DeltaKind
    element_type: str
    sheet: int
    sheet_label: str
    description: str
    confidence: float
    bbox_a: Optional[tuple] = None
    bbox_b: Optional[tuple] = None
    text_a: Optional[str] = None
    text_b: Optional[str] = None
    evidence: dict[str, Any] = field(default_factory=dict)
    llm_assisted: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _fmt(text: str | None, limit: int = 60) -> str:
    if not text:
        return "(unlabeled element)"
    t = text.strip()
    return t if len(t) <= limit else t[: limit - 1] + "…"


def _bbox_shift(a: Element, b: Element) -> float:
    ax, ay = a.center
    bx, by = b.center
    return math.hypot(ax - bx, ay - by)


def _describe_modified(a: Element, b: Element, kind_hint: str) -> tuple[str, str]:
    """Returns (element_type, description)."""
    if a.text == b.text:
        return "moved", f"{a.kind.capitalize()} '{_fmt(a.text)}' moved"
    if a.kind == "dimension" or b.kind == "dimension":
        va, vb = extract_numeric_value(a.text), extract_numeric_value(b.text)
        if va is not None and vb is not None and va != vb:
            return "dimension", f"Dimension changed: {_fmt(a.text)} → {_fmt(b.text)}"
        return "dimension", f"Dimension text changed: '{_fmt(a.text)}' → '{_fmt(b.text)}'"
    return b.kind, f"{b.kind.capitalize()} changed: '{_fmt(a.text)}' → '{_fmt(b.text)}'"


def _match_delta(match: Match, sheet_idx: int, sheet_label: str, move_threshold: float,
                  llm_describe: Optional[Callable[[Element, Element], str]]) -> Optional[DeltaItem]:
    a, b = match.a, match.b
    same_text = (a.text or "") == (b.text or "")
    shift = _bbox_shift(a, b)

    if same_text and shift <= move_threshold:
        return None  # genuinely unchanged

    element_type, description = _describe_modified(a, b, kind_hint=b.kind)
    if same_text and shift > move_threshold:
        element_type, description = "moved", f"{b.kind.capitalize()} '{_fmt(b.text)}' moved"

    llm_assisted = False
    if BORDERLINE_LOW <= match.score < BORDERLINE_HIGH and llm_describe is not None:
        try:
            description = llm_describe(a, b)
            llm_assisted = True
        except Exception as e:
            log.warning(f"llm_describe failed, falling back to template description: {e}")

    confidence = round(match.score * min(a.confidence, b.confidence), 3)
    return DeltaItem(
        id="", kind="modified", element_type=element_type, sheet=sheet_idx, sheet_label=sheet_label,
        description=description, confidence=confidence,
        bbox_a=a.bbox, bbox_b=b.bbox, text_a=a.text, text_b=b.text,
        evidence={"element_a_id": a.id, "element_b_id": b.id, "match_score": match.score},
        llm_assisted=llm_assisted,
    )


def compute_delta(doc_a: Document, doc_b: Document, match_min: float, move_threshold: float,
                   llm_describe: Optional[Callable[[Element, Element], str]] = None,
                   trace: Optional[Trace] = None) -> list[DeltaItem]:
    items: list[DeltaItem] = []

    sheets_a = {s.index: s for s in doc_a.sheets}
    sheets_b = {s.index: s for s in doc_b.sheets}
    all_sheet_idx = sorted(set(sheets_a) | set(sheets_b))

    for idx in all_sheet_idx:
        sa, sb = sheets_a.get(idx), sheets_b.get(idx)
        label = (sb or sa).label

        if sa is None:  # whole sheet added
            for e in sb.elements:
                items.append(_whole_sheet_item("added", e, idx, label))
            continue
        if sb is None:  # whole sheet removed
            for e in sa.elements:
                items.append(_whole_sheet_item("removed", e, idx, label))
            continue

        ctx = trace.span("align_sheet", input={"sheet": idx, "n_a": len(sa.elements), "n_b": len(sb.elements)}) \
            if trace else None
        if ctx:
            ctx.__enter__()
        try:
            result = align_sheet(sa.elements, sb.elements, match_min=match_min)
        finally:
            if ctx:
                ctx.__exit__(None, None, None)

        for match in result.matched:
            item = _match_delta(match, idx, label, move_threshold, llm_describe)
            if item:
                items.append(item)
        for e in result.unmatched_a:
            items.append(_removed_item(e, idx, label))
        for e in result.unmatched_b:
            items.append(_added_item(e, idx, label))

    for i, item in enumerate(sorted(items, key=lambda it: (it.sheet, it.kind, -it.confidence))):
        item.id = f"D-{i + 1:03d}"

    log.info(f"computed delta: {len(items)} items "
             f"(added={sum(1 for i in items if i.kind=='added')}, "
             f"removed={sum(1 for i in items if i.kind=='removed')}, "
             f"modified={sum(1 for i in items if i.kind=='modified')})")
    return items


def _added_item(e: Element, sheet_idx: int, sheet_label: str) -> DeltaItem:
    return DeltaItem(id="", kind="added", element_type=e.kind, sheet=sheet_idx, sheet_label=sheet_label,
                      description=f"{e.kind.capitalize()} added: '{_fmt(e.text)}'" if e.text
                      else f"{e.kind.capitalize()} added",
                      confidence=round(e.confidence, 3), bbox_b=e.bbox, text_b=e.text,
                      evidence={"element_b_id": e.id})


def _removed_item(e: Element, sheet_idx: int, sheet_label: str) -> DeltaItem:
    return DeltaItem(id="", kind="removed", element_type=e.kind, sheet=sheet_idx, sheet_label=sheet_label,
                      description=f"{e.kind.capitalize()} removed: '{_fmt(e.text)}'" if e.text
                      else f"{e.kind.capitalize()} removed",
                      confidence=round(e.confidence, 3), bbox_a=e.bbox, text_a=e.text,
                      evidence={"element_a_id": e.id})


def _whole_sheet_item(kind: str, e: Element, sheet_idx: int, sheet_label: str) -> DeltaItem:
    base = _added_item(e, sheet_idx, sheet_label) if kind == "added" else _removed_item(e, sheet_idx, sheet_label)
    base.description = f"[whole sheet {kind}] " + base.description
    return base
