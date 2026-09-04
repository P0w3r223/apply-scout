# CLAUDE.md — apply-scout

Guidance for Claude Code (and any contributor) working in this repository.

## What this project is

An LLM agent that, given a job-posting URL,
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
  matching.py     # crude token containment, shared by the guardrail and the harness (no deps)
  guardrail.py    # deterministic anti-hallucination guardrail: letter->report filter (removes) +
                  # report->posting grounding (measures only, removes nothing)
  pipeline.py     # assess(): deterministic gather -> synthesize -> guard; produces the deliverables
  evaluation.py   # the eval harness: metrics (requirement F1, citation fidelity), aggregate, table
  cassette.py     # record/replay of every external seam (LLM, structurer, fetch, extract, GitHub)
  env.py          # loads the gitignored .env into the environment (exported vars win)
  tools/
    base.py               # Tool contract: Pydantic input schema, run(); errors return as structured results
    registry.py           # name -> tool dispatch; unknown tool = structured error
    fetch_job_posting.py  # real: fetch + extract + structure -> JobPosting
    read_cv.py            # real: read file + structure -> CVProfile
    github_evidence.py    # real: find_evidence (pure) + GitHub-backed tool -> Evidence[]
    submit_report.py      # terminal tool: the deliverable arrives as a contract, not prose
    real.py               # real_tools() factory (all four tools live)
    mock.py               # stand-ins matching the real tools' contracts (used by the loop tests)
  retrieval/      # the retrieval evaluation: `python -m apply_scout.retrieval`
    corpus.py             # repos, READMEs and queries read back out of the committed cassette
    judgments.py          # the hand-annotated ground truth, and the three rules that decided it
    retrievers.py         # substring (ships), matching.mentions (the predicted fix), BM25
    metrics.py            # recall@k / MRR / nDCG, scored only where retrieval is possible
    report.py             # attempts -> the published table and the decomposition of the 87%
  attack/         # the security measurement: `python -m apply_scout.attack`
    payloads.py           # what an attacker prints, and what counts as getting it (text+demand+judge)
    pages.py              # the one base posting, and the four placements the payload is printed at
    obey.py               # the reader that obeys everything — the model removed as a variable
    suite.py              # the grid: 2 extractors x 5 payloads x 4 placements against real_tools()
    report.py             # attempts -> the published tables, and the list of surprises
scripts/
  demo.py         # capture (a real run -> docs/demo-cast.json) and render the README demo
  demo_svg.py     # pure: cast -> animated SVG (fixed-size scrolling terminal, CSS only)
tests/            # pytest; the loop is tested under a scripted fake model (no network, no key)
eval/tasks.example.json  # annotated task fixtures (documents the eval format)
eval/results/     # trajectory JSONL + eval markdown tables (gitignored)
eval/cassettes/   # recorded external responses (COMMITTED — this is what replays in CI)
eval/expected/    # the approved tables CI diffs against, attack.md among them (COMMITTED)
eval/retrieval/   # relevance judgments: which repo proves which requirement (COMMITTED)
docs/decisions/   # ADRs
docs/demo.svg     # the README demo, generated from docs/demo-cast.json (both COMMITTED)
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
- **A partial deliverable never reports as `completed`.** A reply cut off by
  `MAX_OUTPUT_TOKENS` is continued in a *user* turn (prefilling the assistant turn is
  rejected by this model family) and the pieces are stitched; running out of
  `MAX_CONTINUATIONS` ends the run as `truncated`. `RunStatus` is what the eval's
  completion rate reads — it has to mean what it says.
- **No hallucinated evidence.** A cover-letter/report claim must trace to an `Evidence`
  with a real, checkable URL. No evidence → rated `none`; do not paper over the gap.
- **The page quotes; it never retypes.** Every number in `docs/index.html` is a verbatim
  cell of a committed artifact under `eval/expected/` or the recorded demo cast. To
  publish a new number, extend the generator that prints it and let CI diff the
  artifact — never type it onto the page. Ratios and comparisons are *arguments*, not
  cells, and belong in the README. A test enforces this; the alternative is what the
  page actually did, which was to state the same ratio two different ways eleven lines
  apart and carry a whole paragraph of figures no committed file contained.
- **Every prompt/loop change ⇒ re-run the harness.** Results land in `eval/results/`
  with the date and commit hash so regressions are visible (later milestone). The
  cassette key hashes the whole request, prompt included, so a prompt edit misses every
  entry it touches — the rule is enforced by the machinery, not by memory.
