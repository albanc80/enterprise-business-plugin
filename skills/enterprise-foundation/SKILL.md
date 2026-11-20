---
name: enterprise-foundation
description: The twelve shared primitives every function depends on — identity and scope resolution, cited retrieval, schema-validated extraction, policy checking, work routing, approval orchestration, execution guarding, audit, evaluation, data protection, decomposition and outcome measurement. Use for questions about how the platform itself works.
---

# Enterprise Foundation

These twelve capabilities are shared plumbing. Every function skill calls them and
none may reimplement them — a second copy of an approval gate is how control
diverges from intent.

| id | capability | what you get | metric |
|---|---|---|---|
| `FND-01` | Identity & authorization resolver | Resolve requesting actor, purpose, group entitlements and minimum data/tool scopes | Unauthorized operations blocked |
| `FND-02` | Enterprise knowledge retrieval | Retrieve and cite current approved policies and procedural evidence with access trimming | Citation validity and answer usefulness |
| `FND-03` | Structured extraction & validation | Turn business documents and messages into schema-valid records without silent field invention | Field-level precision and completeness |
| `FND-04` | Policy & obligation checker | Evaluate proposed activity against versioned internal rules and escalation logic | Policy decision agreement |
| `FND-05` | Workflow classification & routing | Classify incoming work, assign owner, urgency and escalation category | Correct routing rate |
| `FND-06` | Human approval orchestration | Package decision evidence, obtain authorized approval and enforce expiry and separation of duties | Approval coverage |
| `FND-07` | Tool execution & transaction guard | Validate parameters, idempotency, write scope, limits and post-conditions at the execution boundary | Unauthorized writes and duplicate rate |
| `FND-08` | Audit, trace & provenance recorder | Persist non-repudiable event evidence for inputs, sources, model/tool versions and final state | Trace completeness |
| `FND-09` | Quality evaluator & regression runner | Run golden cases, safety adversarial tests, drift checks and release-blocking scoring | Critical test pass rate |
| `FND-10` | Sensitive data protection | Detect, minimize, redact and apply retention/deletion policies to protected information | Sensitive data leakage incidents |
| `FND-11` | Task decomposition & handoff | Break a requested outcome into bounded, verifiable steps with explicit ownership and retry rules | Handoff rework rate |
| `FND-12` | Outcome measurement & feedback | Bind each deployment to baseline, adoption, cost, error and business outcome telemetry | Realized value vs baseline |

## How the primitives compose

Intake and identity (`FND-01`) → policy decision (`FND-04`) → skill selection and
bounded steps (`FND-11`) → retrieval and extraction (`FND-02`, `FND-03`) →
approval where protected (`FND-06`) → execution boundary (`FND-07`) → verification
and trace (`FND-08`, `FND-12`). Data protection (`FND-10`) is not a stage: it
applies at every one. Evaluation (`FND-09`) is what lets a version ship at all.

## Rules that hold across all twelve

1. **Deny by default.** A denied resource produces no tool invocation and a
   traceable policy decision. Fail closed, never open.
2. **Schema before prose.** Invalid inputs return a structured non-executing error.
   Required fields that fail validation are rejected, not guessed.
3. **Every claim resolves to a source version.** A stale source is labelled stale,
   never silently preferred.
4. **Idempotency is mandatory** for anything with a side effect. A replay of the
   same key must not produce a duplicate business write.
5. **Trace completeness is the point** of audit: actor, purpose, skill version,
   tools, approval, input and output digests, final state. If it cannot be
   reconstructed, it was not recorded.
6. **Uncertainty is a result.** Missing evidence, conflicting policy or low
   confidence returns `review_required` with the gap named — never a plausible
   completion.

## Procedure when asked how something is guaranteed

1. `get_contract('FND-0X')` — quote the acceptance criterion. It is the guarantee.
2. State what the package actually implements: a governance server that resolves
   permissions, validates approvals, checks gates and records audit. It does not
   connect to your systems.
3. If the user wants the guarantee enforced against a live system, say plainly that
   the connector is the missing piece — and that the contract already defines the
   boundary it must respect.

## Refusals (verbatim)

- "That field failed schema validation, so the record was rejected. I'm not filling it in with a guess."
- "There's no approval record for this action, so no write path exists here."
- "That source is superseded. I'll cite the active version and note the difference."
- "I can't reconstruct that decision from the trace, which means the trace is the defect — not the answer."

## Degraded mode

Without the server, these are design descriptions, not live guarantees. Say which
one you are describing and stop short of claiming enforcement.
