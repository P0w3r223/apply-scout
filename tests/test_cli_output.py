"""Tests for the CLI's output-stream hardening.

Regression: `apply-scout run --verbose` crashed with `UnicodeEncodeError` when rich
rendered an em-dash to a legacy Windows console (cp1250). `_make_output_utf8_safe`
reconfigures the streams to UTF-8 with `errors="replace"` so no render can raise.
"""

from __future__ import annotations

import sys

import pytest

from apply_scout import cli


class _Reconfigurable:
    def __init__(self) -> None:
        self.kwargs: dict | None = None

    def reconfigure(self, **kwargs: object) -> None:
        self.kwargs = kwargs


class _Raising:
    def reconfigure(self, **kwargs: object) -> None:
        raise ValueError("cannot reconfigure")


class _Plain:
    """A stream with no `reconfigure` (e.g. already wrapped)."""


def test_reconfigures_both_streams_to_utf8_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    out, err = _Reconfigurable(), _Reconfigurable()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    cli._make_output_utf8_safe()

    assert out.kwargs == {"encoding": "utf-8", "errors": "replace"}
    assert err.kwargs == {"encoding": "utf-8", "errors": "replace"}


def test_tolerates_missing_or_raising_reconfigure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdout", _Plain())
    monkeypatch.setattr(sys, "stderr", _Raising())

    cli._make_output_utf8_safe()  # must not raise