- **Replay never falls back to the network.** An unrecorded request raises `CassetteMiss`.
  Serving it live would turn a reproducible evaluation back into a paid, unverifiable one.
- **No secrets in code.** `ANTHROPIC_API_KEY` is read from the environment at call time.
- **`real_tools()` puts all three legs of the lethal trifecta in one context.** It reads
  untrusted web text (`fetch_job_posting`), reaches local files and a GitHub token (`read_cv`,
  `github_evidence`), and makes outbound requests to a model-chosen URL (`fetch_job_posting`
  again) — so an instruction injected into a posting has both a way to read and a way to send.
  One leg is cut on purpose (`submit_report` hands the deliverable to a human) and two are now
  narrowed: `read_cv` honours only the file `--cv` named, and `fetch` refuses non-public
  addresses on every redirect hop. When adding or widening a tool, prefer the version that
  removes a leg over the one that adds a capability; a new argument naming a file, a host, a
  command or a query reconstitutes what that cut was for. The README's **Limitations** section
  carries the current inventory and what the narrowing does *not* buy, and is the contract —
  deliberately not repeated here, because two copies of a line number is one copy that goes stale.
- **Three invariants hold that confinement up; all are easy to undo by accident.** The URL guard
  is composed *outside* the cassette, because CI runs `replay` and nothing else — moved inside,
  it would never execute in the only mode the build exercises. The readable set is
  constructor state rather than a field on `ReadCVInput`, because a cassette key hashes the tool
  definitions along with the conversation: widening the schema misses every recorded entry and
  turns a free replay into a paid re-record. And **a caller passing `fetch=` to `real_tools()`
  replaces the guarded tool it would have built** — that ran unguarded in the eval harness for a
  whole stage of security work, invisibly, because a live `HttpFetcher` re-checks each hop itself
  while a cassette in `replay` checks nothing. `real_tools` now refuses an unguarded `fetch=`.
  A test pins each tool's spec, and two more assert the assembled toolset refuses a blocked URL.
- **A suite that measures a defence must be checked for the flattering failure, not the alarming
  one.** `attack/` reports `0` for a guard that held and for a fixture that could never have
  expressed the attack, and they are indistinguishable from outside. Both are now caught: every
  run first *removes* `read_cv`'s allowlist and requires the leak to land (`suite.calibrate`,
  fatal on failure), and `report.unlanded` fails a run where a payload reached nobody. The first
  of those was written because the first published table was in exactly that state.
- **Immutable contracts, no magic numbers.** Value objects are frozen; thresholds and
  model IDs live in `config.py`.

## How to run

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # Windows
pytest                                             # the loop runs under a fake model
ruff check .
```

Real runs need `ANTHROPIC_API_KEY` (and optionally `GITHUB_TOKEN` for a higher GitHub rate
limit). Copy `.env.example` to `.env` — the CLI loads it at startup (`env.py`); an already
exported variable wins. A `--cassette-mode replay` run needs neither key nor network:

```bash
apply-scout run --url <posting-url> --cv path/to/cv.md --github-user <user> --verbose
# streams each step, writes the trajectory JSONL to eval/results/, prints a summary
```

Score the retriever against the committed judgments (corpus, queries and ground truth are all in
the repository, so this is offline and free). Exits non-zero if a judgment names a repository the
corpus does not contain, or a query has no judgment:

```bash
python -m apply_scout.retrieval --out eval/expected/retrieval.md
```

Re-measure the attack surface (no key, no network, no cassette — the reader is a function and the
attacker's server is a transport, so it is free and deterministic). Exits non-zero when an outcome
disagrees with what the payload declared:

```bash
python -m apply_scout.attack --out eval/expected/attack.md
```

Evaluate over annotated tasks (writes a markdown table comparing two models):

```bash
apply-scout eval --tasks eval/tasks.json --models claude-haiku-4-5,claude-opus-4-8
```

Regenerate the README demo from the committed recording (free, offline — re-record only when
the run itself should change, and expect to pay for it):

```bash
python scripts/demo.py capture --url <recorded-url> --cv cv/candidate.md \
  --github-user P0w3r223 --cassette-mode replay
