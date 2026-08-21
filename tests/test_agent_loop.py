"""The milestone-1 acceptance test: the loop with mock tools calls tools in a sensible
order and finishes within the step limit — and starving the budget stops it cleanly
with a partial report."""

from __future__ import annotations

from fakes import ScriptedLLM, final_turn, tool_use_turn, truncated_turn

from apply_scout.agent import Agent, AgentConfig, RunStatus
from apply_scout.budget import Budget, BudgetBreach
from apply_scout.prompts import CONTINUE_INSTRUCTION
from apply_scout.tools.mock import mock_tools
from apply_scout.tools.registry import ToolRegistry
from apply_scout.trajectory import StepKind


def _agent(turns, *, budget: Budget | None = None, max_continuations: int | None = None) -> Agent:
    llm = ScriptedLLM(turns)
    overrides = {}
    if budget is not None:
        overrides["budget"] = budget
    if max_continuations is not None:
        overrides["max_continuations"] = max_continuations
    cfg = AgentConfig(**overrides) if overrides else None
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


def test_answer_cut_off_by_the_output_cap_is_continued_and_stitched():
    agent = _agent(
        [
            truncated_turn("# Match Report\n| Python | strong |\n| SQL |"),
            final_turn(" none |\n\nOverall: partial fit."),
        ]
    )
    result = agent.run("Assess my fit")

    assert result.status is RunStatus.COMPLETED
    # One report, not the last fragment of one — and no seam between the pieces.
    assert result.final_text == (
        "# Match Report\n| Python | strong |\n| SQL | none |\n\nOverall: partial fit."
    )
    kinds = [s.kind for s in result.trajectory.steps]
    assert kinds.count(StepKind.CONTINUATION) == 1
    assert kinds[-1] is StepKind.FINAL


def test_continuation_is_asked_for_in_a_user_turn():
    """Prefilling the assistant's own turn is rejected by this model family, so the ask
    to continue has to be a user message — assert the shape, not just the outcome."""
    llm = ScriptedLLM([truncated_turn("cut off here"), final_turn(" and finished.")])
    agent = Agent(llm, ToolRegistry(mock_tools()))
    agent.run("Assess my fit")

    messages = llm.requests[-1]["messages"]
    ask = {"role": "user", "content": CONTINUE_INSTRUCTION}
    assert ask in messages
    # The truncated turn stays in the history — the continuation extends it rather than
    # replacing it, which is what makes the stitched text continuous.
    assert messages[messages.index(ask) - 1]["role"] == "assistant"


def test_running_out_of_continuations_reports_truncated_not_completed():
    agent = _agent([truncated_turn(f"piece {i} ") for i in range(4)], max_continuations=2)
    result = agent.run("Assess my fit")

    assert result.status is RunStatus.TRUNCATED  # never `completed` on a partial report
    assert result.final_text == "piece 0 piece 1 piece 2 "  # every piece kept
    assert result.steps == 3  # the first call plus two continuations
    assert result.trajectory.steps[-1].note == "max_tokens"


def test_a_continuation_still_obeys_the_step_budget():
    agent = _agent(
        [truncated_turn("partial ") for _ in range(4)],
        budget=Budget(max_steps=2, max_tokens=10**9, max_cost_usd=10**9),
        max_continuations=10,
    )
    result = agent.run("Assess my fit")

    assert result.status is RunStatus.BUDGET_STOPPED
    assert result.breach is BudgetBreach.STEPS
    assert result.steps == 2
    assert result.final_text == "partial partial "  # the pieces so far, not nothing


def test_only_a_continuation_accretes_text():
    """A continued answer is one answer. Text from an ordinary turn is not glued onto the
    next one — otherwise the report would carry the model's earlier thinking-out-loud."""
    agent = _agent(
        [
            tool_use_turn([("t1", "read_cv", {"path": "cv.md"})], text="checking the CV first"),
            final_turn("FINAL REPORT"),
        ]
    )
    result = agent.run("Assess my fit")
    assert result.final_text == "FINAL REPORT"


def test_trajectory_serializes_to_jsonl():
    agent = _agent([final_turn("nothing to do")])
    result = agent.run("noop")
    lines = result.trajectory.to_jsonl().splitlines()
    assert len(lines) == len(result.trajectory.steps)
    assert lines[0].startswith("{") and lines[0].endswith("}")
