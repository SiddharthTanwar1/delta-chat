"""Grounded answer generation: retrieve -> constrained prompt -> answer, then
*deterministically* validate every citation the model emitted actually
corresponds to a chunk we handed it. This is a real automated groundedness
check (not the model's self-report) -- invalid citations are flagged/
stripped rather than trusted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.chat.index import Chunk, RetrievalIndex
from src.chat.llm import LLMClient
from src.observability.logging import get_logger
from src.observability.tracing import Trace

log = get_logger("chat.answer")

SYSTEM_PROMPT = """You are a grounded assistant for engineering document revisions. You are given
excerpts from two document revisions (PID-A = base, PID-B = revised) and a delta report describing
what changed between them.

Rules:
- Answer ONLY using the provided context. Never invent content that isn't there.
- Every factual claim must end with a citation tag copied EXACTLY from the context labels shown,
  e.g. [PID-A sheet1] or [D-005]. Do not invent citation ids.
- If the context does not contain enough information to answer, say so plainly
  ("I don't have enough information in the provided documents to answer that.") -- do not guess.
- Be concise and specific (mention actual values/sheet numbers when present)."""

_CITATION_RE = re.compile(r"\[([A-Za-z0-9\-_ ]+)\]")


@dataclass
class AnswerResult:
    text: str
    raw_text: str
    citations_valid: list[str] = field(default_factory=list)
    citations_invalid: list[str] = field(default_factory=list)
    retrieved: list[Chunk] = field(default_factory=list)
    grounded: bool = True
    llm_cost_usd: float = 0.0


def _build_context(chunks: list[Chunk]) -> str:
    lines = []
    for c in chunks:
        lines.append(f"[{c.source_id}] {c.text}")
    return "\n".join(lines)


def answer_question(question: str, index: RetrievalIndex, llm: LLMClient, top_k: int = 8,
                     trace: Trace | None = None) -> AnswerResult:
    span_ctx = trace.span("retrieve", input={"question": question}) if trace else None
    if span_ctx:
        span_ctx.__enter__()
    try:
        chunks = index.search(question, top_k=top_k)
    finally:
        if span_ctx:
            span_ctx.output = {"n_chunks": len(chunks), "ids": [c.source_id for c in chunks]}
            span_ctx.__exit__(None, None, None)

    valid_ids = {c.source_id for c in chunks}

    if not chunks:
        return AnswerResult(
            text="I don't have enough information in the provided documents to answer that.",
            raw_text="", retrieved=[], grounded=True,
        )

    context = _build_context(chunks)
    user_prompt = f"Context:\n{context}\n\nQuestion: {question}"

    resp = llm.complete(SYSTEM_PROMPT, user_prompt, max_tokens=600, trace=trace, span_name="chat_answer")

    found = _CITATION_RE.findall(resp.text)
    valid = [c for c in found if c in valid_ids]
    invalid = [c for c in found if c not in valid_ids]

    cleaned = resp.text
    for bad in set(invalid):
        cleaned = cleaned.replace(f"[{bad}]", "[unverified citation removed]")
        log.warning(f"stripped ungrounded citation '[{bad}]' not present in retrieved context")

    grounded = len(invalid) == 0

    return AnswerResult(
        text=cleaned, raw_text=resp.text, citations_valid=valid, citations_invalid=invalid,
        retrieved=chunks, grounded=grounded, llm_cost_usd=resp.cost_usd,
    )
