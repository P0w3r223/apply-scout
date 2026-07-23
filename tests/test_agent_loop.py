"""The milestone-1 acceptance test: the loop with mock tools calls tools in a sensible
order and finishes within the step limit — and starving the budget stops it cleanly
with a partial report."""

from __future__ import annotations

from fakes import ScriptedLLM, final_turn, tool_use_turn

from apply_scout.agent import Agent, AgentConfig, RunStatus
from apply_scout.budget import Budget, BudgetBreach
from apply_scout.tools.mock import mock_tools
from apply_scout.tools.registry import ToolRegistry
from apply_scout.trajectory import StepKind


def _agent(turns, *, budget: Budget | None = None) -> Agent:
    llm = ScriptedLLM(turns)
    cfg = AgentConfig(budget=budget) if budget is not None else None
    return Agent(llm, ToolRegistry(mock_tools()), agent_config=cfg)


def test_loop_runs_tools_in_order_then_finishes():
    agent = _agent(
        [
            tool_use_turn([("t1", "fetch_job_posting", {"url": "https://example.com/job"})]),
            tool_use_turn([("t2", "read_cv", {"path": "cv.md"})]),
            tool_use_turn(
                [("t3", "github_evidence", {"requirement": "FastAPI", "github_user": "P0w3r223"})]
            ),
            final_turn("MATCH REPORT: Python strong, FastAPI strong, SQL none."),
        ]
    )
    result = agent.run("Assess my fit for https://example.com/job")

    assert result.status is RunStatus.COMPLETED
    assert "MATCH REPORT" in result.final_text

    kinds = [s.kind for s in result.trajectory.steps]
    assert kinds.count(StepKind.MODEL_CALL) == 4
    assert kinds.count(StepKind.TOOL_RESULT) == 3
    assert kinds[-1] is StepKind.FINAL

    tools_called = [s.tool_name for s in result.trajectory.steps if s.kind is StepKind.TOOL_RESULT]
    assert tools_called == ["fetch_job_posting", "read_cv", "github_evidence"]

    assert result.steps == 4
    assert all(s.tool_ok for s in result.trajectory.steps if s.kind is StepKind.TOOL_RESULT)
    assert result.cost_usd > 0  # usage was accounted


def test_budget_stops_run_with_partial_report():
    # The model would loop forever; max_steps=2 must cut it off after two calls.
    turns = [
        tool_use_turn([("t", "fetch_job_posting", {"url": "u"})], text="still gathering evidence")
        for _ in range(6)
    ]
    agent = _agent(turns, budget=Budget(max_steps=2, max_tokens=10**9, max_cost_usd=10**9))
    result = agent.run("Assess my fit")

    assert result.status is RunStatus.BUDGET_STOPPED
    assert result.breach is BudgetBreach.STEPS
    assert result.steps == 2  # exactly max_steps model calls
    assert result.final_text == "still gathering evidence"  # partial report, not empty
    assert result.trajectory.steps[-1].kind is StepKind.BUDGET_STOP


def test_bad_tool_input_returns_structured_error_without_crashing():
    agent = _agent(
        [
            tool_use_turn([("t1", "fetch_job_posting", {})]),  # missing required 'url'
            final_turn("Recovered and produced a report."),
        ]
    )
    result = agent.run("Assess my fit")

    assert result.status is RunStatus.COMPLETED
    tool_step = next(s for s in result.trajectory.steps if s.kind is StepKind.TOOL_RESULT)
    assert tool_step.tool_ok is False
    assert "Invalid input" in tool_step.tool_summary


def test_unknown_tool_is_reported_not_fatal():
    agent = _agent(
        [
            tool_use_turn([("t1", "teleport", {})]),  # not a registered tool
            final_turn("done"),
        ]
    )
    result = agent.run("Assess my fit")
    tool_step = next(s for s in result.trajectory.steps if s.kind is StepKind.TOOL_RESULT)
    assert tool_step.tool_ok is False
    assert "Unknown tool" in tool_step.tool_summary


def test_trajectory_serializes_to_jsonl():
    agent = _agent([final_turn("nothing to do")])
    result = agent.run("noop")
    lines = result.trajectory.to_jsonl().splitlines()
    assert len(lines) == len(result.trajectory.steps)
    assert lines[0].startswith("{") and lines[0].endswith("}")
