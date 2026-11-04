import pytest

from debatedojo.graph import ReportError, normalise_coaching, normalise_scorecard
from debatedojo.llm import strict_schema
from debatedojo.rubric import RUBRICS, Coaching, FactCheck, Improvement, Score, Scorecard


def test_each_mode_has_its_five_criteria():
    assert [c.id for c in RUBRICS["debate"]] == ["argument", "evidence", "rebuttal", "structure", "delivery"]
    assert [c.id for c in RUBRICS["meeting"]] == ["clarity", "data", "pushback", "common_ground", "ask"]
    assert [c.id for c in RUBRICS["sales"]] == ["acknowledge", "clarify", "reframe", "evidence", "next_step"]
    assert all(c.looks_for for cs in RUBRICS.values() for c in cs)


@pytest.mark.parametrize("model", [FactCheck, Scorecard, Coaching])
def test_strict_schema_requires_everything(model):
    schema = strict_schema(model)

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            assert not {"minimum", "maximum", "default"} & set(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)


def _card(quote: str, *, drop: str | None = None, score: int = 6) -> Scorecard:
    return Scorecard(
        scores=[
            Score(criterion=c.id, score=score, explanation="Because.", quote=quote, turn=1)
            for c in RUBRICS["sales"]
            if c.id != drop
        ],
        summary="Fine.",
        decision="Deal moving",
    )


def test_scorecard_quotes_are_pinned_to_the_users_words():
    turns = ["Thanks for your time.", "I understand the price is a worry. Can we book a demo next Tuesday?"]
    card = normalise_scorecard(_card("i understand the price is a worry"), "sales", turns)
    s = card["scores"][0]
    assert s["quote"] == "I understand the price is a worry" and s["quote_exact"] and s["turn"] == 2
    # A paraphrase is snapped to the closest real sentence, and marked as not exact.
    loose = normalise_scorecard(_card("we could book a demo"), "sales", turns)["scores"][0]
    assert loose["quote"] == "Can we book a demo next Tuesday?" and not loose["quote_exact"]
    assert card["overall"] == 60 and [x["criterion"] for x in card["scores"]] == [c.id for c in RUBRICS["sales"]]


def test_scorecard_missing_a_criterion_is_rejected():
    with pytest.raises(ReportError, match="next_step"):
        normalise_scorecard(_card("x", drop="next_step"), "sales", ["x"])


def test_scorecard_scores_are_clamped_and_dashes_cleaned():
    raw = _card("Thanks", score=10)
    raw.scores[0].score = 14
    raw.summary = "Good — mostly."
    card = normalise_scorecard(raw, "sales", ["Thanks"])
    assert card["scores"][0]["score"] == 10 and card["summary"] == "Good - mostly."


def test_coaching_needs_three_improvements_and_a_real_turn():
    turns = [{"text": "First turn.", "phase_name": "Opening"}, {"text": "Second.", "phase_name": "Objections"}]
    tip = Improvement(title="Do it", why="Because", drill="Practise")
    with pytest.raises(ReportError):
        normalise_coaching(Coaching(improvements=[tip], weakest_turn=1, rewrite="x", why_stronger=["y"]), turns)
    ok = normalise_coaching(
        Coaching(improvements=[tip] * 4, weakest_turn=7, rewrite="Better.", why_stronger=["y"]), turns
    )
    assert len(ok["improvements"]) == 3
    assert ok["weakest_turn"] == 2 and ok["original"] == "Second." and ok["weakest_phase"] == "Objections"
