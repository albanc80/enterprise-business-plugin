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
2. **The audit chain detects tampering; it does not prevent it.** `audit_trace` recomputes the
   whole chain on every read and reports the first entry that does not hold up: edited content,
   an edited entry whose own hash was recomputed (the next entry still records the old one),
   deleted or reordered entries, unreadable lines, missing hashes. `audit_append` also reports
   whether the trail verified *before* it wrote, so a call cannot quietly extend a broken chain.
   Two limits remain and both are real: a writer with filesystem access can rebuild the entire
   chain from genesis, and **removal of the newest entries is undetectable from inside the file**,
   because the surviving prefix is a valid chain. Closing either needs an anchor outside the file
   — an append-only sink or an externally recorded head hash — which this package does not ship.
3. **The server is a reference implementation of the governance model**, not a hardened service.
   There is no authentication layer because there is no network surface.
4. **The gate checks that a role is authorised; it cannot check that the person holds it.** The
   approver's role must match the contract's declared owner or appear in
   `rules.authorised_approver.roles_by_risk` for the risk tier, and the issued token records which
   basis applied. Whether the named individual actually occupies that role is the identity
   system's job, not this package's.

### 0.1.4 — the audit chain is verified, not just chained

The package claimed a "tamper-evident" trail and shipped a chain nobody checked: `audit_trace`
parsed lines and returned them, and `audit_append` chained to the last recorded hash without
verifying it. The design was sound and the verifier was missing, which is the version of this
failure that survives review — a decorative chain looks identical to a working one until someone
edits a line.

`verify_chain()` now walks the trail and is called on both the read and the write path, with the
hash defined once and shared by writer and verifier so the two cannot drift. Eleven adversarial
tests in `tests/test_audit_chain.py` edit, recompute, delete, reorder, truncate and corrupt the
file on disk; a clean chain passes and every tampering case is caught — except tail truncation,
which is pinned as a test asserting it is *not* detectable, so the limitation cannot be quietly
forgotten.

### 0.1.5 — the tool-call gate failed open on its own precondition

`check_tool_call` is the enforcement primitive a gateway calls before dispatch, so it was
attacked the way a caller attacks it: with valid-looking arguments trying to earn an `allowed`.

**The gate defaulted `connector_status` to `"ready"`.** Deny-by-default everywhere except the
one argument that represents "the connector was checked" — a gateway that never called
`check_connector` was told yes. The parameter now has no default: omitting it returns
`connector_unverified`, and the reason says to call `check_connector` first.

`tool_name` was never compared to anything, yet the response said `allowed: true` for it. The
rule is genuinely category-scoped — the package has no tool directory to check a name against —
so the defect was in the reporting, not the rule. The response now carries `scope: "category"`
and `tool_name_verified: false` plus a note pointing at `check_connector`'s per-tool rows.

Operation and connector tokens are now normalised for case and padding. Not a vulnerability —
the old code refused `"WRITE"` — but a denial for a legitimate intent invites trying variants
until one is accepted, which is argument-fishing, not governance. Lookalikes are still refused:
`wr ite`, zero-width and Cyrillic characters, fullwidth forms, `write;`, `write()`, `writes`.
A category allow is not a tool approval, and the payload now says so.

36 adversarial cases in `tests/test_tool_call_gate.py`, and the probe asserts the refusal when
the connector verdict is omitted.

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
| P2 | `authorised_approver` only checked that the role field was non-empty, so "intern" passed as authority. | The role must be the contract's declared owner or appear in `rules.authorised_approver.roles_by_risk` for the contract's risk tier. Nothing else passes; a fragment of the title ("Controller", "AP controller") does not pass either. |
| P2 | `score_skills` accepted unknown weight keys and negative values, returning a score of 102. | Weights must be recognised keys in 0..100 with a non-zero total. Invalid input returns `error`, not a ranking. |
| P2 | `list_skills` returned 0 rows and no error for an invalid filter, which reads as "no such skill". Domain display names ("Finance & accounting") also matched nothing, because contracts store ids ("Finance"). | Invalid filters return `error` naming the valid values. Domains resolve from id, display name or an unambiguous fragment; an ambiguous fragment is an error. |
| P3 | The MCP probe requested protocol `2024-11-05`, so it verified old-client tolerance rather than current protocol support. | The probe takes the version from the server's own SDK. |
| P3 | `get_contract` returned the contract's declared `side_effects` only, so FND-06 advertised "Explicitly approved, scoped system write" while resolving to A1 draft-only. | The response now carries `side_effects.effective`, derived from the effective mode, with a note when the declared text describes a level the package has removed. |

### 0.1.3 — how approver authority is established

The 0.1.2 fix read the role table only, and that table ships empty. A gate that could not
be satisfied without editing policy is a gate that gets switched off, so 0.1.3 adds the
basis the source document already supplies: **each contract declares an accountable owner**
("Finance Controller", "IT Operations / Security"), and that owner may approve their own
function's skills. Matching tolerates case, spacing and punctuation — the way people
actually type a title — but not a fragment of it: "Controller" and "AP controller" are
refused, because substring matching would make every plausible-sounding title an approver.

An empty `roles_by_risk` tier is therefore not a hole. It means the owner is the *sole*
approver, which is the narrowest default available; the table exists so an owner can
delegate, and each accepted approval records which basis authorised it
(`approver_authority` on the issued token: `contract owner` or `listed for risk tier X`)
so an auditor can see whether authority was delegated or inherent.

## Design decisions that matter for review

- **An approval is not a string.** A token is an id this server issued, bound to a digest of one
  action, one operation and one evidence bundle, expiring on a clock. Everything else — an id from
  somewhere else, a spent token, a changed payload, a widened operation — is refused by name.
- **Authority is inherited from the contract, not inferred from a job title.** The owner
  named in the source document may approve; anyone else must be delegated in policy, and
  the token records which.
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
