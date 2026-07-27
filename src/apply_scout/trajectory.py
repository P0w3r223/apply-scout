"""The trajectory: an append-only record of every step the agent took.

This is the project's flagship artifact. 95% of junior agent projects stop at "it
worked on my example"; this one writes a machine-readable log of each model call,
each tool call, and the cost, so runs can be replayed, diffed, and scored. The log
is the substrate the evaluation harness (a later milestone) reads.

I/O is isolated: steps accumulate in memory; only `write` touches disk.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class StepKind(StrEnum):
    MODEL_CALL = "model_call"  # one call to the LLM, with its token/cost usage
    TOOL_RESULT = "tool_result"  # one tool executed on the model's behalf
    FINAL = "final"  # the run completed normally (model stopped calling tools)
    BUDGET_STOP = "budget_stop"  # the run was cut short by a safety ceiling


class TrajectoryStep(BaseModel):
    """One entry in the trajectory. Serialized as a single JSONL line."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    index: int
    kind: StepKind
    # model_call fields
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    tool_calls_requested: int | None = None
    text: str | None = Field(None, description="Assistant's visible text on a model_call step.")
    # tool_result fields
    tool_name: str | None = None
    tool_input: dict | None = None
    tool_ok: bool | None = None
    tool_summary: str | None = Field(None, description="Short, log-safe summary of the result.")
    # final / budget_stop
    note: str | None = None


class TrajectoryLogger:
    """Collects steps in order and can flush them to a JSONL file.

    Kept dead simple and dependency-free so tests can assert on `.steps` directly and
    the eval harness can read `.to_jsonl()` without a running agent."""

    def __init__(self) -> None:
        self.steps: list[TrajectoryStep] = []

    def record(self, step: TrajectoryStep) -> None:
        self.steps.append(step)

    def to_jsonl(self) -> str:
        return "\n".join(step.model_dump_json() for step in self.steps)

    def write(self, path: Path) -> Path:
        """Write the trajectory to `path` as JSONL. The only method that touches disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_jsonl(), encoding="utf-8")
        return path
