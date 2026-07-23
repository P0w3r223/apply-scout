"""The data contracts are validated value objects: immutable and strict."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from apply_scout.contracts import Importance, JobPosting, Requirement


def test_requirement_defaults_to_required():
    assert Requirement(text="Python").importance is Importance.REQUIRED


def test_contracts_are_frozen():
    req = Requirement(text="Python")
    with pytest.raises(ValidationError):
        req.text = "Rust"  # frozen -> assignment rejected


def test_unknown_fields_are_rejected():
    # A typo'd field from a tool's JSON output must be a loud error, not a silent drop.
    with pytest.raises(ValidationError):
        Requirement(text="Python", importnce="required")  # note the typo


def test_empty_requirement_text_rejected():
    with pytest.raises(ValidationError):
        Requirement(text="")


def test_jobposting_round_trips_through_json():
    posting = JobPosting(
        url="https://example.com/job",
        title="Junior Python Developer",
        requirements=(Requirement(text="Python"), Requirement(text="SQL")),
    )
    restored = JobPosting.model_validate_json(posting.model_dump_json())
    assert restored == posting
