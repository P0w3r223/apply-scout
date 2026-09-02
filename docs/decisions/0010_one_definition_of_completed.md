# ADR 0010 — One definition of "Completed" for both runners

Date: 2026-08-21
Status: accepted
Author: P0w3r223
Related to: [ADR 0006](0006_scoring_the_agent_loop.md) — where the second runner arrived;
[ADR 0005](0005_requirement_coverage_not_f1.md) — the same class of mistake in a different metric

---

## Context

The published table has one **Completed** column and, until this change, two different
questions behind it.

- The **agent** row required a deliverable: `agent_assess_fn` scores a task only when
  `submit.submitted is not None`, because the loop can talk instead of submitting.
- The **pipeline** rows required only that nothing raised: `pipeline_assess_fn` returned
  `None` on `PipelineError` and nothing else.

On the JavaScript-only posting the pipeline therefore produced, and counted as a success:

```
posting title: Job Posting | posting reqs: 0
report assessments: 0
letter sentences: 2 removed: 0
   "I am writing to express my interest in the position at Zapier."
   "I look forward to the opportunity to discuss how I can contribute to your team."
```

Zero requirements, zero ratings, two sentences of boilerplate. The task's own fixture says
what should have happened — `eval/tasks.json`: *"expected to fail extraction and score as
not-completed"* — and the agent runner did exactly that with the same inputs.

No other column could catch it. Coverage, both grounding columns and fidelity all return
`n/a` for that task precisely because there is nothing there to score, so the empty run fed
only the one number it inflated: **75% where 62% is honest**, on both pipeline rows.

## Decision

`pipeline_assess_fn` treats a report that rates nothing as no deliverable, exactly as the
agent path treats a missing submission. The check lives in the runner-specific function, not
in `run_evaluation`, because "what counts as a deliverable" is knowledge about how that runner
finishes — the harness stays generic.

Rejected alternative: raise `PipelineError` inside `assess()` when the posting has no
requirements. That would make an honest empty result an *exception*, and this project's
standing rule is the opposite — an empty result is a finding, not a crash. The pipeline should
still be able to return "I read the page and there was nothing in it"; it is the *scoring* that
must not call that a completed assessment.

## Consequences

**Both pipeline rows move 75% → 62%, and all three rows now read 62%** — which is the point:
they are finally answering the same question. Two knock-on moves, both arithmetic rather than
behavioural, because the medians and means now run over 5 completed tasks instead of 6:

| | before | after |
|---|---|---|
| pipeline Haiku — median cost | $0.0291 | $0.0306 |
| pipeline Opus — median cost | $0.1827 | $0.1910 |
| pipeline Haiku — cited | 0.29 | 0.34 (5) |
| pipeline Opus — cited | 0.11 | 0.13 (5) |

The dropped task was the cheapest of the six ($0.0104 / $0.0930) and its letter cited nothing,
so removing it raises both the median cost and the citation rate. The loop-vs-pipeline ratio
becomes 2.4× on a like-for-like basis (1.9× as the table stands), from 2.5× / 2.0×.

**Cost: $0.** Completion is a pure function of the recorded assessment, so both tables
re-scored from the committed cassette with 0 recorded.

**`RunStatus` is not what the completion rate reads, and the documentation said it was.**
CLAUDE.md carried that rule from milestone 10. Measured against the recording, every one of the
eight agent runs — including the three that submitted nothing — reports
`RunStatus.COMPLETED`, so reading the status would publish **100% completion**. The status
answers "did the loop stop cleanly", the metric answers "did a deliverable arrive", and only the
second belongs in this column. The rule is corrected rather than the code.
