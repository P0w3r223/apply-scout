"""Tools the agent can call. Each tool is a typed contract (Pydantic input schema +
a pure-ish `run`) that is testable without an LLM, and whose errors come back to the
model as structured results rather than exceptions."""

from __future__ import annotations

from apply_scout.tools.base import PydanticTool, Tool, ToolResult
from apply_scout.tools.registry import ToolRegistry

__all__ = ["PydanticTool", "Tool", "ToolResult", "ToolRegistry"]
