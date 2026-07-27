"""The runner: a full end-to-end assessment under a scripted model + mock tools."""

from __future__ import annotations

from fakes import ScriptedLLM, final_turn, tool_use_turn

from apply_scout.agent import RunStatus
from apply_scout.budget import Budget, BudgetBreach
from apply_scout.runner import build_task, run_assessment
from apply_scout.tools.mock import mock_tools
from apply_scout.tools.registry import ToolRegistry


def test_build_task_includes_the_inputs():
    task = build_task(job_url="https://x/job", cv_path="cv.md", github_user="P0w3r223")
    assert "https://x/job" in task
    assert "cv.md" in task
    assert "P0w3r223" in task


def test_run_assessment_end_to_end():
    llm = ScriptedLLM(
        [
            tool_use_turn([("t1", "fetch_job_posting", {"url": "https://x/job"})]),
            tool_use_turn([("t2", "read_cv", {"path": "cv.md"})]),
            tool_use_turn(
                [("t3", "github_evidence", {"requirement": "FastAPI", "github_user": "P0w3r223"})]
            ),
            final_turn("MATCH REPORT: Python strong, FastAPI strong."),
        ]
    )
    result = run_assessment(
        job_url="https://x/job",
        cv_path="cv.md",
        github_user="P0w3r223",
        llm=llm,
        tools=ToolRegistry(mock_tools()),
    )
    assert result.status is RunStatus.COMPLETED
    assert "MATCH REPORT" in result.final_text
    assert result.steps == 4
    assert result.cost_usd > 0


def test_run_assessment_respects_budget():
    llm = ScriptedLLM(
        [
            tool_use_turn([("t", "fetch_job_posting", {"url": "u"})], text="working")
            for _ in range(6)
        ]
    )
    result = run_assessment(
        job_url="u",
        cv_path="c",
        github_user="g",
        llm=llm,
        tools=ToolRegistry(mock_tools()),
        budget=Budget(max_steps=2, max_tokens=10**9, max_cost_usd=10**9),
    )
    assert result.status is RunStatus.BUDGET_STOPPED
    assert result.breach is BudgetBreach.STEPS


def test_on_step_observer_sees_every_step():
    seen = []
    llm = ScriptedLLM([final_turn("done")])
    result = run_assessment(
        job_url="u",
        cv_path="c",
        github_user="g",
        llm=llm,
        tools=ToolRegistry(mock_tools()),
        on_step=seen.append,
    )
    assert len(seen) == len(result.trajectory.steps)
    assert seen[0].kind.value == "model_call"