python scripts/demo.py render      # docs/demo-cast.json -> docs/demo.svg
python scripts/demo.py render-gif  # the same cast -> docs/demo.gif (needs Pillow)
```

Both pictures come from one cast and both are committed. The SVG is the better artifact —
text, a tenth the size, crisp at any zoom — and it is what the project page embeds, through
`<object>` rather than `<img>` because a browser will not animate an SVG loaded as an image.
The README needs the GIF: GitHub sanitises HTML, so `<object>` is unavailable there, and
every row of this recording starts at `opacity: 0`. Re-render **both** after re-recording;
a test fails on a GIF whose frame count no longer matches the cast.

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
6. **Evaluation harness.** ✅ `evaluation` + `apply-scout eval`: annotated tasks
   scored for completion, requirement coverage, citation fidelity, median LLM calls / cost →
   markdown table comparing two models.
7. **Interface + docs.** ✅ rich CLI (colored step stream + eval table),
   README with the eval-table shape + cost analysis + honest limitations + mermaid diagram,
   ADR-0002 (pipeline vs loop) and ADR-0003 (structured outputs + guardrail).
8. **Record/replay cassettes.** ✅ `cassette.py`: every external seam
   (LLM, structurer, HTTP fetch, GitHub) records to a committed JSONL cassette and replays
   with no network, no key and no cost. `--cassette-mode {off,record,replay,auto}` on both
   subcommands; a CI job replays the evaluation on every PR and push to main. The 8-posting × 2-model
   cassette is recorded and committed (68 entries, $0.88); replay reproduces the published
   table byte-for-byte. Main-text extraction is a recorded seam too — trafilatura's output
   differs between versions, so re-running it on replay changes the structuring key and
   misses. `env.py` loads `.env` so a real run needs no shell setup.
9. **The demo.** ✅ `scripts/demo.py capture` records a real run (recorded 2026-08-21: 8 steps,
   $0.5948, 138 s → `eval/cassettes/run.jsonl`) and `scripts/demo.py render` turns the cast into
   `docs/demo.svg` — a CSS-animated, fixed-size scrolling terminal, no recorder binary and no
   JavaScript. `--cassette-mode replay` regenerates it offline, so the picture stays an artifact
   of a reproducible run; CI replays it and fails on any drift.
10. **Truthful completion.** ✅ A reply stopped by `max_tokens` used to be
   reported as `completed` with the report cut off mid-table. The loop now asks for the rest in a
   user turn and stitches the pieces; out of continuations it returns the new `RunStatus.TRUNCATED`.
   Covered by tests rather than by the demo — a cut-off `submit_report` call is unparseable JSON and
   cannot be continued at all, which is why milestone 12 raised `MAX_OUTPUT_TOKENS`.
11. **A metric that means something.** ✅ `requirement_f1` scored an exact set
   match against an annotation that lists only the load-bearing skills, so extracting a posting
   thoroughly *lowered* the score — a flawless extraction could not have beaten 0.68 on this task
   set. Replaced by `requirement_coverage` (recall, containment matching); precision is not
   reported because no honest denominator exists here (ADR-0005). Re-scoring cost $0: the metric
   is a pure function of the recorded assessments, so the cassette recomputed the table offline.
12. **The loop, finally measured.** ✅ `submit_report` makes the loop finish with a validated
   `MatchReport` + `CoverLetterDraft`, so `agent_assess_fn` scores it on the same axes as the
   pipeline (`apply-scout eval --runner agent`). On `claude-haiku-4-5` the loop costs 3.3× the
   pipeline and is the only configuration that both cites (0.74 of sentences) and gets every
   citation right — grounded letters at half the price of switching to Opus (ADR-0006). Surfaced a
   live bug: cost was priced from the API's *response* model id, a dated snapshot missing from
   `PRICING`, so the loop billed $0.00 and `max_cost` could never fire.
13. **Metrics that can say "not applicable".** ✅ A code review caught both metrics
   returning their *best* score when they had no data: an unannotated task scored 1.00 coverage, and
   a letter citing nothing scored 1.00 fidelity. The published table therefore read 0.80/0.68 and
   credited Opus with a headline it had not earned — five of its six letters cite nothing at all.
   Both return `None` now, print as `n/a`, carry the count of tasks behind each mean, and are
   published beside a new **citation rate**. Also fixed: a `max_tokens` cut inside a `tool_use` block
   used to build a conversation the API rejects (crash, trajectory lost) and now stops as
   `truncated`; `run` exits non-zero when nothing was submitted; the structurer seam re-derives cost
   from recorded tokens so the rate card is never frozen in the artifact; CI diffs the replayed
   tables against `eval/expected/` instead of only printing them.
14. **Prompt caching (this milestone).** ✅ The loop re-sends the conversation every step and
   ~65% of its cost is input tokens, so requests carry a **top-level** `cache_control` — chosen
   over per-block breakpoints precisely because it leaves `{model, system, messages, tools}`
   byte-identical, so no cassette entry is invalidated (verified: 0 recorded, tables byte-identical).
   `Usage` gained cache counters and `token_cost` prices them at 0.10× / 1.25×, because with caching
   on the API's `input_tokens` is the *uncached remainder* and charging for that alone would
   under-report the bill. **Measured** by re-recording only the model turns for $0.73: 53% of the
   loop's prompt tokens came from cache, **26% saved** ($0.3994 → $0.2950), 16% on the shorter demo,
   and 0% on the task where the loop gave up after one call. Re-recording also moved the loop's
   completion 75% → 62% with no code change — eight tasks is a small sample (ADR-0007).
15. **Grounding the report in the posting (this milestone).** ✅ The guardrail checked the letter
   against the report and **nothing checked the report against the posting** — the hole an earlier
   recording fell straight into (ten requirements lifted from the candidate's CV on a page the loop
   could not read, every citation valid). `guardrail.requirement_grounding` scores what a report rates
   against the postings `fetch_job_posting` actually returned — captured on the tool instance
   (`FetchJobPosting.postings`, the `SubmitReport.submitted` idiom), carried as the **required**
   `Assessment.source_postings` so it is never the report's own account of itself and never silently
   unwired, matched against *every* fetch because the loop retries, and published as **Report grounded**. A report
   rating requirements with **no** posting behind it scores 0.0, not `n/a`: that case *is* the
   measurement (ADR-0008). Cost **$0** — a pure function of recorded assessments, tool schemas and
   prompts untouched, so both tables re-scored offline (0 recorded). **It reads 1.00 everywhere:** the
   fabricating run is no longer in the cassette (the caching re-record replaced it with a refusal), so
   the column is a control that fired nowhere, and the README says so. Surfaced the underlying cause,
   deliberately unfixed here: an unreadable page still yields *some* text, so the tool returns a valid
   `JobPosting` with **zero requirements** instead of an error — fixing that changes the conversation
   the cassette is keyed on and costs a full re-record.
16. **Evidence grounding (this milestone).** ✅ Last unchecked link of the chain: tool retrieves evidence
   → report cites it → letter cites the report. `citation_fidelity` scores only the last hop, so a
   fabricated URL that reaches the *report* becomes a valid citation target and launders itself into a
   perfect fidelity. `guardrail.evidence_grounding` scores the report's links against what
   `github_evidence` returned (`GithubEvidence.returned` → required `Assessment.source_evidence`),
   published as **Evidence grounded**. **Compared at repository level (`repo_of` → `owner/name`), never
   by URL string** — the tool returns a README's `html_url` while a report may cite the repo root, and
   treating those as two sources produced a false positive that was published and then retracted
   (ADR-0009). Reads 1.00 across the recording; cost $0. Deliberately *not* changed: per-requirement
   tightening of the letter check — measured first, and the one apparent cross-requirement citation
   turned out to be a correct multi-skill sentence, so the tightening would convict accurate writing.
17. **Review pass: one definition of "Completed" (this milestone).** ✅ A code review found the published
   table asking two different questions in one column: the agent path required a submission, the pipeline
   only required that nothing raised — so the JavaScript-only task counted as a pipeline success with
   **zero requirements, zero ratings and two sentences of boilerplate**, against its own fixture. Both
   pipeline rows move **75% → 62%**; all three rows now agree (ADR-0010). Same pass: `repo_of` parsed URLs
   by slicing on `"github.com/"`, so `#readme` / `?tab=` landed inside the repo name (a link the tools
   *did* return scoring as fabricated) while `mygithub.com/owner/name` and a redirector's
   `?to=github.com/...` scored as grounded — now `urlsplit` + case-folded host check. Also: the letter
   guardrail compares GitHub citations by repository like the metric does; the structurer seam records its
   cache split so a replay cannot re-price cached tokens at the full rate; `Cited` gained the denominator
   every other column carries; `matching.tokens` stopped shattering Polish words (`różnych` →
   `['r', 'nych']` made a one-letter needle match noise). Cost $0 — all of it re-scored from the cassette.
