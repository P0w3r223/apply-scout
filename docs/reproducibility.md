# Reproducibility — record once, replay forever

The evaluation runs against live job postings and a paid API. Both decay: ads get taken down (two of
these eight already have), and re-running the numbers costs money every time. An evaluation nobody can
re-run is a claim, not a measurement.

So every outbound seam — the model transport, the structuring calls, the HTTP fetch, and the GitHub API
— is wrapped by [`cassette.py`](src/apply_scout/cassette.py), which records what came back into a
**committed** JSONL cassette ([`eval/cassettes/`](eval/cassettes/)) and serves it again on replay.
Main-text extraction is recorded too, even though it never leaves the machine: trafilatura's output
shifts between its own versions and libxml2 builds, so a replay that re-ran it would key its
structuring request off different text and miss every entry behind it — which is exactly what CI
caught on a runner with a newer trafilatura.

```bash
apply-scout eval --tasks eval/tasks.json --models claude-haiku-4-5,claude-opus-4-8 \
  --cassette-mode replay      # no network, no ANTHROPIC_API_KEY, $0.00
```

- **Replay never falls back to the network.** An unrecorded request raises `CassetteMiss` and stops the
  run. Quietly serving it live would turn a reproducible evaluation back into a paid, unverifiable one.
- **Cost survives the offline path.** Token counts and USD are replayed from what was captured *at
  recording time*, so the cost column above is real measurement, not a zero.
- **A prompt edit invalidates exactly what it touches.** The cassette key hashes the whole request,
  system prompt included — so the project's "change a prompt ⇒ re-run the harness" rule is enforced by
  the machinery instead of by memory.
- **CI replays it on every pull request and every push to `main`**, which turns the published table
  into a regression test.

Recording the whole 8-posting × 2-model table cost **$0.88** and produced 68 entries (40 structuring
calls, 8 pages, 6 extractions, 14 GitHub responses). Every reproduction since has been free.
