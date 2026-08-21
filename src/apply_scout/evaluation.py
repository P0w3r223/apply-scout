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
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median

from pydantic import BaseModel, ConfigDict, ValidationError

from apply_scout import config
from apply_scout.budget import Budget
from apply_scout.contracts import CVProfile, JobPosting
from apply_scout.fetch import Extractor, Fetcher
from apply_scout.github import GitHubClient
from apply_scout.guardrail import guardrail_letter
from apply_scout.llm import LLMClient
from apply_scout.pipeline import Assessment, PipelineError, assess
from apply_scout.runner import run_assessment
from apply_scout.structuring import AnthropicStructurer, Structurer
from apply_scout.tools.submit_report import SubmitReport


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
    requirement_coverage: float
    citation_fidelity: float
    unsupported_fraction: float
    llm_calls: int
    cost_usd: float


@dataclass(frozen=True)
class Aggregate:
    model: str
    n_tasks: int
    completion_rate: float
    mean_requirement_coverage: float
    mean_citation_fidelity: float
    median_llm_calls: float
    median_cost_usd: float


# Runs one task, returning (assessment or None if it failed, cost_usd, llm_calls).
AssessFn = Callable[[EvalTask], "tuple[Assessment | None, float, int]"]


def _tokens(text: str) -> list[str]:
    """Lowercased word tokens, with a trailing plural `s` folded away.

    Deliberately crude: it exists to stop `embeddings` and `embedding models` counting
    as different skills, not to do linguistics. Anything cleverer would need its own
    tests to justify, and a metric nobody can re-derive by hand is worse than a blunt one.
    """
    words = re.split(r"[^a-z0-9+#]+", text.lower())
    return [w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words if w]


def mentions(requirement_text: str, expected: str) -> bool:
    """Whether one extracted requirement names the annotated skill.

    Containment, not equality: an annotation says `PyTorch` while a posting says
    "experience with PyTorch or TensorFlow in production". Those are the same finding,
    and scoring them as a miss measures the annotation format rather than the extraction.
    Tokens must appear consecutively, so `vector databases` does not match a requirement
    that merely happens to contain both words far apart.
    """
    want = _tokens(expected)
    if not want:
        return False
    got = _tokens(requirement_text)
    return any(got[i : i + len(want)] == want for i in range(len(got) - len(want) + 1))


def requirement_coverage(extracted: list[str], expected: list[str]) -> float:
    """Fraction of the annotated skills that appear somewhere in the extracted requirements.

    This is recall, and recall alone, on purpose — see `docs/decisions/0005`. The
    annotation lists the skills a human judged load-bearing, never every requirement in
    the posting, so there is no denominator that would make precision mean anything: a
    posting with 24 requirements annotated with 9 skills caps precision at 9/24 however
    perfect the extraction is. Reporting an F1 built on that denominator would grade the
    annotation's length, not the agent.
    """
    if not expected:
        return 1.0
    return sum(any(mentions(x, want) for x in extracted) for want in expected) / len(expected)


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
        requirement_coverage=requirement_coverage(extracted, list(task.expected_requirements)),
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
                    requirement_coverage=0.0,
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
        mean_requirement_coverage=(
            mean(m.requirement_coverage for m in completed) if completed else 0.0
        ),
        mean_citation_fidelity=mean(m.citation_fidelity for m in completed) if completed else 0.0,
        median_llm_calls=median(m.llm_calls for m in completed) if completed else 0.0,
        median_cost_usd=median(m.cost_usd for m in completed) if completed else 0.0,
    )


def format_comparison(aggregates: list[Aggregate]) -> str:
    """A markdown table, one row per model."""
    header = (
        "| Model | Tasks | Completed | Req coverage | Citation fidelity "
        "| Median LLM calls | Median cost |\n"
        "|---|---|---|---|---|---|---|\n"
    )
    rows = "".join(
        f"| {a.model} | {a.n_tasks} | {a.completion_rate:.0%} "
        f"| {a.mean_requirement_coverage:.2f} "
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
    extractor: Extractor | None = None,
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
                extractor=extractor,
                model=model,
                structure_model=model,  # uniform model for a head-to-head comparison
            )
        except PipelineError:
            assessment = None
        # Cost/calls are read off the structurer, so any wrapper standing in for it must
        # report them too — including a replay wrapper, which serves the recorded figures.
        return assessment, getattr(structurer, "cost_usd", 0.0), getattr(structurer, "calls", 0)

    return run


def agent_assess_fn(
    model: str,
    *,
    llm_factory: Callable[[], LLMClient],
    structurer_factory: Callable[[], Structurer] = AnthropicStructurer,
    fetcher: Fetcher | None = None,
    github: GitHubClient | None = None,
    extractor: Extractor | None = None,
    budget: Budget | None = None,
) -> AssessFn:
    """The other AssessFn: score the *agent loop* on the same tasks and the same metrics.

    This is what makes the project's headline claim checkable. Until now the harness only
    ever ran `pipeline_assess_fn`, so every published number described the deterministic
    pipeline — while the from-scratch loop, the thing ADR-0001 argues for, went unmeasured
    outside unit tests. The loop reaches the same contracts through `submit_report`, the
    same deterministic guardrail runs over its letter, so the two rows are comparable
    rather than merely adjacent.

    Cost and calls cover the *whole* run: the loop's own model calls plus the structuring
    the tools did on its behalf. Comparing the loop's token bill against a pipeline figure
    that quietly excluded half the work would be the kind of flattering accounting this
    harness exists to prevent.
    """

    ceilings = budget or Budget(
        max_steps=config.EVAL_AGENT_MAX_STEPS, max_cost_usd=config.EVAL_AGENT_MAX_COST_USD
    )

    def run(task: EvalTask) -> tuple[Assessment | None, float, int]:
        structurer = structurer_factory()
        submit = SubmitReport()
        result = run_assessment(
            job_url=task.job_url,
            cv_path=task.cv_path,
            github_user=task.github_user,
            llm=llm_factory(),
            model=model,
            budget=ceilings,
            fetcher=fetcher,
            structurer=structurer,
            github=github,
            extractor=extractor,
            submit=submit,
        )
        cost = result.cost_usd + float(getattr(structurer, "cost_usd", 0.0) or 0.0)
        calls = result.steps + int(getattr(structurer, "calls", 0) or 0)
        if submit.submitted is None:
            # The loop ran out of budget, or talked instead of submitting. Either way it
            # produced no deliverable, which is exactly what "not completed" means here.
            return None, cost, calls
        guard = guardrail_letter(submit.submitted.letter, submit.submitted.report)
        report = submit.submitted.report
        try:
            posting = JobPosting(
                url=report.job_url,
                title=report.job_title,
                # The requirements the loop actually reported on — there is no separate
                # posting object to score, and rating a requirement is what claiming to
                # have extracted it means.
                requirements=tuple(a.requirement for a in report.assessments),
            )
        except ValidationError:
            return None, cost, calls  # a submission too malformed to score
        assessment = Assessment(
            posting=posting,
            cv=CVProfile(),  # unused by every metric; the loop never returns one
            report=report,
            letter=guard.filtered,
            guardrail=guard,
        )
        return assessment, cost, calls

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
