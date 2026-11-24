# Security

## Reporting

Open a private security advisory on this repository, or email the address on the
author's GitHub profile. Do not open a public issue for a suspected vulnerability.

## What this package does not do

Stated up front because it determines the threat model:

- **No network calls.** The server opens no sockets and contacts nothing.
- **No enterprise connection.** No credential store, no connector, no token, no API key.
- **No system writes.** It cannot modify any record in any system of record.
- **No execution.** It cannot run a command, a runbook or a transaction.

The blast radius of the shipped package is limited to: the text it produces, the files it
writes under its own data directory, and the judgement a human applies to that text.

## What it does write

`audit.jsonl`, a hash-chained JSONL append log, and nothing else.

It is written to a **persistent data directory, never inside the install folder** — the install
folder is a cache the client replaces on every update, so an audit trail there disappears exactly
when someone needs to review it. Resolution order: `ENTERPRISE_DATA_DIR`, then the client's
`PLUGIN_DATA` / `CLAUDE_PLUGIN_DATA`, then a per-user location
(`%LOCALAPPDATA%\enterprise-business-plugin`, or `$XDG_DATA_HOME/...`). A variable the client failed
to expand is ignored rather than used literally.

## Known limitations

These are deliberate and visible rather than implied to be solved:

1. **The issued-token ledger is in-process.** Only ids this server issued can be redeemed, so a
   forged id fails closed; but a restart empties the ledger and therefore voids outstanding
   approvals. That is the intended direction — it fails toward "ask a human again", never toward
   "honour a stale authorisation". A durable ledger belongs in the same store as the audit trail.
2. **The audit chain detects tampering, it does not prevent it.** A writer with filesystem access
   can rewrite the whole chain. Anchoring requires an external append-only sink.
3. **The server is a reference implementation of the governance model**, not a hardened service.
   There is no authentication layer because there is no network surface.
4. **Validation of an approval is not verification of an approver's authority.** The gate checks
   separation of duties, expiry, binding and evidence completeness. Confirming that a named
   approver actually held the delegated authority is the identity system's job.

## Review findings

An external review of 0.1.0 found a defect in the approval gate. It is recorded here because a
governance package whose failure is invisible has no business claiming to govern anything.

| Severity | Finding | Fix |
|---|---|---|
| P0 | `approval_id` was accepted as an opaque string: any invented id redeemed successfully, because the server kept only a list of *already-spent* ids and no record of what it *issued*. | The server now keeps an issued-token ledger. An unknown id returns `unissued_approval`; tokens are scoped to the ledger that issued them. |
| P0 | A valid token redeemed for a *different* action: the digest was computed at issue time and then discarded, so the binding was decorative. | The digest now covers skill, operation, action and evidence; redemption recomputes it and refuses any change as `action_changed`. |
| P1 | A token could be issued to release a payment on `FIN-02`, a drafting-only skill — the gate never consulted the autonomy ceiling. | Issuance resolves effective autonomy first and refuses when the mode is `advisory_only` / `draft_only`. No approval exists for a capability the ceiling forbids, and no amount of evidence creates one. |
| P1 | Separation of duties compared raw strings, so `Alice` / `alice ` / `ALICE` passed as different people. | Identities compare on a normalised form (casefold, whitespace collapsed); a missing identity now fails instead of passing. |
| P2 | The audit trail was written inside the install folder and was destroyed by the next update. | Persistent data directory, documented above. |
| P3 | Claude reported unknown fields in the marketplace manifest. | Removed; `claude plugin validate` now passes with no warnings. |

Each fix carries a regression test in `tests/test_approval_gate.py` that reproduces the original
attack. The tests were written to fail against 0.1.0.

A second review pass then attacked the tools around the gate, and found that several accepted
input they should have refused. Fixed in 0.1.2:

| Severity | Finding | Fix |
|---|---|---|
| P2 | The approver's `evidence.proposed_action` did not have to match the action being approved, so a summary saying something else still passed. | The two must match after whitespace normalisation. Spacing is tolerated; different content is not. |
| P2 | `authorised_approver` only checked that the role field was non-empty, so "intern" passed as authority. | The role must appear in `rules.authorised_approver.roles_by_risk` for the contract's risk tier. That table ships empty and denies until the adopter populates it — the pack verifies delegated authority, it cannot invent an org chart. |
| P2 | `score_skills` accepted unknown weight keys and negative values, returning a score of 102. | Weights must be recognised keys in 0..100 with a non-zero total. Invalid input returns `error`, not a ranking. |
| P2 | `list_skills` returned 0 rows and no error for an invalid filter, which reads as "no such skill". Domain display names ("Finance & accounting") also matched nothing, because contracts store ids ("Finance"). | Invalid filters return `error` naming the valid values. Domains resolve from id, display name or an unambiguous fragment; an ambiguous fragment is an error. |
| P3 | The MCP probe requested protocol `2024-11-05`, so it verified old-client tolerance rather than current protocol support. | The probe takes the version from the server's own SDK. |
| P3 | `get_contract` returned the contract's declared `side_effects` only, so FND-06 advertised "Explicitly approved, scoped system write" while resolving to A1 draft-only. | The response now carries `side_effects.effective`, derived from the effective mode, with a note when the declared text describes a level the package has removed. |

## Design decisions that matter for review

- **An approval is not a string.** A token is an id this server issued, bound to a digest of one
  action, one operation and one evidence bundle, expiring on a clock. Everything else — an id from
  somewhere else, a spent token, a changed payload, a widened operation — is refused by name.
- **The ceiling outranks the approver.** A valid, complete, well-separated approval still cannot
  authorise an action the skill's effective autonomy forbids. Permission is not paperwork.
- **Deny over degrade.** Every failure path denies. Missing evidence, an unknown skill id, a
  malformed level or an expired window all produce a refusal, never a default-allow.
- **Downgrades are reported.** A permission capped by the package ceiling or the risk tier says
  so in the response. Silent degradation is treated as a security defect, not a convenience.
- **Guarantees live in tools.** Every enforced rule is evaluated in code from policy files. A
  skill that explains a gate without calling it is treated as a defect — see
  `skills/ai-governance-controls`.
- **The ceiling cannot be raised inside a session.** It requires editing
  `src/policies/autonomy-config.yaml`, which `tools/validate.py` fails the build on if changed to
  A2 or if A3 is enabled.

## Prompt-injection stance

Retrieved content is data, never instruction. Skills that consume retrieved content are told to
treat it that way and to cite the source version. The server has no tool that acts on retrieved
content, which is the structural defence: there is nothing to escalate to.

## Supported versions

The current minor version receives fixes. This package is a reference implementation published
for reuse, not a maintained product with an SLA.
