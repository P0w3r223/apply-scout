# What each metric means (and why)

- **Completed** — did the run produce a report + letter without a fatal error. Catches brittleness on
  edge-case postings.
- **Req coverage** — the fraction of the human-annotated skills that appear somewhere in the extracted
  requirements, over the tasks that *have* an annotation (the bracketed count). Measures how well the
  posting was actually understood, not just fetched. It is recall and nothing else, on purpose: the
  annotation lists the five to ten skills a human judged load-bearing, never all two dozen requirements
  in the posting, so there is no denominator that would make precision mean anything — see
  [ADR-0005](docs/decisions/0005_requirement_coverage_not_f1.md). This column previously reported an
  exact-match F1 (0.33 / 0.23); on this task set a *flawless* extraction could not have scored above
  0.68 under that metric, because every correctly extracted requirement the annotator had not listed
  counted against it.
- **Report grounded** — of the requirements a report rates, the fraction that trace back to the posting
  that was actually fetched. Checked deterministically, against the posting object `fetch_job_posting`
  returned — never against the report's own list, which would ask a document to confirm itself. It
  closes the hole the citation columns cannot see: a letter can cite its report perfectly while the
  *report* was invented, which is what an earlier recording of the JavaScript-only task did (ten
  requirements lifted from the candidate's own CV, every citation valid). **A report that rates
  requirements with no posting behind it scores 0.00, not `n/a`** — calling the fabrication case
  "not applicable" would drop the one run the metric exists for. It reads 1.00 everywhere in this
  recording; see the limitations for what that does and does not prove.
- **Evidence grounded** — of the links the *report* cites, the fraction pointing at a repository
  `github_evidence` actually returned during that run. This is the link the citation columns cannot
  see: they score the letter against the report, so a fabricated URL that reaches the report becomes a
  valid citation target and launders itself into a perfect fidelity. Compared at repository level
  (`owner/name`), not by URL string — the tool returns a README's link while a report may cite the
  repository root, and calling those two sources produced a false positive the first time this was
  measured by hand ([ADR-0009](docs/decisions/0009_evidence_grounding.md)). Reads 1.00 across the
  recording: every cited link traces to a repository the tools retrieved.
- **Citation fidelity** — of the letter's sentences that cite evidence, the fraction whose citation is
  a real link from the report. The anti-hallucination guardrail computes this deterministically; a low
  number means the model was inventing citations. **Never read it without the next column**: a letter
  that cites nothing scores no fidelity at all (`n/a`), and one that cites once and gets it right scores
  1.00 — the same as one that cites forty times and gets them all right.
- **Cited** — of everything the letter wrote, the fraction of sentences that cite anything. This is the
  denominator fidelity throws away. Opus's pipeline letters sit at **0.13**: they make claims and back
  almost none of them, which is how they reach a 1.00 fidelity over a single task. The loop sits at
  **0.45**.
- **Median LLM calls / cost** — the price of a task, per model. This is the "cheaper model enough?"
  question made quantitative.
