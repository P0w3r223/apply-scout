# Limitations

Every row is judged **only on the attempts that reached the reader**, and that qualifier is doing
real work — see the third point below. Three readings, and only the first is good news:

- **The two narrowed legs held, on every attempt that landed, under both extractors.** They read
  identically in both arms, which is the point of running both: `read_cv` and the URL policy do not
  care how the instruction arrived.
- **The outbound leg is narrowed, not closed — and it fails on everything that lands.** An allowlist
  restricts *where* a request may go, not *what* a permitted request carries. The reader composed a
  URL encoding the attacker's data in its query and sent it to a perfectly ordinary public host.
  Closing that needs the content leaving to be constrained, not just the destination.
- **Extraction is not the third guard it looks like — and it is not even stable.** Which of the four
  placements reach the reader was measured twice, on two machines, from the same commit:

  | | trafilatura 2.1.0 / libxml2 2.11.9 | trafilatura 2.2.0 / libxml2 2.14.6 (CI) |
  |---|---|---|
  | trafilatura arm | `body` | `body`, **`hidden`** |
  | stdlib fallback arm | `body`, `hidden`, `tail` | `body`, `hidden`, `tail` |

  A **patch-level bump of a content extractor opened a placement**: a `display:none` div, invisible
  to any human reading the posting, now reaches the model in the production path. Nothing in this
  project changed. Those placements were never defended, they were **unparsed** — by a readability
  heuristic, on a page the attacker wrote, in whichever version the deployment happens to have. That
  is why the approved file carries no count of them: the run prints them into the log beside the
  versions that produced them, and freezing them would turn somebody's dependency bump into a failed
  build while defending nothing.

Two things the suite still cannot see, named rather than left to be assumed:

- **The resolved address is not the address connected to.** `check_resolved` resolves the name, and
  the HTTP client resolves it again when it connects. A DNS answer that changes between the two is
  not caught — and the suite substitutes the transport, so `check_resolved` does not run in it at
  all; that half is covered by unit tests. Closing it needs the connection pinned to the address
  that was checked, which means a custom transport — deliberately out of scope here, against an
  attack that needs the attacker to run their own resolver.
- **Whether a real model obeys is not asked.** On purpose. A model that refuses is not a boundary,
  and the number would move with every re-recording while the architecture stood still.

The honest reading is now *one leg cut; two narrowed, and measured shut against a fully compromised
reader; one open and failing on everything that reaches it; one tool that holds a token and has been
neither narrowed nor measured — and a fourth thing that is not a guard at all, quietly deciding how
much reaches*.

- **JavaScript-only postings.** `fetch_job_posting` fetches static HTML with no headless browser, so a
  client-rendered page yields only its pre-hydration shell. In the eval, the deliberately JavaScript-only
  Ashby posting still *completed* on every runner — robustness to thin input rather than crashing — but
  there was almost no text to read, so anything reported for such a page is unreliable, and the agent
  loop went further and invented requirements outright (see below).

- **Extraction is only as good as the model.** Odd posting layouts can drop or merge requirements; the
  coverage metric exists precisely to quantify this rather than assume it away. The Reddit posting is
  the worked example — it yields a single extracted requirement and scores **0.00 coverage**.
- **Nothing measures over-extraction.** Coverage is recall only, so an extractor that split a posting
  into far too many requirements would still score well. The task set has no exhaustive annotation to
  support a precision metric, and inventing one from a partial annotation is what the old F1 did
  wrong ([ADR-0005](docs/decisions/0005_requirement_coverage_not_f1.md)).
- **A fabricated posting is now measured — but this recording does not contain one.** The gap was real:
  on the JavaScript-only page an earlier recording of the loop could not read the ad, said so in its
  summary, and then rated ten requirements taken from the **candidate's own CV**, all `strong`, with a
  letter citing its own invented report. The guardrail passed it, because those citations really did
  point at the report; only the report was fiction. **Report grounded** closes that blind spot by
  scoring the report against the posting `fetch_job_posting` returned. Two honest caveats: the column
  reads **1.00 on every completed task here**, so it is a control that fired nowhere rather than a catch
  — and the very run it was built from is **no longer in the cassette**, because re-recording the loop
  for the caching measurement produced a different reply, in which it refuses to assess rather than
  inventing (that is the same re-record that moved completion 75% → 62%). The unit tests pin the
  behaviour the task set no longer exercises.
