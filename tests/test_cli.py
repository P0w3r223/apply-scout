"""The CLI wiring: parse args, run (stubbed), write the trajectory, print, exit code."""

from __future__ import annotations

import pytest

import apply_scout.cli as cli
from apply_scout.agent import AgentResult, RunStatus
from apply_scout.cassette import CassetteLLM, CassetteMiss
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


def test_eval_writes_markdown_table_and_prints(tmp_path, monkeypatch, capsys):
    from apply_scout.evaluation import Aggregate

    fake = [Aggregate("good", 1, 1.0, 1.0, 1.0, 4, 0.01)]
    monkeypatch.setattr(cli, "run_models", lambda tasks, models, **kwargs: fake)
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text(
        '[{"name": "t", "job_url": "u", "cv_path": "c", "github_user": "g", '
        '"expected_requirements": ["Python"]}]',
        encoding="utf-8",
    )
    out = tmp_path / "report.md"

    code = cli.main(["eval", "--tasks", str(tasks_file), "--models", "good", "--out", str(out)])

    assert code == 0
    assert "| good |" in out.read_text(encoding="utf-8")  # markdown table (for the README)
    assert "good" in capsys.readouterr().out  # rich table rendered to the console


# --- cassette wiring ----------------------------------------------------------


def _capture_run(monkeypatch) -> dict:
    captured: dict = {}

    def stub(**kwargs):
        captured.update(kwargs)
        return _canned_result()

    monkeypatch.setattr(cli, "run_assessment", stub)
    return captured


def test_run_stays_live_unless_a_cassette_mode_is_asked_for(tmp_path, monkeypatch):
    captured = _capture_run(monkeypatch)

    cli.main(
        ["run", "--url", "u", "--cv", "c", "--github-user", "g", "--out", str(tmp_path / "t.jsonl")]
    )

    # No cassette collaborators injected -> run_assessment builds the production wiring.
    assert "llm" not in captured and "fetcher" not in captured


def test_run_replay_injects_the_cassette_collaborators(tmp_path, monkeypatch, capsys):
    captured = _capture_run(monkeypatch)

    cli.main(
        [
            "run", "--url", "u", "--cv", "c", "--github-user", "g",
            "--out", str(tmp_path / "t.jsonl"),
            "--cassette-mode", "replay", "--cassette", str(tmp_path / "c.jsonl"),
        ]
    )

    assert isinstance(captured["llm"], CassetteLLM)
    assert not captured["llm"].live  # replay must not construct a real client
    assert not captured["fetcher"].live
    # Extraction is a recorded seam too — a live one here would re-derive the page text
    # from the local trafilatura and miss every entry keyed on the recorded text.
    assert not captured["extractor"].live
    assert "cassette[replay]" in capsys.readouterr().out


def test_eval_replay_swaps_in_a_cassette_backed_assess_factory(tmp_path, monkeypatch):
    from apply_scout.evaluation import Aggregate

    captured: dict = {}

    def stub(tasks, models, **kwargs):
        captured.update(kwargs)
        return [Aggregate("m", 1, 1.0, 1.0, 1.0, 4, 0.01)]

    monkeypatch.setattr(cli, "run_models", stub)
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text(
        '[{"name": "t", "job_url": "u", "cv_path": "c", "github_user": "g", '
        '"expected_requirements": ["Python"]}]',
        encoding="utf-8",
    )

    cli.main(
        [
            "eval", "--tasks", str(tasks_file), "--models", "m",
            "--out", str(tmp_path / "r.md"),
            "--cassette-mode", "replay", "--cassette", str(tmp_path / "c.jsonl"),
        ]
    )

    assert callable(captured["assess_fn_factory"])


def test_a_cassette_miss_exits_two_with_a_readable_message(tmp_path, monkeypatch, capsys):
    """A replay miss must read as 'the cassette is stale', not as a stack trace."""

    def boom(**kwargs):
        raise CassetteMiss("no recorded llm response for claude-x")

    monkeypatch.setattr(cli, "run_assessment", boom)

    code = cli.main(
        [
            "run", "--url", "u", "--cv", "c", "--github-user", "g",
            "--out", str(tmp_path / "t.jsonl"),
            "--cassette-mode", "replay", "--cassette", str(tmp_path / "c.jsonl"),
        ]
    )

    assert code == 2
    assert "cassette miss" in capsys.readouterr().err


def test_an_unknown_cassette_mode_is_rejected_at_parse_time(tmp_path):
    with pytest.raises(SystemExit):
        cli.main(
            ["run", "--url", "u", "--cv", "c", "--github-user", "g", "--cassette-mode", "nope"]
        )
