# Boundaries

What this package refuses to do is a design decision, not a missing feature. Stating it plainly
is cheaper than discovering it during a safety review.

## No enterprise system connection

There is no connector to HRIS, ERP, ITSM, CRM, EHS, CLM, IAM or a data warehouse. The server
performs no network call of any kind.

This is deliberate for a package installed with one command. Each of the 93 contracts already
declares the system categories it would need and the boundary a connector must respect — access
scope, preconditions, side effects, post-conditions, rollback. A team integrating its own system
is filling in a defined shape, not inventing one.

**Consequence:** the pack is useful on day one for analysis, drafting and governance reasoning,
and useless for acting on live records until someone builds that connector and accepts its blast
radius.

## No consequential final decision

The following stay with an authorised human, always, regardless of what any model produces:

- hiring, promotion, termination, selection
- payroll release and payment execution
- contract acceptance, signature, waiver or renewal
- safety authorisation and permit-to-work
- medical and legal determination
- residual risk acceptance
- regulated or otherwise high-consequence final decisions

The pack analyses, drafts, routes and evidences in all of these areas. It does not decide.

## No autonomy above A1 without an explicit, evidenced edit

The shipped ceiling is A1 (draft). A2 requires an entry in `src/policies/autonomy-config.yaml`
that supplies every field in `opt_in.requires`: a named process owner, a configured approval
gate, audit enabled and a rollback path. Three behaviours keep that honest:

1. **The server reads the evidence.** Missing or falsy fields fail closed to the default
   ceiling, and the reason is reported in the resolution — an opt-in that silently does nothing
   is worse than no opt-in, because the operator believes it worked.
2. **The gate rejects malformed opt-ins.** A bare skill id, an unknown skill, or an entry
   missing a required field fails `tools/validate.py`, so it cannot ship and cannot be silently
   inert.
3. **An opt-in cannot exceed the contract.** It restores at most what the skill's own
   `autonomy_requested` declares. Raising a skill past its designed level is a contract change,
   not a config change.

A3 is defined in the model but **not implemented, and not reachable by configuration**. There is
no A3 opt-in key in `autonomy-config.yaml`; the validator rejects unknown keys there, so a slot
cannot be added back and left dormant. `a3_shipped` must stay `false` or the build fails. The
three contracts that request it resolve to A1 and say so.

This is the one place the package deliberately keeps a concept it does not implement: deleting
the tier would misrepresent the source document and hide what is being withheld. Keeping it,
labelled and unreachable, is the honest form of the same decision.

## No invented number

Every metric in the registry is a hypothesis taken from the SRD's planning targets. No baseline
has been measured, no denominator exists, and no result has been observed. Any figure quoted from
this package is a target, and the skills are instructed to say so.

## No completion claim without evidence

A capability is documented, not validated. Deployment requires G1 and G2 evidence; expansion
requires G3. Privacy signoff, the kill-switch test and the proof that no unauthorised action
occurred are never waivable.

## No silent downgrade

Every permission resolution reports what was requested, what is effective and why. A skill that
asks for A2 and receives A1 says so in the same breath. Silent degradation is the failure mode
that makes a governance layer worse than none, because it manufactures false confidence.

## Degraded mode is explicit

Without `uv` or the server, skills still load and still reason about their domain. They lose the
deterministic verdicts and must say so. The one thing they must never do is reconstruct a
permission level, an approval state or a gate result from memory — those answers exist only in
the server, and a plausible substitute is exactly what the governance layer exists to prevent.