- **An unreadable posting comes back as a *success*.** On the JavaScript-only page the extractor does
  find some text, so `fetch_job_posting` returns a valid `JobPosting` titled "Job Posting" with **zero
  requirements** rather than an error — and the model is told "posting 'Job Posting' with 0
  requirement(s)". That is an invitation to fill the gap from the CV, which is exactly what the earlier
  recording did. Turning it into a tool error would change the text the model reads, and every cassette
  entry is keyed on the conversation, so the fix costs a full re-record — deliberately not bundled into
  the change that added the measurement.
- **The metric bounds untraceable claims, not false ones.** Matching is the same crude token containment
  used by coverage, so a fabricated requirement that happens to echo the posting's wording counts as
  grounded. It is the report-level analogue of the citation check: it proves provenance, not truth.
- **Report grounded has exactly one firing mode, and that is now measured too.** Scored at three
  strictness levels — exact token equality, one-directional containment, and the symmetric containment
  that ships — every completed task reads 1.00 under **all three**, with the rated-requirement count
  equal to the posting's on every task (19/19, 21/21, 12/12, 19/19, 1/1). Both runners copy the
  requirement list **verbatim**: neither paraphrases, neither adds. So the column can only fall when a
  report rates requirements the posting never yielded — a real and worthwhile guard, but not the general
  "is this report grounded" check the name suggests.
- **Evidence grounding reads 1.00, and the "catch" that motivated it was a measurement error.** An
  earlier pass over this cassette reported the loop's `konux` report citing
  `https://github.com/P0w3r223/P0w3r223` as a link no tool returned. It was not: that repository *is*
  in the recorded GitHub responses, and `github_evidence` returned its README URL
  (`…/blob/main/README.md`) while the report cited the repository itself. Comparing raw URL strings
  called one source two, which is why **Evidence grounded** compares the `owner/name` a link points at
  rather than the string. Scored that way, every cited link in this recording traces to a repository the
  tools actually retrieved.
- **The guardrail checks citations, not truth.** It removes sentences citing links absent from the
  report; it does not fact-check a grounded claim's phrasing. It bounds hallucinated *citations*, not
  every possible overstatement.
- **The live task set decays.** Job ads are removed; two of these eight 404 within a month of being
  annotated. The cassette makes past results reproducible, but it cannot keep the *task set* fresh —
  extending or refreshing it means new annotation and a new paid recording.
- **A cassette is a snapshot, not a guarantee of current behaviour.** Replay proves what the models did
  on the recorded requests, not what they would do today. Re-record to make that claim.
- **A long answer can outgrow one response.** `MAX_OUTPUT_TOKENS` caps a single reply at 16000 tokens.
  A cut-off *sentence* is recoverable — the loop asks the model to continue and stitches the pieces,
  and running out of `MAX_CONTINUATIONS` ends the run `truncated`, never `completed`. A cut-off
  `submit_report` **tool call** is not: partial JSON has nothing to continue, so the run fails rather
  than delivering half a report.
- **A budget can be overshot by one call.** Ceilings are checked *before* each model call, so a single
  expensive reply can end a run above its limit. The stop is graceful and honest; it is a ceiling on
  starting work, not a hard cap on spend. The demo used to be the worked example — an earlier recording
  spent $0.5948 against the $0.50 default ceiling and stopped there — but prompt caching brought the same
  run to **$0.4368**, so the committed demo now finishes on `end_turn` without ever breaching. The
  behaviour is pinned by tests rather than by the picture.
- **Only the cheap model has been measured in the loop.** The third eval row is
  `claude-haiku-4-5`; the Opus × loop cell would cost ≈$4.7 to record and is deliberately empty
  ([ADR-0006](docs/decisions/0006_scoring_the_agent_loop.md)). Read the loop-vs-pipeline comparison as
  established for one model, not two.
- **English/Polish postings assumed.** Other languages are untested.
- **No application is ever submitted.** apply-scout drafts a report and a letter for a human to review
  and send — it does not act on the candidate's behalf.
