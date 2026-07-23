"""The evaluation harness: metrics, aggregation, the markdown table, and regression visibility."""

from __future__ import annotations

from apply_scout.contracts import (
    CoverLetterDraft,
    CVProfile,
    JobPosting,
    LetterSentence,
    MatchReport,
    Requirement,
)
from apply_scout.evaluation import (
    Aggregate,
    EvalTask,
    TaskMetrics,
    aggregate,
    citation_fidelity,
    evaluate_and_report,
    evaluate_task,
    format_comparison,
    requirement_f1,
    run_evaluation,
)
from apply_scout.guardrail import GuardrailResult
from apply_scout.pipeline import Assessment


def _assessment(*, requirements, letter_sentences, removed, unsupported_before=0.0) -> Assessment:
    posting = JobPosting(
        url="https://x", title="X", requirements=tuple(Requirement(text=r) for r in requirements)
    )
    letter = CoverLetterDraft(sentences=tuple(letter_sentences))
    guard = GuardrailResult(
        filtered=letter,
        removed=tuple(removed),
        unsupported_before=unsupported_before,
        unsupported_after=0.0,
    )
    return Assessment(
        posting=posting,
        cv=CVProfile(),
        report=MatchReport(job_title="X", job_url="https://x"),
        letter=letter,
        guardrail=guard,
    )


def _task(expected) -> EvalTask:
    return EvalTask(
        name="t", job_url="u", cv_path="c", github_user="g", expected_requirements=tuple(expected)
    )


def test_requirement_f1_is_case_insensitive_and_set_based():
    assert requirement_f1(["Python", "SQL"], ["python", "sql"]) == 1.0
    assert requirement_f1(["Python", "Java"], ["Python", "SQL"]) == 0.5  # tp=1, p=r=0.5
    assert requirement_f1([], []) == 1.0


def test_citation_fidelity_is_grounded_over_cited():
    kept = [
        LetterSentence(text="a", evidence_urls=("u1",)),
        LetterSentence(text="b", evidence_urls=("u2",)),
        LetterSentence(text="hello"),  # connective, not counted
    ]
    removed = [LetterSentence(text="bad", evidence_urls=("fabricated",))]
    a = _assessment(requirements=["Python"], letter_sentences=kept, removed=removed)
    assert citation_fidelity(a) == 2 / 3  # 2 grounded cited / (2 + 1 removed)


def test_evaluate_task_scores_a_completed_run():
    a = _assessment(
        requirements=["Python", "FastAPI"],
        letter_sentences=[LetterSentence(text="x", evidence_urls=("u",))],
        removed=[],
    )
    metrics = evaluate_task(_task(["Python", "FastAPI"]), a, cost_usd=0.01, llm_calls=4)
    assert metrics.completed
    assert metrics.requirement_f1 == 1.0
    assert metrics.citation_fidelity == 1.0
    assert metrics.llm_calls == 4
    assert metrics.cost_usd == 0.01


def test_run_evaluation_marks_failures_not_completed():
    metrics = run_evaluation([_task(["Python"])], lambda t: (None, 0.02, 1))
    assert metrics[0].completed is False
    assert metrics[0].cost_usd == 0.02


def test_aggregate_uses_completed_only_and_medians():
    metrics = [
        TaskMetrics("a", True, 1.0, 1.0, 0.0, 4, 0.01),
        TaskMetrics("b", True, 0.5, 0.8, 0.2, 6, 0.03),
        TaskMetrics("c", False, 0.0, 0.0, 0.0, 1, 0.005),
    ]
    agg = aggregate("m", metrics)
    assert agg.n_tasks == 3
    assert agg.completion_rate == 2 / 3
    assert agg.mean_requirement_f1 == 0.75
    assert agg.median_llm_calls == 5  # median of [4, 6]
    assert agg.median_cost_usd == 0.02  # median of [0.01, 0.03]


def test_format_comparison_is_markdown():
    agg = Aggregate("claude-haiku-4-5", 2, 1.0, 0.90, 0.95, 4, 0.012)
    table = format_comparison([agg])
    assert "| Model |" in table
    assert "claude-haiku-4-5" in table
    assert "100%" in table
    assert "0.90" in table
    assert "$0.0120" in table


def test_two_model_comparison_makes_regression_visible():
    good = _assessment(
        requirements=["Python", "FastAPI"],
        letter_sentences=[LetterSentence(text="x", evidence_urls=("u",))],
        removed=[],
    )
    broken = _assessment(  # worse extraction and a fabricated citation
        requirements=["Ruby"],
        letter_sentences=[],
        removed=[LetterSentence(text="bad", evidence_urls=("fabricated",))],
        unsupported_before=1.0,
    )

    def factory(model):
        chosen = good if model == "good" else broken
        return lambda task: (chosen, 0.01, 4)

    table = evaluate_and_report(
        [_task(["Python", "FastAPI"])], ["good", "broken"], assess_fn_factory=factory
    )
    good_row = next(line for line in table.splitlines() if "| good |" in line)
    broken_row = next(line for line in table.splitlines() if "| broken |" in line)
    assert "1.00" in good_row  # perfect extraction + citations
    assert "0.00" in broken_row  # the regression is visible in the table
