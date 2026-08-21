# ADR 0006 — Score the agent loop on the same axes as the pipeline

Date: 2026-08-21
Status: accepted
Author: P0w3r223
Related to: [ADR 0001](0001_own_loop_vs_framework.md) (own the loop),
[ADR 0002](0002_pipeline_vs_agent_loop.md) (why both exist),
[ADR 0005](0005_requirement_coverage_not_f1.md) (what the coverage metric means)

---

## Context

ADR-0002 kept two execution paths: a deterministic pipeline that reliably produces the
deliverables, and the from-scratch agent loop that ADR-0001 argues is the point of the
project. Every published number described the **pipeline**. The loop was covered by unit
tests and nothing else — the harness had no way to run it, so the project's headline
artifact was the one thing it never measured.

The obstacle was shape, not plumbing. `run_models` already takes an `assess_fn_factory`,
so a second runner is a small wiring change. But the metrics score an `Assessment` —
`JobPosting`, `MatchReport`, `CoverLetterDraft`, guardrail — while the loop ended by
writing markdown prose and never produced a cover letter at all. There was nothing to
score.

## Decision — the loop finishes by calling a tool, not by talking

A new terminal tool, `submit_report`, takes the finished `MatchReport` and
`CoverLetterDraft` as its input schema. The system prompt directs the agent to end there
instead of writing the report as a message.

Three consequences follow, and all three are the reason for choosing it over the
alternatives:

- **The deliverable is validated at the boundary.** The loop already validates every tool
  call against a Pydantic schema and hands failures back as recoverable errors, so a
  malformed report is a retry the model can act on — not a parse failure downstream.
- **The two runners produce the same contracts**, so the same guardrail runs over the
  loop's letter and the same metrics score both. The rows compare rather than merely sit
  next to each other.
- **The agent does not mark its own homework.** `submit_report` stores and validates;
  grounding is decided afterwards by the same deterministic guardrail the pipeline uses.

Rejected: **post-hoc structuring** of the loop's prose (an extra model call per task, and
citation fidelity would then partly measure the parser rather than the loop) and
**loop-specific metrics** (cheap, but produces a second table that answers a different
question — which is the problem this ADR exists to solve).

`MAX_OUTPUT_TOKENS` rises from 4096 to 16000 as a direct consequence: a cut-off sentence
can be continued (see `MAX_CONTINUATIONS`), a cut-off `tool_use` block is unparseable JSON
and cannot. The eval also gives the loop looser ceilings than a production run
(`EVAL_AGENT_MAX_*`), because a budget stop yields no deliverable and would be scored as a
model failure — the harness measures what the loop does when allowed to finish.

## What it found

| Runner | Model | Completed | Req coverage | Citation fidelity | Median calls | Median cost |
|---|---|---|---|---|---|---|
| pipeline | `claude-haiku-4-5` | 75% | 0.80 | 0.83 | 4 | $0.0291 |
| pipeline | `claude-opus-4-8` | 75% | 0.68 | 1.00 | 4 | $0.1827 |
| **agent loop** | `claude-haiku-4-5` | 75% | 0.80 | **1.00** | 9.5 | $0.0963 |

On the same model, the loop costs **3.3× the pipeline** and makes 2.4× the calls, and buys
exactly one thing: **citation fidelity, 0.83 → 1.00**. Coverage and completion are
identical — unsurprising, since both paths reach the posting through the same tool.

The useful comparison is the diagonal. Grounded letters can be had either by moving to the
strong model in the pipeline ($0.1827) or by keeping the cheap model and giving it the loop
($0.0963) — **half the price, with better requirement coverage** (0.80 against Opus's 0.68).
The agency is what fixes the citations, not the model tier.

## Consequences

- **The project's central claim is now measured rather than asserted.** ADR-0001 argued for
  owning the loop; this is the first evidence in the repository about what that buys.
- **A cost-accounting bug surfaced immediately, and it was load-bearing.** The loop prices
  the *response* model id, which the API returns as a dated snapshot
  (`claude-haiku-4-5-20251001`) that was absent from `PRICING`, so `token_cost` silently
  returned 0.0. The loop's entire cost column read as $0.00 — and, worse, `max_cost` could
  never fire, since a run that never spends anything cannot breach a spend ceiling.
  `price_for` now resolves the longest matching prefix, and the affected cassette entries
  were backfilled from their recorded token counts (no re-record: cost is derived from
  tokens, which were captured correctly). **The first table this runner produced said the
  loop was 3.5× cheaper than the pipeline. It is 3.3× more expensive.**
- **The Opus row of the loop is deliberately not recorded.** It would cost roughly $4.7 to
  answer "does the loop help the strong model too?", and the strong model already scores
  1.00 on citation fidelity — the one axis the loop was shown to move. The question is open,
  and cheap to answer later if the answer starts to matter.
- **Two runners now share one prompt and one toolset.** `apply-scout run` finishes through
  `submit_report` exactly as the eval does, so the thing measured is the thing shipped. The
  cost is that changing either invalidates the run cassette; the demo was re-recorded.
