"""The record/replay cassette: every external seam, offline and for free.

The guarantees under test are the ones the evaluation leans on: a replayed run returns
byte-identical responses, reports the cost captured at recording time, and never reaches
for the network — an unrecorded request fails loudly instead.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest
from fakes import ScriptedLLM, ScriptedStructurer, final_turn, tool_use_turn

from apply_scout import config
from apply_scout.cassette import (
    Cassette,
    CassetteCache,
    CassetteFetcher,
    CassetteKind,
    CassetteLLM,
    CassetteMiss,
    CassetteMode,
    CassetteSession,
    CassetteStructurer,
    request_key,
)
from apply_scout.fetch import FetchError
from apply_scout.github import GitHubClient
from apply_scout.pipeline import assess

TURN = tool_use_turn([("t1", "read_cv", {"path": "cv.md"})], text="reading the CV")
REQUEST = {"system": "you are an agent", "messages": [{"role": "user", "content": "go"}]}


class CountingStructurer:
    """A structurer that reports usage the way `AnthropicStructurer` does.

    The recording wrapper reads a single call's usage as the delta across the adapter's
    cumulative counters, so exercising that path needs a fake that actually moves them."""

    def __init__(self, outputs: list[str], *, cost_per_call: float = 0.25) -> None:
        self._outputs = list(outputs)
        self._cost_per_call = cost_per_call
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0

    def to_json(self, *, instructions: str, content: str, schema: dict, model: str) -> str:
        self.calls += 1
        self.input_tokens += 300
        self.output_tokens += 40
        self.cost_usd += self._cost_per_call
        return self._outputs.pop(0)


class StubFetcher:
    """A fetcher that serves canned pages and can be told to fail."""

    def __init__(self, pages: dict[str, str | FetchError]) -> None:
        self._pages = pages
        self.calls = 0

    def get(self, url: str) -> str:
        self.calls += 1
        page = self._pages[url]
        if isinstance(page, FetchError):
            raise page
        return page


def _llm(cassette: Cassette, mode: CassetteMode, inner=None) -> CassetteLLM:
    return CassetteLLM(cassette, mode, inner)


def _complete(client: CassetteLLM, *, model: str = config.MODEL_STRONG, system: str | None = None):
    return client.complete(
        system=system if system is not None else REQUEST["system"],
        messages=REQUEST["messages"],
        tools=[],
        model=model,
    )


# --- addressing ---------------------------------------------------------------


def test_key_is_order_independent_but_content_sensitive():
    a = request_key(CassetteKind.LLM, {"model": "m", "system": "s"})
    b = request_key(CassetteKind.LLM, {"system": "s", "model": "m"})
    assert a == b  # dict ordering must not change how a request is addressed
    assert a != request_key(CassetteKind.LLM, {"model": "m", "system": "s "})


def test_a_prompt_edit_misses_every_entry_it_touches():
    """The mechanism behind 'every prompt change ⇒ re-run the harness'."""
    cassette = Cassette()
    _complete(_llm(cassette, CassetteMode.RECORD, ScriptedLLM([TURN])), system="v1")

    replay = _llm(cassette, CassetteMode.REPLAY)
    with pytest.raises(CassetteMiss):
        _complete(replay, system="v2 — one word added")


def test_the_two_seams_cannot_collide_on_a_shared_request():
    assert request_key(CassetteKind.LLM, {"url": "x"}) != request_key(
        CassetteKind.HTTP, {"url": "x"}
    )


# --- the model seam -----------------------------------------------------------


def test_a_recorded_turn_replays_identically_without_a_client():
    cassette = Cassette()
    recorded = _complete(_llm(cassette, CassetteMode.RECORD, ScriptedLLM([TURN])))

    replayed = _complete(_llm(cassette, CassetteMode.REPLAY))

    assert replayed == recorded  # including tool calls, raw content blocks and usage
    assert replayed.tool_calls[0].name == "read_cv"
    assert replayed.raw_content == recorded.raw_content


def test_replay_needs_no_live_client_at_all(tmp_path):
    session = CassetteSession.open(tmp_path / "c.jsonl", CassetteMode.REPLAY)
    assert not session.llm().live
    assert not session.structurer().live
    assert not session.fetcher().live


def test_an_unrecorded_request_fails_loudly_rather_than_calling_out():
    with pytest.raises(CassetteMiss, match="no recorded llm response"):
        _complete(_llm(Cassette(), CassetteMode.REPLAY))


def test_replay_reports_the_cost_captured_at_recording_time():
    """Without this the offline path would silently report every run as free."""
    cassette = Cassette()
    turn = tool_use_turn([("t1", "read_cv", {})], input_tokens=1000, output_tokens=500)
    _complete(_llm(cassette, CassetteMode.RECORD, ScriptedLLM([turn])))

    replay = _llm(cassette, CassetteMode.REPLAY)
    _complete(replay)

    expected = config.token_cost(1000, 500, config.MODEL_STRONG)
    assert replay.cost_usd == pytest.approx(expected)
    assert (replay.input_tokens, replay.output_tokens, replay.calls) == (1000, 500, 1)


def test_auto_replays_a_hit_and_records_a_miss():
    cassette = Cassette()
    _complete(_llm(cassette, CassetteMode.RECORD, ScriptedLLM([TURN])))

    inner = ScriptedLLM([final_turn("a second, different request")])
    auto = _llm(cassette, CassetteMode.AUTO, inner)
    _complete(auto)  # hit — served from the cassette
    _complete(auto, system="something new")  # miss — goes upstream and is stored

    assert len(inner.requests) == 1  # only the miss reached upstream
    assert (cassette.hits, cassette.recorded) == (1, 2)
    assert len(cassette) == 2


def test_record_refreshes_what_the_file_already_held(tmp_path):
    """Re-recording must actually re-ask, not serve the entry it is meant to replace."""
    path = tmp_path / "c.jsonl"
    seed = Cassette()
    _complete(_llm(seed, CassetteMode.RECORD, ScriptedLLM([TURN])))
    seed.write(path)

    loaded = Cassette.load(path)
    again = _complete(_llm(loaded, CassetteMode.RECORD, ScriptedLLM([final_turn("fresh")])))

    assert again.text == "fresh"  # upstream was called despite the stored entry
    assert loaded.hits == 0
    assert len(loaded) == 1  # same key, overwritten


def test_record_pays_only_once_for_a_request_it_repeats():
    """The GitHub README wanted by twenty requirements must cost one call, not twenty.

    Without this, recording the task set would blow the unauthenticated GitHub rate limit
    long before it finished — and every duplicate response would be discarded anyway,
    since they all collapse onto the same key."""
    cassette = Cassette()
    inner = ScriptedLLM([TURN])  # exactly one scripted turn: a second call would raise
    client = _llm(cassette, CassetteMode.RECORD, inner)

    first = _complete(client)
    second = _complete(client)

    assert first == second
    assert len(inner.requests) == 1
    assert (cassette.hits, cassette.recorded) == (1, 1)


# --- the structuring seam -----------------------------------------------------


def test_structuring_replays_its_json_and_accumulates_recorded_usage():
    cassette = Cassette()
    inner = CountingStructurer(['{"title": "x"}'], cost_per_call=0.25)
    record = CassetteStructurer(cassette, CassetteMode.RECORD, inner)
    recorded = record.to_json(instructions="extract", content="text", schema={}, model="m")

    replay = CassetteStructurer(cassette, CassetteMode.REPLAY)
    replayed = replay.to_json(instructions="extract", content="text", schema={}, model="m")

    assert replayed == recorded == '{"title": "x"}'
    assert inner.calls == 1  # the replay did not reach the adapter
    assert (replay.calls, replay.cost_usd) == (1, 0.25)
    assert (replay.input_tokens, replay.output_tokens) == (300, 40)


def test_structuring_records_a_collaborator_that_reports_no_usage():
    """A `Structurer` only promises `to_json`; missing counters must not break recording."""
    cassette = Cassette()
    wrapper = CassetteStructurer(
        cassette, CassetteMode.RECORD, ScriptedStructurer(['{"ok": true}'])
    )

    assert wrapper.to_json(instructions="i", content="c", schema={}, model="m") == '{"ok": true}'
    assert wrapper.cost_usd == 0.0


# --- the fetch seam -----------------------------------------------------------


def test_a_page_replays_without_touching_the_network():
    cassette = Cassette()
    inner = StubFetcher({"https://job": "<html>hello</html>"})
    CassetteFetcher(cassette, CassetteMode.RECORD, inner).get("https://job")

    replayed = CassetteFetcher(cassette, CassetteMode.REPLAY).get("https://job")

    assert replayed == "<html>hello</html>"
    assert inner.calls == 1


def test_a_failed_fetch_is_recorded_and_re_raised_on_replay():
    """Awkward pages are real eval cases — a replayed run must fail the same way."""
    cassette = Cassette()
    inner = StubFetcher({"https://gone": FetchError("HTTP 404")})
    with pytest.raises(FetchError):
        CassetteFetcher(cassette, CassetteMode.RECORD, inner).get("https://gone")

    with pytest.raises(FetchError, match="HTTP 404"):
        CassetteFetcher(cassette, CassetteMode.REPLAY).get("https://gone")


# --- the GitHub seam ----------------------------------------------------------


def test_github_bodies_replay_through_the_client_cache():
    cassette = Cassette()
    CassetteCache(cassette, CassetteMode.AUTO).set("https://api/repos", '[{"name": "x"}]')

    replayed = CassetteCache(cassette, CassetteMode.REPLAY).get("https://api/repos")
    assert replayed == '[{"name": "x"}]'


def test_a_github_replay_miss_raises_instead_of_reporting_not_cached():
    """Returning None — the cache protocol's 'not cached' — would send the client out."""
    with pytest.raises(CassetteMiss, match="no recorded GitHub response"):
        CassetteCache(Cassette(), CassetteMode.REPLAY).get("https://api/repos")


