"""Command-line entry point.

- `apply-scout run --url ... --cv ... --github-user ...` — assess one posting with the
  agent loop, streaming steps under `--verbose` and writing the trajectory JSONL.
- `apply-scout eval --tasks tasks.json --models a,b` — run the evaluation harness and
  write a markdown results table (plus a pretty table in the terminal).

Both accept `--cassette-mode` to record every external response to a cassette, or to
replay one — which is how the evaluation reruns with no network, no API key, and no
cost (see `cassette.py`).

Uses `rich` for the terminal UI; the machine-readable outputs (trajectory JSONL, the
markdown eval table) stay plain so they drop straight into a file or the README.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from apply_scout import config
from apply_scout.agent import RunStatus
from apply_scout.budget import Budget
from apply_scout.cassette import (
    CassetteMiss,
    CassetteMode,
    CassetteSession,
    default_cassette_path,
)
from apply_scout.env import load_dotenv
from apply_scout.evaluation import (
    Aggregate,
    agent_assess_fn,
    format_comparison,
    format_score,
    load_tasks,
    pipeline_assess_fn,
    run_models,
)
from apply_scout.formatting import format_report, format_step, format_summary, step_style
from apply_scout.github import GitHubClient
from apply_scout.llm import AnthropicLLM
from apply_scout.runner import run_assessment
from apply_scout.tools.submit_report import SubmitReport
from apply_scout.trajectory import TrajectoryStep

_CASSETTE_MODES = ("off", *(mode.value for mode in CassetteMode))


def _add_cassette_args(parser: argparse.ArgumentParser, default_name: str) -> None:
    """The record/replay switches, identical on every subcommand."""
    parser.add_argument(
        "--cassette-mode",
        choices=_CASSETTE_MODES,
        default="off",
        help=(
            "off: call the real services (default). record: call them and store every "
            "response. replay: serve responses from the cassette only — no network, no "
            "API key. auto: replay what is recorded, record what is not."
        ),
    )
    parser.add_argument(
        "--cassette",
        default=None,
        help=f"Cassette file (default: {default_cassette_path(default_name)}).",
    )


def _open_session(args: argparse.Namespace, default_name: str) -> CassetteSession | None:
    """Build the cassette session for this invocation, or None when running live."""
    if args.cassette_mode == "off":
        return None
    path = Path(args.cassette) if args.cassette else default_cassette_path(default_name)
    return CassetteSession.open(path, CassetteMode(args.cassette_mode))


def _report_session(session: CassetteSession | None) -> None:
    if session is None:
        return
    print(session.summary())
    saved = session.save()
    if saved is not None:
        print(f"cassette written: {saved}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apply-scout",
        description="LLM agent: match a job posting against a CV and GitHub evidence.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Assess fit for a single posting.")
    run_p.add_argument("--url", required=True, help="Job posting URL.")
    run_p.add_argument("--cv", required=True, help="Path to the candidate's CV file.")
    run_p.add_argument("--github-user", required=True, help="Candidate's GitHub username.")
    run_p.add_argument("--model", default=config.DEFAULT_MODEL, help="Agent model id.")
    run_p.add_argument("--verbose", action="store_true", help="Print each step as it happens.")
    run_p.add_argument("--out", default=None, help="Where to write the trajectory JSONL.")
    run_p.add_argument("--max-steps", type=int, default=config.DEFAULT_MAX_STEPS)
    run_p.add_argument("--max-cost", type=float, default=config.DEFAULT_MAX_COST_USD)
    _add_cassette_args(run_p, "run")

    eval_p = sub.add_parser("eval", help="Run the evaluation harness over a tasks file.")
    eval_p.add_argument("--tasks", required=True, help="Path to a JSON array of eval tasks.")
    eval_p.add_argument(
        "--models",
        default=f"{config.MODEL_CHEAP},{config.MODEL_STRONG}",
        help="Comma-separated model ids to compare.",
    )
    eval_p.add_argument("--out", default=None, help="Where to write the markdown results table.")
    eval_p.add_argument(
        "--runner",
        choices=("pipeline", "agent"),
        default="pipeline",
        help=(
            "pipeline: the deterministic gather-synthesize-guard path (default). "
            "agent: the from-scratch tool loop, finishing through submit_report. Same "
            "tasks, same metrics — this is the loop-vs-pipeline comparison."
        ),
    )
    _add_cassette_args(eval_p, "eval")
    return parser


def _run(args: argparse.Namespace) -> int:
    console = Console()

    def print_step(step: TrajectoryStep) -> None:
        console.print(format_step(step), style=step_style(step), markup=False)

    on_step = print_step if args.verbose else None
    budget = Budget(max_steps=args.max_steps, max_cost_usd=args.max_cost)
    session = _open_session(args, "run")
    wiring = (
        {}
        if session is None
        else {
            "llm": session.llm(),
            "fetcher": session.fetcher(),
            "structurer": session.structurer(),
            "extractor": session.extractor(),
            "github": GitHubClient(cache=session.github_cache()),
        }
    )

    # Held by us rather than the toolset, so the finished deliverable can be printed:
    # the agent submits a contract now, not prose (tools/submit_report.py).
    submit = SubmitReport()
    result = run_assessment(
        job_url=args.url,
        cv_path=args.cv,
        github_user=args.github_user,
        model=args.model,
        budget=budget,
        on_step=on_step,
        submit=submit,
        **wiring,
    )

    out_path = (
        Path(args.out)
        if args.out
        else config.RESULTS_DIR / f"trajectory-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
    )
    result.trajectory.write(out_path)

    # Plain print for the summary + path so they're copy-pasteable and unwrapped.
    print()
    print(format_summary(result))
    if submit.submitted is not None:
        print()
        print(format_report(submit.submitted.report, submit.submitted.letter))
    print(f"\ntrajectory: {out_path}")
    _report_session(session)
    if submit.submitted is None:
        # A run can end `completed` — the model stopped calling tools — and still have
        # submitted nothing, which is what both dead-URL tasks do: it gives up in prose.
        # The deliverable is the point, so that is a failure exit however the loop ended.
        print("no report was submitted", file=sys.stderr)
        return 1
    return 0 if result.status is RunStatus.COMPLETED else 1


def _eval_table(aggregates: list[Aggregate]) -> Table:
    table = Table(title="Evaluation — model comparison")
    columns = (
        "Model",
        "Tasks",
        "Completed",
        "Req cov.",
        "Citation",
        "Cited",
        "Med. calls",
        "Med. cost",
    )
    for column in columns:
        table.add_column(column)
    for a in aggregates:
        table.add_row(
            a.model,
            str(a.n_tasks),
            f"{a.completion_rate:.0%}",
            format_score(a.mean_requirement_coverage, a.scored_coverage),
            format_score(a.mean_citation_fidelity, a.scored_fidelity),
            format_score(a.mean_citation_rate),
            f"{a.median_llm_calls:g}",
            f"${a.median_cost_usd:.4f}",
        )
    return table


def _assess_fn_factory(session: CassetteSession | None, runner: str):
    """Bind the chosen runner — and the cassette's collaborators, if any — into the
    harness's per-model AssessFn factory.

    The fetcher and GitHub client are shared across tasks (they hold no per-task state),
    while the structurer is created per task — that is what keeps cost and call counts
    attributable to a single task."""
    wiring: dict = {}
    if session is not None:
        wiring = {
            "structurer_factory": session.structurer,
            "fetcher": session.fetcher(),
            "extractor": session.extractor(),
            "github": GitHubClient(cache=session.github_cache()),
        }

    def factory(model: str):
        if runner == "agent":
            llm_factory = session.llm if session is not None else AnthropicLLM
            return agent_assess_fn(model, llm_factory=llm_factory, **wiring)
        return pipeline_assess_fn(model, **wiring)

    return factory


def _eval(args: argparse.Namespace) -> int:
    tasks = load_tasks(Path(args.tasks))
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    session = _open_session(args, "eval")
    aggregates = run_models(
        tasks, models, assess_fn_factory=_assess_fn_factory(session, args.runner)
    )

    out_path = (
        Path(args.out)
        if args.out
        else config.RESULTS_DIR / f"eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(format_comparison(aggregates), encoding="utf-8")  # markdown for the README

    Console().print(_eval_table(aggregates))
    print(f"results (markdown): {out_path}")
    _report_session(session)
    return 0


def _make_output_utf8_safe() -> None:
    """Rich renders through ``sys.stdout``; on a legacy Windows console its codepage
    (e.g. cp1250) can't encode characters like ``—`` and raises ``UnicodeEncodeError``
    mid-render. Make the streams tolerant: prefer UTF-8, and never raise on a glyph the
    stream can't encode."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(OSError, ValueError):  # a detached / already-closed stream
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _make_output_utf8_safe()
    # Pick up a local .env before anything can need a key. Harmless when there is none,
    # and an already-exported variable still wins (see env.py).
    load_dotenv()
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "eval":
            return _eval(args)
        return _run(args)
    except CassetteMiss as exc:
        # A replay miss is a harness problem, not a model problem: the prompts or the
        # inputs moved on since the cassette was cut. Say so in one line and stop —
        # silently reaching for the network here would defeat the whole mechanism.
        print(f"cassette miss: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
