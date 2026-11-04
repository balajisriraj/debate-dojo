"""The scripted model is the demo and the CI opponent, so its behaviour is tested like product code."""

import pytest
from conftest import MOTION, of, play

from debatedojo.scripted import fact_check, key_point, motion_core
from debatedojo.text import DASHES, overlap


def _claims(text):
    return {c["verdict"]: c["claim"] for c in fact_check(text)["claims"]}


def test_fact_checker_flags_statistics_research_absolutes_and_superlatives():
    assert "unsupported" in _claims("Replacing an agent costs about eight thousand pounds.")
    assert "unsupported" in _claims("Research shows pupils learn less with phones nearby.")
    assert _claims("Nobody has ever benefited from a phone in class.")["doubtful"].startswith("Nobody")
    assert "doubtful" in _claims("It is the best tool on the market.")


def test_fact_checker_leaves_plans_questions_sources_and_reported_speech_alone():
    assert (
        fact_check("We will trial it for three months and stop if response times slip by ten percent.")["claims"] == []
    )
    assert fact_check("Do 40% of teachers agree?")["claims"] == []
    assert fact_check("You said everyone loses out.")["claims"] == []
    sourced = fact_check("According to the published census, 12% of households have no car.")["claims"]
    assert [c["verdict"] for c in sourced] == ["supported"]


def test_key_point_and_motion_core():
    assert motion_core("This house would ban smartphones in schools") == "ban smartphones in schools"
    assert motion_core("This house believes that cities should be car-free") == "cities should be car-free"
    assert (
        key_point("Hi. But attention is the scarcest resource in any classroom.")
        == "Attention is the scarcest resource in any classroom"
    )


@pytest.mark.parametrize(
    ("mode", "kw", "turns"),
    [
        (
            "debate",
            {"format_id": "oxford", "topic": MOTION},
            ["Phones destroy focus.", "You said a ban is blunt. Blunt rules are clear.", "In summary, focus wins."],
        ),
        (
            "debate",
            {"format_id": "lincoln-douglas", "topic": MOTION},
            [
                "My value is learning.",
                "Do you accept phones distract?",
                "Why is that liberty?",
                "What would you do instead?",
                "Learning wins.",
            ],
        ),
        (
            "meeting",
            {"topic": "Move support to a four-day week", "persona_id": "engineering-lead"},
            [
                "I propose a four-day week trial.",
                "What breaks first is cover, so we test each rota.",
                "Two people own it.",
                "We review monthly.",
                "Can we agree to start next Monday?",
            ],
        ),
        (
            "sales",
            {"topic": "A booking tool for clinics", "persona_id": "busy-founder"},
            [
                "How do you book patients today?",
                "It is a great tool.",
                "I understand, timing matters.",
                "Compared with the hours lost, it pays for itself.",
                "Of course, ask your boss.",
                "Can we book a demo next Tuesday?",
            ],
        ),
    ],
)
async def test_the_opponent_engages_every_turn_in_every_mode(service, mode, kw, turns):
    session = service.start(mode=mode, **kw)
    results = await play(service, session["id"], turns)
    for text, events in zip(turns, results, strict=True):
        reply = of(events, "reply")[0]["turn"]["text"]
        assert reply and not DASHES.search(reply)
        assert overlap(reply, text) >= 0.2, (text, reply)


async def test_the_buyer_raises_each_objection_once_then_asks_for_a_next_step(service):
    session = service.start(mode="sales", topic="A booking tool", persona_id="procurement-manager")
    replies = [
        of(e, "reply")[0]["turn"]["text"]
        for e in await play(service, session["id"], ["Hello there, thanks for the time."] * 5)
    ]
    assert (
        "price" in replies[0]
        and "already" in replies[1]
        and "quarter" in replies[2]
        and ("boss" in replies[3] or "manager" in replies[3])
    )
    assert "next step" in replies[4]


async def test_the_lincoln_douglas_opponent_answers_questions(service):
    session = service.start(mode="debate", topic=MOTION, format_id="lincoln-douglas")
    results = await play(
        service, session["id"], ["My value is learning.", "Do you accept that a notification interrupts learning?"]
    )
    reply = of(results[1], "reply")[0]["turn"]["text"]
    assert reply.startswith('You asked "Do you accept that a notification interrupts learning?"')
    assert "ask you one back" in reply