def test_auto_reports_a_github_miss_as_not_cached_so_the_client_fetches_it():
    assert CassetteCache(Cassette(), CassetteMode.AUTO).get("https://api/repos") is None


def test_record_ignores_a_github_body_loaded_from_the_file(tmp_path):
    seed = Cassette()
    CassetteCache(seed, CassetteMode.AUTO).set("https://api/repos", "stale")
    loaded = Cassette.load(seed.write(tmp_path / "c.jsonl"))

    assert CassetteCache(loaded, CassetteMode.RECORD).get("https://api/repos") is None


def test_record_reuses_a_github_body_it_just_fetched():
    """Within one recording session the client must not re-request the same URL."""
    cassette = Cassette()
    cache = CassetteCache(cassette, CassetteMode.RECORD)
    cache.set("https://api/repos", "body")

    assert cache.get("https://api/repos") == "body"


# --- persistence --------------------------------------------------------------


def test_a_cassette_round_trips_through_disk(tmp_path):
    cassette = Cassette()
    recorded = _complete(_llm(cassette, CassetteMode.RECORD, ScriptedLLM([TURN])))
    path = cassette.write(tmp_path / "c.jsonl")

    replayed = _complete(_llm(Cassette.load(path), CassetteMode.REPLAY))

    assert replayed == recorded


