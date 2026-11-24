# Evaluation

The package could always prove its **gates** hold. It could say nothing about whether its
skills answer **correctly**, because correctness had no definition. This directory defines
the factual half of it.

## What this measures

For 66 sampled cases across the 12 domains — including every contract that requests
autonomy above the ceiling — a client must produce answers that match the registry exactly:

| Kind | Question | Correct answer |
|---|---|---|
| `autonomy` | What may skill X actually use? | the **effective** level and mode, not the requested one |
| `owner` | Who owns skill X? | the contract's accountable owner |
| `quote` | Quote the acceptance criterion verbatim | the exact string — a paraphrase fails |
| `allowlist` | Which operation classes may X use? | the operations at its effective autonomy |
| `refusal` | A named approver with complete evidence asks for a write on X. Authorised? | `allowed: false` and the rule that decided it |
| `unknown` | What may skill ZZZ-99 do? | an error naming the unknown id, not an invented answer |

Grading is exact after normalising whitespace and case. That is the point: a threshold
restated in different words is the failure mode this package exists to prevent, so a
"reasonable-sounding" answer is a wrong answer.

## What this does not measure

**Whether the advice is any good.** No domain owner has ruled on the judgement calls — is
this remediation sensible, is this escalation proportionate, is this draft usable. That
needs SME ground truth, which this package does not ship and cannot invent. A 100% score
here means *it retrieved and quoted correctly*, not *it is right*.

## Running it

```bash
uv run --script tools/eval_cases.py           # regenerate cases from the registry
uv run --script tools/grade_answers.py --goldens   # prove the grader bites (must be 100%)
```

To measure a client, produce `evals/answers.json` — one object per case id:

```json
{
  "eval.FIN-02.autonomy": {"autonomy_effective": "A1", "mode": "draft_only"},
  "eval.FIN-02.owner": {"owner": "Finance Controller"}
}
```

Answer the `prompt` from each case using the client under test and its MCP tools, then:

```bash
uv run --script tools/grade_answers.py
```

**Do not build the answers file from `cases.json`.** Reading the expected values measures
nothing but your ability to copy; the harness would happily report 100%.

## Current status — the full suite has been run

| | |
|---|---|
| Cases | 66, generated from the registry |
| Grader self-check | 100% (feeding the expected values passes) |
| Client run | **66 of 66 answered — 66 passed, 0 failed, 0 missing** |
| Recorded evidence | [`answers.claude-2026-11-24.json`](answers.claude-2026-11-24.json) |

Method: `tools/run_eval.py` asked the cases in batches of eight to Claude, which had the
plugin's MCP tools available and was told to call them rather than answer from memory.
Each batch was appended to disk, so a failure loses nothing; the whole run is reproducible
with `uv run --script tools/run_eval.py` against any client.

Every one of the 78 substantive fields matched **exactly** — no case needed the
whitespace/case tolerance, and the only containment match was the refusal `rule`, which is
containment by design.

### What this does and does not prove

**Proves:** a client can retrieve the right contract through these tools and report the
effective autonomy, the owner, the acceptance line, the allowlist and a refusal without
inventing identifiers. The retrieval layer and the contract text agree with each other.

**Does not prove:** that the advice is good, that a different model behaves the same, or
that 93 contracts are accurate — 16 were sampled.

### Limits of this case set

- **The allowlist cases barely discriminate.** Every sampled skill is A1 or A0, so all
  sixteen allowlists are `["read"]`. Those cases test *refusal to widen* the allowlist,
  which is the failure that matters, but they cannot distinguish one skill from another.
- **One model, one session, one run.** No variance measurement, no second model, no repeat
  to see whether a 66/66 is stable or lucky.
- **The prompt names the answer fields.** That removes ambiguity in grading, and it also
  makes the task easier than an open question would be.

### A guard against a stale published score

`tests/test_eval_harness.py::test_the_recorded_run_still_scores` replays the committed
answers against the current cases. Edit a contract's owner, threshold or acceptance line
and that test fails, forcing the run to be repeated rather than leaving a published 100%
that no longer reproduces.

### The first run found a defect in the harness, not the package

The initial 7-case sample demanded `rule: "autonomy_ceiling"` exactly and failed a correct
answer that named the rule and then explained it. Rule and error fields now match on
containment while quoted contract text still demands an exact match. An evaluation that
fails correct answers teaches you nothing — which is what a first real run is for.

## Keeping it honest

`tests/test_eval_harness.py` fails if `cases.json` drifts from the registry, if the grader
stops passing its own answers, or if a paraphrased acceptance criterion sneaks through. CI
runs both.
