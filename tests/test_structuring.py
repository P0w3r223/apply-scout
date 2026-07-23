"""Structuring: validate-and-retry, and giving up with a readable error."""

from __future__ import annotations

import pytest
from fakes import ScriptedStructurer

from apply_scout.contracts import JobPosting
from apply_scout.structuring import StructuringError, _strip_unsupported, structure

VALID = '{"url": "https://example.com/job", "title": "Junior Python Developer"}'
INVALID = '{"title": ""}'  # missing required url; empty title -> ValidationError


def test_valid_output_on_first_attempt():
    structurer = ScriptedStructurer([VALID])
    posting = structure(
        "text", JobPosting, structurer=structurer, model="m", instructions="do it", max_attempts=3
    )
    assert posting.title == "Junior Python Developer"
    assert structurer.calls == 1


def test_retries_then_succeeds():
    structurer = ScriptedStructurer([INVALID, VALID])
    posting = structure(
        "text", JobPosting, structurer=structurer, model="m", instructions="do it", max_attempts=3
    )
    assert posting.title == "Junior Python Developer"
    assert structurer.calls == 2  # one rejected, one accepted


def test_gives_up_after_max_attempts():
    structurer = ScriptedStructurer([INVALID, INVALID])
    with pytest.raises(StructuringError):
        structure(
            "text",
            JobPosting,
            structurer=structurer,
            model="m",
            instructions="do it",
            max_attempts=2,
        )
    assert structurer.calls == 2  # exactly the attempt budget, no more


def test_unsupported_schema_keywords_are_stripped():
    schema = {
        "type": "object",
        "properties": {"title": {"type": "string", "minLength": 1, "maxLength": 80}},
        "required": ["title"],
    }
    stripped = _strip_unsupported(schema)
    assert "minLength" not in stripped["properties"]["title"]
    assert "maxLength" not in stripped["properties"]["title"]
    assert stripped["properties"]["title"]["type"] == "string"
