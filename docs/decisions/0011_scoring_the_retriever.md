# ADR-0011: Score the retriever, and score it only where retrieval is possible

Date: 2026-09-03
Status: accepted
Author: Piotr Cząstkiewicz + Claude
Related to: [ADR-0005](0005_requirement_coverage_not_f1.md), [ADR-0009](0009_evidence_grounding.md)

---

## Context

This project is a retrieval-augmented pipeline. A posting is fetched and structured into
requirements; `github_evidence.find_evidence` retrieves repositories that prove them; `synthesis`
writes a report and a letter citing what was retrieved; `guardrail` checks the citations back
against it.

Every link in that chain has a column in the published table and a test that can redden — except
the first one. `evidence_grounding` scores the report *against what the retriever returned*, which
makes the retrieval the ground truth: **if `find_evidence` misses the repository that proves a
requirement, nothing in the harness notices.** The report cannot cite what it was never given, and
a report citing nothing scores `n/a` rather than zero.

The README has named this since milestone 3, as limitation #3 of 18, and measured it: *63 of 72
probes (87 %) return no evidence, and 48 of those 63 contain a distinctive keyword that is present
in one of the READMEs.* That measurement lived in prose. It was in no metric, no table, no test and
no CI check, while five other properties were scored to three decimal places.

## Decision

**Score the retriever offline, against hand-written relevance judgments, and change nothing about
`find_evidence` in the same step.**

The corpus (13 repositories and their READMEs) and the queries (72 requirements) have been in the
committed cassette since milestone 8, so the evaluation costs nothing and needs no network. The
ground truth is a new committed artifact, `eval/retrieval/judgments.json`.

`find_evidence` is deliberately untouched. Its output is hashed into every cassette key, so giving
it a ranking invalidates the recording and costs a full paid re-record — and re-recording has
moved published numbers before with no code change (completion 75 % → 62 %). Measuring first
separates *what is wrong* from *what changing it costs*, and leaves the repair as its own decision
with numbers under it.

### Queries are scored in three classes, not one

This is the load-bearing part. **Most of this query set has no correct answer to retrieve.**

| class | queries | correct behaviour |
|---|---:|---|
| a repository genuinely proves it | 27 | return that repository |
| a real skill this portfolio lacks | 26 | return nothing |
| nothing a repository could prove — a degree, a tenure, a language | 19 | return nothing |

Recall, MRR and nDCG are computed over the first class only; the other two are reported as
*correct silence*. Both are printed, because neither is honest alone — a retriever that returns
everything wins recall and destroys silence, and one that returns nothing does the reverse.

This is ADR-0005's rule applied to a new metric: a rate with no data reports `n/a`, never its best
value, and every mean carries the count it was taken over.

### Rank-sensitive metrics are `n/a` for retrievers that do not rank

`find_evidence` returns everything that matched in repository-list order. A `recall@1` computed
over that would report *when the account created its repositories*, not retrieval quality. So the
unranked retrievers get an unrestricted "found at all" and `n/a` everywhere a rank is required.

## Consequences

**The published 87 % overstated the defect, and the 48-of-63 overstated the remedy.** Of the 63
misses, 44 are the tool behaving correctly. The recoverable misses number **19**, not 48 — most of
those keyword hits were collisions on words like `field`, `system` and `production`. The original
48 is not reproducible: no committed code produced it. This module is the re-runnable replacement.

**The real defect is smaller and worse.** Scored where retrieval is possible, the shipped retriever
finds a relevant repository for **8 of 27** queries.

**The audit predicted the wrong repair.** `0005` § 3.1 lists "the portfolio's better matcher is not
wired to the retriever" as one of three defects, which reads as a fix waiting to be applied. It is
not: `matching.mentions` requires the query's tokens to appear *consecutively*, which is barely
weaker than a substring, and it scores identically to the substring on every honest column. A
standard BM25 finds a relevant repository for **all 27** — and returns something for 33 of the 45
queries that should have got nothing.

So the defect is **not the matching function; it is the absence of ranking**. Loose matching finds
everything and cannot say which; that is a scoring problem, and a score is exactly what
`find_evidence` does not have.

**The judgments are one annotator's.** Single-sourced, hand-made, and the three rules that decided
every contested call are written into `retrieval/judgments.py` so a second annotator can disagree
with something specific rather than with a vibe: named in the README rather than merely used, full
coverage rather than a near neighbour, building rather than consuming.

## Alternatives considered

**A new repository for retrieval evaluation** (`0005` § 4 variant A, 12–18 days). Rejected: the
relevance judgments dominate its cost, hand-made judgments are the weakest kind of "measured" claim
in this portfolio, and it adds a thirteenth surface to maintain to close a gap that already has a
host three quarters built.

**Retrieval over `doc-extract`'s corpora** (variant C, 8–12 days). Rejected: nothing about invoice
extraction poses a retrieval question, so the query set would be built from nothing, and bolting a
second thesis onto the portfolio's sharpest one dilutes it.

**Fix and measure together.** Rejected for this step: it costs a paid re-record and confounds the
measurement with the change. Now a separate decision, informed by the numbers above.
