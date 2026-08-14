# ADR 0002 — A deterministic pipeline alongside the agent loop

Date: 2026-07-23
Status: accepted
Author: P0w3r223

---

## Context

By milestone 4 apply-scout had an agent loop: the model decides which tools to call, the
loop records a trajectory and enforces safety budgets. That loop is the flagship — it
demonstrates agentic, model-driven tool use.

Milestone 5 added the structured deliverables: a `MatchReport` and a cover letter, plus a
guardrail that must run over the *structured* letter and evidence. Milestone 6 added an
evaluation harness that scores structured outputs against annotations (requirement F1,
citation fidelity). Both need the gathered data as typed contracts (`JobPosting`,
`CVProfile`, `Evidence`, `MatchReport`) — but the agent loop's output is free text, and
its gathered evidence lives inside the model's conversation, not in a form the harness can
score.

## Options

1. **Extract structured artifacts out of the loop.** Add an observer to the loop that
   parses each tool result into contracts, then synthesize after the loop. Couples the
   generic loop to the domain, or requires a second structured LLM call over the whole
   conversation.
2. **Make the loop's final turn a structured `MatchReport`.** Couples the generic loop to
   one output type, and the loop no longer just "uses tools".
3. **A separate deterministic pipeline** that runs the same tools in a fixed order and
   produces the structured deliverables directly.

## Decision

**Option 3 — keep the agent loop generic, and add a deterministic `pipeline.assess()`.**

The loop and the pipeline serve different, complementary purposes and reuse the same tools
and contracts:

- **The agent loop** (`runner`/`agent`) is the *agentic* artifact: the model orchestrates
  the tools, the trajectory and budgets are first-class, and it stays a generic loop over
  an `LLMClient` + `ToolRegistry`. It answers "can the agent drive the tools sensibly, and
  at what step/cost?".
- **The deterministic pipeline** (`pipeline.assess`) fetches → reads the CV → gathers
  evidence per requirement → generates the report → generates the letter → guardrails it,
  in a fixed order. It answers "reliably produce the structured deliverables, and let the
  harness score them". It reuses the real tools (single source of the gathering logic) and
  the synthesis/guardrail modules.

The evaluation harness scores the **pipeline** (its metrics — requirement F1, citation
fidelity — are about the structured deliverables). The loop's trajectory-based metrics
(variable steps, budget behaviour) are a complementary view of the same system.

## Consequences

- Two orchestration entry points exist. They are not redundant: one is model-driven with a
  trajectory, the other is deterministic and structured. Both are thin — the substance is
  in the shared tools, contracts, synthesis, and guardrail.
- The pipeline's "steps" are a fixed count of LLM calls (a cost proxy), not the variable,
  model-chosen step count of the loop. The harness reports LLM calls + cost accordingly.
- If a future milestone needs the *loop itself* scored end-to-end (its free-text output
  structured and graded), the cleanest path is Option 1's observer — revisited then, not
  now.
