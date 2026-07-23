"""Rendering of steps and the run summary (pure string builders)."""

from __future__ import annotations

from apply_scout.agent import AgentResult, RunStatus
from apply_scout.budget import BudgetBreach
from apply_scout.formatting import format_step, format_summary
from apply_scout.trajectory import StepKind, TrajectoryLogger, TrajectoryStep


def test_format_model_call_includes_cost_and_reasoning_text():
    step = TrajectoryStep(
        index=0,
        kind=StepKind.MODEL_CALL,
        model="claude-opus-4-8",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.0018,
        tool_calls_requested=1,
        text="Fetching the posting first.",
    )
    out = format_step(step)
    assert "claude-opus-4-8" in out
    assert "$0.0018" in out
    assert "Fetching the posting first." in out


def test_format_tool_result():
    step = TrajectoryStep(
        index=1,
        kind=StepKind.TOOL_RESULT,
        tool_name="read_cv",
        tool_ok=True,
        tool_summary="CV with 5 skills",
    )
    out = format_step(step)
    assert "read_cv" in out
    assert "ok" in out
    assert "CV with 5 skills" in out


def test_format_summary_shows_status_totals_and_report():
    result = AgentResult(
        status=RunStatus.BUDGET_STOPPED,
        final_text="partial report",
        trajectory=TrajectoryLogger(),
        steps=2,
        input_tokens=200,
        output_tokens=100,
        cost_usd=0.0030,
        breach=BudgetBreach.STEPS,
    )
    out = format_summary(result)
    assert "budget_stopped" in out
    assert "breach: max_steps" in out
    assert "$0.0030" in out
    assert "partial report" in out
