"""Structuring: validate-and-retry, and giving up with a readable error."""

from __future__ import annotations

import pytest
from fakes import ScriptedStructurer

from apply_scout.contracts import JobPosting
from apply_scout.structuring import (
    StructuringError,
    _strip_unsupported,
    normalize_newlines,
    structure,
)

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


class CapturingStructurer(ScriptedStructurer):
    """Records the content it was handed, to assert on what the request actually carried."""

    def __init__(self, outputs: list[str]) -> None:
        super().__init__(outputs)
        self.seen: list[str] = []

    def to_json(self, *, instructions: str, content: str, schema: dict, model: str) -> str:
        self.seen.append(content)
        return super().to_json(
            instructions=instructions, content=content, schema=schema, model=model
        )


def test_newlines_are_normalized_before_the_request_is_built():
    """Pins the invariant the cassette keys depend on: one document, one request shape.

    `read_text` already normalizes, so this guards the boundary rather than a live bug."""
    windows = CapturingStructurer([VALID])
    unix = CapturingStructurer([VALID])
    kwargs = {"model": "m", "instructions": "do it", "max_attempts": 3}

    structure("a\r\nb\rc\n", JobPosting, structurer=windows, **kwargs)
    structure("a\nb\nc\n", JobPosting, structurer=unix, **kwargs)

    assert windows.seen == unix.seen == ["a\nb\nc\n"]


def test_normalize_newlines_handles_all_three_conventions():
    assert normalize_newlines("a\r\nb\rc\nd") == "a\nb\nc\nd"
    assert normalize_newlines("untouched") == "untouched"


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
