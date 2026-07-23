"""A scripted fake model, so the agent loop can be tested without a network or a key.

`ScriptedLLM` returns a pre-baked sequence of `LLMResponse`s and records the requests
it saw. Helpers build the two turn shapes the loop cares about: a turn that asks for
tools, and a turn that finishes.
"""

from __future__ import annotations

from apply_scout import config
from apply_scout.llm import LLMResponse, ToolCall, Usage


def tool_use_turn(
    calls: list[tuple[str, str, dict]],
    *,
    text: str = "",
    input_tokens: int = 100,
    output_tokens: int = 50,
    model: str = config.MODEL_STRONG,
) -> LLMResponse:
    """A model turn that asks for one or more tools. `calls` are (id, name, input)."""
    tool_calls = tuple(ToolCall(id=i, name=n, input=inp) for i, n, inp in calls)
    raw: list[dict] = []
    if text:
        raw.append({"type": "text", "text": text})
    raw.extend({"type": "tool_use", "id": i, "name": n, "input": inp} for i, n, inp in calls)
    return LLMResponse(
        stop_reason="tool_use",
        text=text,
        tool_calls=tool_calls,
        usage=Usage(input_tokens, output_tokens),
        model=model,
        raw_content=raw,
    )


def final_turn(
    text: str,
    *,
    input_tokens: int = 100,
    output_tokens: int = 50,
    model: str = config.MODEL_STRONG,
) -> LLMResponse:
    """A model turn that finishes (no tool calls)."""
    return LLMResponse(
        stop_reason="end_turn",
        text=text,
        tool_calls=(),
        usage=Usage(input_tokens, output_tokens),
        model=model,
        raw_content=[{"type": "text", "text": text}],
    )


class ScriptedLLM:
    """Replays `turns` in order; records each request for assertions."""

    def __init__(self, turns: list[LLMResponse]) -> None:
        self._turns = list(turns)
        self.requests: list[dict] = []

    def complete(self, *, system: str, messages: list[dict], tools: list[dict], model: str):
        self.requests.append(
            {"system": system, "messages": messages, "tools": tools, "model": model}
        )
        if not self._turns:
            raise AssertionError("ScriptedLLM ran out of scripted turns")
        return self._turns.pop(0)


class ScriptedStructurer:
    """A fake Structurer that returns pre-baked JSON strings, one per call, in order.
    Feed it an invalid string then a valid one to exercise the validate-and-retry path."""

    def __init__(self, outputs: list[str]) -> None:
        self._outputs = list(outputs)
        self.calls = 0

    def to_json(self, *, instructions: str, content: str, schema: dict, model: str) -> str:
        self.calls += 1
        if not self._outputs:
            raise AssertionError("ScriptedStructurer ran out of outputs")
        return self._outputs.pop(0)
