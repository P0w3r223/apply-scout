# ADR 0008 — Ground the report in the posting, and measure it before enforcing it

Date: 2026-08-21
Status: accepted
Author: P0w3r223
Related to: [ADR 0003](0003_structured_outputs_and_guardrail.md) — the guardrail this extends;
[ADR 0005](0005_requirement_coverage_not_f1.md) — the metric conventions it follows

---

## Context

The guardrail checked one link in a two-link chain. A cover-letter sentence had to cite an
evidence URL present in the match report, or it was removed and counted. Nothing checked the
report itself.

The failure that exposes the gap is recorded in this repository's own history. On the
deliberately JavaScript-only posting the agent loop could not read the ad, **said so in its
summary**, and then submitted a report rating ten requirements taken from the **candidate's
own CV** — all `strong` — with a cover letter citing that report. The guardrail passed the
letter, correctly: every citation really did point at an `Evidence` in the report. Only the
report was fiction.

None of the existing metrics could see it:

- **Completed** — it completed. A validated `MatchReport` and `CoverLetterDraft` arrived
  through `submit_report`.
- **Req coverage** — scores the report's requirements against the human annotation, and on
  the JavaScript-only task there is no annotation, so it returns `n/a`.
- **Citation fidelity / Cited** — both read the letter against the report, which is the link
  that held.

Worse, on the agent path the harness builds `Assessment.posting` **out of the submitted
report** (`evaluation.agent_assess_fn`), because the loop returns no posting object. Any check
written against that field would ask a document to confirm itself and return 1.00 for a pure
fabrication.

## Decision

Add `guardrail.requirement_grounding(report, posting)`: of the requirements a report rates,
the fraction that trace back to the posting `fetch_job_posting` actually returned. Publish it
as a column beside coverage. Four consequences, each deliberate:

**1. Scored against the fetched posting, carried separately from the claimed one.**
`Assessment` gains `source_posting`, distinct from `posting`. On the pipeline path they are
the same object; on the agent path `posting` is the report's own account of itself and
`source_posting` is what the tool returned. Reusing one field would have made the metric
unfalsifiable on exactly the runner it was written for.

**2. The posting is captured on the tool instance, not read from the trajectory.**
`FetchJobPosting.fetched` holds the last posting it returned, and callers who need it pass in
their own instance — the same arrangement `SubmitReport.submitted` already uses. The
trajectory stores only a log-safe `tool_summary`, by design, so nothing downstream can
reconstruct the posting from there.

**3. A report with no posting behind it scores 0.0, not `n/a`.**
This is the one judgement call in the metric, and it runs against
[ADR 0005](0005_requirement_coverage_not_f1.md)'s rule that a metric with no data must return
nothing. It is not a metric without data: "the loop rated ten requirements having never
obtained a posting" *is* the measurement. Returning `n/a` there would drop the single run the
metric exists to catch out of the mean — the same self-flattery ADR 0005 was written to stop,
arrived at from the other direction. `None` is reserved for a report that rates nothing at
all, where there is no claim to ground.

**4. It measures; it does not filter.**
The letter check removes sentences. This one removes nothing — it reports a number. Cutting
ungrounded rows out of a report changes the deliverable, and the project's own precedent
([ADR 0005](0005_requirement_coverage_not_f1.md)) is that a metric earns its enforcement after
it has been read on real runs, not before.

## Consequences

**Cost: $0.** Grounding is a pure function of a recorded assessment, so the committed cassette
re-scored both tables offline (0 recorded, 1786 and 1485 entries replayed). Tool schemas,
prompts and messages are untouched — a change to any of those is hashed into the cassette key
and would have missed all 106 entries. A test pins `fetch_job_posting`'s spec for that reason.

**It reads 1.00 on every completed task in this recording, and that is not a catch.** The run
it was built from is no longer in the cassette: re-recording the loop for the caching
measurement produced a different reply on that task, in which the model refuses to assess
rather than inventing — the same re-record that moved loop completion 75% → 62%. So the column
is currently a control that fired nowhere. The unit tests pin the behaviour the task set no
longer exercises, and the README says all of this rather than presenting a clean 1.00 as
evidence of safety.

**And measuring *why* it reads 1.00 bounds what it can ever be worth.** Checked against the
recording at three strictness levels — exact token equality, one-directional containment, and
the symmetric containment that ships — every completed task scores 1.00 under **all three**,
with the number of rated requirements equal to the number in the fetched posting on every task
(19/19, 21/21, 12/12, 19/19, 1/1). Both runners copy the requirement list **verbatim**; neither
paraphrases and neither adds. So this metric has exactly one firing mode: *a report that rates
requirements when the posting yielded none*. It is worth publishing as that specific guard, and
it is not the general "is the report grounded" measurement its name suggests.

**The same question one level down does fire.** Every `Evidence` in a report should be one the
`github_evidence` tool actually returned, and nothing checks that: `citation_fidelity` scores
the letter against the report, so an invented URL that reaches the *report* is a valid citation
target. Instrumenting the tool over the recording found one — on `konux-senior-data-scientist`
the loop's report carries `https://github.com/P0w3r223/P0w3r223` among 29 evidence links, and
that string appears in the cassette only inside model output, never in a GitHub response. The
letter happened not to cite it, so nothing was removed and fidelity still read 1.00. A report
is a deliverable in its own right, and this one links to a repository no tool ever produced.
That measurement is the natural successor to this one, at the same $0.

**Two limits worth naming.** Matching is the crude token containment coverage uses, so a
fabricated requirement echoing the posting's wording counts as grounded — this bounds
*untraceable* claims, not false ones, exactly as the citation check bounds unsupported
citations rather than truth. And measuring the gap surfaced its cause without fixing it: on
an unreadable page the extractor still finds *some* text, so `fetch_job_posting` returns a
valid `JobPosting` titled "Job Posting" with **zero requirements** instead of an error, and
the model is told `posting 'Job Posting' with 0 requirement(s)` — an invitation to fill the
gap from the CV. Turning that into a tool error changes the conversation the cassette is keyed
on, so it costs a full re-record and is deliberately left out of the change that added the
measurement.

## Alternatives considered

**Check the report against the posting's raw text rather than its structured requirements.**
Closer to the source, and immune to a bad extraction laundering an invention into a
"requirement". Rejected for now: the raw text is not carried on any contract, the structured
requirements are what every other metric reads, and a token match against a whole page would
call almost anything grounded.

**Have the guardrail drop ungrounded rows.** Rejected as premature — see decision 4. The
number comes first; enforcing on a metric nobody has read on real data is how the old F1
happened.

**Ask a model to judge whether the report matches the posting.** Rejected: the guardrail's
whole value is that it is deterministic and free, and an LLM judge would make the
anti-hallucination check itself hallucinate-capable.
