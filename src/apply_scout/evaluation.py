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

from pydantic import BaseModel, ConfigDict, ValidationError

from apply_scout import config
from apply_scout.budget import Budget
from apply_scout.contracts import CVProfile, JobPosting
from apply_scout.fetch import Extractor, Fetcher, HttpFetcher
from apply_scout.github import DiskCache, GitHubClient
from apply_scout.guardrail import evidence_grounding, guardrail_letter, requirement_grounding
from apply_scout.llm import LLMClient
from apply_scout.matching import mentions
from apply_scout.pipeline import Assessment, PipelineError, assess
from apply_scout.runner import run_assessment
from apply_scout.structuring import AnthropicStructurer, Structurer
from apply_scout.tools.fetch_job_posting import FetchJobPosting
from apply_scout.tools.github_evidence import GithubEvidence
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
    """One task's scores. `None` means "this task cannot answer that question" — an
    unannotated posting has no coverage to measure, a letter with no citations has no
    fidelity. Averaging a stand-in value over those is how a metric flatters itself."""

    name: str
    completed: bool
    requirement_coverage: float | None
    requirement_grounding: float | None
    evidence_grounding: float | None
    citation_fidelity: float | None
    citation_rate: float | None
    llm_calls: int
    cost_usd: float


@dataclass(frozen=True)
class Aggregate:
    model: str
    n_tasks: int
    completion_rate: float
    mean_requirement_coverage: float | None
    mean_requirement_grounding: float | None
    mean_evidence_grounding: float | None
    mean_citation_fidelity: float | None
    mean_citation_rate: float | None
    # How many tasks each mean is actually over — a 1.00 from one task is not a 1.00
    # from six, and the table has no business hiding which it is.
    scored_coverage: int
    scored_grounding: int
    scored_evidence: int
    scored_fidelity: int
    scored_rate: int
    median_llm_calls: float
    median_cost_usd: float


# Runs one task, returning (assessment or None if it failed, cost_usd, llm_calls).
AssessFn = Callable[[EvalTask], "tuple[Assessment | None, float, int]"]


def requirement_coverage(extracted: list[str], expected: list[str]) -> float | None:
    """Fraction of the annotated skills that appear somewhere in the extracted requirements.

    This is recall, and recall alone, on purpose — see `docs/decisions/0005`. The
    annotation lists the skills a human judged load-bearing, never every requirement in
    the posting, so there is no denominator that would make precision mean anything: a
    posting with 24 requirements annotated with 9 skills caps precision at 9/24 however
    perfect the extraction is. Reporting an F1 built on that denominator would grade the
    annotation's length, not the agent.

    `None` when the task has no annotation at all. Scoring that 1.0 — as this did — hands
    a perfect row to the deliberately-unreadable JavaScript-only task, which is 1 of 6
    completed tasks and so lifted every published mean by a sixth of a point for having
    nothing to be right about.
    """
    if not expected:
        return None
    return sum(any(mentions(x, want) for x in extracted) for want in expected) / len(expected)


def citation_fidelity(assessment: Assessment) -> float | None:
    """Of the letter sentences that cite evidence, the fraction whose citations are grounded.

    The guarded letter keeps only grounded cited sentences; the removed ones were exactly
    the ungrounded citations, so this is kept_cited / (kept_cited + removed).

    `None` when the letter cited nothing at all. This used to return 1.0, which made the
    metric say its most flattering thing about its worst case: a letter of a dozen factual
    claims carrying no citations scored a perfect fidelity, indistinguishable from one that
    cited a real link for every claim. Read it alongside `citation_rate` — a fidelity
    without its denominator is not a result.
    """
    kept_cited = sum(1 for sentence in assessment.letter.sentences if sentence.evidence_urls)
    removed = len(assessment.guardrail.removed)
    total_cited = kept_cited + removed
    return kept_cited / total_cited if total_cited else None


def citation_rate(assessment: Assessment) -> float | None:
    """Of all the letter's sentences, the fraction that cite anything at all.

    The denominator `citation_fidelity` throws away. A model that avoids citations cannot
    be caught fabricating them, so fidelity alone rewards writing vaguely; this is what
    separates "grounded" from "said nothing checkable"."""
    written = len(assessment.letter.sentences) + len(assessment.guardrail.removed)
    if not written:
        return None
    cited = sum(1 for s in assessment.letter.sentences if s.evidence_urls)
    return (cited + len(assessment.guardrail.removed)) / written


def evaluate_task(
    task: EvalTask, assessment: Assessment, *, cost_usd: float, llm_calls: int
) -> TaskMetrics:
    extracted = [requirement.text for requirement in assessment.posting.requirements]
    return TaskMetrics(
        name=task.name,
        completed=True,
        requirement_coverage=requirement_coverage(extracted, list(task.expected_requirements)),
        # Scored against the *fetched* postings, never `assessment.posting` — on the agent
        # path that one is rebuilt from the report, and a report always grounds itself.
        requirement_grounding=requirement_grounding(assessment.report, assessment.source_postings),
        # One level down: the links the report itself cites, against what the tools retrieved.
        # `citation_fidelity` cannot see this — it scores the letter against the report, so a
        # link that reaches the report is already a valid citation target.
        evidence_grounding=evidence_grounding(assessment.report, assessment.source_evidence),
        citation_fidelity=citation_fidelity(assessment),
        citation_rate=citation_rate(assessment),
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
                    # Not zero: a run that produced nothing has no quality to score, and a
                    # zero would drag the mean as if it had been measured and found bad.
                    # Failure is already reported by the completion rate.
                    requirement_coverage=None,
                    requirement_grounding=None,
                    evidence_grounding=None,
                    citation_fidelity=None,
                    citation_rate=None,
                    llm_calls=llm_calls,
                    cost_usd=cost_usd,
                )
            )
        else:
            results.append(evaluate_task(task, assessment, cost_usd=cost_usd, llm_calls=llm_calls))
    return results


