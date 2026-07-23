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
  github.py       # GitHub API client: list repos + README, pagination, rate limits, on-disk cache
  prompts.py      # the system prompt (a change here => re-run the harness)
  agent.py        # the from-scratch loop: model -> tool_use -> result -> next, with budgets + trajectory
  runner.py       # run_assessment(): assemble real tools + LLM + budget, run one posting end-to-end
  formatting.py   # render steps (--verbose) and the run summary (ASCII, pure)
  cli.py          # `apply-scout run --url ... --cv ... --github-user ...` (+ __main__ for `python -m`)
  synthesis.py    # generate MatchReport + CoverLetterDraft from gathered evidence (LLM-structured)
  guardrail.py    # deterministic anti-hallucination guardrail + unsupported-fraction measurement
  pipeline.py     # assess(): deterministic gather -> synthesize -> guard; produces the deliverables
  evaluation.py   # the eval harness: metrics (requirement F1, citation fidelity), aggregate, table
  tools/
    base.py               # Tool contract: Pydantic input schema, run(); errors return as structured results
    registry.py           # name -> tool dispatch; unknown tool = structured error
    fetch_job_posting.py  # real: fetch + extract + structure -> JobPosting
    read_cv.py            # real: read file + structure -> CVProfile
    github_evidence.py    # real: find_evidence (pure) + GitHub-backed tool -> Evidence[]
    real.py               # real_tools() factory (all three tools live)
    mock.py               # stand-ins matching the real tools' contracts (used by the loop tests)
tests/            # pytest; the loop is tested under a scripted fake model (no network, no key)
eval/tasks.example.json  # annotated task fixtures (documents the eval format)
eval/results/     # trajectory JSONL + eval markdown tables (gitignored)
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

Real runs need `ANTHROPIC_API_KEY` (and optionally `GITHUB_TOKEN` for a higher GitHub rate limit):

```bash
apply-scout run --url <posting-url> --cv path/to/cv.md --github-user <user> --verbose
# streams each step, writes the trajectory JSONL to eval/results/, prints a summary
```

Evaluate over annotated tasks (writes a markdown table comparing two models):

```bash
apply-scout eval --tasks eval/tasks.json --models claude-haiku-4-5,claude-opus-4-8
```

## Roadmap (7 milestones)

1. **Architecture + contracts + loop skeleton.** ✅ Pydantic contracts, budgets,
   trajectory, from-scratch loop, mock tools, tests.
2. **`fetch_job_posting` + `read_cv`.** ✅ httpx fetch + trafilatura extraction + LLM
   structuring with validate-and-retry; `real_tools()` factory.
3. **`github_evidence`.** ✅ GitHub API client (pagination, rate limit), evidence search
   (repo metadata + README, with snippets), on-disk cache. `real_tools()` is fully real.
4. **Full loop + budgets.** ✅ `run_assessment()` + `apply-scout run` CLI: real tools wired
   end-to-end, per-model cost accounting, `--verbose` step stream, trajectory JSONL.
5. **Report + letter + guardrail.** ✅ `synthesis` (MatchReport + cover letter), a deterministic
   anti-hallucination `guardrail` (removes fabricated citations; measures unsupported before/after),
   and `pipeline.assess()`.
6. **Evaluation harness (this milestone).** ✅ `evaluation` + `apply-scout eval`: annotated tasks
   scored for completion, requirement F1, citation fidelity, median LLM calls / cost → markdown
   table comparing two models.
7. **Interface + docs (this milestone).** ✅ rich CLI (colored step stream + eval table),
   README with the eval-table shape + cost analysis + honest limitations + mermaid diagram,
   ADR-0002 (pipeline vs loop) and ADR-0003 (structured outputs + guardrail). Demo GIF pending a
   live run.

## What not to do

- Do not add a dependency on LangChain or any agent framework (ADR 0001).
- Do not let a tool raise into the loop — return a structured error instead.
- Do not turn a budget breach into an exception — it is a controlled stop.
- Do not embed a real CV, a real API key, or PolEmo-style dataset text in the repo.
