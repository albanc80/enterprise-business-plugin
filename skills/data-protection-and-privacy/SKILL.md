---
name: data-protection-and-privacy
description: Classify, minimise, redact and retain protected information across prompts, retrieval, outputs, logs and exports — and keep tenants and functions isolated. Use whenever a request involves employee records, personal data, customer data, or anything leaving the organisation.
---

# Data Protection and Privacy

Data handling is a design input, not a review step. You minimise before you
reason, and you say what you withheld.

## The rule that outranks usefulness

If a field is not necessary for the stated purpose, it does not enter the context.
Not redacted later, not "handled securely" — not retrieved.

## Procedure

1. **Classify before reading.** Public, internal, confidential, restricted. A
   restricted field (protected-category HR data, health, payment instruments,
   credentials, named individual performance) is out of scope for general flows
   regardless of who asks.
2. **Trim to purpose.** `get_contract(skill_id)` states the skill's
   `data_handling` and its `preconditions`. Honour them literally: "data minimized
   to purpose, tenancy and role" is an instruction, not a slogan.
3. **Check the tenancy boundary.** Retrieval, memory, caches and logs are all leak
   paths. A cross-tenant or cross-function answer is a defect even when the answer
   is correct.
4. **Redact with a visible marker.** Never silently drop a required field: emit
   `[redacted: <classification>]` so the human sees the gap and cannot mistake the
   absence for a zero.
5. **Bound retention.** State where the artifact lands and for how long. Meeting
   transcripts need consent; recordings need a retention decision; exports inherit
   the source classification.
6. **Record the handling decision** with `audit_append` — purpose, scope, what was
   withheld and why. Not the sensitive values themselves.

## Function-specific traps

- **HR** — employee-relations and protected-category cases never enter a general
  queue (`HR-06`). A personal-record correction needs an authorised steward.
- **HSE** — incident narratives carry injury and personal detail. Retain the
  original account, restrict the audience (`HSE-02`).
- **Legal** — privilege and matter confidentiality. Clause extraction quotes spans;
  quote only what the reviewer needs (`LGL-01`).
- **Finance** — payment instruments and bank details are restricted, not
  confidential. Never place them in a draft for a third party.
- **Support** — account sensitivity and consent status gate the response (`CSP-01`).
- **Workplace** — utilization data is aggregate-only; suppress below the approved
  minimum group size (`OFC-07`).

## Refusals (verbatim)

- "That's restricted data outside this flow's purpose. I'll work from a redacted extract — here is what I need."
- "I can't put that in the log. The audit entry records the decision, not the values."
- "This answer mixes two tenants, so I'm discarding it rather than reporting it."
- "There's no consent on record for that transcript, so I can't produce minutes from it yet."

## Degraded mode

Without the server you may apply the classification and minimisation rules as
stated. You may not assert a skill's declared data-handling contract, because that
lives in the registry — say the contract needs checking instead of guessing it.
