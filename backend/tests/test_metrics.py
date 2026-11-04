import json

import pytest

from debatedojo.config import ROOT
from debatedojo.metrics import FILLERS, count_fillers, measure, summarise, word_count, words_per_minute

# The same fixture drives the browser's implementation (frontend/src/delivery.test.ts).
CASES = json.loads((ROOT.parent / "fixtures" / "delivery-cases.json").read_text())


@pytest.mark.parametrize("case", CASES["fillers"], ids=lambda c: c["text"][:30] or "empty")
def test_filler_counting_matches_the_shared_fixture(case):
    got = {k: v for k, v in count_fillers(case["text"]).items() if v}
    assert got == case["expect"]


@pytest.mark.parametrize("case", CASES["words"])
def test_word_count(case):
    assert word_count(case["text"]) == case["words"]


@pytest.mark.parametrize("case", CASES["wpm"])
def test_words_per_minute(case):
    assert words_per_minute(case["words"], case["seconds"]) == case["wpm"]


def test_every_filler_is_reported_even_when_zero():
    assert list(count_fillers("A clean sentence.")) == list(FILLERS)


def test_voice_turn_measures_pace_pause_and_talk_time():
    d = measure(
        "um so we basically need a decision today",
        source="voice",
        talk_seconds=4,
        limit_seconds=60,
        longest_pause_s=2.34,
    )
    assert d.words == 8 and d.wpm == 120.0
    assert d.filler_total == 2 and d.fillers_per_100 == 25.0
    assert d.longest_pause_s == 2.3
    assert d.talk_ratio == 0.07 and not d.over_time


def test_typed_turn_has_no_pace_or_pause():
    d = measure("A typed answer.", source="typed", talk_seconds=50, limit_seconds=30, longest_pause_s=9, over_time=True)
    assert d.wpm is None and d.longest_pause_s is None
    assert d.over_time and d.talk_ratio == 1.67


def test_session_summary_averages_spoken_turns():
    turns = [
        measure("one two three four five six", source="voice", talk_seconds=3, limit_seconds=30, longest_pause_s=1.0),
        measure(
            "um uh like you know", source="voice", talk_seconds=6, limit_seconds=30, longest_pause_s=4.0, over_time=True
        ),
        measure("typed", source="typed", talk_seconds=10, limit_seconds=30),
    ]
    s = summarise(turns)
    assert s["spoken_turns"] == 2 and s["turns"] == 3
    assert s["avg_wpm"] == 85.0  # (120 + 50) / 2
    assert s["longest_pause_s"] == 4.0
    assert s["over_time_turns"] == 1
    assert summarise([]) == {"turns": 0, "spoken_turns": 0}
