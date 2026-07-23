# CLAUDE.md — apply-scout

Guidance for Claude Code (and any contributor) working in this repository.

## What this project is

Portfolio project **P3** (the flagship). An LLM agent that, given a job-posting URL,
fetches and structures the requirements, compares them against the candidate's CV and
the evidence in their GitHub repositories, and produces a match report plus a
cover-letter draft with cited sources — built on a **from-scratch tool loop** with
**safety budgets** and a **trajectory-evaluation harness** (success rate, citation
fidelity, cost, steps). The evaluation is the point: it's what separates this from
"works on my one example".

Provider: **Anthropic** (`claude-haiku-4-5` as the cheap model, `claude-opus-4-8` as
the strong one — the eval compares the two). The Anthropic SDK is used only as the
model transport; the agent loop is ours (ADR 0001).

## Architecture

```
src/apply_scout/
  config.py       # models, pricing, budget defaults, paths, token_cost() — no I/O, no secrets
  contracts.py    # frozen Pydantic value objects: JobPosting, CVProfile, Evidence, MatchReport, ...
  budget.py       # Budget (max_steps/max_tokens/max_cost) + BudgetTracker; breach = controlled stop
  trajectory.py   # TrajectoryStep + TrajectoryLogger (JSONL); the flagship artifact
  llm.py          # LLMClient protocol + AnthropicLLM adapter (lazy import); loop is provider-agnostic
  fetch.py        # httpx fetch + trafilatura/stdlib main-text extraction (for fetch_job_posting)
  structuring.py  # LLM text -> contract with validate-and-retry (Structurer protocol + Anthropic impl)
  prompts.py      # the system prompt (a change here => re-run the harness)
  agent.py        # the from-scratch loop: model -> tool_use -> result -> next, with budgets + trajectory
  tools/
    base.py               # Tool contract: Pydantic input schema, run(); errors return as structured results
    registry.py           # name -> tool dispatch; unknown tool = structured error
    fetch_job_posting.py  # real: fetch + extract + structure -> JobPosting
    read_cv.py            # real: read file + structure -> CVProfile
    real.py               # real_tools() factory (github_evidence still mocked until milestone 3)
    mock.py               # stand-ins matching the real tools' contracts (used by the loop tests)
tests/            # pytest; the loop is tested under a scripted fake model (no network, no key)
eval/results/     # trajectory JSONL + metric tables (later milestone)
docs/decisions/   # ADRs
```

Data flows one way: tools emit contracts, the agent reasons over them and logs a
trajectory, the harness (later) scores the trajectory.

## Rules (do not violate)

- **Own the loop.** No LangChain or agent framework — the whole control flow is in
  `agent.py`, which is what makes budgets/trajectory/eval possible (ADR 0001).
- **Tools are testable without an LLM.** A tool is `validate input -> work -> ToolResult`.
  Tool errors (bad args, failed fetch) come back to the model as `is_error` results,
  never as exceptions — the loop must not crash on a bad tool call.
- **Budgets stop gracefully.** Hitting `max_steps` / `max_tokens` / `max_cost` ends the
  run with a **partial report**, not a raised exception.
- **No hallucinated evidence.** A cover-letter/report claim must trace to an `Evidence`
  with a real, checkable URL. No evidence → rated `none`; do not paper over the gap.
- **Every prompt/loop change ⇒ re-run the harness.** Results land in `eval/results/`
  with the date and commit hash so regressions are visible (later milestone).
- **No secrets in code.** `ANTHROPIC_API_KEY` is read from the environment at call time.
- **Immutable contracts, no magic numbers.** Value objects are frozen; thresholds and
  model IDs live in `config.py`.

## How to run

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # Windows
pytest                                             # the loop runs under a fake model
ruff check .
```

Real runs (later milestones) need `ANTHROPIC_API_KEY` in the environment.

## Roadmap (7 milestones)

1. **Architecture + contracts + loop skeleton.** ✅ Pydantic contracts, budgets,
   trajectory, from-scratch loop, mock tools, tests.
2. **`fetch_job_posting` + `read_cv` (this milestone).** ✅ httpx fetch + trafilatura
   extraction + LLM structuring with validate-and-retry; `real_tools()` factory.
3. `github_evidence` (GitHub API: pagination, rate limit, evidence search, disk cache).
4. Full loop wired on real tasks + budgets + cost accounting + `--verbose` trajectory.
5. Match report + cover letter + **anti-hallucination guardrail** (with measurement).
6. **Evaluation harness**: 20–30 annotated tasks, metrics, markdown table, two-model compare.
7. CLI (rich) + README with the eval table + cost analysis + limitations + ADRs.

## What not to do

- Do not add a dependency on LangChain or any agent framework (ADR 0001).
- Do not let a tool raise into the loop — return a structured error instead.
- Do not turn a budget breach into an exception — it is a controlled stop.
- Do not embed a real CV, a real API key, or PolEmo-style dataset text in the repo.
