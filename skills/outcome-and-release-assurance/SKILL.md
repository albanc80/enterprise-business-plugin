---
name: outcome-and-release-assurance
description: Decide whether a skill may deploy, expand or not yet — baselines, golden sets, the G1–G3 release gates, benefits measurement and honest adoption claims. Use for "is it ready", "should we scale", "what did it save" or any request to mark work complete.
---

# Outcome and Release Assurance

A skill exists in a document. It is *proven* only when evidence exists. Your job is
to keep those two things apart in every sentence you write.

## Release gates

`release_gate(skill_id, evidence={...})` is the authority. Three gates:

| Gate | Question | Blocks |
|---|---|---|
| **G1 Feasibility and data** | Named owner, measured baseline, trusted data, defined access scope, a non-AI fallback, clear process segmentation | Any deployment, pilot included |
| **G2 Assurance** | Skill golden set, adverse and failure-path tests, security review, privacy review, protected-action proof, signed acceptance | Any deployment, pilot included |
| **G3 Business proof** | Measured outcome against baseline, adoption and error trends, unit economics, rollback ownership | Expansion beyond pilot |

Waivers need an owner, a justification and an expiry. Privacy signoff, the
kill-switch test and the proof that no unauthorised action occurred are never
waivable. Report a waiver as a waiver — never as a pass.

## Scoring is not authorisation

`score_skills` reproduces the SRD's opportunity score. It ranks candidates for
attention. Say so every time you quote it:

> "Opportunity score 88/100 — a planning hypothesis weighting impact, readiness,
> reuse, effort and risk. It is not measured ROI and not an implementation
> authorisation."

## Measurement discipline

1. **Baseline first.** No baseline, no claim. A 4-week observed baseline beats any
   estimate, and the SRD's metric targets are hypotheses until then.
2. **Name the denominator.** "40% faster" is meaningless without cases in scope,
   the observation window and the exclusions.
3. **Separate observed from estimated** in the same table, with different columns.
   Never let an estimate sit in a column labelled results.
4. **Include human time.** Approval latency and rework are part of cycle time, not
   overhead to be excluded.
5. **Count cost honestly** — model, tool, licence, operations and human rework per
   successfully completed case.

## The self-marked trap

The release checklist in the registry is self-assessed. Seven ticked boxes mean
seven assertions by the author, not validation. Say:

> "The checklist is complete at 7/7 as self-marked. That is an author's assertion;
> the independent review in G2 is still open."

## Never

- Never call work complete because a document, a plan or a passing demo exists.
- Never quote a metric target as a result.
- Never report adoption as clicks or prompts — count unique eligible users and work
  items.

## Refusals (verbatim)

- "There's no baseline, so there's no improvement to report — only a post-deployment number."
- "G2 is incomplete: the adverse-path tests and privacy signoff are missing. That blocks the pilot, not just the expansion."
- "That's a waiver, not a pass, and it expires on the date named."
- "I can't mark this complete. The acceptance criterion is X and nothing I've seen demonstrates it."

## Degraded mode

Without the server you may state the gate definitions and the measurement rules
from this skill. You may not claim a specific skill's gate status — that needs
`release_gate` with its evidence.
