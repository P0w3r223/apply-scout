# ADR 0005 — Requirement coverage, not requirement F1

Date: 2026-08-21
Status: accepted
Author: P0w3r223
Related to: [ADR 0004](0004_record_replay_cassettes.md) — the cassette is what made re-scoring free

---

## Context

The harness scored extraction with an F1 between two sets: the requirement texts the agent
pulled out of a posting, and the `expected_requirements` a human annotated in
`eval/tasks.json`. Matching was exact after case-folding. The published table read **0.33
for the cheap model and 0.23 for the strong one**, and the README carried a footnote asking
readers to treat it as "a strict lower bound".

A footnote apologising for a metric is a sign the metric is wrong. Two defects, and only the
second one is fatal:

**The matcher was too literal.** An annotation says `PyTorch`; the posting says "experience
with PyTorch or TensorFlow in production". Those are the same finding, and scoring them as a
miss measures the annotation's phrasing rather than the extraction.

**The annotation cannot support a precision denominator.** `expected_requirements` is the
list of skills a human judged load-bearing — five to ten per posting, and
`eval/tasks.example.json` documents it that way. A posting has two dozen requirements. Every
correctly extracted requirement the annotator did not list counts as a false positive, so
extracting the posting *more* thoroughly lowers the score.

That is not a lower bound; it is a ceiling that moves with annotation length. Computed
against the recorded runs:

| task | annotated | extracted | best F1 reachable |
|---|---:|---:|---:|
| jeeves-senior-ai-engineer | 9 | 19 | 0.64 |
| reddit-senior-ml-engineer-ads | 10 | 1 | 0.18 |
| konux-senior-data-scientist | 10 | 21 | 0.65 |
| allegro-junior-data-scientist-pl | 10 | 12 | 0.91 |
| allegro-data-scientist-allegro-pay-pl | 10 | 19 | 0.69 |
| zapier-ai-ml-js-only-edge | 0 | 0 | 1.00 |

**Mean ceiling: 0.68.** A flawless extraction could not have scored above it, and most of the
gap between 0.68 and the reported 0.33 was the metric, not the model.

## Decision — report recall over the annotated skills, and nothing else

`requirement_coverage` = the fraction of annotated skills that appear somewhere in the
extracted requirements. Matching is containment over normalised word tokens: the annotated
phrase must appear as consecutive tokens, so `vector databases` does not match a requirement
that merely contains both words far apart, and `R` does not match "Rust". A trailing plural
`s` is folded so `embeddings` matches "embedding models". Nothing more — a metric that cannot
be re-derived by hand is worse than a blunt one.

Precision is **not reported**, because no honest denominator exists for it here. This is a
deliberate narrowing: the harness now answers "did it find what a human said mattered?" and
stays silent on "did it find only that", which the task set was never annotated to answer.

The published numbers move from 0.33 / 0.23 to **0.80 / 0.68**. The ordering is unchanged —
the cheap model still extracts better than the strong one — so the README's split-decision
conclusion survives re-scoring rather than depending on the old metric.

## Amendment (same day) — a metric must be allowed to say "not applicable"

The first version of this change kept a habit from the old one: returning `1.0` when there was
nothing to score. A code review caught what that did. `zapier-ai-ml-js-only-edge` has an empty
annotation by design — it is the JavaScript-only page — so it scored a perfect 1.00 on a posting
that was never read, and as 1 of 6 completed tasks it lifted every published mean by a sixth of
a point for having nothing to be right about. Removing it: **0.80 → 0.76** and **0.68 → 0.62**.

`citation_fidelity` had the identical bug and it mattered more. A letter that cites nothing has
an empty denominator, and returning `1.0` made the metric say its most flattering thing about its
worst case. Five of six Opus letters in the published run cite nothing at all — so the README's
"the strong model wins on the letter" rested on it promising nothing checkable.

Both now return `None`, are excluded from the mean, and print as `n/a`. The table also carries the
count of tasks each mean is over, and a new **citation rate** (cited / written sentences) — the
denominator fidelity throws away. A model that avoids citations cannot be caught fabricating them,
so fidelity alone rewards writing vaguely.

The rule this leaves behind: **a metric with no data must return nothing, not its best score.**

## Consequences

- **Re-scoring cost nothing.** The metric is a pure function of a recorded `Assessment`, so
  replaying the committed cassette recomputed the whole table offline, for $0. Had this been
  a change to what we *ask* the model, it would have meant a paid re-record — the asymmetry is
  worth noticing when choosing what to fix.
- **Thorough extraction is no longer punished.** A run that reports twenty real requirements
  beyond the annotation now scores the same as one that reports only the annotated skills.
  A test pins that property, because it is the whole reason for the change.
- **A real failure is now legible.** The Reddit posting yields a single extracted requirement
  and scores 0.00. Under the old metric it was a 0.18-ceiling task whose low score was
  indistinguishable from the denominator artefact affecting every other row.
- **Precision remains unmeasured.** Answering "does it invent requirements?" needs an
  exhaustive annotation of at least a few postings, which is new annotation work and a
  separate decision. Citation fidelity already bounds fabrication on the letter, which is
  where invented claims actually reach the reader.
- **Coverage is gameable in a way F1 was not.** An extractor that emitted the entire posting
  as one requirement per sentence would score well. That is worth stating plainly; it is
  bounded in practice by the contract (`JobPosting.requirements` is structured output, not
  free text) and would be caught by the precision metric that this task set cannot support.
