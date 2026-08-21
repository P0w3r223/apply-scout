"""Human-readable rendering of a run: one line per step (for --verbose) and a summary.

Pure string builders (no printing here) so they are unit-tested directly. ASCII only —
these print to a terminal that may not be UTF-8 (Windows console).
"""

from __future__ import annotations

from apply_scout.agent import AgentResult
from apply_scout.trajectory import StepKind, TrajectoryStep

# Rich style per step kind. Lives here rather than in the CLI because more than one
# surface renders a step stream (the terminal, and the demo recorder in scripts/) —
# and they must agree on what a step looks like.
STEP_STYLE: dict[StepKind, str] = {
    StepKind.MODEL_CALL: "cyan",
    StepKind.TOOL_RESULT: "dim",
    StepKind.FINAL: "bold green",
    StepKind.BUDGET_STOP: "bold yellow",
}
FAILED_TOOL_STYLE = "red"


def step_style(step: TrajectoryStep) -> str:
    """The rich style a step should be printed in. A failed tool call outranks its kind."""
    if step.kind is StepKind.TOOL_RESULT and step.tool_ok is False:
        return FAILED_TOOL_STYLE
    return STEP_STYLE.get(step.kind, "")


def format_step(step: TrajectoryStep) -> str:
    """One (or two) lines describing a single trajectory step."""
    if step.kind is StepKind.MODEL_CALL:
        cost = f"${step.cost_usd:.4f}" if step.cost_usd is not None else "$?"
        line = (
            f"[{step.index}] model {step.model} | {step.input_tokens}+{step.output_tokens} tok "
            f"| {cost} | {step.tool_calls_requested} tool call(s)"
        )
        if step.text:
            indented = step.text.strip().replace("\n", "\n     ")
            line += f"\n     {indented}"
        return line
    if step.kind is StepKind.TOOL_RESULT:
        mark = "ok" if step.tool_ok else "ERR"
        return f"    - {step.tool_name} -> {mark}: {step.tool_summary}"
    if step.kind is StepKind.FINAL:
        return f"[done] finished ({step.note})"
    if step.kind is StepKind.BUDGET_STOP:
        return f"[stop] {step.note}"
    return f"[{step.index}] {step.kind.value}"


def format_summary(result: AgentResult) -> str:
    """The end-of-run block: status, totals, and the final report text."""
    breach = f" (breach: {result.breach.value})" if result.breach is not None else ""
    return (
        f"status: {result.status.value}{breach}\n"
        f"steps: {result.steps} | tokens: {result.input_tokens}+{result.output_tokens} "
        f"| cost: ${result.cost_usd:.4f}\n"
        f"--- report ---\n{result.final_text}"
    )
