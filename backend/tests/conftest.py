import pytest

from debatedojo.config import Settings
from debatedojo.llm import ScriptedLLM
from debatedojo.service import Service
from debatedojo.store import Store

MOTION = "This house would ban smartphones in schools"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(llm="scripted", db_path=tmp_path / "test.db")


@pytest.fixture
def service(settings) -> Service:
    return Service.from_settings(settings, llm=ScriptedLLM(), store=Store(":memory:"))


async def collect(stream) -> list[dict]:
    return [e async for e in stream]


async def play(service: Service, session_id: str, texts: list[str], **kw) -> list[list[dict]]:
    """Take each turn in order; return the events of each."""
    return [await collect(service.turn(session_id, t, **kw)) for t in texts]


def of(events: list[dict], kind: str) -> list[dict]:
    return [e for e in events if e["type"] == kind]
