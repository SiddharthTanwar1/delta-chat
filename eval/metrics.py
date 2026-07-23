"""Delta P/R/F1 and chat correctness/groundedness scoring.

Delta matching: an expected item matches a predicted DeltaItem if kind +
sheet agree and either (a) a `text_anchor` substring is found in the
predicted item's text_a/text_b/description, or (b) there's no anchor (e.g.
a geometry move with no stable text) and element_type agrees -- matched
greedily, each predicted item consumed at most once so counts aren't
inflated.

Chat scoring combines a deterministic citation-validity check (real
groundedness, not self-report) with an LLM-as-judge correctness score
(0/0.5/1), which we spot-validate by hand against a few examples -- see
README "Judge validation".
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from src.chat.answer import AnswerResult
from src.chat.llm import LLMClient
from src.delta.engine import DeltaItem


@dataclass
class DeltaScore:
    precision: float
    recall: float
    f1: float
    true_positives: int
    false_positives: int
    false_negatives: int
    misses: list[dict] = field(default_factory=list)          # expected items not found (recall failures)
    unexplained: list[dict] = field(default_factory=list)     # predicted items with no matching expectation


def _haystack(item: DeltaItem) -> str:
    return " ".join(filter(None, [item.text_a, item.text_b, item.description])).lower()


def score_delta(expected: list[dict], predicted: list[DeltaItem]) -> DeltaScore:
    used: set[str] = set()
    tp = 0
    misses = []

    for exp in expected:
        anchor = (exp.get("text_anchor") or "").lower()
        match = None
        for p in predicted:
            if p.id in used:
                continue
            if p.kind != exp["kind"] or p.sheet != exp["sheet"]:
                continue
            if anchor:
                if anchor not in _haystack(p):
                    continue
            else:
                if exp.get("type") and p.element_type != exp["type"]:
                    continue
            match = p
            break
        if match:
            used.add(match.id)
            tp += 1
        else:
            misses.append(exp)

    fp_items = [p for p in predicted if p.id not in used]
    fn = len(misses)
    fp = len(fp_items)

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    return DeltaScore(
        precision=round(precision, 3), recall=round(recall, 3), f1=round(f1, 3),
        true_positives=tp, false_positives=fp, false_negatives=fn,
        misses=misses, unexplained=[p.to_dict() for p in fp_items],
    )


JUDGE_SYSTEM = """You are grading a grounded-chat answer for correctness against an expected answer summary.
Score strictly 0, 0.5, or 1:
- 1 = fully correct, matches the expected facts
- 0.5 = partially correct or missing some expected facts
- 0 = wrong or off-topic
Respond with ONLY a JSON object: {"score": <0|0.5|1>, "reason": "<one short sentence>"}"""


def llm_judge_correctness(question: str, expected_keywords: list[str], answer_text: str,
                           unanswerable: bool, llm: LLMClient) -> dict:
    expected_desc = (
        "The correct behavior is to say the answer is not available / not found in the documents."
        if unanswerable else
        f"A correct answer should include/reflect these facts: {expected_keywords}"
    )
    prompt = f"Question: {question}\n{expected_desc}\n\nModel's answer:\n{answer_text}"
    resp = llm.complete(JUDGE_SYSTEM, prompt, max_tokens=150)
    try:
        parsed = json.loads(resp.text.strip())
        return {"score": float(parsed["score"]), "reason": parsed.get("reason", ""), "cost_usd": resp.cost_usd}
    except Exception:
        return {"score": None, "reason": f"unparseable judge output: {resp.text!r}", "cost_usd": resp.cost_usd}


def keyword_correctness(expected_keywords: list[str], answer_text: str, unanswerable: bool) -> float:
    """Cheap deterministic fallback/cross-check alongside the LLM judge."""
    text = answer_text.lower()
    if unanswerable:
        hedge_words = ["don't have enough information", "not found", "no information", "cannot find",
                        "not available", "unable to find"]
        return 1.0 if any(h in text for h in hedge_words) else 0.0
    if not expected_keywords:
        return 1.0
    hits = sum(1 for kw in expected_keywords if kw.lower() in text)
    return round(hits / len(expected_keywords), 3)
