"""The evaluation harness: metrics, aggregation, the markdown table, and regression visibility."""

from __future__ import annotations

from apply_scout.contracts import (
    CoverLetterDraft,
    CVProfile,
    JobPosting,
    LetterSentence,
    MatchAssessment,
    MatchReport,
    Rating,
    Requirement,
)
from apply_scout.evaluation import (
    Aggregate,
    EvalTask,
    TaskMetrics,
    aggregate,
    citation_fidelity,
    citation_rate,
    evaluate_and_report,
    evaluate_task,
    format_comparison,
    mentions,
    requirement_coverage,
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
        source_postings=(posting,),
        source_evidence=(),
    )


def _task(expected) -> EvalTask:
    return EvalTask(
        name="t", job_url="u", cv_path="c", github_user="g", expected_requirements=tuple(expected)
    )


def test_a_skill_counts_when_a_requirement_names_it():
    """The annotation says `PyTorch`; the posting says a whole sentence around it."""
    assert mentions("Experience with PyTorch or TensorFlow in production", "PyTorch")
    assert mentions("Strong Python for AI/ML workloads", "python")
    assert mentions("chunking strategies, embedding models, vector DBs", "embeddings")  # plural
    assert mentions("Deep knowledge of scikit-learn", "scikit-learn")  # punctuation


def test_a_skill_does_not_count_on_a_coincidental_word():
    assert not mentions("Experience with TensorFlow", "PyTorch")
    # Both words present, but not as the phrase — `vector` and `databases` are far apart.
    assert not mentions("vector search over relational databases", "vector databases")
    # Substring of a longer word is not a mention.
    assert not mentions("Familiarity with Rust", "R")


def test_coverage_is_recall_over_the_annotated_skills():
    extracted = [
        "Strong Python for AI/ML workloads",
        "Experience with Docker and Kubernetes",
    ]
    assert requirement_coverage(extracted, ["Python", "Docker", "Kubernetes"]) == 1.0
    assert requirement_coverage(extracted, ["Python", "Airflow"]) == 0.5
    assert requirement_coverage([], ["Python"]) == 0.0


def test_an_unannotated_task_scores_no_coverage_at_all():
    """It used to score 1.0, which handed the deliberately-unreadable JavaScript-only task
    a perfect row on a page nothing could be extracted from — 1 of 6 completed tasks, so a
    sixth of every published mean was awarded for having nothing to be right about."""
    assert requirement_coverage([], []) is None
    assert requirement_coverage(["anything at all"], []) is None


def test_coverage_does_not_punish_extracting_more_than_the_annotation():
    """The annotation is the skills a human judged load-bearing, never the whole posting.
    Extracting twenty further real requirements is not a mistake, and must not score as one."""
    thorough = ["Python", *[f"unannotated requirement {i}" for i in range(20)]]
    assert requirement_coverage(thorough, ["Python"]) == 1.0


def test_citation_fidelity_is_grounded_over_cited():
    kept = [
        LetterSentence(text="a", evidence_urls=("u1",)),
        LetterSentence(text="b", evidence_urls=("u2",)),
        LetterSentence(text="hello"),  # connective, not counted
    ]
    removed = [LetterSentence(text="bad", evidence_urls=("fabricated",))]
    a = _assessment(requirements=["Python"], letter_sentences=kept, removed=removed)
    assert citation_fidelity(a) == 2 / 3  # 2 grounded cited / (2 + 1 removed)
    assert citation_rate(a) == 3 / 4  # 3 of 4 written sentences carried a citation


def test_a_letter_that_cites_nothing_has_no_fidelity_to_report():
    """This used to score a perfect 1.00 — the metric's most flattering answer for its
    worst case. Five of six Opus letters in the published run cite nothing at all, so the
    'strong model wins on citation fidelity' claim rested on it promising nothing checkable."""
    uncited = [LetterSentence(text="I would be a great fit."), LetterSentence(text="I ship a lot.")]
    a = _assessment(requirements=["Python"], letter_sentences=uncited, removed=[])
    assert citation_fidelity(a) is None
    assert citation_rate(a) == 0.0


def test_evaluate_task_scores_a_completed_run():
    a = _assessment(
        requirements=["Python", "FastAPI"],
        letter_sentences=[LetterSentence(text="x", evidence_urls=("u",))],
        removed=[],
    )
    metrics = evaluate_task(_task(["Python", "FastAPI"]), a, cost_usd=0.01, llm_calls=4)
    assert metrics.completed
    assert metrics.requirement_coverage == 1.0
    assert metrics.citation_fidelity == 1.0
    assert metrics.llm_calls == 4
    assert metrics.cost_usd == 0.01


