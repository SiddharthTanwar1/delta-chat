"""Content alignment between two revisions -- the hard part of a delta, per
the assignment brief ("matching is the hard part, not diffing"). Builds a
cost matrix over text similarity + spatial proximity + kind agreement, then
solves optimal one-to-one assignment with the Hungarian algorithm
(scipy.optimize.linear_sum_assignment) rather than a greedy nearest-match,
so a run's alignment doesn't depend on element ordering.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from difflib import SequenceMatcher

import numpy as np
from scipy.optimize import linear_sum_assignment

from src.canonical.model import Element


@dataclass
class Match:
    a: Element
    b: Element
    score: float  # 0..1, higher = more similar


@dataclass
class AlignmentResult:
    matched: list[Match]
    unmatched_a: list[Element]
    unmatched_b: list[Element]


def _text_sim(a: str | None, b: str | None) -> float:
    if a is None and b is None:
        return 1.0
    if a is None or b is None:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _spatial_sim(a: Element, b: Element, diag: float) -> float:
    if diag <= 0:
        return 1.0
    ax, ay = a.center
    bx, by = b.center
    dist = math.hypot(ax - bx, ay - by)
    return max(0.0, 1.0 - dist / diag)


def _pair_score(a: Element, b: Element, diag: float) -> float:
    score = 0.6 * _text_sim(a.text, b.text) + 0.4 * _spatial_sim(a, b, diag)
    if a.kind != b.kind:
        score *= 0.2  # a text element should essentially never match a geometry element
    return score


def align_sheet(elements_a: list[Element], elements_b: list[Element], match_min: float) -> AlignmentResult:
    if not elements_a or not elements_b:
        return AlignmentResult(matched=[], unmatched_a=list(elements_a), unmatched_b=list(elements_b))

    all_w = [e.bbox[2] for e in elements_a + elements_b]
    all_h = [e.bbox[3] for e in elements_a + elements_b]
    diag = math.hypot(max(all_w, default=1), max(all_h, default=1)) or 1.0

    n, m = len(elements_a), len(elements_b)
    cost = np.ones((n, m))
    for i, a in enumerate(elements_a):
        for j, b in enumerate(elements_b):
            cost[i, j] = 1.0 - _pair_score(a, b, diag)

    row_ind, col_ind = linear_sum_assignment(cost)

    matched: list[Match] = []
    matched_a_idx: set[int] = set()
    matched_b_idx: set[int] = set()
    for i, j in zip(row_ind, col_ind):
        score = 1.0 - cost[i, j]
        if score >= match_min:
            matched.append(Match(a=elements_a[i], b=elements_b[j], score=round(score, 4)))
            matched_a_idx.add(i)
            matched_b_idx.add(j)

    unmatched_a = [e for i, e in enumerate(elements_a) if i not in matched_a_idx]
    unmatched_b = [e for j, e in enumerate(elements_b) if j not in matched_b_idx]
    return AlignmentResult(matched=matched, unmatched_a=unmatched_a, unmatched_b=unmatched_b)
