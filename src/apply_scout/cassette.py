"""Record once, replay forever: an on-disk cassette of every external interaction.

A real run costs money and touches three networks — Anthropic, the posting's host, and
GitHub. That makes the evaluation expensive to repeat and impossible to run in CI, which
is fatal for a project whose whole claim is that *the evaluation is the point*. So every
outbound seam the system has (`LLMClient`, `Structurer`, `Fetcher`, and the GitHub
response `Cache`) gets a wrapper here that writes what came back to a JSONL cassette and
can serve it again later with no network and no API key.

`Extractor` is wrapped too, though it never leaves the machine: its output depends on the
installed trafilatura and libxml2, so re-running it during a replay makes the offline run
a function of the environment rather than of the recording. Everything the structuring
request is keyed on has to come out of the cassette, not out of the local venv.

Three modes:

- `record` — always call upstream and store the response.
- `replay` — never call upstream; a request with no recorded response raises
  `CassetteMiss`. Loud on purpose: falling back to the network would quietly turn a
  reproducible evaluation back into a paid one.
- `auto` — replay a hit, record a miss. What you want when *extending* a task set, so
  only the genuinely new work costs anything.

Replay reports the token counts and USD cost captured **at recording time**, so the cost
metrics survive the offline path instead of collapsing to zero.

A cassette key is a hash of the whole request — including the system prompt and the tool
schemas. Editing a prompt therefore misses every entry it touches, which turns the
project's "every prompt change ⇒ re-run the harness" rule from a line in CLAUDE.md into
a mechanism you cannot forget to obey.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from apply_scout import config
from apply_scout.fetch import Extractor, Fetcher, FetchError, HttpFetcher, MainTextExtractor
from apply_scout.llm import AnthropicLLM, LLMClient, LLMResponse, ToolCall, Usage
from apply_scout.structuring import AnthropicStructurer, Structurer


class CassetteMode(StrEnum):
    RECORD = "record"  # always call upstream, store what comes back
    REPLAY = "replay"  # never call upstream; an unrecorded request is an error
    AUTO = "auto"  # replay a hit, record a miss


class CassetteKind(StrEnum):
    """Which seam an entry came from. Kept in the key so two seams can never collide."""

    LLM = "llm"
    STRUCTURE = "structure"
    HTTP = "http"
    EXTRACT = "extract"
    GITHUB = "github"


class CassetteMiss(LookupError):
    """A request had no recorded response and the current mode forbids going upstream."""


# Flush a recording cassette to disk every N new entries, so a crash late in a long,
# expensive run costs one interval's worth of calls rather than the whole run.
AUTOSAVE_EVERY = 10


class CassetteEntry(BaseModel):
    """One recorded interaction: how it was addressed, what came back, what it cost."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str  # sha256 of the canonical request
    kind: CassetteKind
    label: str  # short human-readable hint, so the committed file is browsable
    payload: dict  # the recorded response, shaped per kind
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    recorded_at: str = ""