def test_evaluate_task_grounds_the_report_in_the_fetched_posting():
    """Coverage and grounding read different documents on purpose: coverage asks how much of
    the annotation the run found, grounding asks whether what it rated came from the ad."""
    posting = JobPosting(url="https://x", title="X", requirements=(Requirement(text="Python"),))
    report = MatchReport(
        job_title="X",
        job_url="https://x",
        assessments=(
            MatchAssessment(requirement=Requirement(text="Python"), rating=Rating.STRONG),
            MatchAssessment(requirement=Requirement(text="Erlang"), rating=Rating.NONE),
        ),
    )
    letter = CoverLetterDraft()
    guard = GuardrailResult(
        filtered=letter, removed=(), unsupported_before=0.0, unsupported_after=0.0
    )
    assessment = Assessment(
        posting=posting,
        cv=CVProfile(),
        report=report,
        letter=letter,
        guardrail=guard,
        source_postings=(posting,),
        source_evidence=(),
    )

    metrics = evaluate_task(_task(["Python"]), assessment, cost_usd=0.01, llm_calls=2)
    assert metrics.requirement_coverage == 1.0  # the annotated skill was extracted
    assert metrics.requirement_grounding == 0.5  # but half the report is not in the ad


def test_run_evaluation_marks_failures_not_completed():
    metrics = run_evaluation([_task(["Python"])], lambda t: (None, 0.02, 1))
    assert metrics[0].completed is False
    assert metrics[0].cost_usd == 0.02


def _metrics(name, completed, coverage, grounding, fidelity, rate, calls, cost) -> TaskMetrics:
    """Keyword-built, so a new metric column cannot silently shift an old assertion."""
    return TaskMetrics(
        name=name,
        completed=completed,
        requirement_coverage=coverage,
        requirement_grounding=grounding,
        evidence_grounding=None,
        citation_fidelity=fidelity,
        citation_rate=rate,
        llm_calls=calls,
        cost_usd=cost,
    )


def test_aggregate_uses_completed_only_and_medians():
    metrics = [
        _metrics("a", True, 1.0, 1.0, 1.0, 1.0, 4, 0.01),
        _metrics("b", True, 0.5, 0.5, 0.8, 0.5, 6, 0.03),
        _metrics("c", False, None, None, None, None, 1, 0.005),
        # Completed, but nothing to score: no annotation and an uncited letter.
        _metrics("d", True, None, None, None, 0.0, 2, 0.02),
    ]
    agg = aggregate("m", metrics)
    assert agg.n_tasks == 4
    assert agg.completion_rate == 3 / 4
    assert agg.mean_requirement_coverage == 0.75  # over the two tasks that had an annotation
    assert agg.scored_coverage == 2  # and the table says so, rather than implying four
    assert agg.mean_citation_fidelity == 0.9
    assert agg.scored_fidelity == 2
    assert agg.mean_citation_rate == 0.5  # includes task d: it wrote a letter, cited nothing
    assert agg.mean_requirement_grounding == 0.75
    assert agg.scored_grounding == 2
    assert agg.median_llm_calls == 4  # median of [4, 6, 2]
    assert agg.median_cost_usd == 0.02  # median of [0.01, 0.03, 0.02]


def _aggregate(**overrides) -> Aggregate:
    defaults = dict(
        model="claude-haiku-4-5",
        n_tasks=2,
        completion_rate=1.0,
        mean_requirement_coverage=0.90,
        mean_requirement_grounding=0.85,
        mean_evidence_grounding=0.70,
        mean_citation_fidelity=0.95,
        mean_citation_rate=0.80,
        scored_coverage=2,
        scored_grounding=2,
        scored_evidence=2,
        scored_fidelity=2,
        median_llm_calls=4,
        median_cost_usd=0.012,
    )
    return Aggregate(**{**defaults, **overrides})


def test_format_comparison_is_markdown():
    table = format_comparison([_aggregate()])
    assert "| Model |" in table
    assert "claude-haiku-4-5" in table
    assert "100%" in table
    assert "0.90" in table
    assert "$0.0120" in table


def test_grounding_has_its_own_column_and_says_n_a_when_unscored():
    """A column nobody can find is a metric nobody reads — and an empty one must not
    borrow the neighbouring number."""
    table = format_comparison([_aggregate(mean_requirement_grounding=None, scored_grounding=0)])
    header, _separator, row = table.splitlines()
    assert "Report grounded" in header
    assert header.count("|") == row.count("|")  # the row still lines up under the header
    assert "n/a" in row


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
