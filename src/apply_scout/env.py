"""Bridge a local `.env` file into the process environment.

Secrets live in exactly two places: a gitignored `.env` on the developer's machine, and
the environment the SDK reads at call time. Nothing else in the project may hold a key
(see CLAUDE.md). Connecting those two ends is a dozen lines of parsing, so it is done
here rather than by taking on a dependency for one utility.

Two rules make this safe to run unconditionally at startup:

- **A real environment variable always wins.** An exported key must never be silently
  replaced by a stale file — CI and a shell export stay authoritative.
- **Values are never returned or logged.** `load_dotenv` reports the *names* it applied,
  which is enough to debug "did my key get picked up?" without printing the key.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from pathlib import Path

from apply_scout import config


def _unquote(value: str) -> str:
    """Strip one matching pair of surrounding quotes, if present."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse `KEY=value` lines, skipping blanks and comments.

    Deliberately literal: an inline `#` is kept, because a secret is allowed to contain
    one and guessing where a comment starts would silently corrupt a valid key."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, separator, value = stripped.partition("=")
        if not separator:
            continue  # not an assignment — ignore rather than guess at intent
        name = name.removeprefix("export ").strip()
        if name:
            values[name] = _unquote(value.strip())
    return values


def load_dotenv(
    path: Path | None = None, *, environ: MutableMapping[str, str] | None = None
) -> tuple[str, ...]:
    """Load `path` (default: the project's `.env`) into `environ`.

    Returns the names actually applied — never the values. A missing or unreadable file
    is not an error: running without a `.env` is the normal case in CI and under replay."""
    path = path or config.PROJECT_ROOT / ".env"
    target = os.environ if environ is None else environ

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:  # missing, unreadable, or a directory — all mean "no .env here"
        return ()

    applied: list[str] = []
    for name, value in parse_dotenv(text).items():
        if name in target:
            continue  # an already-set variable is authoritative
        target[name] = value
        applied.append(name)
    return tuple(applied)