18. **The trifecta, confined and then measured (this milestone).** ✅ `read_cv` honours only the file
   `--cv` named; `fetch_job_posting` refuses non-public addresses **on every redirect hop** — a red proof
   found the first fix still fetched `169.254.169.254` through a client built `follow_redirects=True`,
   because httpx walked the chain internally and returned only the final response. Then `attack/`
   turned the claim into a number: 5 payloads × 4 placements × 2 extractors against `real_tools()`,
   read by a reader that obeys everything, so the result is a property of the architecture and not of
   whichever model was cheapest that day. **The two narrowed legs never succeeded; exfiltration
   succeeded on every attempt that reached the reader** — an allowlist bounds where a request goes,
   not what it carries. Third finding, from CI: **which placements reach the reader is not
   reproducible.** Same commit, two machines — under trafilatura 2.1.0 / libxml2 2.11.9 only the
   body arrives; under 2.2.0 / 2.14.6 a `display:none` div arrives too. A patch bump of a content
   extractor opened an injection placement with nothing in this project changing — the same hazard
   that once made a CI runner's trafilatura miss every cassette entry. So the approved file states only what the guards
   did with what arrived, and the reach counts are printed to the log with the trafilatura and
   libxml2 that produced them. Freezing them would defend nothing and redden the build on a
   dependency bump. Cost $0: no key, no network, no cassette.

