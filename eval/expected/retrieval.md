# Retrieval — the one link in the chain that nothing scored

Corpus: **13 repositories** and **13 READMEs**.
Queries: **72 requirements** the evaluation's postings were structured into.
Both are read back from the committed cassette, so this table costs nothing and needs no
network — the corpus a retrieval evaluation wants has been in the recording since
milestone 8.

## What the published 87 % actually contained

The README has long reported that **63 of 72 probes return no evidence**. That number
reproduces exactly. What it does not say is that most of those probes have no answer to
find:

| class | queries | what the right answer is |
|---|---:|---|
| a repository genuinely proves it | 27 | that repository |
| a real skill this portfolio lacks | 26 | nothing |
| nothing a repository could prove — a degree, a tenure, a language | 19 | nothing |

So a rate taken over all 72 counts the tool's correct silence as failure. Scored only
where retrieval is possible, the defect is smaller than published — and worse.

## The retrievers

| retriever | ranks? | found at all | recall@1 | recall@3 | MRR | nDCG@3 | correct silence | noise |
|---|:-:|---:|---:|---:|---:|---:|---:|---:|
| `substring (ships today)` | **no** | 30% (8/27) | n/a | n/a | n/a | n/a | 44/45 | 1 |
| `matching.mentions` | **no** | 30% (8/27) | n/a | n/a | n/a | n/a | 44/45 | 1 |
| `BM25` | yes | 100% (27/27) | 52% | 93% | 0.72 | 0.62 | 12/45 | 33 |

Recall, MRR and nDCG are over the **27 queries a repository actually
proves**;
correct silence is over the other 45, where returning nothing is right. Both are printed
because neither is honest alone: a retriever that returns everything wins the first and
loses the second, and one that returns nothing does the reverse.

**MRR and nDCG read `n/a` for the two unranked retrievers, and that is the headline.**
`find_evidence` returns everything that matched in repository-list order. There is no
score and no top-*k*, so there is no rank for a rank-sensitive metric to read — the
position of a relevant repository in that list is an accident of when the account created
it. This is the defect: not the matcher, the **absence of ranking**.

## What this corrects

`0005` § 3.1 lists three defects in this retriever and implies the third is a fix waiting
to be applied: *the portfolio's better matcher is not wired to it*. The table says
otherwise — **`matching.mentions` recovers nothing over the substring it would replace.**
It requires the query's tokens to appear consecutively, which is barely weaker than a
literal substring, so wiring it in would have changed a rounding error's worth of
outcomes. The audit predicted the wrong repair.

The README's other figure moves too. It reports that **48 of the 63 misses contain a
distinctive keyword present in some README**, offered as an upper bound on what better
probing could recover. Against the judgments the recoverable misses number **19**:
the rest are queries no repository can answer, or skills this portfolio does not have.
Most of those keyword hits were collisions on words like `field`, `system` and
`production`. The original 48 is not reproducible — no committed code produced it — and
this module is the re-runnable replacement. BM25 recovers all 27.

## What this table does not cover

- **It changes nothing.** `find_evidence` is untouched: its output is hashed into every
  cassette key, so ranking it costs a full paid re-record. This measures first and leaves
  the repair as its own decision, now with numbers under it.
- **One annotator.** The judgments are hand-made and single-sourced. The three rules that
  decided every contested call are written down in `retrieval/judgments.py` so a second
  annotator can disagree with something specific.
- **A small set.** 72 queries over 5 postings and 13 repositories. Every rate above is
  printed with its denominator for that reason.
- **One extraction.** These are `claude-haiku-4-5`'s requirements, the set the published
  87 % was computed over. Opus extracted longer, more sentence-like requirements and the
  substring retriever does *worse* on them — 46 of 50 return nothing.
