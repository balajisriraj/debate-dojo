"""The dojo as a LangGraph state machine.

    START ─┬─ turn ──> record ─┬─> fact_check ─┐
           │                   └─> opponent ───┴─> advance ─┬─> END          (more turns to go)
           │                                                └─> judge ─> coach ─> END
           └─ finish ───────────────────────────────────────────> judge

Every user turn is recorded with its delivery metrics, then the fact-checker and the opponent
run in parallel: the flags land on the transcript while the reply streams. When the format's
last exchange is done, the judge scores the session against the mode's rubric and the coach
turns that into advice. Each node reports progress through LangGraph's custom stream.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Literal, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from . import prompts
from .config import Settings
from .formats import Catalog, Format, overtime, plan, position
from .llm import LLM
from .metrics import Delivery, measure, summarise
from .rubric import RUBRICS, Coaching, FactCheck, Scorecard
from .store import Store
from .text import clean, closest_sentence, find_quote

log = logging.getLogger("debatedojo")


class DojoState(TypedDict, total=False):
    action: Literal["turn", "finish"]
    session_id: str
    # the user's turn, as submitted
    text: str
    input: str
    duration_s: float
    talk_seconds: float | None
    longest_pause_s: float | None
    timed_out: bool
    # what the nodes produce
    user_turn: dict
    flags: list[dict]
    reply: dict
    position: dict
    scorecard: dict
    coaching: dict


class ReportError(ValueError):
    """The model's report did not match the rubric, even after a retry."""


def _ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _emit(**event) -> None:
    get_stream_writer()(event)


def normalise_scorecard(raw: Scorecard, mode: str, user_texts: list[str]) -> dict:
    """Check the judge's card against the rubric and pin every quote to the user's own words."""
    by_id = {s.criterion: s for s in raw.scores}
    missing = [c.id for c in RUBRICS[mode] if c.id not in by_id]
    if missing:
        raise ReportError(f"The scorecard is missing: {', '.join(missing)}")
    scores = []
    for c in RUBRICS[mode]:
        s = by_id[c.id]
        located = find_quote(s.quote, user_texts)
        exact = located is not None
        if located is None:
            located = closest_sentence(s.quote, user_texts)
        turn, quote = located if located else (max(0, s.turn - 1), "")
        scores.append(
            {
                "criterion": c.id,
                "name": c.name,
                "looks_for": c.looks_for,
                "score": max(1, min(10, s.score)),
                "explanation": s.explanation.strip(),
                "quote": quote.strip(),
                "quote_exact": exact,
                "turn": turn + 1,
            }
        )
    overall = round(sum(s["score"] for s in scores) / len(scores) * 10)
    return clean(
        {"scores": scores, "overall": overall, "summary": raw.summary.strip(), "decision": raw.decision.strip()}
    )


def normalise_coaching(raw: Coaching, user_turns: list[dict]) -> dict:
    if len(raw.improvements) < 3:
        raise ReportError("The coach must give three improvements.")
    weakest = max(1, min(len(user_turns), raw.weakest_turn))
    original = user_turns[weakest - 1] if user_turns else {"text": "", "phase_name": ""}
    return clean(
        {
            "improvements": [i.model_dump() for i in raw.improvements[:3]],
            "weakest_turn": weakest,
            "weakest_phase": original["phase_name"],
            "original": original["text"],
            "rewrite": raw.rewrite.strip(),
            "why_stronger": [w.strip() for w in raw.why_stronger][:4],
        }
    )