19. **The retriever, finally scored (this milestone).** ✅ Every link of the RAG chain had a column in
   the published table except the first: `evidence_grounding` scores the report *against what the
   retriever returned*, so a miss by `find_evidence` is invisible to the harness. The corpus and the
   queries were already in the cassette, so `retrieval/` scores it offline for $0 against committed
   relevance judgments (ADR-0011). **It corrects the README in both directions**: of the published
   63 misses, **44 are the tool behaving correctly** — a degree, a tenure, a language, or a skill the
   portfolio genuinely lacks — so 87 % overstated the defect; and the recoverable misses are **19**,
   not the 48 claimed, which overstated the remedy. The real number is **8 of 27**. **It also
   corrects `0005` § 3.1**, which named the unwired `matching.mentions` as a defect implying a fix:
   it scores *identically* to the substring, because it needs the query's tokens consecutively. BM25
   finds all 27 and returns noise for 33 of 45. **The defect is the absence of ranking, not the
   matcher** — which is why MRR and nDCG read `n/a` for the shipped retriever rather than a number.
   `find_evidence` is deliberately untouched: its output is hashed into every cassette key.

## What not to do

- Do not add a dependency on LangChain or any agent framework (ADR 0001).
- Do not let a tool raise into the loop — return a structured error instead.
- Do not turn a budget breach into an exception — it is a controlled stop.
- Do not embed a real CV, a real API key, or PolEmo-style dataset text in the repo.

The confinement is measured, not asserted: `python -m apply_scout.attack` runs every payload in
every placement against a reader that obeys everything, and CI diffs the table against
`eval/expected/attack.md`. The narrowed legs hold; the outbound leg does not, and neither does
extraction. Read the README's **Limitations** for the numbers and what they still cannot see.

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

This project has a knowledge graph. Reach for the code-review-graph MCP
tools ahead of Grep/Glob/Read when the question is **structural** — what
calls this, what breaks if it changes, what covers it — because the graph
answers those in one call, with callers, dependents and test coverage
attached, for fewer tokens than reading the files.

### Where the graph answers better

- **Exploring code**: `semantic_search_nodes_tool` or `query_graph_tool` instead of Grep
- **Understanding impact**: `get_impact_radius_tool` instead of manually tracing imports
- **Code review**: `detect_changes_tool` + `get_review_context_tool` instead of reading entire files
- **Finding relationships**: `query_graph_tool` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview_tool` + `list_communities_tool`

Grep, Glob and Read stay the right tools when the question is about text rather
than structure, and when the graph has no answer for it.

### Key Tools

| Tool | Use when |
| ------ | ---------- |
| `detect_changes_tool` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context_tool` | Need source snippets for review — token-efficient |
| `get_impact_radius_tool` | Understanding blast radius of a change |
| `get_affected_flows_tool` | Finding which execution paths are impacted |
| `query_graph_tool` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes_tool` | Finding functions/classes by name or keyword |
| `get_architecture_overview_tool` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. No hooks installed — run `code-review-graph update` after code changes.
2. Use `detect_changes_tool` for code review.
3. Use `get_affected_flows_tool` to understand impact.
4. Use `query_graph_tool` pattern="tests_for" to check coverage.
