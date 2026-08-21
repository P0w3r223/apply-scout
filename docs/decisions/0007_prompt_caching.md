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

## What it saved (measured)

Re-recorded on 2026-08-21 for **$0.73** total. Only the model turns were re-recorded: the
fetch, extraction, GitHub and structuring entries replayed from the existing cassette, so the
runs saw byte-identical inputs and the comparison is not confounded by a changed posting.

The saving is measured **inside each run** — the same prompts and the same replies, priced as
if none of it had been cached. Comparing two separate runs would credit the cache with the
model's own sampling variance:

| recorded run | prompt tokens | from cache | cost | same run, uncached | saved |
|---|---:|---:|---:|---:|---:|
| eval loop — Haiku, 38 turns | 248,710 | 53% | $0.2950 | $0.3994 | **26%** |
| demo — Opus, 5 turns | 48,978 | 51% | $0.4368 | $0.5195 | **16%** |

Per task (loop, median): **$0.0741 → $0.0592**. The spread is the interesting part — 36% on the
longest task, and **0% on the Reddit task**, where the loop gave up after a single call so
nothing was ever re-sent. The five-turn demo saves less than the 38-turn eval for the same
reason in miniature: at 1.25× a cache *write* is a loss until something reads it back. Caching
pays for turns over a growing prefix, not for calling a model.

## Consequences

- **Shipping this cost nothing; measuring it cost $0.73.** No cassette churn and no change to
  the pipeline rows — their seams were never touched.
- **Re-recording moved the loop's quality numbers, and the code did not.** Completion went
  75% → 62% and the citation rate 0.74 → 0.45 on identical inputs. That is sampling on an
  eight-task set, and it is now stated wherever those numbers appear: the ordering survived
  both runs, the decimals did not.
- **The published table now mixes bases** — the loop row is cached, the pipeline rows are not.
  The uncached counterfactual ($0.0741 median) is published beside it so the runner comparison
  is made on one basis rather than flattering the loop.
- **The first call of each task will not cache on the cheap model.** The minimum cacheable
  prefix is 4096 tokens for `claude-haiku-4-5` and 1024 for `claude-opus-4-8` — not
  monotonic across tiers, hence `CACHE_MIN_PREFIX_TOKENS` as a table. The loop's opening
  request is ~2,769 tokens, under Haiku's floor. Expect the saving on the later, larger
  turns, which is where the tokens are anyway.
- **A cache write costs 1.25×, so a prefix used once is a small loss.** With a loop of five
  to ten steps over a growing prefix that trade is heavily positive, but it is a trade, not
  free money — the tests pin that a read is cheaper and never free.
