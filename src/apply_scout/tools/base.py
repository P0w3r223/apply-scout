"""The tool contract.

Two rules the whole project leans on (see CLAUDE.md):

1. **Testable without an LLM.** A tool is `validate input -> do work -> ToolResult`.
   You can call it directly in a unit test; no model in the loop.
2. **Errors are results, not exceptions.** A malformed argument or a failed fetch
   comes back as a `ToolResult` with `ok=False`. The agent hands that straight to the
   model as a `tool_result` with `is_error=True`, so the model can read the message
   and try again — the loop never crashes on a bad tool call.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ValidationError


@dataclass(frozen=True)
class ToolResult:
    """What a tool hands back: text for the model plus a short log-safe summary."""

    ok: bool
    content: str  # goes into the tool_result block the model reads
    summary: str  # short line for the trajectory log (never dumps full payloads)

    @classmethod
    def success(cls, content: str, summary: str) -> ToolResult:
        return cls(ok=True, content=content, summary=summary)

    @classmethod
    def error(cls, message: str) -> ToolResult:
        return cls(ok=False, content=message, summary=message)


@runtime_checkable
class Tool(Protocol):
    """The minimal surface the registry and agent need from any tool."""

    name: str
    description: str

    def spec(self) -> dict: ...  # {name, description, input_schema} for the model
    def run(self, raw_input: dict) -> ToolResult: ...


class PydanticTool(ABC):
    """Base class: derives the JSON schema from a Pydantic input model, validates the
    model's arguments, and turns validation failures into structured errors.

    Subclasses set `name`, `description`, `input_model`, and implement `_run`."""

    name: str
    description: str
    input_model: type[BaseModel]

    def spec(self) -> dict:
        """The tool definition passed to the model (Anthropic `tools` entry)."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
        }

    def run(self, raw_input: dict) -> ToolResult:
        try:
            data = self.input_model.model_validate(raw_input)
        except ValidationError as exc:
            # A deliberately broken argument must produce a readable error the model
            # can recover from — this path is directly tested.
            return ToolResult.error(f"Invalid input for '{self.name}': {exc}")
        return self._run(data)

    @abstractmethod
    def _run(self, data: BaseModel) -> ToolResult:
        """Do the actual work on already-validated input."""
        raise NotImplementedError
