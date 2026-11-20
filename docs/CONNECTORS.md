# Connectors

This package ships **no connectors**. It ships the interface a connector must satisfy, and a
validator that tells you whether yours does.

The reason is the same one behind every other boundary here: a pack installed with one command
must not arrive holding credentials to your ERP. The interface is the part that transfers; the
blast radius has to be your decision.

## The two-minute version

1. Write a manifest describing the connector you already have (or plan to build): its system
   categories, transport, and every tool it exposes.
2. Run `tools/check_connector.py` — or call `check_connector` in a session.
3. Fix what it reports, or accept that the affected skills stop at drafting.

```bash
uv run --script tools/check_connector.py examples/connectors/mock-itsm.yaml --all-skills
```

## What the check actually verifies

**Structural.** A connector that cannot carry the guarantees is rejected outright:

| Requirement | Why it is not negotiable |
|---|---|
| `audit_passthrough` | Without it, a decision cannot be reconstructed — the audit trail stops at the model |
| `least_privilege` | A connector credential wider than the requesting actor is an escalation path |
| `no_ambient_credentials` | A credential from the environment or a shared profile is not attributable to a person |
| `bounded_retry` | An unbounded retry can duplicate a write or amplify an outage |
| write tools declare `idempotency_key` | A replay after a timeout must not duplicate a business write |
| write tools declare `post_condition` | Without proof the write landed, nobody knows the transaction completed |
| write tools declare `rollback` | An irreversible write with no compensation path needs explicit, separate approval |

Forbidden outright: `shared_service_account`, `ambient_credentials`, `unbounded_retry`,
`unlogged_write`.

**Fit.** Per skill, the required operation class comes from the skill's *effective* autonomy, not
from a guess:

| Skill's effective mode | Connector must expose |
|---|---|
| A0 `advisory_only` | a `read` tool in a declared category |
| A1 `draft_only` | a `read` tool in a declared category |
| A2 `human_confirm` | a `write` tool (only reachable via an opted-in skill) |
| A3 `auto` | not reachable in this package |

Coverage is **per connector and per category**. A structurally sound read-only connector serves
the skills whose contracts name categories it declares — an ITSM connector serves the IT skills
and reports the finance ones as gaps, because no tool of its can reach an ERP. That is the honest
answer, not a defect: most deployments need several connectors, one per system family.

## Enforcement: three functions, one rule

FR-04 requires that *"disallowed tools cannot be invoked even when model output requests them."*
This package cannot enforce that — it does not route tool calls. What it does is make the rule
computable, in three pieces:

| Call | Answers | Use it |
|---|---|---|
| `tool_allowlist(skill_id)` | Which categories and operations may this skill use? | Once per skill, to configure your gateway |
| `check_connector(manifest, skills)` | Does this connector carry the guarantees, and which of its tools may each skill call? | On connector onboarding, and at change time |
| `check_tool_call(skill_id, tool, op, category, connector_status)` | May this skill call this tool, right now? | **Before every dispatch** |

The last one is the enforcement point. Deny-by-default, with the rule that fired named in the
response:

```json
{"allowed": false, "rule": "operation_not_permitted",
 "reason": "'write' is not permitted at A1 (allowed: ['read'])"}
```

Both layers must allow before a write is legitimate. They answer different questions:

> `route_autonomy` — may this capability write **at all**?
> `check_tool_call` — may it reach **this tool**?

### What your gateway has to do

1. Resolve the skill and its effective autonomy before dispatch.
2. Read the tool's declared `operation` and `category` from the connector manifest — never from
   the model's description of the tool.
3. Call `check_tool_call`; refuse on anything other than `allowed: true`, and log the refusal
   with the correlation id.
4. Refuse to dispatch at all while the connector's decision is not `ready`.

The honest caveat: if your client has no per-skill tool gating, this degrades into a checklist.
A checklist is not a control. The allowlist only becomes an actual guarantee when something
between the model and the connector applies it.

## What it does not verify

Say this out loud when you report a pass:

- It does not check that your tools map to the contract's actual fields.
- It does not check that your process logic is right.
- It does not check behaviour under load, latency, partial writes or schema drift.
- It cannot detect a manifest that declares `true` for an obligation the code does not honour.

A pass means **"capable of carrying the guarantees"**. Proving a connector and a skill together
actually work is G1/G2 release evidence (`docs/BOUNDARIES.md`) — baseline, golden set, adverse
paths, security and privacy review.

## Manifest shape

```yaml
connector: mock-itsm
system_categories: [ITSM, CMDB]
transport: mcp-stdio              # mcp-stdio | https-mcp | direct-api
owner: service-desk-platform
version: "1.0.0"

audit_passthrough: true           # all four must be true
least_privilege: true
no_ambient_credentials: true
bounded_retry: true

tools:
  - name: itsm.get_incident
    operation: read               # read | propose | write
    resource: incident
    schema_version: "1"

  - name: itsm.create_ticket
    operation: write
    resource: ticket
    schema_version: "1"
    idempotency_key: request_id
    post_condition: "ticket number returned and re-readable from itsm.get_incident"
    rollback: "close the created ticket with an audit note"
```

Working examples, one conforming and one deliberately broken:
[`examples/connectors/`](../examples/connectors).

## Prompt-injection consequence

Once a connector exists, retrieved content becomes an attack surface that did not exist before.
Two rules follow, and both are already stated in the skills:

- Retrieved content is **data**, never instruction (`SG-01`).
- Tool arguments are allowlisted and validated at the boundary; a model asking for an
  unlisted tool gets a refusal, not a call (`FND-04`, `FND-07`).

The structural defence is that this package's own tools cannot act on retrieved content. When you
add a connector, that property is yours to preserve — the validator will not notice if you do not.
