# ADR 0004 — Record/replay cassettes at our own seams, not at the HTTP layer

Date: 2026-08-21
Status: accepted
Author: P0w3r223
Related to: ADR 0001 (own loop), ADR 0003 (structured outputs + guardrail)

---

## Context

The evaluation is this project's central claim, and it was the least reproducible thing in
it. A single `apply-scout eval` run over the eight annotated tasks on two models touches
three networks — Anthropic, each posting's host, and the GitHub API — and costs real money
every time. Two consequences followed, and both showed up in practice:

- **The published table decayed.** Between the first recording (2026-07-27) and the second
  (2026-08-21), two of the eight advertisements were taken down and now return HTTP 404.
  Completion fell from 100% to 75% with nothing in the pipeline having changed. The web
  moved underneath the task set.
- **CI could not run it.** Anything requiring an `ANTHROPIC_API_KEY` and a card is not a
  regression test; the published numbers were taken on trust rather than checked.

An evaluation nobody can re-run is a claim, not a measurement.

## Decision — wrap the four seams we already own

Every outbound dependency is already an injected protocol: `LLMClient`, `Structurer`,
`Fetcher`, and the GitHub response `Cache`. `cassette.py` wraps each one with a recorder
that stores the response in a keyed JSONL cassette and serves it again on replay. The
cassette for the published task set is **committed** (`eval/cassettes/eval.jsonl`), and CI
replays the evaluation from it on every pull request and every push to `main`.

Modes: `record` (always call upstream, store the result), `replay` (never call upstream),
`auto` (replay a hit, record a miss — so extending a task set only pays for what is new),
and `off`.

### Why our seams rather than an HTTP-level VCR

The obvious alternative is a cassette library that intercepts transport (`vcrpy`,
`responses`, `respx`) and records raw HTTP exchanges. Rejected, for reasons specific to
this project:

- **The seams are the interesting boundary.** A recording at protocol level captures
  request bodies with headers and auth in them; a recording at our own protocol level
  captures exactly the response object the code consumes. Nothing sensitive is even
  eligible for the file — the key is a hash of the request, and only the response is
  stored.
- **The GitHub cache is not HTTP.** It is an on-disk cache keyed by our own scheme. One
  mechanism covering all four dependencies is simpler than an HTTP recorder plus a separate
  story for the cache.
- **It stays consistent with ADR 0001.** We own the loop precisely so this kind of
  instrumentation is possible without fighting a framework; the same argument applies to
  not adding a transport-level dependency to get it.

### The extraction seam — recorded even though it never leaves the machine

The first CI run of the replay job failed where every local run passed. The cassette stored
each posting's raw HTML, but `extract_main_text` (trafilatura) still ran live on the
runner — and trafilatura 2.2.0 extracts two of the eight recorded pages differently from
2.1.0, the version that produced the recording. Different text means a different
structuring request, which means a different key, which means `CassetteMiss` on every
entry behind it.

Pinning the extraction stack was rejected: it would freeze an application dependency for
the benefit of the evaluation, and it would not even be sufficient — lxml ships different
libxml2 builds per platform, so a Linux runner and a Windows laptop can diverge on
identical versions. Instead `Extractor` became an injected dependency like every other
collaborator, and the cassette records its output keyed on the markup. **Replay now never
runs the extractor at all**, so the offline result is a function of the recorded page
rather than of the environment reading it.

The general rule this exposed: *everything a replayed request is keyed on must come out of
the cassette*. A seam is worth recording when its output is not reproducible, not only
when it crosses the network.

### Consequential details, each deliberate

- **A miss under `replay` raises `CassetteMiss` — it never falls back to the network.**
  Silently serving one live request would turn a free, reproducible evaluation back into a
  paid and unverifiable one, and the resulting table would be a blend of two runs with no
  marker saying so.
- **The key hashes the whole request, system prompt and tool schemas included.** So editing
  a prompt misses every entry it touches, and the project's "every prompt change ⇒ re-run
  the harness" rule becomes a mechanism instead of a habit.
- **Cost is replayed as captured at recording time.** Token counts and USD come out of the
  entry, so the cost column of an offline run stays a measurement rather than collapsing to
  zero — which is the whole point of the cheap-vs-strong comparison.
- **A recording cassette autosaves every N entries.** A crash on the last task then costs an
  interval's worth of calls rather than the entire paid run.
- **Entries serialize sorted by key.** A re-record produces a reviewable diff instead of
  reshuffling a 1.5 MB file, and `.gitattributes` marks the cassette `-text` so no
  line-ending conversion can silently corrupt it.
- **A stable "not found" is recorded; a transient failure is not.** A posting that 404s and
  a repo with no README are *answers* — the task set contains both on purpose — so they go
  into the cassette and replay the same way. A rate limit or a 5xx is noise: recording it
  would bake one bad afternoon into the published numbers, so it is left out, and a replay
  of a run that hit one fails loudly and asks to be re-cut. The distinction is whether the
  response would come back the same tomorrow.

## Consequences

- The published table reproduces offline, at no cost and with no key:
  `apply-scout eval --tasks eval/tasks.json --models claude-haiku-4-5,claude-opus-4-8
  --cassette-mode replay`. Recording it cost $0.88 and produced 68 entries; every
  reproduction since has been free.
- The repository carries a ~1.5 MB data artifact of third-party responses, including raw
  posting HTML. That is the price of reproducibility, and it is paid once per re-record.
- A replayed run is only as current as its recording. It answers "does this code still
  produce these numbers on these inputs", not "is the model still behaving this way today"
  — that question still requires a paid `record` run, which is exactly when the cassette
  gets refreshed.
- The wrappers are injected like everything else, so the unit tests continue to run under
  scripted fakes with no cassette at all.
