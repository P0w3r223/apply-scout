# ADR 0001 — A from-scratch tool loop, not an agent framework

Date: 2026-07-23
Status: accepted
Author: P0w3r223

---

## Context

apply-scout is an LLM agent: it calls a model, the model asks for tools, we run them,
feed the results back, and repeat until the model is done. That loop is a solved problem
in libraries like LangChain / LangGraph, and the Anthropic SDK itself ships a beta "tool
runner" that drives the loop for you.

The project's real deliverable, though, is not "an agent that runs" — it's a **measured**
agent: safety budgets, a machine-readable trajectory of every step and its cost, and an
evaluation harness that scores runs and compares two models. The question is whether to
build the loop on a framework or write it ourselves.

## Options

1. **LangChain / LangGraph.** Batteries included: agents, tool abstractions, memory,
   callbacks. Fast to a first demo.
2. **Anthropic SDK tool runner (beta).** Official, minimal, drives the request→tool→loop
   cycle over tools we define, with per-turn hooks.
3. **Our own loop** over `POST /v1/messages`, with the SDK used purely as the transport.

## Decision

**Option 3 — write the loop ourselves.**

The loop is genuinely small (see `agent.py`), and owning it makes the parts that matter
first-class rather than bolted-on:

- **Budgets as a hard invariant.** The loop checks `max_steps` / `max_tokens` / `max_cost`
  before every model call and stops with a *partial report* on breach. This is a property
  of our control flow, not a callback we hope fires.
- **A trajectory we define.** Every model call and tool call is recorded as a typed
  `TrajectoryStep` with token usage and cost — the exact shape the evaluation harness
  needs. We are not reverse-engineering a framework's internal event stream.
- **Evaluability.** Because the loop depends only on an `LLMClient` protocol and a
  `ToolRegistry`, it runs under a scripted fake model with no network — so the loop's
  behaviour (tool order, termination, budget stops, error handling) is unit-tested
  deterministically.
- **Understanding, for the interview.** Every concept here — function calling, tool
  schemas, the assistant/tool_result round-trip, retry and budget strategy — has to be
  explainable out loud. A framework would hide exactly the parts worth understanding.

We keep the official **Anthropic SDK** as the model transport (typed requests, streaming,
retries) — the "no framework" rule is about the *agent loop*, not about hand-rolling HTTP.

## Consequences

- We own the loop's correctness: parallel tool results in one turn, appending assistant
  content (including thinking/tool_use blocks) verbatim, `pause_turn` handling for any
  server tools. These are covered by tests and, later, the harness.
- Swapping providers is a single new `LLMClient` adapter; the loop is provider-agnostic.
- We forgo framework conveniences (built-in memory, prebuilt tools). For this project's
  scope — a handful of typed tools and a measured loop — that is a feature, not a cost.
- If requirements later demand a hosted, stateful, sandboxed agent, the managed-agent
  route is reconsidered in a new ADR; it does not change this milestone.
