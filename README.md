# apply-scout

**An LLM agent that matches a job posting against a candidate's CV and GitHub evidence —
with a from-scratch tool loop, safety budgets, and a trajectory-evaluation harness.**

Portfolio project **P3** (the flagship). Given a job-posting URL, the agent fetches and
structures the requirements, compares them against the candidate's CV and the evidence in
their GitHub repositories, and produces a **match report** (requirement → evidence → rating,
with links) and a **cover-letter draft built only from facts it can cite**. It runs on a
tool loop written from scratch — no agent framework — so that budgets, a machine-readable
trajectory log, and a proper evaluation are possible.

> Status: **milestone 6 of 7** — the from-scratch loop, all three real tools, an end-to-end run,
> the structured deliverables (match report + cover letter), the measured anti-hallucination
> guardrail, **and the evaluation harness**: annotated tasks scored for completion, requirement-
> extraction F1 (vs a human annotation), citation fidelity, and median LLM calls / cost — written
> as a markdown table comparing two models (`apply-scout eval`). Only the CLI/README polish remains.

## Why it's built this way

- **A tool loop written from scratch (no LangChain).** A deliberate, defensible choice:
  full control over the control flow is what makes safety budgets, the trajectory log, and
  systematic evaluation possible. See [`docs/decisions/0001_own_loop_vs_framework.md`](docs/decisions/0001_own_loop_vs_framework.md).
- **Safety budgets.** Every run is bounded by `max_steps`, `max_tokens`, and `max_cost`.
  Exceeding a ceiling is a **controlled stop with a partial report**, never a crash.
- **A trajectory for every run.** Each model call, tool call, and its cost is logged as
  JSONL — the substrate the evaluation harness reads. *95% of junior agent projects stop
  at "it worked on my example"; this one measures.*
- **Evidence or nothing.** A report/letter claim must trace to a real, checkable link.
  A requirement with no evidence is rated `none` — the gap is reported, not hidden.
- **Two models, honestly compared.** The harness runs a cheap model (`claude-haiku-4-5`)
  and a strong one (`claude-opus-4-8`) to answer "when is the cheaper model enough?".

## Architecture

```
job URL ─▶ fetch_job_posting ─▶ JobPosting
              read_cv          ─▶ CVProfile
              github_evidence  ─▶ Evidence[]        ┌── budgets: steps / tokens / cost
                     │                              │   (breach ⇒ controlled stop)
                     ▼                              │
        agent loop (from scratch) ──────────────────┤── trajectory log (JSONL)
                     │                              │
                     ▼                              └── evaluation harness (later)
              MatchReport + CoverLetterDraft
```

The loop depends only on an `LLMClient` protocol and a `ToolRegistry`, so it runs under a
scripted fake model with no network and no API key — which is exactly how the tests drive
it.

## Install & test

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # Windows
pytest
```

The test suite exercises the full loop against mock tools and a scripted model — no
`ANTHROPIC_API_KEY` needed. Real runs (later milestones) read the key from the environment.

## Roadmap

| # | Milestone | Deliverable |
|---|-----------|-------------|
| 1 | Architecture + contracts + loop skeleton | ✅ this repo: contracts, budgets, trajectory, loop, mock tools, tests |
| 2 | `fetch_job_posting` + `read_cv` | ✅ httpx fetch + trafilatura extraction + LLM structuring with validate-and-retry |
| 3 | `github_evidence` | ✅ GitHub API client (pagination, rate limit), evidence search, on-disk cache |
| 4 | Full loop + budgets | ✅ `apply-scout run` CLI, cost accounting, `--verbose`, trajectory JSONL |
| 5 | Report + letter + guardrail | ✅ MatchReport, cover letter, measured anti-hallucination guardrail |
| 6 | **Evaluation harness** | ✅ annotated tasks, metrics (F1, citation fidelity, calls, cost), markdown table, two-model compare |
| 7 | Interface + docs | rich CLI, README eval table, cost analysis, limitations, ADRs, demo |

## License

MIT — see [LICENSE](LICENSE).