def request_key(kind: CassetteKind, request: dict) -> str:
    """Address a request by the hash of its canonical JSON form.

    `sort_keys` makes the hash independent of dict ordering. `default=str` is a
    deliberate safety valve: an exotic content block must not crash a recording run
    that has already spent real money on the calls before it."""
    canonical = json.dumps(
        {"kind": kind.value, "request": request},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Cassette:
    """A keyed store of recorded interactions, persisted as JSONL.

    Counters are kept here rather than on the wrappers because one cassette is shared by
    all four seams — the totals only mean something when they are pooled."""

    def __init__(
        self,
        entries: list[CassetteEntry] | None = None,
        *,
        autosave_path: Path | None = None,
        autosave_every: int = AUTOSAVE_EVERY,
    ) -> None:
        self._entries: dict[str, CassetteEntry] = {e.key: e for e in entries or []}
        # Keys written during *this* session, as opposed to loaded from the file. The
        # distinction is what lets `record` refresh stale entries while still answering a
        # request it has already paid for once.
        self._fresh: set[str] = set()
        # Recording costs real money, and a full task-set recording runs for many minutes.
        # Flushing periodically means a crash on the last task doesn't discard everything
        # bought before it — the run resumes from the cassette instead of paying twice.
        self._autosave_path = autosave_path
        self._autosave_every = autosave_every
        self._saved_count = 0
        self.hits = 0
        self.misses = 0
        self.recorded = 0

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        autosave_path: Path | None = None,
        autosave_every: int = AUTOSAVE_EVERY,
    ) -> Cassette:
        """Read a cassette from disk. A missing file is an empty cassette, not an error —
        that is what makes the first `record` run work without any setup."""
        entries: list[CassetteEntry] = []
        if path.exists():
            entries = [
                CassetteEntry.model_validate_json(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        return cls(entries, autosave_path=autosave_path, autosave_every=autosave_every)

    def get(self, key: str, *, fresh_only: bool = False) -> CassetteEntry | None:
        """Look up an entry. `fresh_only` restricts the lookup to this session's writes."""
        if fresh_only and key not in self._fresh:
            return None
        return self._entries.get(key)

    def put(self, entry: CassetteEntry) -> None:
        self._entries[entry.key] = entry
        self._fresh.add(entry.key)
        self.recorded += 1
        if (
            self._autosave_path is not None
            and self._autosave_every > 0
            and self.recorded - self._saved_count >= self._autosave_every
        ):
            self.write(self._autosave_path)
            self._saved_count = self.recorded

    def to_jsonl(self) -> str:
        """Serialize sorted by key — a stable order keeps the committed file's git diffs
        reviewable instead of reshuffling on every re-record."""
        return "\n".join(self._entries[key].model_dump_json() for key in sorted(self._entries))

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_jsonl(), encoding="utf-8")
        return path

    def __len__(self) -> int:
        return len(self._entries)


# What a live call hands back to be stored: (payload, input_tokens, output_tokens, cost).
Recorded = tuple[dict, int, int, float]


class _Seam:
    """Shared record/replay decision for one wrapped dependency."""

    def __init__(self, cassette: Cassette, mode: CassetteMode) -> None:
        self.cassette = cassette
        self.mode = mode

    def resolve(
        self,
        kind: CassetteKind,
        request: dict,
        label: str,
        call: Callable[[], Recorded],
    ) -> CassetteEntry:
        key = request_key(kind, request)
        # `record` deliberately ignores what the file already held — refreshing it is the
        # point — but still reuses what this session recorded. Without that, one repeated
        # request (the same README wanted by twenty requirements) would be paid for twenty
        # times and only the last response would survive anyway.
        entry = self.cassette.get(key, fresh_only=self.mode is CassetteMode.RECORD)
        if entry is not None:
            self.cassette.hits += 1
            return entry
        if self.mode is CassetteMode.REPLAY:
            self.cassette.misses += 1
            raise CassetteMiss(
                f"no recorded {kind.value} response for {label} (key {key[:12]}…). "
                "Re-record the cassette — a prompt or an input has changed."
            )

        payload, input_tokens, output_tokens, cost_usd = call()
        entry = CassetteEntry(
            key=key,
            kind=kind,
            label=label,
            payload=payload,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            recorded_at=_now(),
        )
        self.cassette.put(entry)
        return entry


def _counters(obj: object) -> tuple[int, int, float]:
    """Read a collaborator's cumulative usage counters, tolerating their absence.

    The `Structurer` protocol only promises `to_json`, so a fake has no counters at all;
    reading them defensively means a recording wrapper works over any implementation and
    simply records zero usage for one that cannot report it."""
    return (
        int(getattr(obj, "input_tokens", 0) or 0),
        int(getattr(obj, "output_tokens", 0) or 0),
        float(getattr(obj, "cost_usd", 0.0) or 0.0),
    )


def _response_to_payload(response: LLMResponse) -> dict:
    return {
        "stop_reason": response.stop_reason,
        "text": response.text,
        "tool_calls": [
            {"id": call.id, "name": call.name, "input": call.input} for call in response.tool_calls
        ],
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
        "model": response.model,
        "raw_content": response.raw_content,
    }


def _response_from_payload(payload: dict) -> LLMResponse:
    usage = payload["usage"]
    return LLMResponse(
        stop_reason=payload["stop_reason"],
        text=payload["text"],
        tool_calls=tuple(
            ToolCall(id=c["id"], name=c["name"], input=c["input"]) for c in payload["tool_calls"]
        ),
        usage=Usage(usage["input_tokens"], usage["output_tokens"]),
        model=payload["model"],
        raw_content=list(payload["raw_content"]),
    )


class CassetteLLM:
    """An `LLMClient` that records or replays whole model turns.

    Exposes the same cumulative counters as the real adapters, filled from the *recorded*
    usage, so a replayed run still reports honest token and cost figures."""

    def __init__(
        self, cassette: Cassette, mode: CassetteMode, inner: LLMClient | None = None
    ) -> None:
        self._seam = _Seam(cassette, mode)
        self._inner = inner
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0

    @property
    def live(self) -> bool:
        """Whether a real upstream client is attached at all — False on a replay path."""
        return self._inner is not None

    def complete(
        self, *, system: str, messages: list[dict], tools: list[dict], model: str
    ) -> LLMResponse:
        request = {"model": model, "system": system, "messages": messages, "tools": tools}

        def call() -> Recorded:
            if self._inner is None:
                raise CassetteMiss("recording a model turn needs a live LLM client")
            response = self._inner.complete(
                system=system, messages=messages, tools=tools, model=model
            )
            cost = config.token_cost(
                response.usage.input_tokens, response.usage.output_tokens, response.model
            )
            return (
                _response_to_payload(response),
                response.usage.input_tokens,
                response.usage.output_tokens,
                cost,
            )

        entry = self._seam.resolve(
            CassetteKind.LLM, request, f"{model} | {len(messages)} message(s)", call
        )
        self.calls += 1
        self.input_tokens += entry.input_tokens
        self.output_tokens += entry.output_tokens
        self.cost_usd += entry.cost_usd
        return _response_from_payload(entry.payload)


class CassetteStructurer:
    """A `Structurer` that records or replays the JSON a structuring call produced.

    `calls` and `cost_usd` are part of this seam's contract, not an extra: the eval
    harness reads them off the structurer to report per-task cost."""

    def __init__(
        self, cassette: Cassette, mode: CassetteMode, inner: Structurer | None = None
    ) -> None:
        self._seam = _Seam(cassette, mode)
        self._inner = inner
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0

    @property
    def live(self) -> bool:
        return self._inner is not None

    def to_json(self, *, instructions: str, content: str, schema: dict, model: str) -> str:
        request = {
            "model": model,
            "instructions": instructions,
            "content": content,
            "schema": schema,
        }

        def call() -> Recorded:
            if self._inner is None:
                raise CassetteMiss("recording a structuring call needs a live structurer")
            # The protocol exposes usage only as cumulative counters on the adapter, so a
            # single call's cost is the delta across it.
            before = _counters(self._inner)
            text = self._inner.to_json(
                instructions=instructions, content=content, schema=schema, model=model
            )
            after = _counters(self._inner)
            return (
                {"text": text},
                after[0] - before[0],
                after[1] - before[1],
                after[2] - before[2],
            )

        first_line = instructions.strip().splitlines()[0] if instructions.strip() else ""
        entry = self._seam.resolve(
            CassetteKind.STRUCTURE, request, f"{model} | {first_line[:60]}", call
        )
        self.calls += 1
        self.input_tokens += entry.input_tokens
        self.output_tokens += entry.output_tokens
        self.cost_usd += entry.cost_usd
        return entry.payload["text"]


class CassetteFetcher:
    """A `Fetcher` that records or replays page HTML — including failures.

    A posting that 404s or serves a non-HTML body is a real evaluation case (the task set
    deliberately contains awkward pages), so the *error* is recorded too and re-raised on
    replay. Otherwise the offline run would silently diverge from the recorded one."""

    def __init__(
        self, cassette: Cassette, mode: CassetteMode, inner: Fetcher | None = None
    ) -> None:
        self._seam = _Seam(cassette, mode)
        self._inner = inner

    @property
    def live(self) -> bool:
        return self._inner is not None

    def get(self, url: str) -> str:
        def call() -> Recorded:
            if self._inner is None:
                raise CassetteMiss("recording a fetch needs a live fetcher")
            try:
                return {"html": self._inner.get(url)}, 0, 0, 0.0
            except FetchError as exc:
                return {"error": str(exc)}, 0, 0, 0.0

        entry = self._seam.resolve(CassetteKind.HTTP, {"url": url}, url, call)
        if "error" in entry.payload:
            raise FetchError(entry.payload["error"])
        return entry.payload["html"]


class CassetteExtractor:
    """An `Extractor` that records what a page extracted *to*, not merely what it served.

    Recording the HTML alone is not enough to make a replay reproducible: extraction runs
    locally, and trafilatura's output moves between its own versions and libxml2 builds. A
    CI runner with a newer trafilatura extracted two of eight recorded pages differently,
    which changed the structuring request keyed off that text and missed every entry behind
    it. With this seam recorded, replay never calls the extractor at all, so the offline run
    depends on the recorded page rather than on the environment reading it."""

    def __init__(
        self, cassette: Cassette, mode: CassetteMode, inner: Extractor | None = None
    ) -> None:
        self._seam = _Seam(cassette, mode)
        self._inner = inner

    @property
    def live(self) -> bool:
        return self._inner is not None

    def extract(self, html: str, url: str = "") -> str:
        def call() -> Recorded:
            if self._inner is None:
                raise CassetteMiss("recording an extraction needs a live extractor")
            return {"text": self._inner.extract(html, url)}, 0, 0, 0.0

        # Keyed on the markup alone: the same page extracts to the same text whatever URL
        # served it, and the URL is carried as the label so the file stays browsable.
        entry = self._seam.resolve(CassetteKind.EXTRACT, {"html": html}, url, call)
        return entry.payload["text"]


class CassetteCache:
    """The GitHub client's response cache, backed by the cassette.

    The client already funnels every request through a `Cache` keyed by URL, so wrapping
    that one seam makes repo and README lookups replayable. The mode changes what a miss
    means: in `replay` it raises, because returning `None` — the protocol's "not cached" —
    would send the client straight to the network and break the offline guarantee."""

    def __init__(self, cassette: Cassette, mode: CassetteMode) -> None:
        self._cassette = cassette
        self._mode = mode

    def get(self, key: str) -> str | None:
        entry = self._cassette.get(
            request_key(CassetteKind.GITHUB, {"url": key}),
            fresh_only=self._mode is CassetteMode.RECORD,
        )
        if entry is not None:
            self._cassette.hits += 1
            return entry.payload["body"]
        if self._mode is CassetteMode.REPLAY:
            self._cassette.misses += 1
            raise CassetteMiss(
                f"no recorded GitHub response for {key}. "
                "Re-record the cassette — a repo set or an input has changed."
            )
        return None

    def set(self, key: str, value: str) -> None:
        self._cassette.put(
            CassetteEntry(
                key=request_key(CassetteKind.GITHUB, {"url": key}),
                kind=CassetteKind.GITHUB,
                label=key,
                payload={"body": value},
                recorded_at=_now(),
            )
        )


@dataclass
class CassetteSession:
    """One cassette on disk plus the wrapped seams that read and write it.

    This is the single place that decides "live collaborator or not": in `replay` no live
    adapter is constructed at all, which is what lets the whole evaluation run with no
    API key present."""

    path: Path
    mode: CassetteMode
    cassette: Cassette

    @classmethod
    def open(cls, path: Path, mode: CassetteMode) -> CassetteSession:
        # Only a recording session autosaves; a replay writes nothing, so the committed
        # artifact stays byte-identical.
        autosave = None if mode is CassetteMode.REPLAY else path
        return cls(path=path, mode=mode, cassette=Cassette.load(path, autosave_path=autosave))

    @property
    def _offline(self) -> bool:
        return self.mode is CassetteMode.REPLAY

    def llm(self, inner: LLMClient | None = None) -> CassetteLLM:
        if inner is None and not self._offline:
            inner = AnthropicLLM()
        return CassetteLLM(self.cassette, self.mode, inner)

    def structurer(self, inner: Structurer | None = None) -> CassetteStructurer:
        if inner is None and not self._offline:
            inner = AnthropicStructurer()
        return CassetteStructurer(self.cassette, self.mode, inner)

    def fetcher(self, inner: Fetcher | None = None) -> CassetteFetcher:
        if inner is None and not self._offline:
            inner = HttpFetcher()
        return CassetteFetcher(self.cassette, self.mode, inner)

    def extractor(self, inner: Extractor | None = None) -> CassetteExtractor:
        if inner is None and not self._offline:
            inner = MainTextExtractor()
        return CassetteExtractor(self.cassette, self.mode, inner)

    def github_cache(self) -> CassetteCache:
        return CassetteCache(self.cassette, self.mode)

    def summary(self) -> str:
        return (
            f"cassette[{self.mode.value}] {len(self.cassette)} entries "
            f"({self.cassette.hits} replayed, {self.cassette.recorded} recorded)"
        )

    def save(self) -> Path | None:
        """Persist the cassette, unless nothing new was recorded.

        A pure replay must leave the file byte-identical — rewriting it would churn the
        committed artifact and blur the line between "reproduced" and "re-recorded"."""
        if self.cassette.recorded == 0:
            return None
        return self.cassette.write(self.path)


def default_cassette_path(name: str) -> Path:
    return config.CASSETTE_DIR / f"{name}.jsonl"
