"""Tools are testable without an LLM, and bad input is a structured error."""

from __future__ import annotations

from apply_scout.contracts import CVProfile, JobPosting
from apply_scout.tools.mock import MockFetchJobPosting, MockReadCV
from apply_scout.tools.registry import ToolRegistry


def test_fetch_returns_valid_jobposting():
    result = MockFetchJobPosting().run({"url": "https://example.com/job"})
    assert result.ok
    JobPosting.model_validate_json(result.content)  # parses back into the contract


def test_read_cv_returns_valid_profile():
    result = MockReadCV().run({"path": "cv.md"})
    assert result.ok
    CVProfile.model_validate_json(result.content)


def test_missing_required_argument_is_structured_error():
    result = MockFetchJobPosting().run({})  # url missing
    assert not result.ok
    assert "Invalid input" in result.content


def test_registry_rejects_unknown_tool():
    registry = ToolRegistry([MockFetchJobPosting()])
    result = registry.dispatch("does_not_exist", {})
    assert not result.ok
    assert "Unknown tool" in result.content


def test_spec_exposes_json_schema():
    spec = MockFetchJobPosting().spec()
    assert spec["name"] == "fetch_job_posting"
    assert spec["input_schema"]["type"] == "object"
    assert "url" in spec["input_schema"]["properties"]
