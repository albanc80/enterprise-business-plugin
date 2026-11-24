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

## Current status

| | |
|---|---|
| Cases | 66, generated from the registry |
| Grader self-check | 100% (feeding the expected values passes) |
| Client answers recorded | **7 of 66** — a first sample, 7/7 correct |
| Full-suite score | **not yet measured** |

The accuracy claim is now **measurable and partly measured**. The 7-case sample covered
every question kind (two autonomy, one each of owner, verbatim quote, allowlist, refusal,
unknown id) and was answered by Claude through the plugin's own MCP tools: 7 correct, 0
wrong, 0 missing. That is evidence the loop works end to end — a client, the tools, the
contract, the grader — not evidence that 93 contracts are accurate.

Running the sample also found a defect **in this harness**: the refusal case demanded
`rule: "autonomy_ceiling"` exactly, and failed a correct answer that named the rule and
then explained it. Rule and error fields now match on containment (`rule_contains`) while
quoted text still demands an exact match. An evaluation that fails correct answers teaches
you nothing, which is what the first real run was for.

## Keeping it honest

`tests/test_eval_harness.py` fails if `cases.json` drifts from the registry, if the grader
stops passing its own answers, or if a paraphrased acceptance criterion sneaks through. CI
runs both.