@dataclass
class Dojo:
    llm: LLM
    store: Store
    catalog: Catalog
    settings: Settings

    def build(self):
        graph = StateGraph(DojoState)
        graph.add_node("record", self.record)
        graph.add_node("fact_check", self.fact_check)
        graph.add_node("opponent", self.opponent)
        graph.add_node("advance", self.advance)
        graph.add_node("judge", self.judge)
        graph.add_node("coach", self.coach)
        graph.add_conditional_edges(START, lambda s: s["action"], {"turn": "record", "finish": "judge"})
        graph.add_edge("record", "fact_check")
        graph.add_edge("record", "opponent")
        graph.add_edge(["fact_check", "opponent"], "advance")
        graph.add_conditional_edges("advance", self.after_advance, {"judge": "judge", "end": END})
        graph.add_edge("judge", "coach")
        graph.add_edge("coach", END)
        return graph.compile()

    # ── helpers ──
    def _session(self, state: DojoState) -> tuple[dict, Format]:
        session = self.store.session(state["session_id"])
        if session is None:
            raise KeyError(state["session_id"])
        return session, Format.model_validate(session["format"])

    def _persona(self, session: dict):
        return self.catalog.persona(session["mode"], session["persona_id"])

    # ── nodes ──
    async def record(self, state: DojoState) -> DojoState:
        started = time.perf_counter()
        _emit(type="step", node="record", status="running")
        session, fmt = self._session(state)
        pos = position(fmt, self.store.user_turn_count(session["id"]))
        if pos.done or pos.slot is None:
            raise ValueError("This session has no turns left.")
        slot = pos.slot
        duration = float(state.get("duration_s") or 0.0)
        source = state.get("input", "typed")
        talk = state.get("talk_seconds")
        delivery: Delivery = measure(
            state["text"],
            source=source,
            talk_seconds=float(talk if talk is not None else duration),
            limit_seconds=slot.seconds,
            longest_pause_s=state.get("longest_pause_s"),
            over_time=bool(state.get("timed_out")) or overtime(slot.seconds, duration),
        )
        turn = self.store.add_turn(
            session["id"],
            speaker="user",
            slot=slot.model_dump(),
            text=state["text"].strip(),
            input=source,
            duration_s=round(duration, 1),
            limit_s=slot.seconds,
            timed_out=bool(state.get("timed_out")),
            delivery=delivery.model_dump(),
        )
        _emit(type="turn", turn=turn)
        _emit(type="step", node="record", status="done", ms=_ms(started), detail=f"{delivery.words} words")
        return {"user_turn": turn}

    async def fact_check(self, state: DojoState) -> DojoState:
        started = time.perf_counter()
        turn = state["user_turn"]
        _emit(type="step", node="fact_check", status="running")
        if not turn["text"]:
            self.store.add_fact_check(turn["id"], checked=0, method="knowledge", flags=[])
            _emit(type="flags", turn_id=turn["id"], flags=[], checked=0, method="knowledge")
            _emit(type="step", node="fact_check", status="skipped", detail="nothing said")
            return {"flags": []}
        session, _ = self._session(state)
        try:
            notes, pages = "", []
            if self.settings.fact_check_web:
                notes, pages = await self.llm.research(prompts.RESEARCH_SYSTEM, turn["text"])
            result = await self.llm.structured(
                prompts.fact_check_system(session, research=bool(notes)),
                prompts.fact_check_message(turn["text"], notes),
                FactCheck,
                self.settings.fact_check_effort,
            )
        except Exception:
            # A failed check must never cost the user their turn; the reply still comes.
            log.exception("fact check failed")
            _emit(type="flags", turn_id=turn["id"], flags=[], checked=0, method="unavailable")
            _emit(type="step", node="fact_check", status="failed", ms=_ms(started), detail="unavailable")
            return {"flags": []}
        method = "web" if notes else "knowledge"
        seen = {p["url"]: p for p in pages}
        flags = []
        for claim in result.claims:
            if claim.verdict == "supported":
                continue
            located = find_quote(claim.claim, [turn["text"]]) or closest_sentence(claim.claim, [turn["text"]])
            flags.append(
                clean(
                    {
                        "claim": located[1] if located else claim.claim,
                        "verdict": claim.verdict,
                        "reason": claim.reason,
                        "evidence_needed": claim.evidence_needed,
                        # Only pages the search actually returned can be cited: no invented sources.
                        "sources": [seen[u] for u in claim.source_urls if u in seen],
                    }
                )
            )
        self.store.add_fact_check(turn["id"], checked=len(result.claims), method=method, flags=flags)
        saved = self.store.turn(turn["id"])["flags"]
        _emit(type="flags", turn_id=turn["id"], flags=saved, checked=len(result.claims), method=method)
        detail = f"{len(flags)} flagged of {len(result.claims)}" if result.claims else "no factual claims"
        _emit(type="step", node="fact_check", status="done", ms=_ms(started), detail=detail)
        return {"flags": saved}

    async def opponent(self, state: DojoState) -> DojoState:
        started = time.perf_counter()
        _emit(type="step", node="opponent", status="running")
        session, fmt = self._session(state)
        turns = session["turns"]
        fmt_slot = plan(fmt)[state["user_turn"]["slot"]].model_dump()
        opponent_turns = sum(1 for t in turns if t["speaker"] == "opponent")
        system = prompts.opponent_system(session, self._persona(session), fmt_slot, opponent_turns)
        text = ""
        async for token in self.llm.stream(system, prompts.opponent_messages(turns), self.settings.opponent_effort):
            token = clean(token)
            text += token
            _emit(type="token", text=token)
        reply = self.store.add_turn(
            session["id"], speaker="opponent", slot=fmt_slot, text=clean(text).strip(), input="model"
        )
        _emit(type="reply", turn=reply)
        _emit(type="step", node="opponent", status="done", ms=_ms(started), detail=f"{len(text.split())} words")
        return {"reply": reply}

    async def advance(self, state: DojoState) -> DojoState:
        session, fmt = self._session(state)
        pos = position(fmt, self.store.user_turn_count(session["id"]))
        if pos.done:
            self.store.set_status(session["id"], "judging")
        _emit(type="position", position=pos.model_dump())
        _emit(
            type="step",
            node="advance",
            status="done",
            detail="session complete" if pos.done else f"turn {pos.turn + 1} of {pos.total}",
        )
        return {"position": pos.model_dump()}

    def after_advance(self, state: DojoState) -> str:
        return "judge" if state["position"]["done"] else "end"

    async def judge(self, state: DojoState) -> DojoState:
        started = time.perf_counter()
        _emit(type="step", node="judge", status="running")
        session, _ = self._session(state)
        self.store.set_status(session["id"], "judging")
        turns = session["turns"]
        user_turns = [t for t in turns if t["speaker"] == "user"]
        deliveries = [Delivery.model_validate(t["delivery"]) for t in user_turns if t["delivery"]]
        system = prompts.judge_system(session)
        messages = prompts.judge_message(session, self._persona(session), turns, summarise(deliveries))
        card = None
        for attempt in range(2):
            try:
                raw = await self.llm.structured(system, messages, Scorecard, self.settings.judge_effort, think=True)
                card = normalise_scorecard(raw, session["mode"], [t["text"] for t in user_turns])
                break
            except (ReportError, ValidationError) as err:
                if attempt:
                    raise
                messages = [
                    *messages,
                    {"role": "user", "content": f"Your last scorecard was rejected: {err}. Score every criterion."},
                ]
        _emit(type="scorecard", scorecard=card)
        _emit(type="step", node="judge", status="done", ms=_ms(started), detail=f"{card['overall']} overall")
        return {"scorecard": card}

    async def coach(self, state: DojoState) -> DojoState:
        started = time.perf_counter()
        _emit(type="step", node="coach", status="running")
        session, _ = self._session(state)
        turns = session["turns"]
        user_turns = [t for t in turns if t["speaker"] == "user"]
        system = prompts.coach_system(session)
        messages = prompts.coach_message(session, self._persona(session), turns, state["scorecard"])
        coaching = None
        for attempt in range(2):
            try:
                raw = await self.llm.structured(system, messages, Coaching, self.settings.coach_effort, think=True)
                coaching = normalise_coaching(raw, user_turns)
                break
            except (ReportError, ValidationError) as err:
                if attempt:
                    raise
                messages = [*messages, {"role": "user", "content": f"Your last answer was rejected: {err}"}]
        self.store.save_report(session["id"], session["mode"], state["scorecard"], coaching)
        _emit(type="coaching", coaching=coaching)
        _emit(
            type="step", node="coach", status="done", ms=_ms(started), detail=f"rewrote turn {coaching['weakest_turn']}"
        )
        return {"coaching": coaching}
