"""Command-line entry point: `apply-scout run --url ... --cv ... --github-user ...`.

A thin, standard-library CLI (a richer TUI is a later milestone). It parses the run
inputs, wires a safety budget, streams each step when `--verbose`, writes the trajectory
JSONL, and prints the summary. Exit code is 0 on a completed run, 1 on a budget stop.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from apply_scout import config
from apply_scout.agent import RunStatus
from apply_scout.budget import Budget
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

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


if __name__ == "__main__":
    raise SystemExit(main())
