# Cost analysis

Each eval row runs one model end-to-end, and every model call's token usage flows through one
`token_cost()` helper, so per-task cost is measured, not estimated. For this task set the result is
unambiguous: **`claude-opus-4-8` costs ≈6× more per task than `claude-haiku-4-5` ($0.1910 vs $0.0306)
and does not buy a better match report** — identical completion (62%, both blocked by the same three
URLs) and *lower* requirement coverage (0.62 vs 0.76).

**What prompt caching actually saved.** The loop re-sends the whole conversation every step, so
requests carry a top-level `cache_control` and a repeated prefix bills at a tenth of the input rate.
Measured **inside each recorded run** — the same prompts and replies, priced as if nothing had been
cached — so the model's own sampling variance cannot be mistaken for a saving:

| recorded run | prompt tokens | served from cache | cost | same run, uncached | saved |
|---|---:|---:|---:|---:|---:|
| eval loop — Haiku, 38 turns | 248,710 | 53% | **$0.2950** | $0.3994 | **26%** |
| demo — Opus, 5 turns | 48,978 | 51% | **$0.4368** | $0.5195 | **16%** |

Per task the saving runs from **36% to nothing**, and the shape is the point: the Reddit task saved
**0%** because the loop gave up after a single call — nothing was ever re-sent, so nothing could be
read back. Caching pays for turns over a growing prefix, and a cache *write* costs 1.25×, which is
why the five-turn demo saves less than the 38-turn eval. On the median task: $0.0741 → **$0.0592**.

Cached tokens are priced and counted against the budget rather than treated as free — with caching on,
the API's `input_tokens` is only the uncached remainder ([ADR-0007](docs/decisions/0007_prompt_caching.md)).

It does not buy a better letter either, which took a metric fix to see. The strong model's 1.00 citation
fidelity is over **one task**; in the other four its letters cite nothing at all (a 0.13 citation rate),
and a letter that promises nothing checkable cannot be caught fabricating. What actually produces
grounded letters on this task set is **giving the cheap model the agent loop** — 0.45 cited, 1.00
fidelity across four tasks, at $0.0592. Spend the money on agency, not on the tier.

One caveat found while measuring the loop, and worth naming because it undercut this very section: cost
was priced from the model id the **API returns**, which for Haiku is a dated snapshot
(`claude-haiku-4-5-20251001`) absent from `PRICING`. `token_cost` silently returned 0.0, so the loop's
whole cost column read `$0.00` — and `max_cost` could never fire, because a run that never spends
anything cannot breach a spend ceiling. `price_for` now resolves the longest matching prefix and the
recorded entries were re-priced from their captured token counts. **The first table this produced said
the loop was 3.5× cheaper than the pipeline; it was 3.3× more expensive** (2.5× today, on a like-for-like
basis, after prompt caching). Measured cost is only as honest as the rate card lookup behind it.
