# ADR 0007 — Prompt caching at the top level, so the cassettes survive it

Date: 2026-08-21
Status: accepted
Author: P0w3r223
Related to: [ADR 0004](0004_record_replay_cassettes.md) (the cassette key),
[ADR 0006](0006_scoring_the_agent_loop.md) (what the loop costs)

---

## Context

The agent loop re-sends the whole conversation on every step. Measured on the committed
recordings, that is where the money goes:

| run | input tokens | output tokens | share of cost that is input |
|---|---:|---:|---:|
| demo (Opus, 5 calls) | 53,687 | 10,760 | ~50% |
| eval loop (Haiku, 48 calls) | 338,985 | 36,545 | **~65%** |

Most of those input tokens are the same prefix sent again. Prompt caching bills a repeated
prefix at a tenth of the input rate, so it is the obvious lever — and the one place where a
performance change could quietly destroy this project's reproducibility guarantee.

## Decision — the top-level `cache_control`, not per-block breakpoints

The Messages API offers two ways to ask for caching: annotate individual content blocks
with `cache_control`, or pass it once at the top level and let the API cache the last
cacheable block. **Both would cache the same thing here. Only one keeps the cassettes.**

The cassette key hashes `{model, system, messages, tools}` (ADR-0004). Per-block markers
turn `system` from a string into a list of blocks and rewrite `messages`, so **every entry
ever recorded would miss** — a re-record of both cassettes, and a table that could not be
reproduced from what is committed. The top-level parameter leaves all four byte-identical.

Verified rather than assumed: after enabling it, replaying both published tables and the
demo reports **0 recorded, 1786 / 2163 / 48 replayed**, and the tables are byte-identical to
`eval/expected/`.

Cost accounting had to move with it. With caching on, the API's `input_tokens` is the
*uncached remainder only*; charging for that alone would report runs as far cheaper than
they were. `Usage` now carries `cache_read_tokens` and `cache_write_tokens`, `token_cost`
prices them at 0.10× and 1.25× the input rate, and the budget tracker counts them — a
ceiling that ignored cached tokens would stop bounding the spend it exists to bound. This is
the same silent-understatement bug that already produced one wrong headline (ADR-0006), so
it is closed by construction rather than by care.

The structurer deliberately does **not** ask for caching: every call carries different
content, and its shared prefix sits under the cheap model's cache minimum. Its counters are
read defensively anyway, so enabling it later cannot silently drop the cost.

## Consequences

- **Shipping this cost nothing.** No re-record, no cassette churn, no change to any
  published number — the committed recordings predate caching and replay as the uncached
  calls they were.
- **Demonstrating it does cost something**, and has not been done. Replayed usage carries no
  cache counters, so the saving cannot be shown from what is committed; publishing a
  cached-cost row means re-recording the demo (~$0.54) and the loop pilot (~$0.52). Until
  then the tables describe uncached runs, and this ADR does not claim a measured saving.
- **The first call of each task will not cache on the cheap model.** The minimum cacheable
  prefix is 4096 tokens for `claude-haiku-4-5` and 1024 for `claude-opus-4-8` — not
  monotonic across tiers, hence `CACHE_MIN_PREFIX_TOKENS` as a table. The loop's opening
  request is ~2,769 tokens, under Haiku's floor. Expect the saving on the later, larger
  turns, which is where the tokens are anyway.
- **A cache write costs 1.25×, so a prefix used once is a small loss.** With a loop of five
  to ten steps over a growing prefix that trade is heavily positive, but it is a trade, not
  free money — the tests pin that a read is cheaper and never free.
