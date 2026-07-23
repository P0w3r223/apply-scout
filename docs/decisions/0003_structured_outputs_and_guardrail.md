# ADR 0003 — Structured outputs with our own validate-and-retry, and a deterministic guardrail

Date: 2026-07-23
Status: accepted
Author: P0w3r223 + Claude

---

## Context

Two places turn model output into something the rest of the system can trust: **structuring**
free text into a contract (a posting or CV into a `JobPosting` / `CVProfile`, evidence into a
`MatchReport`), and the **anti-hallucination guardrail** over the cover letter. Both could lean
on the model, and both could lean on the SDK's conveniences. The question is how much to trust
the model, and where to put the check.

## Decision 1 — structuring: constrained output *and* our own validate-and-retry

The structurer (`structuring.structure`) asks the model for JSON constrained to the target
schema (structured outputs), then **validates the result against the Pydantic contract itself
and retries on failure**, up to a small attempt budget, before giving up with a readable
`StructuringError`.

Why both, rather than trusting the API's structured-output guarantee alone:

- The retry is **ours and explicit** — the strategy and its limit are visible and unit-tested
  (invalid → retry → succeed; always-invalid → give up), which is the point of the exercise.
- Validation is the real contract boundary: `extra="forbid"` frozen models reject a stray or
  mistyped field loudly, so a drift in the model's output is a caught error, not silent data.
- Unsupported JSON-schema keywords (e.g. `minLength`) are stripped before the request so a real
  call isn't rejected, while we still enforce them on the parsed result.

A tool error (bad input, failed fetch, unstructurable text) is returned as a **structured tool
result**, never raised — the agent reads it and adapts.

## Decision 2 — the guardrail is deterministic, not an LLM judge

The cover letter is generated to cite, per sentence, the evidence links that back it. The
guardrail (`guardrail.guardrail_letter`) then verifies coverage **mechanically**: a sentence
citing a link absent from the report's evidence is removed; a sentence citing nothing is
treated as connective and kept.

Why deterministic rather than a second model grading the first:

- **Measurable and reproducible.** It reports `unsupported_before` / `unsupported_after` — the
  fraction of sentences whose citations don't hold up, before and after. An LLM judge would add
  cost, latency, and its own noise to the very number meant to quantify hallucination.
- **Auditable.** The rule is one function anyone can read; a reviewer can see exactly why a
  sentence was cut.
- **The right tool for the claim.** "Does this cited link exist in the report?" is a set
  membership test, not a judgement call. Reserve model judgement for things that actually need
  it.

## Consequences

- The guardrail bounds hallucinated **citations**, not every possible overstatement: a grounded
  sentence's phrasing is not fact-checked. This is stated plainly in the README limitations.
- Structuring costs one (occasionally more) model call per artifact; the retry caps the worst
  case. Extraction runs on the cheap model, keeping that cost low.
- Both mechanisms are injectable and fully tested under fakes, so the whole extract-and-guard
  path runs with no network and no key.
