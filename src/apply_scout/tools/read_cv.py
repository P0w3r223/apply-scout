"""The real `read_cv` tool: read a CV file and structure it into a CVProfile.

Reading is plain disk I/O; the structuring is injected (same `Structurer` as the
posting tool), so a scripted fake drives the tests. A missing/empty/unreadable file is
a structured error, not an exception.

The set of files this tool may open is fixed by its constructor, not by its argument. The
argument's *schema* is unchanged — still one string — because the cassette key hashes the
tool definitions along with the conversation, so widening the input model would miss every
recorded entry and cost a full paid re-record. What changed is which values it honours.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, Field

from apply_scout import config
from apply_scout.contracts import CVProfile
from apply_scout.structuring import Structurer, StructuringError, structure
from apply_scout.tools.base import PydanticTool, ToolResult

_INSTRUCTIONS = """You extract a candidate's CV into structured data.

Produce a CVProfile: name, a one-line headline, skills, experience bullets (kept \
faithful to the CV, not embellished), and education. Leave a field empty or null if the \
CV does not mention it. Do not add skills or achievements that are not in the text."""


class ReadCVInput(BaseModel):
    path: str = Field(..., description="Path to the candidate's CV file (text or markdown).")


class ReadCV(PydanticTool):
    name = "read_cv"
    description = "Parse the candidate's CV file into a structured, searchable profile."
    input_model = ReadCVInput

    def __init__(
        self,
        *,
        structurer: Structurer,
        readable: Iterable[str | Path],
        model: str = config.STRUCTURE_MODEL,
        max_attempts: int = config.STRUCTURE_MAX_ATTEMPTS,
    ) -> None:
        self._structurer = structurer
        self._readable = frozenset(Path(p).resolve() for p in readable)
        self._model = model
        self._max_attempts = max_attempts

    def _run(self, data: ReadCVInput) -> ToolResult:  # type: ignore[override]
        path = Path(data.path).resolve()
        if path not in self._readable:
            # The caller names the CV at startup (`--cv`), so the model is choosing among files
            # already chosen rather than naming one — the argument is a selector, not a path.
            # Without this the argument is a free path picked from a conversation that carries
            # text off the internet, and the file's contents come straight back to the model.
            return ToolResult.error(f"Not a CV this run may read: {data.path}")
        if not path.is_file():
            return ToolResult.error(f"CV file not found: {data.path}")
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ToolResult.error(f"Could not read the CV file: {exc}")
        if not text.strip():
            return ToolResult.error("The CV file is empty.")

        try:
            cv = structure(
                text[: config.STRUCTURE_MAX_CHARS],
                CVProfile,
                structurer=self._structurer,
                model=self._model,
                instructions=_INSTRUCTIONS,
                max_attempts=self._max_attempts,
            )
        except StructuringError as exc:
            return ToolResult.error(str(exc))

        return ToolResult.success(
            cv.model_dump_json(),
            summary=f"CV for {cv.name or 'candidate'} with {len(cv.skills)} skill(s)",
        )
