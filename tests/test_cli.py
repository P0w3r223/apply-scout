"""The CLI wiring: parse args, run (stubbed), write the trajectory, print, exit code."""

from __future__ import annotations

import apply_scout.cli as cli
from apply_scout.agent import AgentResult, RunStatus
from apply_scout.trajectory import StepKind, TrajectoryLogger, TrajectoryStep


def _canned_result(status: RunStatus = RunStatus.COMPLETED, breach=None) -> AgentResult:
    traj = TrajectoryLogger()
    traj.record(
        TrajectoryStep(
            index=0,
            kind=StepKind.MODEL_CALL,
            model="m",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.0001,
            tool_calls_requested=0,
            text="done",
        )
    )
    traj.record(TrajectoryStep(index=1, kind=StepKind.FINAL, note="end_turn"))
    return AgentResult(
        status=status,
        final_text="REPORT",
        trajectory=traj,
        steps=1,
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.0001,
        breach=breach,
    )


def test_run_writes_trajectory_and_returns_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_assessment", lambda **kwargs: _canned_result())
    out = tmp_path / "traj.jsonl"

    code = cli.main(
        ["run", "--url", "https://x/job", "--cv", "cv.md", "--github-user", "g", "--out", str(out)]
    )

    assert code == 0
    assert out.exists()
    assert len(out.read_text(encoding="utf-8").splitlines()) == 2  # two steps written
    printed = capsys.readouterr().out
    assert "REPORT" in printed
    assert str(out) in printed


def test_budget_stop_returns_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli, "run_assessment", lambda **kwargs: _canned_result(status=RunStatus.BUDGET_STOPPED)
    )
    code = cli.main(
        ["run", "--url", "u", "--cv", "c", "--github-user", "g", "--out", str(tmp_path / "t.jsonl")]
    )
    assert code == 1


def test_verbose_passes_on_step_callback(tmp_path, monkeypatch):
    captured: dict = {}

    def stub(**kwargs):
        captured.update(kwargs)
        return _canned_result()

    monkeypatch.setattr(cli, "run_assessment", stub)

    cli.main(
        ["run", "--url", "u", "--cv", "c", "--github-user", "g", "--out", str(tmp_path / "a.jsonl")]
    )
    assert captured["on_step"] is None  # no --verbose -> no observer

    cli.main(
        [
            "run", "--url", "u", "--cv", "c", "--github-user", "g",
            "--verbose", "--out", str(tmp_path / "b.jsonl"),
        ]
    )
    assert captured["on_step"] is not None  # --verbose -> observer wired
