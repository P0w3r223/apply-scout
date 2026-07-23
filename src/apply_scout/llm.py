"""The model transport: a narrow protocol the agent depends on, plus the Anthropic
adapter that implements it.

The agent loop talks only to `LLMClient`. That keeps the loop provider-agnostic and,
crucially, testable without a network or an API key: the tests inject a scripted fake
that returns canned tool calls. Swapping Claude for another provider would mean one
new adapter here and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from apply_scout import config


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation the model asked for."""

    id: str
    name: str
    input: dict


@dataclass(frozen=True)
class Usage:
    """Token usage for a single model call."""

    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class LLMResponse:
    """A normalized model response the loop can act on without provider specifics.

    `raw_content` is the assistant's content blocks exactly as returned, so the loop
    can append them verbatim to the message history for the next turn (thinking and
    tool_use blocks must survive the round-trip unchanged)."""

    stop_reason: str
    text: str
    tool_calls: tuple[ToolCall, ...]
    usage: Usage
    model: str
    raw_content: list[dict] = field(default_factory=list)


@runtime_checkable
class LLMClient(Protocol):
    """What the agent needs from a model: one turn in, one normalized turn out."""

    def complete(
        self,
        *,
        system: str,
        messages: list[dict],
        tools: list[dict],
        model: str,
    ) -> LLMResponse: ...


class AnthropicLLM:
    """Adapter over the official Anthropic SDK. Used for real runs; not exercised by
    the unit tests (which use a fake). The `anthropic` package is imported lazily so
    importing the agent never requires a configured key."""

    def __init__(self, client: object | None = None) -> None:
        self._client = client

    def _ensure_client(self) -> object:
        if self._client is None:
            import anthropic  # lazy: only needed for real calls

            self._client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
        return self._client

    def complete(
        self,
        *,
        system: str,
        messages: list[dict],
        tools: list[dict],
        model: str,
    ) -> LLMResponse:
        client = self._ensure_client()
        response = client.messages.create(  # type: ignore[attr-defined]
            model=model,
            max_tokens=config.MAX_OUTPUT_TOKENS,
            system=system,
            messages=messages,
            tools=tools,
            thinking={"type": "adaptive"},
            output_config={"effort": config.DEFAULT_EFFORT},
        )
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        raw_content: list[dict] = []
        for block in response.content:
            raw_content.append(block.model_dump())
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=dict(block.input)))
        return LLMResponse(
            stop_reason=response.stop_reason,
            text="".join(text_parts),
            tool_calls=tuple(tool_calls),
            usage=Usage(response.usage.input_tokens, response.usage.output_tokens),
            model=response.model,
            raw_content=raw_content,
        )
