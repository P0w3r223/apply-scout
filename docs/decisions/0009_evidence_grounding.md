# ADR 0009 — Ground the report's evidence in what the tools retrieved

Date: 2026-08-21
Status: accepted
Author: P0w3r223
Related to: [ADR 0008](0008_grounding_the_report.md) — the same check one level up;
[ADR 0003](0003_structured_outputs_and_guardrail.md) — the letter check this completes

---

## Context

The chain is: a tool retrieves evidence → the report cites it → the letter cites the report.
Two of those three links were checked. `guardrail_letter` verifies the letter against the
report, and [ADR 0008](0008_grounding_the_report.md) added the report's *requirements* against
the fetched posting. Nothing verified the report's *evidence* against what `github_evidence`
actually returned.

That gap has a specific shape: because `citation_fidelity` scores the letter against the
report, **a link that reaches the report becomes a valid citation target**. A fabricated URL
in the report is laundered into a perfectly grounded letter. And the report is a deliverable in
its own right — `apply-scout run` prints it for a human to click.

## Decision

Add `guardrail.evidence_grounding(report, retrieved)`: of the links a report cites, the
fraction pointing at a repository the tools returned during this run. Published as an
**Evidence grounded** column beside the others. The evidence is captured on a
`GithubEvidence.returned` instance attribute, the same idiom as `FetchJobPosting.postings` and
`SubmitReport.submitted`, and carried as the **required** `Assessment.source_evidence`.

**Compared at repository level, not by URL string.** This is the decision, and it was learned
the hard way. Investigating the gap by hand produced what looked like a real catch: the loop's
`konux` report citing `https://github.com/P0w3r223/P0w3r223`, a string absent from the GitHub
seam of the cassette. It was published as a finding, and it was wrong. The repository *is* in
the recorded responses; `github_evidence` returns a README's `html_url`
(`…/owner/name/blob/main/README.md`) while the report cited the repository root
(`…/owner/name`). Two spellings, one source. A string comparison would have shipped that false
positive as a metric, accusing every run whose model links a repo instead of its README. So
`repo_of` reduces a link to the `owner/name` it points at, and a citation is grounded when that
repository is one the tools produced. A test pins both spellings.

**`None` when the report cites nothing; 0.0 when it cites while the tools returned nothing.**
The same asymmetry as ADR 0008, for the same reason: a report that honestly rates everything
`none` has no citation to check and must not be scored, while a report citing links against an
empty retrieval is the fabrication case itself.

**Measures; removes nothing.** As with ADR 0008, enforcement waits until the number has been
read on real runs.

## Consequences

**Cost: $0** — a pure function of a recorded assessment. Both tables re-scored from the
committed cassette with 0 recorded, and no prompt, tool schema or message changed.

**It reads 1.00 everywhere, and this time that is a result rather than a shrug.** Every cited
link in the recording traces to a repository the tools retrieved: 3 scored tasks for
pipeline-Haiku, 1 for pipeline-Opus, 4 for the loop. The bracketed counts are small because
most reports cite nothing at all — which is what the `Cited` column has been saying.

**It bounds provenance, not relevance.** A link can point at a retrieved repository and still
be poor support for the specific claim. Which leads to the one change deliberately *not* made:

## Alternative considered and rejected: tighten the letter check per requirement

`valid_evidence_urls` pools every URL in the report, so a sentence can cite evidence gathered
for a different requirement — "I have Kubernetes experience [link found for Python]" — and pass.
The obvious tightening is to require a sentence's citations to belong to the requirements the
sentence names.

**Measured before implementing, and the measurement rejected it.** Across the recording exactly
one sentence looked like a cross-requirement citation, and reading it showed the check would
have been wrong: *"The candidate demonstrates proficiency with multiple programming languages
including C++, SQL, and Bash in addition to Python"*, citing both the repo found for "additional
programming language" and the one found for SQL. A sentence that names several skills correctly
cites several requirements' evidence. Tightening this way would convict accurate, specific
sentences and push the model toward writing one thin claim per sentence — the opposite of what
the citation columns exist to encourage. The pooling stays, and the limitation is documented
rather than "fixed" into a worse metric.
