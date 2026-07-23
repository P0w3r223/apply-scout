"""A small registry: hold the tools, expose their specs to the model, and dispatch a
named call to the right tool. An unknown tool name is a structured error, not a crash."""

from __future__ import annotations

from collections.abc import Iterable

from apply_scout.tools.base import Tool, ToolResult


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool]) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"Duplicate tool name: {tool.name!r}")
            self._tools[tool.name] = tool

    def specs(self) -> list[dict]:
        """Tool definitions for the model's `tools` parameter, in registration order."""
        return [tool.spec() for tool in self._tools.values()]

    def dispatch(self, name: str, raw_input: dict) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            # The model hallucinated a tool that doesn't exist — tell it so, don't die.
            return ToolResult.error(f"Unknown tool: {name!r}")
        return tool.run(raw_input)
