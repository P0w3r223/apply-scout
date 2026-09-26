# Demo

A real `apply-scout run` against a live posting (Jeeves — *Senior AI Engineer*), matched against the
synthetic candidate CV (`cv/candidate.md`) and the public `P0w3r223` GitHub:

Recorded live on 2026-08-21 against `claude-opus-4-8` (**5 model calls, 33 `github_evidence` probes,
48 978+10 983 tokens, $0.4368 with prompt caching — $0.5195 without, 125 s**), then **rendered from a
replay of that recording** — which is why the steps are evenly paced: a replay has no thinking time to
show. Repeated probes are folded up with an explicit count (`... 7 more github_evidence call(s)`) and
one frame contributes at most six rows; nothing is edited or reordered.

**Reproduce it yourself — offline, in under a second, with no API key:**

```bash
python scripts/demo.py capture --url https://jobs.lever.co/tryjeeves/2f00206f-6091-4eed-8b5f-1325afdbfe30 \
  --cv cv/candidate.md --github-user P0w3r223 --cassette-mode replay
python scripts/demo.py render
```

The replay reproduces the recorded stream **character for character** — under a second instead of 125 s,
$0 instead of $0.4368 — because every external seam of that run is committed in
`eval/cassettes/run.jsonl` (see [ADR-0004](docs/decisions/0004_record_replay_cassettes.md)).

Three things the run shows:

- **It finishes by calling a tool, not by talking.** The last step is
  `submit_report -> ok: submitted: 29 rating(s), 4 letter sentence(s)` — the deliverable arrives as a
  validated `MatchReport` + `CoverLetterDraft`, which is what lets the harness score this loop on the
  same axes as the pipeline ([ADR-0006](docs/decisions/0006_scoring_the_agent_loop.md)).
- **It rates honestly, and audits its own evidence.** Requirements with no retrieved evidence come back
  `none` — including "5+ years professional experience", which no repository can prove. It also throws
  out its own hits: the `Go` probes matched repos, but the agent noticed every snippet was the English
  word "go/goes" in prose rather than the language, and rated the requirement `none` anyway.
- **It says what it could not verify.** The closing summary flags that the CV lists skills the
  repository search never surfaced as citable evidence, and that those were rated `none` for lack of
  *retrievable proof* rather than lack of skill. That distinction is the whole point of the evidence
