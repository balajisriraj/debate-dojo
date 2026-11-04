import pytest
from conftest import MOTION, collect, of, play

from debatedojo.llm import ScriptedLLM
from debatedojo.rubric import Claim, FactCheck, Scorecard
from debatedojo.service import Conflict, Service
from debatedojo.store import Store

STAT = "Studies show that 73% of teachers say phones are the biggest distraction in class."


def _steps(events):
    return [(e["node"], e["status"]) for e in events if e["type"] == "step" and e["status"] != "running"]


async def test_a_turn_records_checks_replies_and_advances(service):
    session = service.start(mode="debate", topic=MOTION, format_id="oxford", side="proposition")
    [events] = await play(service, session["id"], [STAT])
    nodes = [n for n, _ in _steps(events)]
    assert nodes[0] == "record" and nodes[-1] == "advance"
    assert {"fact_check", "opponent"} <= set(nodes)  # the two run in parallel, in either order
    [turn] = of(events, "turn")
    assert turn["turn"]["phase_id"] == "opening" and turn["turn"]["delivery"]["words"] == 14
    [flags] = of(events, "flags")
    assert flags["flags"][0]["verdict"] == "unsupported" and "73%" in flags["flags"][0]["claim"]
    assert flags["method"] == "knowledge"
    tokens = "".join(e["text"] for e in of(events, "token"))
    [reply] = of(events, "reply")
    assert tokens.strip() == reply["turn"]["text"]
    assert "73% of teachers" in reply["turn"]["text"]  # the opponent answers what was actually said
    assert of(events, "position")[0]["position"]["slot"]["phase_id"] == "rebuttal"
    assert events[-1]["type"] == "final" and events[-1]["status"] == "live"


async def test_the_last_turn_triggers_the_judge_and_the_coach(service):
    session = service.start(mode="sales", topic="A booking tool for clinics", persona_id="procurement-manager")
    turns = [
        "Hi, how do you handle reminders today?",
        "I understand. What are you comparing it with? Compared with the hours lost each week, the cost of doing nothing is higher.",
        "That's fair. What do people like about the current system? We run alongside it for a month.",
        "That makes sense. The busy quarter is when the manual work hurts most.",
        "Of course, she should see it. What will matter most to her?",
        "Can we book a demo with you both next Tuesday at ten?",
    ]
    results = await play(service, session["id"], turns)
    assert all(not of(r, "scorecard") for r in results[:-1])
    last = results[-1]
    [card] = of(last, "scorecard")
    [coaching] = of(last, "coaching")
    assert [s["criterion"] for s in card["scorecard"]["scores"]] == [
        "acknowledge",
        "clarify",
        "reframe",
        "evidence",
        "next_step",
    ]
    for s in card["scorecard"]["scores"]:
        assert s["explanation"] and s["quote"] and s["quote_exact"]
        assert s["quote"] in turns[s["turn"] - 1]
    assert len(coaching["coaching"]["improvements"]) == 3 and coaching["coaching"]["rewrite"]
    assert last[-1]["status"] == "finished"
    saved = service.get(session["id"])
    assert saved["report"]["scorecard"]["overall"] == card["scorecard"]["overall"]
    assert len(saved["turns"]) == 12 and saved["position"]["done"]


async def test_no_turns_after_the_session_is_over(service):
    session = service.start(mode="debate", topic=MOTION, format_id="rapid-fire")
    await play(service, session["id"], [f"Point {n}: phones distract pupils." for n in range(5)])
    with pytest.raises(Conflict):
        await collect(service.turn(session["id"], "One more"))
    with pytest.raises(Conflict):
        await collect(service.finish(session["id"]))


async def test_finishing_early_judges_what_was_said(service):
    session = service.start(
        mode="meeting", topic="Replace the status meeting with written updates", persona_id="finance-director"
    )
    with pytest.raises(Conflict):
        await collect(service.finish(session["id"]))  # nothing to judge yet
    await play(
        service, session["id"], ["I propose written updates, because the meeting takes 6 hours of team time a week."]
    )
    events = await collect(service.finish(session["id"]))
    assert [n for n, _ in _steps(events)] == ["judge", "coach"]
    assert of(events, "scorecard")[0]["scorecard"]["scores"][2]["criterion"] == "pushback"
    assert service.get(session["id"])["status"] == "finished"


