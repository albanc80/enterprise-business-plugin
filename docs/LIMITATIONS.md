# Limitations

Six limits are **accepted by design**, not defects waiting for a fix. Each one is stated
here with what it costs, why it is accepted, what would change that judgement, and the test
that pins it so a green suite cannot be read as completeness.

A limitation you cannot test for is a belief. Every entry below has a test asserting the
gap **exists** — a failing test would mean the limitation has silently changed.

| # | Limitation | Costs | Pinned by |
|---|---|---|---|
| [L1](#l1--the-token-ledger-is-in-process) | Token ledger is in-process | Restart voids outstanding approvals | `test_l1_restart_voids_outstanding_tokens` |
| [L2](#l2--the-audit-chain-has-no-external-anchor) | No external anchor on the audit chain | Tail truncation and a full rewrite are undetectable | `test_l2_a_consistently_rewritten_chain_verifies` |
| [L3](#l3--approver-identity-is-not-verified) | Approver identity is not verified | The *role* is authorised; the person holding it is not proven | `test_l3_role_authorises_but_the_person_is_not_proven` |
| [L4](#l4--no-authentication-or-transport-security) | No authentication | Anything that can start the server can call every tool | `test_l4_the_server_speaks_stdio_with_no_auth_layer` |
| [L5](#l5--the-tool-verdict-is-category-scoped) | Tool verdict is category-scoped | A specific tool name is not resolved | `test_l5_tool_name_is_not_resolved` |
| [L6](#l6--operation-is-the-callers-declaration) | `operation` is the caller's declaration | The gate cannot verify what was actually done | `test_l6_operation_is_whatever_the_caller_declares` |

---

## L1 — The token ledger is in-process

**What it means.** Approvals issued by the server live in a module-level dictionary
(`_ISSUED`). Nothing is written to disk, so a restart — or a second server process —
knows nothing about a token the first one issued.

**What it costs.** An approval obtained before a restart must be requested again after it.
In a long-running deployment, a crash during an approval window loses that window.

**Why accepted.** It fails **safe**: an unknown token is refused with `unissued_approval`,
never honoured. The alternative — persisting tokens — turns a stale authorisation into a
durable one, and stale authorisation is the more expensive failure. "The approval is gone,
ask a human again" is the correct behaviour for a governance gate.

**What would change this.** A deployment needing approval continuity across restarts must
supply its own durable ledger (the `issued` parameter accepts one). That is the adopter's
decision about retention and revocation, not a default this package should pick.

## L2 — The audit chain has no external anchor

**What it means.** Entries are hash-chained: each records `previous_hash` and its own
`entry_hash`, and verification recomputes every hash and checks every link. The first
entry of an empty chain links to the literal `"genesis"`, which lives in this codebase.

So verification detects edits, deletions, reordering, edited-and-rehashed entries, and
appends onto a broken chain — **within the file**. It cannot detect:

- **tail truncation** — dropping the newest entries leaves a shorter but perfectly valid chain;
- **a full rewrite** — replacing every entry and recomputing every hash from `"genesis"`
  produces a chain that verifies.

**What it costs.** A trail that has not been tampered with cannot be *proved* untampered by
the file alone. Integrity is only as strong as custody of the file.

**Why accepted.** Closing either gap needs an external anchor — a signed head published
somewhere else, an append-only service, or a timestamping authority. All three mean a
network dependency and a credential, which a local reference implementation should not
invent. The honest position is that this detects casual tampering and documents the rest.

**What would change this.** Record the latest `entry_hash` somewhere out of the writer's
reach (a signed release artifact, a second system, a periodic export). Comparing that
recorded head against the current tail is what turns truncation into a detectable event.

## L3 — Approver identity is not verified

**What it means.** `authorised_approver` checks that the stated role is the contract owner
or listed for the risk tier, and separation of duties compares the requester and approver
strings. Nothing proves the person named actually holds that role.

**What it costs.** Someone who can call the tool can type any name and the owning role and
pass. Identity rests entirely on the caller.

**Why accepted.** Verifying identity is an IdP's job — this server has no directory, no
tokens, and no session. Pretending to authenticate would be worse than declaring it does
not: a gate that *looks* like it verified identity gets trusted as if it had.

**What would change this.** A deployment puts the gate behind its own authenticated
service and passes the verified principal, then treats `approver_id` as evidence from that
service rather than from the model.

## L4 — No authentication or transport security

**What it means.** The server speaks MCP over stdio (`mcp.run("stdio")`). It opens no
port, and every tool is callable by whoever started it.

**What it costs.** Authorisation is per-skill policy, not per-caller. If the process runs,
the process may ask.

**Why accepted.** This is a reference implementation intended to run as a local child
process of a client that already authenticated the human. Adding an auth layer would
duplicate the client's identity model and create a second thing to get wrong.

**What would change this.** The moment the server listens on a socket, it needs
authentication, TLS, and a decision about tenancy. Do not bridge it to a network as it is.

## L5 — The tool verdict is category-scoped

**What it means.** `check_tool_call` decides on the **operation class** (`read`,
`propose`, `write`) drawn from the skill's contract, not on the concrete tool name. It
echoes the name and returns `scope: "category"` with `tool_name_verified: false`.

**What it costs.** It cannot tell you "this specific tool is permitted". A gateway must map
its tools to operation classes itself, and that mapping is where a mistake becomes a bypass.

**Why accepted.** The package has no tool directory — it does not know what tools an
adopter's MCP servers expose. Inventing a registry would mean asserting authority over
names it has never seen. Labelling the verdict accurately is the honest move.

**What would change this.** An adopter supplies its tool→category map (or a manifest the
gate can read); the gate then resolves names and can set `tool_name_verified: true`.

## L6 — `operation` is the caller's declaration

**What it means.** The gate is told which operation class an action belongs to. It cannot
observe what the action actually does.

**What it costs.** A caller that declares `read` for something that writes is governed as
a read. The gate is honest about the allowlist; it cannot audit intent.

**Why accepted.** The server performs no actions — it computes decisions and appends
records. There is nothing to observe. Enforcement belongs to the system that executes.

**What would change this.** The executing system derives the operation class from its own
tool manifest and passes that, so the declaration comes from code rather than from a model.

---

## What these six have in common

Each is a place where **the package stops and another layer must begin**: durable state,
an external anchor, an identity provider, a transport, a tool registry, an executor.
Naming the boundary is the control. Silently guessing across it is how a governance pack
becomes decoration.

## Related

- [`SECURITY.md`](../SECURITY.md) — findings and fixes, by review round.
- [`evals/README.md`](../evals/README.md) — what is measured (retrieval and quoting) and
  what is not (whether the advice is good).
- [`docs/CONNECTORS.md`](CONNECTORS.md) — the connector contract, validated against
  synthetic manifests only.
