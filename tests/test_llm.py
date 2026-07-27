"""Tests for the AnthropicLLM adapter's request construction and response normalization.

The adapter is not exercised by the loop tests (those inject a scripted fake), so these
drive it directly with a fake Anthropic client that records the kwargs it receives —
no network, no key. The gating matters: Haiku 4.5 rejects adaptive thinking + effort
with a 400, so the adapter must omit them for such models.
"""

from __future__ import annotations

from apply_scout import config
from apply_scout.llm import AnthropicLLM


class _TextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text

    def model_dump(self) -> dict:
        return {"type": "text", "text": self.text}


class _Usage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _Response:
    def __init__(self, model: str) -> None:
        self.content = [_TextBlock("hi")]
        self.stop_reason = "end_turn"
        self.model = model
        self.usage = _Usage(10, 3)


class _Messages:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs: object) -> _Response:
        self.calls.append(kwargs)
        return _Response(str(kwargs["model"]))


class _FakeClient:
    def __init__(self) -> None:
        self.messages = _Messages()


def _complete(model: str) -> tuple[_FakeClient, object]:
    client = _FakeClient()
    llm = AnthropicLLM(client=client)
    response = llm.complete(system="s", messages=[], tools=[], model=model)
    return client, response


def test_strong_model_gets_adaptive_thinking_and_effort() -> None:
    client, _ = _complete(config.MODEL_STRONG)
    kwargs = client.messages.calls[-1]
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"] == {"effort": config.DEFAULT_EFFORT}


def test_haiku_omits_adaptive_thinking_and_effort() -> None:
    # Regression: Haiku 4.5 returns 400 'adaptive thinking is not supported' if sent.
    client, _ = _complete(config.MODEL_CHEAP)
    kwargs = client.messages.calls[-1]
    assert "thinking" not in kwargs
    assert "output_config" not in kwargs


def test_response_is_normalized() -> None:
    _, response = _complete(config.MODEL_STRONG)
    assert response.text == "hi"
    assert response.stop_reason == "end_turn"
    assert response.usage.input_tokens == 10
    assert response.usage.output_tokens == 3
    assert response.model == config.MODEL_STRONG
