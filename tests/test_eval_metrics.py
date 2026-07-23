from eval.metrics import score_delta, keyword_correctness
from src.delta.engine import DeltaItem


def _item(id, kind, element_type, sheet=0, text_a=None, text_b=None, description=""):
    return DeltaItem(id=id, kind=kind, element_type=element_type, sheet=sheet, sheet_label="Sheet 1",
                      description=description, confidence=1.0, text_a=text_a, text_b=text_b)


def test_score_delta_perfect_match():
    expected = [{"kind": "modified", "type": "dimension", "sheet": 0, "text_anchor": "R0.50"}]
    predicted = [_item("D-001", "modified", "dimension", text_a="R0.50", text_b="R0.75")]
    score = score_delta(expected, predicted)
    assert score.precision == 1.0 and score.recall == 1.0 and score.f1 == 1.0


def test_score_delta_miss_and_extra():
    expected = [{"kind": "removed", "type": "note", "sheet": 0, "text_anchor": "NOTE THAT SHOULD BE REMOVED"}]
    predicted = [_item("D-001", "modified", "note", text_a="NOTE THAT SHOULD BE REMOVED", text_b="SOMETHING ELSE")]
    score = score_delta(expected, predicted)
    assert score.true_positives == 0
    assert score.false_negatives == 1
    assert score.false_positives == 1
    assert len(score.misses) == 1
    assert len(score.unexplained) == 1


def test_score_delta_no_anchor_matches_by_type():
    expected = [{"kind": "modified", "type": "moved", "sheet": 0, "text_anchor": None}]
    predicted = [_item("D-001", "modified", "moved", text_a=None, text_b=None)]
    score = score_delta(expected, predicted)
    assert score.true_positives == 1


def test_keyword_correctness_unanswerable():
    assert keyword_correctness([], "I don't have enough information in the provided documents.", True) == 1.0
    assert keyword_correctness([], "Sure, here's the answer.", True) == 0.0


def test_keyword_correctness_partial():
    score = keyword_correctness(["R0.50", "R0.75"], "The value changed to R0.75.", False)
    assert score == 0.5
