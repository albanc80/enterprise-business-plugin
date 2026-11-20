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

`audit.jsonl`, in `PLUGIN_DATA` when the client supplies it, otherwise in `.data/` inside the
package. It is a hash-chained JSONL append log. Nothing else is written.

## Known limitations

These are deliberate and visible rather than implied to be solved:

1. **The redeemed-approval ledger is in-process.** It resets when the server restarts, so
   single-use enforcement does not survive a restart. A real deployment backs it with the same
   durable store as the audit trail. Stated in `list_capabilities` so a caller cannot assume
   durability.
2. **The audit chain detects tampering, it does not prevent it.** A writer with filesystem access
   can rewrite the whole chain. Anchoring requires an external append-only sink.
3. **The server is a reference implementation of the governance model**, not a hardened service.
   There is no authentication layer because there is no network surface.
4. **Validation of an approval is not verification of an approver's authority.** The gate checks
   separation of duties, expiry, binding and evidence completeness. Confirming that a named
   approver actually held the delegated authority is the identity system's job.

## Design decisions that matter for review

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
