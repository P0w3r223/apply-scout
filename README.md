# apply-scout

**An LLM agent that matches a job posting against a candidate's CV and GitHub evidence —
with a from-scratch tool loop, safety budgets, and a trajectory-evaluation harness.**

Portfolio project **P3** (the flagship). Given a job-posting URL, the agent fetches and
structures the requirements, compares them against the candidate's CV and the evidence in
their GitHub repositories, and produces a **match report** (requirement → evidence → rating,
with links) and a **cover-letter draft built only from facts it can cite**. It runs on a
tool loop written from scratch — no agent framework — so that budgets, a machine-readable
trajectory log, and a proper evaluation are possible.

> Status: **milestone 3 of 7** — the architecture, contracts, budgets, trajectory log, and
> from-scratch loop, plus **all three real tools**: `fetch_job_posting` (httpx + trafilatura +
> LLM structuring with validate-and-retry), `read_cv`, and `github_evidence` (GitHub API with
> pagination, rate-limit handling, and an on-disk cache). Wiring the tools into a real end-to-end
> run and the evaluation harness follow. See the roadmap.

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
| 4 | Full loop + budgets | end-to-end on real tasks, cost accounting, `--verbose` trajectory |
| 5 | Report + letter + guardrail | match report, cover letter, measured anti-hallucination guardrail |
| 6 | **Evaluation harness** | 20–30 annotated tasks, metrics, markdown table, two-model comparison |
| 7 | Interface + docs | rich CLI, README eval table, cost analysis, limitations, ADRs, demo |

## License

MIT — see [LICENSE](LICENSE).