def aggregate(model: str, metrics: list[TaskMetrics]) -> Aggregate:
    completed = [m for m in metrics if m.completed]
    coverage = [m.requirement_coverage for m in completed if m.requirement_coverage is not None]
    grounding = [m.requirement_grounding for m in completed if m.requirement_grounding is not None]
    evidence = [m.evidence_grounding for m in completed if m.evidence_grounding is not None]
    fidelity = [m.citation_fidelity for m in completed if m.citation_fidelity is not None]
    rate = [m.citation_rate for m in completed if m.citation_rate is not None]
    return Aggregate(
        model=model,
        n_tasks=len(metrics),
        completion_rate=(len(completed) / len(metrics)) if metrics else 0.0,
        mean_requirement_coverage=mean(coverage) if coverage else None,
        mean_requirement_grounding=mean(grounding) if grounding else None,
        mean_evidence_grounding=mean(evidence) if evidence else None,
        mean_citation_fidelity=mean(fidelity) if fidelity else None,
        mean_citation_rate=mean(rate) if rate else None,
        scored_coverage=len(coverage),
        scored_grounding=len(grounding),
        scored_evidence=len(evidence),
        scored_fidelity=len(fidelity),
        scored_rate=len(rate),
        median_llm_calls=median(m.llm_calls for m in completed) if completed else 0.0,
        median_cost_usd=median(m.cost_usd for m in completed) if completed else 0.0,
    )


def format_score(value: float | None, scored: int | None = None) -> str:
    """A metric cell: the number and, where it matters, how many tasks it averages."""
    if value is None:
        return "n/a"
    return f"{value:.2f}" if scored is None else f"{value:.2f} ({scored})"


def format_comparison(aggregates: list[Aggregate]) -> str:
    """A markdown table, one row per model.

    Both citation columns are printed together on purpose: fidelity says how many cited
    claims were grounded, and the rate says how many claims were cited at all. Fidelity
    alone reads best for a letter that promises nothing checkable.

    `Report grounded` sits next to coverage for the same reason: coverage says how much of
    the posting was found, grounding how much of the report came from the posting at all.
    A run can score well on the first while inventing its way to the second."""
    header = (
        "| Model | Tasks | Completed | Req coverage | Report grounded | Evidence grounded "
        "| Citation fidelity | Cited | Median LLM calls | Median cost |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n"
    )
    rows = "".join(
        f"| {a.model} | {a.n_tasks} | {a.completion_rate:.0%} "
        f"| {format_score(a.mean_requirement_coverage, a.scored_coverage)} "
        f"| {format_score(a.mean_requirement_grounding, a.scored_grounding)} "
        f"| {format_score(a.mean_evidence_grounding, a.scored_evidence)} "
        f"| {format_score(a.mean_citation_fidelity, a.scored_fidelity)} "
        f"| {format_score(a.mean_citation_rate, a.scored_rate)} "
        f"| {a.median_llm_calls:g} | ${a.median_cost_usd:.4f} |\n"
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
        else:
            if not assessment.report.assessments:
                # A report that rates nothing is not a deliverable, and the published table
                # had two definitions of "Completed" sitting in adjacent rows: the agent path
                # already requires a submission, while this one counted the JavaScript-only
                # task as a success on the strength of a posting with no requirements, an empty
                # report and two sentences of boilerplate. Its own fixture says "expected to
                # fail extraction and score as not-completed". Every grounding column returns
                # `n/a` there, so nothing else in the table could catch it — it fed only the
                # completion rate it inflated, from an honest 62% to 75%.
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
        max_steps=config.EVAL_AGENT_MAX_STEPS,
        max_tokens=config.EVAL_AGENT_MAX_TOKENS,
        max_cost_usd=config.EVAL_AGENT_MAX_COST_USD,
    )
    # Resolved once, not per task: these are handed both to our own tool instances and to the
    # toolset, so a live run opens one HTTP client (and one on-disk cache) for the whole
    # evaluation instead of two per task, none of which anything closes.
    fetcher = fetcher or HttpFetcher()
    github = github or GitHubClient(cache=DiskCache(config.CACHE_DIR))

    def run(task: EvalTask) -> tuple[Assessment | None, float, int]:
        structurer = structurer_factory()
        submit = SubmitReport()
        # Ours rather than the toolset's, so the postings the loop actually read can be
        # recovered afterwards — the report has to be checked against something the report
        # did not write. Built with the same collaborators the run gets, and left on the
        # structuring model the toolset would have chosen, so nothing about the requests
        # changes: a different model here would miss every recorded cassette entry.
        fetch = FetchJobPosting(fetcher=fetcher, structurer=structurer, extractor=extractor)
        evidence = GithubEvidence(client=github)
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
            fetch=fetch,
            evidence=evidence,
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
            # The independent side of the grounding check. Empty when the loop submitted a
            # report without ever successfully fetching the ad — which is exactly the run
            # the metric was added for, not a gap in the data.
            source_postings=fetch.postings,
            source_evidence=evidence.returned,
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
