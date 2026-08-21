"""The terminal tool the loop finishes with, and the harness path that scores it.

The point of `submit_report` is that the agent's deliverable arrives as a contract, so
the same metrics can score the loop and the pipeline. These tests pin both halves: the
tool validates and holds a submission, and `agent_assess_fn` turns one into a scored
`Assessment` — under a scripted model, so no network and no key.
"""

from __future__ import annotations

from fakes import ScriptedLLM, ScriptedStructurer, final_turn, tool_use_turn

from apply_scout.budget import Budget
from apply_scout.evaluation import EvalTask, agent_assess_fn
from apply_scout.tools.submit_report import SubmitReport

REPORT = {
    "job_title": "Senior AI Engineer",
    "job_url": "https://example.com/job",
    "assessments": [
        {
            "requirement": {"text": "Python"},
            "rating": "strong",
            "evidence": [
                {
                    "requirement": "Python",
                    "kind": "readme",
                    "url": "https://github.com/u/r/blob/main/README.md",
                }
            ],
        },
        {"requirement": {"text": "Kubernetes"}, "rating": "none", "evidence": []},
    ],
}
GROUNDED = "Built a Python service end to end."
FABRICATED = "Ran a Kubernetes cluster in production."
LETTER = {
    "sentences": [
        {"text": GROUNDED, "evidence_urls": ["https://github.com/u/r/blob/main/README.md"]},
        {"text": FABRICATED, "evidence_urls": ["https://invented.example/proof"]},
    ]
}


def _submit_turn(tool_id: str = "s1"):
    return tool_use_turn([(tool_id, "submit_report", {"report": REPORT, "letter": LETTER})])


def test_tool_holds_the_submission_and_reports_what_it_got():
    tool = SubmitReport()
    assert tool.submitted is None

    result = tool.run({"report": REPORT, "letter": LETTER})

    assert result.ok
    assert tool.submitted is not None
    assert tool.submitted.report.job_title == "Senior AI Engineer"
    assert "2 rating(s)" in result.summary


def test_a_malformed_submission_is_a_recoverable_error_not_a_crash():
    tool = SubmitReport()
    result = tool.run({"report": {"job_title": "x"}, "letter": LETTER})  # no job_url

    assert result.ok is False
    assert "Invalid input for 'submit_report'" in result.content
    assert tool.submitted is None  # nothing half-written is kept


def test_agent_assess_fn_scores_a_submitted_report():
    task = EvalTask(
        name="t",
        job_url="https://example.com/job",
        cv_path="cv/candidate.md",
        github_user="u",
        expected_requirements=("Python", "Airflow"),
    )
    assess = agent_assess_fn(
        "claude-opus-4-8",
        llm_factory=lambda: ScriptedLLM([_submit_turn(), final_turn("submitted")]),
        structurer_factory=lambda: ScriptedStructurer([]),
    )
    assessment, cost, calls = assess(task)

    assert assessment is not None
    # Coverage reads the requirements the loop actually rated: Python yes, Airflow no.
    assert [r.text for r in assessment.posting.requirements] == ["Python", "Kubernetes"]
    # The guardrail ran over the loop's letter exactly as it does over the pipeline's.
    assert [s.text for s in assessment.letter.sentences] == [GROUNDED]
    assert [s.text for s in assessment.guardrail.removed] == [FABRICATED]
    assert calls >= 1 and cost >= 0.0


def test_a_run_that_never_submits_scores_as_not_completed():
    task = EvalTask(
        name="t", job_url="u", cv_path="c", github_user="g", expected_requirements=("Python",)
    )
    assess = agent_assess_fn(
        "claude-opus-4-8",
        # The model talks instead of submitting — a plausible failure, and not a success.
        llm_factory=lambda: ScriptedLLM([final_turn("Here is my report in prose instead.")]),
        structurer_factory=lambda: ScriptedStructurer([]),
    )
    assessment, _, calls = assess(task)

    assert assessment is None
    assert calls >= 1  # the work still cost something, and is still reported


def test_a_budget_stop_before_submitting_scores_as_not_completed():
    task = EvalTask(
        name="t", job_url="u", cv_path="c", github_user="g", expected_requirements=("Python",)
    )
    assess = agent_assess_fn(
        "claude-opus-4-8",
        llm_factory=lambda: ScriptedLLM([_submit_turn(f"s{i}") for i in range(5)]),
        structurer_factory=lambda: ScriptedStructurer([]),
        budget=Budget(max_steps=0, max_tokens=10**9, max_cost_usd=10**9),
    )
    assessment, _, _ = assess(task)
    assert assessment is None


def test_the_guardrail_is_not_the_agents_to_mark():
    """The tool stores what it was given; grounding is decided afterwards, outside it."""
    tool = SubmitReport()
    tool.run({"report": REPORT, "letter": LETTER})
    assert tool.submitted is not None
    # Both sentences survive inside the tool — including the fabricated one.
    assert len(tool.submitted.letter.sentences) == 2


def test_the_model_is_handed_the_contract_itself_as_the_schema():
    """The loop's output and the pipeline's have to be the same shape, or the two rows of
    the comparison would not be measuring the same thing."""
    schema = SubmitReport().spec()["input_schema"]
    assert set(schema["properties"]) == {"report", "letter"}
    definitions = schema.get("$defs", {})
    # The nested contracts survive schema generation — the model is asked for a
    # MatchReport, not for a loosely-typed blob it can shape however it likes.
    assert {"MatchReport", "MatchAssessment", "Evidence", "CoverLetterDraft"} <= set(definitions)
    assert definitions["Rating"]["enum"] == ["strong", "weak", "none"]
