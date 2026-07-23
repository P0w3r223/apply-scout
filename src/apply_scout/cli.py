"""Command-line entry point.

- `apply-scout run --url ... --cv ... --github-user ...` — assess one posting with the
  agent loop, streaming steps under `--verbose` and writing the trajectory JSONL.
- `apply-scout eval --tasks tasks.json --models a,b` — run the evaluation harness over a
  set of annotated tasks and write a markdown results table (two-model comparison).

A thin, standard-library CLI (a richer TUI is a later milestone).
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from apply_scout import config
from apply_scout.agent import RunStatus
from apply_scout.budget import Budget
from apply_scout.evaluation import evaluate_and_report, load_tasks
from apply_scout.formatting import format_step, format_summary
from apply_scout.runner import run_assessment


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

    eval_p = sub.add_parser("eval", help="Run the evaluation harness over a tasks file.")
    eval_p.add_argument("--tasks", required=True, help="Path to a JSON array of eval tasks.")
    eval_p.add_argument(
        "--models",
        default=f"{config.MODEL_CHEAP},{config.MODEL_STRONG}",
        help="Comma-separated model ids to compare.",
    )
    eval_p.add_argument("--out", default=None, help="Where to write the markdown results table.")
    return parser


def _run(args: argparse.Namespace) -> int:
    on_step = (lambda step: print(format_step(step))) if args.verbose else None
    budget = Budget(max_steps=args.max_steps, max_cost_usd=args.max_cost)

    result = run_assessment(
        job_url=args.url,
        cv_path=args.cv,
        github_user=args.github_user,
        model=args.model,
        budget=budget,
        on_step=on_step,
    )

    out_path = (
        Path(args.out)
        if args.out
        else config.RESULTS_DIR / f"trajectory-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
    )
    result.trajectory.write(out_path)

    if args.verbose:
        print()  # separate the step stream from the summary
    print(format_summary(result))
    print(f"\ntrajectory: {out_path}")
    return 0 if result.status is RunStatus.COMPLETED else 1


def _eval(args: argparse.Namespace) -> int:
    tasks = load_tasks(Path(args.tasks))
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    table = evaluate_and_report(tasks, models)

    out_path = (
        Path(args.out)
        if args.out
        else config.RESULTS_DIR / f"eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(table, encoding="utf-8")

    print(table)
    print(f"results: {out_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "eval":
        return _eval(args)
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
