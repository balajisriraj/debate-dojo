"""Language-model layer.

Every agent talks to an ``LLM``: either Claude, or a scripted model that answers
deterministically so the whole product can be exercised offline and in CI.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from .config import Settings
from .scripted import ScriptedLLM

T = TypeVar("T", bound=BaseModel)

# Server-side fallback: if Claude's safety classifiers decline a request, the API re-runs it on
# Anthropic's recommended fallback model instead of returning a refusal.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
WEB_SEARCH_TOOL = "web_search_20260209"


class LLMRefusal(RuntimeError):
    """The model declined the request (``stop_reason == "refusal"``)."""


class LLM(Protocol):
    name: str

    async def structured(
        self, system: str, messages: list[dict], schema: type[T], effort: str, think: bool = False
    ) -> T: ...

    def stream(self, system: str, messages: list[dict], effort: str) -> AsyncIterator[str]: ...

    async def research(self, system: str, text: str) -> tuple[str, list[dict]]:
        """Web research notes on ``text`` and the pages they came from, as ``{title, url}``."""
        ...


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON Schema for structured outputs: every field required, no extra keys, no numeric bounds."""

    def tighten(node: Any) -> Any:
        if isinstance(node, dict):
            drop = ("title", "default", "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems")
            node = {k: tighten(v) for k, v in node.items() if k not in drop}
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
        elif isinstance(node, list):
            node = [tighten(v) for v in node]
        return node

    schema = model.model_json_schema()
    defs = schema.pop("$defs", None)
    schema = tighten(schema)
    if defs:
        schema["$defs"] = {k: tighten(v) for k, v in defs.items()}
    return schema


class AnthropicLLM:
    """Claude through the official SDK.

    Structured outputs for the fact-checker, the judge and the coach; streaming for the opponent.
    Adaptive thinking is always on for this model; ``effort`` sets how deep it goes per agent.
    """

    name = "anthropic"

    def __init__(self, settings: Settings) -> None:
        import anthropic

        self.client = anthropic.AsyncAnthropic()
        self.model = settings.model
        self.web_max_uses = settings.web_search_max_uses

    async def structured(
        self, system: str, messages: list[dict], schema: type[T], effort: str, think: bool = False
    ) -> T:
        extra: dict[str, Any] = {"thinking": {"type": "adaptive"}} if think else {}
        async with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=32000 if think else 8000,
            system=system,
            messages=messages,
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": strict_schema(schema)}},
            betas=[FALLBACK_BETA],
            fallbacks="default",
            **extra,
        ) as stream:
            response = await stream.get_final_message()
        if response.stop_reason == "refusal":
            raise LLMRefusal("Claude declined this request.")
        text = next(block.text for block in response.content if block.type == "text")
        return schema.model_validate(json.loads(text))

    async def stream(self, system: str, messages: list[dict], effort: str) -> AsyncIterator[str]:
        async with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=4000,
            system=system,
            messages=messages,
            output_config={"effort": effort},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        ) as stream:
            async for text in stream.text_stream:
                yield text
            final = await stream.get_final_message()
        if final.stop_reason == "refusal":
            raise LLMRefusal("Claude declined to answer.")

    async def research(self, system: str, text: str) -> tuple[str, list[dict]]:
        """One server-side web search pass. The pages it found are returned so the checker can only cite those."""
        messages: list[dict] = [{"role": "user", "content": f"<turn>{text}</turn>"}]
        tools = [{"type": WEB_SEARCH_TOOL, "name": "web_search", "max_uses": self.web_max_uses}]
        notes: list[str] = []
        found: dict[str, str] = {}
        for _ in range(3):  # a long search turn can pause; resume it a bounded number of times
            response = await self.client.beta.messages.create(
                model=self.model,
                max_tokens=8000,
                system=system,
                messages=messages,
                tools=tools,
                output_config={"effort": "low"},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
            for block in response.content:
                if block.type == "text":
                    notes.append(block.text)
                elif block.type == "web_search_tool_result" and isinstance(block.content, list):
                    for r in block.content:
                        found.setdefault(r.url, r.title)
            if response.stop_reason != "pause_turn":
                break
            messages = [*messages, {"role": "assistant", "content": response.content}]
        if response.stop_reason == "refusal":
            raise LLMRefusal("Claude declined to research this turn.")
        return "".join(notes).strip(), [{"title": title, "url": url} for url, title in found.items()]


def make_llm(settings: Settings) -> LLM:
    if settings.llm == "scripted":
        return ScriptedLLM(delay=settings.scripted_delay)
    if settings.llm == "anthropic":
        return AnthropicLLM(settings)
    raise ValueError(f"Unknown LLM backend: {settings.llm}")
