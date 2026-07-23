"""Turn free text into a typed contract via an LLM, with our own validate-and-retry.

The structuring model returns JSON; *we* validate it against the target Pydantic model
and, on failure, re-ask with the error until a small attempt budget is spent — then
give up with a readable error. Owning the retry (rather than trusting the SDK's) is the
point: the strategy and its limit are explicit and testable.

The structurer is injected, so tests drive this with a scripted fake — no network.
"""

from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ValidationError

_T = TypeVar("_T", bound=BaseModel)

# Structured-outputs does not support these JSON-schema keywords; strip them so a real
# request isn't rejected. We still enforce them ourselves on the parsed result.
_UNSUPPORTED_SCHEMA_KEYS = frozenset(
    {"minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum",
     "exclusiveMaximum", "multipleOf", "pattern", "minItems", "maxItems"}
)


class StructuringError(Exception):
    """Raised when the model's output cannot be validated after all attempts."""


@runtime_checkable
class Structurer(Protocol):
    """Given instructions + content + a JSON schema, return the model's JSON text."""

    def to_json(self, *, instructions: str, content: str, schema: dict, model: str) -> str: ...


def _strip_unsupported(node: object) -> object:
    """Recursively drop schema keywords structured-outputs rejects."""
    if isinstance(node, dict):
        return {
            key: _strip_unsupported(value)
            for key, value in node.items()
            if key not in _UNSUPPORTED_SCHEMA_KEYS
        }
    if isinstance(node, list):
        return [_strip_unsupported(item) for item in node]
    return node


def structure(
    content: str,
    model_cls: type[_T],
    *,
    structurer: Structurer,
    model: str,
    instructions: str,
    max_attempts: int,
) -> _T:
    """Extract `content` into an instance of `model_cls`, retrying on invalid output.

    Raises `StructuringError` if no attempt produces a valid instance."""
    schema = _strip_unsupported(model_cls.model_json_schema())
    last_error: ValidationError | None = None

    for _ in range(max_attempts):
        hint = (
            ""
            if last_error is None
            else f"\n\nYour previous response failed validation: {last_error}. "
            "Return corrected JSON only."
        )
        raw = structurer.to_json(
            instructions=instructions + hint, content=content, schema=schema, model=model
        )
        try:
            return model_cls.model_validate_json(raw)
        except ValidationError as exc:
            last_error = exc

    raise StructuringError(
        f"could not structure text into {model_cls.__name__} after {max_attempts} "
        f"attempt(s): {last_error}"
    )


class AnthropicStructurer:
    """Real structurer: one Claude call constrained to the target JSON schema.

    Used for real runs; not exercised by the unit tests (a scripted fake is). The
    `anthropic` package is imported lazily."""

    def __init__(self, client: object | None = None) -> None:
        self._client = client
        # Accumulated across calls, so the eval harness can report per-task cost.
        self.calls = 0
        self.cost_usd = 0.0

    def _ensure_client(self) -> object:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def to_json(self, *, instructions: str, content: str, schema: dict, model: str) -> str:
        from apply_scout import config

        client = self._ensure_client()
        response = client.messages.create(  # type: ignore[attr-defined]
            model=model,
            max_tokens=config.MAX_OUTPUT_TOKENS,
            system=instructions,
            messages=[{"role": "user", "content": content}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        self.calls += 1
        self.cost_usd += config.token_cost(
            response.usage.input_tokens, response.usage.output_tokens, model
        )
        for block in response.content:
            if block.type == "text":
                return block.text
        return ""
