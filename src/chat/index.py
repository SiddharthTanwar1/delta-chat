"""Retrieval over the two documents + the delta report. Lexical (BM25) by
design: this domain is dense with exact tokens (dimension values, part/sheet
numbers, note ids) where lexical match is a strong, zero-cost,
provider-agnostic fit -- no embedding API call needed. Trade-off documented
in README ("future work: hybrid with embeddings" for paraphrase-heavy
queries where lexical match alone would miss).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from rank_bm25 import BM25Okapi

from src.canonical.model import Document
from src.delta.engine import DeltaItem


@dataclass
class Chunk:
    source_id: str          # citation anchor, e.g. "PID-A p1" or "D-014"
    pool: str                # "pid_a" | "pid_b" | "delta"
    sheet: Optional[int]
    text: str
    ref: dict                # enough to render a precise citation


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9°'\"±⌀ø.]+", text.lower())


def _doc_chunks(doc: Document, label: str) -> list[Chunk]:
    chunks = []
    for sheet, el in doc.all_elements():
        text = el.text or f"[{el.kind} element, no text]"
        chunks.append(Chunk(
            source_id=f"{label} sheet{sheet.index + 1}",
            pool="pid_a" if label == "PID-A" else "pid_b",
            sheet=sheet.index,
            text=f"({el.kind}) {text}",
            ref={"pid": doc.pid, "sheet": sheet.index, "element_id": el.id, "kind": el.kind},
        ))
    return chunks


def _delta_chunks(items: list[DeltaItem]) -> list[Chunk]:
    chunks = []
    for it in items:
        text = f"({it.kind}/{it.element_type}) {it.description}"
        chunks.append(Chunk(
            source_id=it.id, pool="delta", sheet=it.sheet, text=text,
            ref={"delta_id": it.id, "sheet": it.sheet, "kind": it.kind},
        ))
    return chunks


class RetrievalIndex:
    def __init__(self, doc_a: Document, doc_b: Document, delta_items: list[DeltaItem]):
        self.chunks: list[Chunk] = (
            _doc_chunks(doc_a, "PID-A") + _doc_chunks(doc_b, "PID-B") + _delta_chunks(delta_items)
        )
        corpus = [_tokenize(c.text) for c in self.chunks]
        self._bm25 = BM25Okapi(corpus) if corpus else None

    def search(self, query: str, top_k: int = 8) -> list[Chunk]:
        if not self._bm25 or not self.chunks:
            return []
        tokens = _tokenize(query)
        scores = self._bm25.get_scores(tokens)

        # query hints: "sheet N" filters, "changed/different/delta" boosts delta pool
        sheet_match = re.search(r"sheet\s*(\d+)", query.lower())
        wants_delta = bool(re.search(r"\bchang(e|ed|es)\b|\bdiffer|\bdelta\b|\badded\b|\bremoved\b|\bmodified\b",
                                      query.lower()))

        scored = list(zip(self.chunks, scores))
        boosted = []
        for chunk, score in scored:
            s = float(score)
            if sheet_match and chunk.sheet is not None and chunk.sheet != int(sheet_match.group(1)) - 1:
                s *= 0.05
            if wants_delta and chunk.pool == "delta":
                s *= 1.6
            boosted.append((chunk, s))

        boosted.sort(key=lambda cs: cs[1], reverse=True)
        return [c for c, s in boosted[:top_k] if s > 0]