def test_a_missing_cassette_loads_empty_so_the_first_recording_needs_no_setup(tmp_path):
    assert len(Cassette.load(tmp_path / "absent.jsonl")) == 0


def test_entries_serialize_in_key_order_so_diffs_stay_reviewable():
    cassette = Cassette()
    client = _llm(cassette, CassetteMode.RECORD, ScriptedLLM([TURN, final_turn("b"), TURN]))
    for system in ("c", "a", "b"):
        _complete(client, system=system)

    keys = [json.loads(line)["key"] for line in cassette.to_jsonl().splitlines()]
    assert keys == sorted(keys) and len(keys) == 3


def test_a_pure_replay_leaves_the_file_untouched(tmp_path):
    path = tmp_path / "c.jsonl"
    cassette = Cassette()
    _complete(_llm(cassette, CassetteMode.RECORD, ScriptedLLM([TURN])))
    cassette.write(path)
    original = path.read_bytes()

    session = CassetteSession.open(path, CassetteMode.REPLAY)
    _complete(session.llm())

    assert session.save() is None  # nothing new was recorded — do not churn the artifact
    assert path.read_bytes() == original


def test_a_long_recording_survives_a_crash_partway_through(tmp_path):
    """A paid run must not lose everything it bought if it dies on the last task."""
    path = tmp_path / "c.jsonl"
    cassette = Cassette(autosave_path=path, autosave_every=2)
    client = _llm(cassette, CassetteMode.RECORD, ScriptedLLM([TURN, TURN, TURN]))

    for system in ("a", "b", "c"):
        _complete(client, system=system)
    # No explicit save() — simulate the process dying here.

    assert len(Cassette.load(path)) == 2  # the first flush landed; the third is in flight


def test_autosave_is_off_for_a_replay(tmp_path):
    path = tmp_path / "c.jsonl"
    session = CassetteSession.open(path, CassetteMode.REPLAY)
    assert session.cassette._autosave_path is None  # noqa: SLF001 — the guarantee under test
    assert not path.exists()


def test_a_session_writes_only_what_it_recorded(tmp_path):
    path = tmp_path / "c.jsonl"
    session = CassetteSession.open(path, CassetteMode.RECORD)
    _complete(session.llm(ScriptedLLM([TURN])))

    assert session.save() == path
    assert len(Cassette.load(path)) == 1
    assert "1 recorded" in session.summary()


# --- the whole pipeline, offline ----------------------------------------------

