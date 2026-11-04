"""Formats, personas and the phase logic that walks a session through them.

A format is data (``formats/*.yaml``): an ordered list of timed phases, each with one or more
exchanges. In every exchange the user speaks first and the opponent answers. The session's
position is derived from how many user turns it has, so it never drifts from the log.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

Mode = Literal["debate", "meeting", "sales"]
MODES: tuple[Mode, ...] = ("debate", "meeting", "sales")

OpponentRole = Literal[
    "opening", "rebuttal", "closing", "constructive", "answer", "rapid", "probe", "pushback", "object", "decide"
]

MIN_SECONDS, MAX_SECONDS = 15, 600


class Phase(BaseModel):
    id: str
    name: str
    exchanges: int = Field(ge=1, le=10)
    seconds: int = Field(ge=MIN_SECONDS, le=MAX_SECONDS)
    you: str = Field(description="Guidance shown to the user for their turn.")
    opponent: OpponentRole


class Format(BaseModel):
    id: str
    name: str
    mode: Mode
    blurb: str
    phases: list[Phase] = Field(min_length=1)

    def with_timers(self, timers: dict[str, int] | None) -> Format:
        """A copy with the user's turn lengths applied, clamped to sane bounds."""
        if not timers:
            return self
        unknown = set(timers) - {p.id for p in self.phases}
        if unknown:
            raise ValueError(f"Unknown phase(s) for {self.id}: {', '.join(sorted(unknown))}")
        phases = [
            p.model_copy(update={"seconds": max(MIN_SECONDS, min(MAX_SECONDS, int(timers.get(p.id, p.seconds))))})
            for p in self.phases
        ]
        return self.model_copy(update={"phases": phases})


class Slot(BaseModel):
    """One user turn in the plan, and the opponent reply that follows it."""

    index: int
    phase_id: str
    phase_name: str
    exchange: int
    exchanges: int
    seconds: int
    guidance: str
    opponent_role: OpponentRole


class Position(BaseModel):
    done: bool
    turn: int = Field(description="How many user turns have been taken.")
    total: int
    slot: Slot | None = Field(description="The slot the user is on now, or None when the session is complete.")


class Persona(BaseModel):
    id: str
    name: str
    role: str
    style: str
    concerns: list[str] = []
    objections: list[str] = []


def plan(fmt: Format) -> list[Slot]:
    slots: list[Slot] = []
    for phase in fmt.phases:
        for exchange in range(1, phase.exchanges + 1):
            slots.append(
                Slot(
                    index=len(slots),
                    phase_id=phase.id,
                    phase_name=phase.name,
                    exchange=exchange,
                    exchanges=phase.exchanges,
                    seconds=phase.seconds,
                    guidance=phase.you,
                    opponent_role=phase.opponent,
                )
            )
    return slots


def position(fmt: Format, user_turns: int) -> Position:
    slots = plan(fmt)
    if user_turns < 0:
        raise ValueError("user_turns cannot be negative")
    if user_turns >= len(slots):
        return Position(done=True, turn=len(slots), total=len(slots), slot=None)
    return Position(done=False, turn=user_turns, total=len(slots), slot=slots[user_turns])


def overtime(limit_s: float, duration_s: float, grace_s: float = 2.0) -> bool:
    """A turn is over time if it ran past its limit, allowing a small grace for network lag."""
    return duration_s > limit_s + grace_s


class Catalog:
    """Every format and persona, loaded once from the data files."""

    def __init__(self, formats_dir: Path, personas_path: Path) -> None:
        self.formats: dict[str, Format] = {}
        for path in sorted(formats_dir.glob("*.yaml")):
            fmt = Format.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
            if fmt.id in self.formats:
                raise ValueError(f"Duplicate format id {fmt.id}")
            self.formats[fmt.id] = fmt
        raw = yaml.safe_load(personas_path.read_text(encoding="utf-8"))
        self.personas: dict[str, dict[str, Persona]] = {
            mode: {p["id"]: Persona.model_validate(p) for p in raw.get(mode, [])} for mode in MODES
        }
        self.samples: dict = raw.get("samples", {})
        for mode in MODES:
            if not self.formats_for(mode):
                raise ValueError(f"No format for mode {mode}")
            if not self.personas[mode]:
                raise ValueError(f"No persona for mode {mode}")

    def formats_for(self, mode: str) -> list[Format]:
        return [f for f in self.formats.values() if f.mode == mode]

    def format(self, format_id: str) -> Format:
        try:
            return self.formats[format_id]
        except KeyError:
            raise KeyError(f"Unknown format {format_id}") from None

    def persona(self, mode: str, persona_id: str | None) -> Persona:
        personas = self.personas[mode]
        if persona_id is None:
            return next(iter(personas.values()))
        try:
            return personas[persona_id]
        except KeyError:
            raise KeyError(f"Unknown persona {persona_id} for {mode}") from None

    def as_json(self) -> dict:
        return {
            "modes": [
                {
                    "id": mode,
                    "formats": [f.model_dump() for f in self.formats_for(mode)],
                    "personas": [p.model_dump() for p in self.personas[mode].values()],
                    "samples": self.samples.get(mode, []),
                }
                for mode in MODES
            ]
        }


@lru_cache
def load_catalog(formats_dir: Path, personas_path: Path) -> Catalog:
    return Catalog(formats_dir, personas_path)
