"""The evaluation harness — the heart of the project.

Runs a set of annotated tasks through the assessment pipeline and scores the results:
did it complete, how well were the posting's requirements extracted (vs a human
annotation), how faithful are the letter's citations, and the median LLM calls and cost
per task. Two models can be compared head to head in one markdown table.

The metrics are pure functions of (task, Assessment) — the LLM variance lives in the
Assessment, so the scoring is deterministic and unit-tested with hand-built results.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median

from pydantic import BaseModel, ConfigDict

from apply_scout.fetch import Fetcher
from apply_scout.github import GitHubClient
from apply_scout.pipeline import Assessment, PipelineError, assess
from apply_scout.structuring import AnthropicStructurer, Structurer


class EvalTask(BaseModel):
    """One annotated evaluation task: the inputs plus the ground truth to score against."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    job_url: str
    cv_path: str
    github_user: str
    expected_requirements: tuple[str, ...]  # human-annotated ground-truth requirement texts
    notes: str | None = None  # e.g. "english posting", "no salary", "JS-required page"


@dataclass(frozen=True)
class TaskMetrics:
    name: str
    completed: bool
    requirement_f1: float
    citation_fidelity: float
    unsupported_fraction: float
    llm_calls: int
    cost_usd: float


@dataclass(frozen=True)
class Aggregate:
    model: str
    n_tasks: int
    completion_rate: float
    mean_requirement_f1: float
    mean_citation_fidelity: float
    median_llm_calls: float
    median_cost_usd: float


# Runs one task, returning (assessment or None if it failed, cost_usd, llm_calls).
AssessFn = Callable[[EvalTask], "tuple[Assessment | None, float, int]"]


def _norm(text: str) -> str:
    return text.strip().lower()


def requirement_f1(extracted: list[str], expected: list[str]) -> float:
    """F1 of the extracted requirement set vs the annotated one (case-insensitive)."""
    got = {_norm(x) for x in extracted}
    want = {_norm(x) for x in expected}
    if not got and not want:
        return 1.0
    tp = len(got & want)
    precision = tp / len(got) if got else 0.0
    recall = tp / len(want) if want else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def citation_fidelity(assessment: Assessment) -> float:
    """Of the letter sentences that cite evidence, the fraction whose citations are grounded.

    The guarded letter keeps only grounded cited sentences; the removed ones were exactly
    the ungrounded citations, so this is kept_cited / (kept_cited + removed)."""
    kept_cited = sum(1 for sentence in assessment.letter.sentences if sentence.evidence_urls)
    removed = len(assessment.guardrail.removed)
    total_cited = kept_cited + removed
    return kept_cited / total_cited if total_cited else 1.0


def evaluate_task(
    task: EvalTask, assessment: Assessment, *, cost_usd: float, llm_calls: int
) -> TaskMetrics:
    extracted = [requirement.text for requirement in assessment.posting.requirements]
    return TaskMetrics(
        name=task.name,
        completed=True,
        requirement_f1=requirement_f1(extracted, list(task.expected_requirements)),
        citation_fidelity=citation_fidelity(assessment),
        unsupported_fraction=assessment.guardrail.unsupported_before,
        llm_calls=llm_calls,
        cost_usd=cost_usd,
    )


def run_evaluation(tasks: list[EvalTask], assess_fn: AssessFn) -> list[TaskMetrics]:
    """Score every task. A task that fails to complete scores as not-completed (zeros)."""
    results: list[TaskMetrics] = []
    for task in tasks:
        assessment, cost_usd, llm_calls = assess_fn(task)
        if assessment is None:
            results.append(
                TaskMetrics(
                    name=task.name,
                    completed=False,
                    requirement_f1=0.0,
                    citation_fidelity=0.0,
                    unsupported_fraction=0.0,
                    llm_calls=llm_calls,
                    cost_usd=cost_usd,
                )
            )
        else:
            results.append(evaluate_task(task, assessment, cost_usd=cost_usd, llm_calls=llm_calls))
    return results


def aggregate(model: str, metrics: list[TaskMetrics]) -> Aggregate:
    completed = [m for m in metrics if m.completed]
    return Aggregate(
        model=model,
        n_tasks=len(metrics),
        completion_rate=(len(completed) / len(metrics)) if metrics else 0.0,
        mean_requirement_f1=mean(m.requirement_f1 for m in completed) if completed else 0.0,
        mean_citation_fidelity=mean(m.citation_fidelity for m in completed) if completed else 0.0,
        median_llm_calls=median(m.llm_calls for m in completed) if completed else 0.0,
        median_cost_usd=median(m.cost_usd for m in completed) if completed else 0.0,
    )


def format_comparison(aggregates: list[Aggregate]) -> str:
    """A markdown table, one row per model."""
    header = (
        "| Model | Tasks | Completed | Req F1 | Citation fidelity "
        "| Median LLM calls | Median cost |\n"
        "|---|---|---|---|---|---|---|\n"
    )
    rows = "".join(
        f"| {a.model} | {a.n_tasks} | {a.completion_rate:.0%} | {a.mean_requirement_f1:.2f} "
        f"| {a.mean_citation_fidelity:.2f} | {a.median_llm_calls:g} | ${a.median_cost_usd:.4f} |\n"
        for a in aggregates
    )
    return header + rows


def load_tasks(path: Path) -> list[EvalTask]:
    """Load tasks from a JSON array file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return [EvalTask.model_validate(item) for item in data]


def pipeline_assess_fn(
    model: str,
    *,
    structurer_factory: Callable[[], Structurer] = AnthropicStructurer,
    fetcher: Fetcher | None = None,
    github: GitHubClient | None = None,
) -> AssessFn:
    """The production AssessFn: run the real pipeline per task, reporting cost + calls.

    A fresh structurer *per task*, so cost and calls are per-task rather than cumulative —
    hence a factory rather than an instance. Passing a cassette-backed factory (plus its
    fetcher and GitHub client) is what makes the whole harness replayable offline; the
    default wiring is the live one. Not exercised by the unit tests (it needs a key +
    network); the harness logic itself is tested with injected fakes."""

    def run(task: EvalTask) -> tuple[Assessment | None, float, int]:
        structurer = structurer_factory()
        try:
            assessment: Assessment | None = assess(
                job_url=task.job_url,
                cv_path=task.cv_path,
                github_user=task.github_user,
                fetcher=fetcher,
                structurer=structurer,
                github=github,
                model=model,
                structure_model=model,  # uniform model for a head-to-head comparison
            )
        except PipelineError:
            assessment = None
        # Cost/calls are read off the structurer, so any wrapper standing in for it must
        # report them too — including a replay wrapper, which serves the recorded figures.
        return assessment, getattr(structurer, "cost_usd", 0.0), getattr(structurer, "calls", 0)

    return run


def run_models(
    tasks: list[EvalTask],
    models: list[str],
    *,
    assess_fn_factory: Callable[[str], AssessFn] = pipeline_assess_fn,
) -> list[Aggregate]:
    """Run the harness for each model and return one aggregate per model."""
    return [aggregate(m, run_evaluation(tasks, assess_fn_factory(m))) for m in models]


def evaluate_and_report(
    tasks: list[EvalTask],
    models: list[str],
    *,
    assess_fn_factory: Callable[[str], AssessFn] = pipeline_assess_fn,
) -> str:
    """Run the harness for each model and return the markdown comparison table."""
    return format_comparison(run_models(tasks, models, assess_fn_factory=assess_fn_factory))
