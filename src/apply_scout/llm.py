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
    """Token usage for a single model call.

    `input_tokens` is the *uncached* remainder once prompt caching is on — the cached
    tokens are reported separately and priced differently, so cost accounting needs all
    three. The cache fields default to zero, which is both what an uncached call reports
    and what a cassette entry recorded before caching existed."""

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def prompt_tokens(self) -> int:
        """Everything the model read this call, cached or not — the size of the prompt,
        as distinct from what was billed at full rate."""
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens


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
        request: dict = {
            "model": model,
            "max_tokens": config.MAX_OUTPUT_TOKENS,
            "system": system,
            "messages": messages,
            "tools": tools,
            # Top-level auto-caching: the API caches the last cacheable block, which in a
            # tool loop is the newest turn — so each step reads the conversation so far
            # from cache instead of paying full rate to re-send it. Deliberately the
            # top-level form rather than per-block `cache_control`: it leaves `system`,
            # `messages` and `tools` byte-identical, so the cassette key is unchanged and
            # every recorded run still replays.
            "cache_control": {"type": "ephemeral"},
        }
        # Adaptive thinking + effort are the Opus / Sonnet-5-tier controls; Haiku 4.5
        # rejects them with a 400, so send them only for models that support them.
        if model not in config.NO_ADAPTIVE_THINKING_MODELS:
            request["thinking"] = {"type": "adaptive"}
            request["output_config"] = {"effort": config.DEFAULT_EFFORT}
        response = client.messages.create(**request)  # type: ignore[attr-defined]
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
            usage=Usage(
                response.usage.input_tokens,
                response.usage.output_tokens,
                # Absent on providers or models that never cache; treat as "nothing cached"
                # rather than assuming the fields are there.
                getattr(response.usage, "cache_read_input_tokens", 0) or 0,
                getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
            ),
            model=response.model,
            raw_content=raw_content,
        )