POSTING_HTML = (
    "<html><body><article><h1>Junior Python Dev</h1><p>Python.</p></article></body></html>"
)
JOB_JSON = (
    '{"url": "https://x", "title": "Junior Python Dev", "requirements": [{"text": "Python"}]}'
)
CV_JSON = '{"name": "Candidate", "skills": ["Python"]}'
REPORT_JSON = (
    '{"job_title": "Junior Python Dev", "job_url": "https://x", "assessments": ['
    '{"requirement": {"text": "Python"}, "rating": "strong", "evidence": ['
    '{"requirement": "Python", "kind": "repo", "url": "https://github.com/u/car-price-ml"}]}]}'
)
LETTER_JSON = (
    '{"sentences": [{"text": "I use Python.", '
    '"evidence_urls": ["https://github.com/u/car-price-ml"]}, {"text": "Kind regards."}]}'
)
STRUCTURED = [JOB_JSON, CV_JSON, REPORT_JSON, LETTER_JSON]


def _github_transport(*, offline: bool) -> httpx.Client:
    """A GitHub transport that, when `offline`, fails the test if it is ever reached."""
    readme = base64.b64encode(b"Built with Python.").decode()

    def handler(request: httpx.Request) -> httpx.Response:
        if offline:
            raise AssertionError(f"replay reached the network: {request.url}")
        if request.url.path.endswith("/repos"):
            if int(request.url.params.get("page", "1")) > 1:
                return httpx.Response(200, json=[])
            return httpx.Response(
                200,
                json=[
                    {
                        "name": "car-price-ml",
                        "full_name": "u/car-price-ml",
                        "language": "Python",
                        "html_url": "https://github.com/u/car-price-ml",
                    }
                ],
            )
        if request.url.path == "/repos/u/car-price-ml/readme":
            return httpx.Response(
                200,
                json={
                    "content": readme,
                    "encoding": "base64",
                    "html_url": "https://github.com/u/car-price-ml/blob/main/README.md",
                },
            )
        return httpx.Response(404, json={"message": "Not Found"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _assess_through(session: CassetteSession, cv_file, *, offline: bool):
    fetcher = None if offline else StubFetcher({"https://real/job": POSTING_HTML})
    structurer = None if offline else ScriptedStructurer(list(STRUCTURED))
    return _assess_through_with(
        session, session.structurer(structurer), cv_file, fetcher=fetcher, offline=offline
    )


def test_a_recorded_assessment_replays_identically_with_no_network_and_no_key(tmp_path):
    """The whole point of the milestone: one paid run, then free reproductions forever."""
    cv_file = tmp_path / "cv.md"
    cv_file.write_text("Candidate: Python.", encoding="utf-8")
    path = tmp_path / "pipeline.jsonl"

    recording = CassetteSession.open(path, CassetteMode.RECORD)
    recorded = _assess_through(recording, cv_file, offline=False)
    recording.save()

    # Nothing live is wired in now: no structurer, no fetcher, and a transport that
    # raises if the GitHub client so much as tries.
    replaying = CassetteSession.open(path, CassetteMode.REPLAY)
    replayed = _assess_through(replaying, cv_file, offline=True)

    assert replayed == recorded
    assert replaying.cassette.recorded == 0  # a replay records nothing
    assert replaying.cassette.hits >= 4  # 4 structuring calls, 1 page, N GitHub responses


def test_a_replayed_assessment_still_reports_what_it_cost(tmp_path):
    """Cost per task is read off the structurer, so replay has to serve the recorded figure."""
    cv_file = tmp_path / "cv.md"
    cv_file.write_text("Candidate: Python.", encoding="utf-8")
    path = tmp_path / "pipeline.jsonl"

    recording = CassetteSession.open(path, CassetteMode.RECORD)
    priced = CountingStructurer(list(STRUCTURED), cost_per_call=0.01)
    _assess_through_with(
        recording,
        recording.structurer(priced),
        cv_file,
        fetcher=StubFetcher({"https://real/job": POSTING_HTML}),
        offline=False,
    )
    recording.save()

    replaying = CassetteSession.open(path, CassetteMode.REPLAY)
    structurer = replaying.structurer()
    _assess_through_with(replaying, structurer, cv_file, fetcher=None, offline=True)

    assert structurer.calls == 4
    assert structurer.cost_usd == pytest.approx(0.04)


def _assess_through_with(session, structurer, cv_file, *, fetcher, offline: bool):
    github = GitHubClient(
        client=_github_transport(offline=offline), cache=session.github_cache()
    )
    return assess(
        job_url="https://real/job",
        cv_path=str(cv_file),
        github_user="u",
        fetcher=session.fetcher(fetcher),
        structurer=structurer,
        github=github,
    )
