"""The dojo as a service: start sessions, take turns, finish and report. The API and the evals share it."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from .config import Settings
from .formats import MODES, Catalog, Format, load_catalog, plan, position
from .graph import Dojo
from .llm import LLM, make_llm
from .rubric import RUBRICS
from .store import Store

SIDES = ("proposition", "opposition")


class NotFound(LookupError):
    pass


class Conflict(RuntimeError):
    """The request does not fit the session's state, e.g. a turn after the session finished."""


@dataclass
class Service:
    settings: Settings
    llm: LLM
    store: Store
    catalog: Catalog
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.dojo = Dojo(self.llm, self.store, self.catalog, self.settings)
        self.graph = self.dojo.build()

    @classmethod
    def from_settings(cls, settings: Settings, *, llm: LLM | None = None, store: Store | None = None) -> Service:
        return cls(
            settings=settings,
            llm=llm or make_llm(settings),
            store=store or Store(settings.db_path),
            catalog=load_catalog(settings.formats_dir, settings.personas_path),
        )

    # ── sessions ──
    def start(
        self,
        *,
        mode: str,
        topic: str,
        format_id: str | None = None,
        persona_id: str | None = None,
        side: str | None = None,
        context: str = "",
        timers: dict[str, int] | None = None,
    ) -> dict:
        if mode not in MODES:
            raise ValueError(f"Unknown mode {mode}")
        fmt = self.catalog.format(format_id) if format_id else self.catalog.formats_for(mode)[0]
        if fmt.mode != mode:
            raise ValueError(f"Format {fmt.id} is not a {mode} format")
        persona = self.catalog.persona(mode, persona_id)
        if mode == "debate":
            side = side or "proposition"
            if side not in SIDES:
                raise ValueError("side must be proposition or opposition")
        else:
            side = None
        topic = " ".join(topic.split())
        if not topic:
            raise ValueError("A topic is required")
        session_id = uuid.uuid4().hex[:16]
        self.store.create_session(
            id=session_id,
            mode=mode,
            format_id=fmt.id,
            format=fmt.with_timers(timers).model_dump(),
            topic=topic,
            side=side,
            persona_id=persona.id,
            context=context.strip(),
        )
        return self.get(session_id)

    def get(self, session_id: str) -> dict:
        session = self.store.session(session_id)
        if session is None:
            raise NotFound(session_id)
        fmt = Format.model_validate(session["format"])
        user_turns = sum(1 for t in session["turns"] if t["speaker"] == "user")
        return {
            **session,
            "plan": [s.model_dump() for s in plan(fmt)],
            "position": position(fmt, user_turns).model_dump(),
            "persona": self.catalog.persona(session["mode"], session["persona_id"]).model_dump(),
            "rubric": [c.model_dump() for c in RUBRICS[session["mode"]]],
        }

    def _lock(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())

    def check_turn(self, session_id: str) -> None:
        """Raise before streaming starts, so the API can answer with a proper status code."""
        session = self.get(session_id)
        if session["status"] != "live" or session["position"]["done"]:
            raise Conflict("This session is over. Start a new one.")
        if self._lock(session_id).locked():
            raise Conflict("The opponent is still answering your last turn.")

    def check_finish(self, session_id: str) -> None:
        session = self.get(session_id)
        if session["status"] == "finished":
            raise Conflict("This session has already been judged.")
        if not any(t["speaker"] == "user" for t in session["turns"]):
            raise Conflict("Take at least one turn before asking for a verdict.")
        if self._lock(session_id).locked():
            raise Conflict("The session is busy. Try again in a moment.")

    async def turn(
        self,
        session_id: str,
        text: str,
        *,
        input: str = "typed",
        duration_s: float = 0.0,
        talk_seconds: float | None = None,
        longest_pause_s: float | None = None,
        timed_out: bool = False,
    ) -> AsyncIterator[dict]:
        """Take a user turn and yield the graph's events, ending with a ``final`` event."""
        self.check_turn(session_id)
        state = {
            "action": "turn",
            "session_id": session_id,
            "text": text,
            "input": input,
            "duration_s": duration_s,
            "talk_seconds": talk_seconds,
            "longest_pause_s": longest_pause_s,
            "timed_out": timed_out,
        }
        async for event in self._run(session_id, state):
            yield event

    async def finish(self, session_id: str) -> AsyncIterator[dict]:
        """End the session now (or re-run a failed verdict) and yield the judge's and coach's events."""
        self.check_finish(session_id)
        async for event in self._run(session_id, {"action": "finish", "session_id": session_id}):
            yield event

    async def _run(self, session_id: str, state: dict) -> AsyncIterator[dict]:
        started = time.perf_counter()
        recorded: dict | None = None
        async with self._lock(session_id):
            try:
                async for mode, chunk in self.graph.astream(state, stream_mode=["custom", "values"]):
                    if mode == "custom":
                        if chunk["type"] == "turn":
                            recorded = chunk["turn"]
                        yield chunk
            except Exception:
                # A turn whose reply never arrived is rolled back, so the user can simply try again.
                # If only the verdict failed, the log is complete and finish() can retry it.
                if recorded is not None and not any(
                    t["speaker"] == "opponent" and t["idx"] > recorded["idx"] for t in self.store.turns(session_id)
                ):
                    self.store.delete_turn(recorded["id"])
                raise
        session = self.get(session_id)
        yield {
            "type": "final",
            "status": session["status"],
            "position": session["position"],
            "ms": round((time.perf_counter() - started) * 1000),
        }

    def progress(self, mode: str) -> dict:
        if mode not in MODES:
            raise ValueError(f"Unknown mode {mode}")
        return {"mode": mode, "rubric": [c.model_dump() for c in RUBRICS[mode]], "sessions": self.store.progress(mode)}