async def test_timed_out_turns_are_kept_and_marked(service):
    session = service.start(mode="debate", topic=MOTION, format_id="oxford")
    [events] = await play(service, session["id"], [""], timed_out=True, duration_s=181)
    turn = of(events, "turn")[0]["turn"]
    assert turn["timed_out"] and turn["text"] == "" and turn["delivery"]["over_time"]
    assert of(events, "step")[2]["node"] in {"fact_check", "opponent"}
    assert "Nothing from you" in of(events, "reply")[0]["turn"]["text"]


class BrokenOpponent(ScriptedLLM):
    async def stream(self, system, messages, effort):
        yield "Let me"
        raise RuntimeError("connection dropped")


async def test_a_failed_reply_rolls_the_turn_back(settings):
    service = Service.from_settings(settings, llm=BrokenOpponent(), store=Store(":memory:"))
    session = service.start(mode="debate", topic=MOTION)
    with pytest.raises(RuntimeError):
        await collect(service.turn(session["id"], "Phones distract pupils."))
    after = service.get(session["id"])
    assert after["turns"] == [] and after["position"]["turn"] == 0  # the user can simply send it again


class BrokenChecker(ScriptedLLM):
    async def structured(self, system, messages, schema, effort, think=False):
        if schema is FactCheck:
            raise RuntimeError("checker down")
        return await super().structured(system, messages, schema, effort, think)


async def test_a_failed_fact_check_never_costs_the_turn(settings):
    service = Service.from_settings(settings, llm=BrokenChecker(), store=Store(":memory:"))
    session = service.start(mode="debate", topic=MOTION)
    [events] = await play(service, session["id"], [STAT])
    assert of(events, "flags")[0]["method"] == "unavailable"
    assert of(events, "reply") and events[-1]["type"] == "final"


class ForgetfulJudge(ScriptedLLM):
    calls = 0

    async def structured(self, system, messages, schema, effort, think=False):
        result = await super().structured(system, messages, schema, effort, think)
        if schema is Scorecard:
            type(self).calls += 1
            if type(self).calls == 1:
                result.scores = result.scores[:-1]  # forgets a criterion the first time
        return result


async def test_an_incomplete_scorecard_is_retried(settings):
    service = Service.from_settings(settings, llm=ForgetfulJudge(), store=Store(":memory:"))
    session = service.start(mode="debate", topic=MOTION)
    await play(service, session["id"], ["Phones distract pupils, because attention is limited."])
    events = await collect(service.finish(session["id"]))
    assert ForgetfulJudge.calls == 2
    assert len(of(events, "scorecard")[0]["scorecard"]["scores"]) == 5


class Researcher(ScriptedLLM):
    async def research(self, system, text):
        return "A national survey found a lower figure.", [{"title": "Survey", "url": "https://survey.example/report"}]

    async def structured(self, system, messages, schema, effort, think=False):
        if schema is FactCheck:
            assert "<research>" in messages[-1]["content"]
            claim = Claim(
                claim="73% of teachers say phones are the biggest distraction",
                verdict="doubtful",
                reason="The survey found a lower figure.",
                evidence_needed="The survey itself.",
                source_urls=["https://survey.example/report", "https://made-up.example"],
            )
            return FactCheck(claims=[claim])
        return await super().structured(system, messages, schema, effort, think)


async def test_web_research_can_only_cite_pages_it_actually_found(settings):
    settings.fact_check_web = True
    service = Service.from_settings(settings, llm=Researcher(), store=Store(":memory:"))
    session = service.start(mode="debate", topic=MOTION)
    [events] = await play(service, session["id"], [STAT])
    [flags] = of(events, "flags")
    assert flags["method"] == "web"
    assert flags["flags"][0]["sources"] == [{"title": "Survey", "url": "https://survey.example/report"}]
    assert flags["flags"][0]["claim"] == "73% of teachers say phones are the biggest distraction"
