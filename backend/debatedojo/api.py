"""HTTP API. Turns and verdicts stream the agents' events as Server-Sent Events."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from .config import Settings, get_settings
from .formats import MAX_SECONDS, MIN_SECONDS
from .llm import LLMRefusal
from .service import Conflict, NotFound, Service

log = logging.getLogger("debatedojo")

SESSION_ID = r"^[a-f0-9]{16}$"


class StartRequest(BaseModel):
    mode: Literal["debate", "meeting", "sales"]
    topic: str = Field(min_length=3, max_length=300)
    format_id: str | None = Field(default=None, max_length=40)
    persona_id: str | None = Field(default=None, max_length=40)
    side: Literal["proposition", "opposition"] | None = None
    context: str = Field(default="", max_length=1500)
    timers: dict[str, int] = Field(default_factory=dict, max_length=12)


class TurnRequest(BaseModel):
    text: str = Field(default="", max_length=6000)
    input: Literal["typed", "voice"] = "typed"
    duration_s: float = Field(default=0.0, ge=0, le=MAX_SECONDS * 3)
    talk_seconds: float | None = Field(default=None, ge=0, le=MAX_SECONDS * 3)
    longest_pause_s: float | None = Field(default=None, ge=0, le=MAX_SECONDS)
    timed_out: bool = False


def create_app(settings: Settings | None = None, service: Service | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.service = service or Service.from_settings(settings)
        yield

    app = FastAPI(title="DebateDojo", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    def svc(request: Request) -> Service:
        return request.app.state.service

    def check_id(session_id: str) -> None:
        import re

        if not re.match(SESSION_ID, session_id):
            raise HTTPException(status_code=400, detail="Invalid session id.")

    @app.get("/api/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "llm": settings.llm,
            "model": settings.model if settings.llm == "anthropic" else "scripted",
            "fact_check": "web" if settings.fact_check_web and settings.llm == "anthropic" else "knowledge",
            "timer_bounds": [MIN_SECONDS, MAX_SECONDS],
        }

    @app.get("/api/catalog")
    async def catalog(request: Request) -> dict:
        return svc(request).catalog.as_json()

    @app.post("/api/sessions", status_code=201)
    async def start(body: StartRequest, request: Request) -> dict:
        try:
            return svc(request).start(**body.model_dump())
        except (ValueError, KeyError) as err:
            raise HTTPException(status_code=422, detail=str(err).strip("'\"")) from None

    @app.get("/api/sessions")
    async def sessions(request: Request) -> list[dict]:
        return svc(request).store.sessions()

    @app.get("/api/sessions/{session_id}")
    async def session(session_id: str, request: Request) -> dict:
        check_id(session_id)
        try:
            return svc(request).get(session_id)
        except NotFound:
            raise HTTPException(status_code=404, detail="No such session.") from None

    @app.delete("/api/sessions/{session_id}")
    async def delete(session_id: str, request: Request) -> dict:
        check_id(session_id)
        if not svc(request).store.delete_session(session_id):
            raise HTTPException(status_code=404, detail="No such session.")
        return {"deleted": session_id}

    def guarded(check, run) -> EventSourceResponse:
        try:
            check()
        except NotFound:
            raise HTTPException(status_code=404, detail="No such session.") from None
        except Conflict as err:
            raise HTTPException(status_code=409, detail=str(err)) from None
        return EventSourceResponse(_sse(run()))

    @app.post("/api/sessions/{session_id}/turns")
    async def turn(session_id: str, body: TurnRequest, request: Request) -> EventSourceResponse:
        check_id(session_id)
        s = svc(request)
        if not body.text.strip() and not body.timed_out:
            raise HTTPException(
                status_code=422, detail="Say something first. Empty turns are only for when time runs out."
            )
        return guarded(
            lambda: s.check_turn(session_id),
            lambda: s.turn(session_id, **body.model_dump(exclude={"text"}), text=body.text),
        )

    @app.post("/api/sessions/{session_id}/finish")
    async def finish(session_id: str, request: Request) -> EventSourceResponse:
        check_id(session_id)
        s = svc(request)
        return guarded(lambda: s.check_finish(session_id), lambda: s.finish(session_id))

    @app.get("/api/progress/{mode}")
    async def progress(mode: str, request: Request) -> dict:
        try:
            return svc(request).progress(mode)
        except ValueError as err:
            raise HTTPException(status_code=404, detail=str(err)) from None

    return app


async def _sse(events: AsyncIterator[dict]) -> AsyncIterator[dict]:
    try:
        async for event in events:
            yield {"event": event["type"], "data": json.dumps(event)}
    except LLMRefusal:
        yield _error("The model declined to continue this one. Try rephrasing your turn.")
    except Conflict as err:
        yield _error(str(err))
    except Exception:
        log.exception("stream failed")
        yield _error("Something went wrong on our side. Your words are still in the box, so send them again.")


def _error(message: str) -> dict:
    return {"event": "error", "data": json.dumps({"type": "error", "message": message})}
