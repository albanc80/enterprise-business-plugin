# Enterprise Business Plugin

[![ci](https://github.com/albanc80/enterprise-business-plugin/actions/workflows/ci.yml/badge.svg)](https://github.com/albanc80/enterprise-business-plugin/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![version](https://img.shields.io/badge/version-0.1.3-orange.svg)](https://github.com/albanc80/enterprise-business-plugin/releases)

A portable **[Agent Plugins v1](https://agent-plugins.org)** package carrying a governed AI
skills layer for business operations: **93 skill contracts across 12 business functions,
served by 16 skills**, backed by a deterministic governance server.

**Draft by default. Advisory by default.** This package ships at autonomy level **A1**: it
produces drafts and analysis, and a named human submits, publishes or executes. It does not
connect to any enterprise system and it does not take a consequential decision.

## What it is, and what it is not

| It is | It is not |
|---|---|
| A versioned, typed catalogue of 93 business capabilities with owners, metrics, acceptance criteria and escalation paths | A deployed system, a working integration, or a set of measured results |
| A governance layer that resolves permission, validates approvals, checks release gates and records audit | An approval authority — it validates approvals a human granted |
| 16 skills that route work, draft artifacts and refuse past the boundary | An autonomous agent swarm, or a replacement for a process owner |
| A starting contract a business function can adopt and validate | Validated. Every capability is **proposed and unvalidated** |

## What you can ask it

| Ask about | You get | Skill |
|---|---|---|
| Who may do this, at what autonomy, with whose approval | Binding level resolved from package ceiling × risk tier × request, every downgrade named | `ai-governance-controls` |
| Can this personal data go in the context, export or log | Classification, minimisation, redaction markers, retention and tenancy checks | `data-protection-and-privacy` |
| Is this skill ready to deploy or scale, and what did it save | Gate-by-gate evidence status (G1–G3), baseline discipline, honest adoption claims | `outcome-and-release-assurance` |
| How does the platform itself work — retrieval, extraction, routing, audit | Contracts for the twelve shared primitives and the guarantees each one makes | `enterprise-foundation` |
| Anything spanning several functions, or naming none | The right function skill, and the permission preflight before any output | `enterprise-ops` |
| Hiring, leave, onboarding, learning, offboarding | Cited policy answers, private case triage, coordination plans — no selection decisions | `hr-operations` |
| Tickets, access, incidents, changes, vulnerabilities | Intake routing, cited runbook steps, access preflight, labelled incident hypotheses | `it-operations` |
| Invoices, matching, expenses, close, variance | Extraction with exceptions flagged, three-way mismatch explanations, reconciled narratives | `finance-operations` |
| Safety policy, incidents, permits, environment | Cited procedures, provisional classifications, go/no-go packets — never authorisation | `hse-and-quality` |
| Cases, replies, SLA, escalation, recovery | Knowledge-grounded drafts, severity-policy routing, resolutions you can evidence | `customer-support-ops` |
| Facilities, meetings, visitors, travel, supplies | Triage, logistics drafts, maintenance escalation, access and duty-of-care preflight | `workplace-services` |
| Requisitions, suppliers, RFQ, bids, inventory | Completeness checks, comparable bid analysis, anomaly explanations — no commitment | `supply-chain-ops` |
| Contracts, obligations, third-party risk, policy lifecycle | Clause spans with citations, playbook deviations, compliance evidence indexes | `legal-and-compliance` |
| CRM hygiene, briefs, quotes, pipeline, renewals | Evidence-backed briefs, authority checks, unflagged-promise detection at handoff | `revenue-operations` |
| Intake, requirements, status, risk, benefits | Testable requirements, status that refuses to infer green, benefits with denominators | `pmo-and-process-excellence` |
| Knowledge discovery, announcements, minutes, localization | Cited synthesis, fact-checked drafts, decisions with owners — never invented ones | `communications-and-knowledge` |

## Autonomy: what is actually permitted

Four levels, defined in [`src/policies/autonomy-tiers.yaml`](src/policies/autonomy-tiers.yaml):

| Level | Permits | Forbids |
|---|---|---|
| **A0 Insight** | Read, retrieve, summarise, flag, advise | Modifying records, publishing, triggering actions |
| **A1 Draft** | Preparing content, cases, plans, recommendations | Submitting, publishing, booking, committing, altering a system of record |
| **A2 Approved action** | Bounded writes after an action-specific authorisation | Expanding scope, reusing an approval, changing values the approver never saw |
| **A3 Bounded automatic** | Pre-authorised, reversible, low-consequence actions inside quotas | Anything safety-critical, legal, employment, financial-release or irreversible |

**This package ships at A1.** A2 is reachable only per skill, by adding an entry to
[`src/policies/autonomy-config.yaml`](src/policies/autonomy-config.yaml) that supplies every
field in `opt_in.requires` — a named process owner, a configured approval gate, audit enabled
and a rollback path. The server reads those fields and **refuses the escalation when any is
missing**; a bare skill id is a configuration error, and `tools/validate.py` fails the build on
it rather than letting it silently do nothing. An opt-in can only restore what a contract already
requests — it never grants a skill more autonomy than its own contract declares.

**A3 is not implemented by this package, and there is no switch for it.** The level stays defined
in the model so the scale is legible and so A2 reads as a ceiling rather than a plateau — but
`autonomy-config.yaml` has no A3 opt-in key, and `tools/validate.py` rejects unknown keys there,
so an `a3_skills` slot cannot be added back and left inert. Enabling A3 is a different package
with a different approval model, not a configuration change.

Three contracts request it (`IT-08`, `CSP-04`, `OFC-04`) and all three resolve to A1, with the
downgrade reported rather than silently applied. There is no executor tool to reach it either:
the thirteen tools produce verdicts and records, and the only thing written to disk is the local
audit log.

Risk is a second ceiling: a Critical-risk capability can never resolve to automatic, whatever
its contract requests.

## The deterministic core

`servers/enterprise_core` is a stdio MCP server. It loads the same policy and contract files
the skills cite, so a skill's explanation and the tool's verdict cannot drift apart.

| Tool | What it enforces |
|---|---|
| `route_autonomy` | Package ceiling ∩ risk cap ∩ request, with every downgrade named |
| `approval_gate` | Action-specific binding, expiry, single use, separation of duties, complete evidence |
| `release_gate` | G1–G3 evidence, waiver rules, and items that are never waivable |
| `get_contract` / `list_skills` | The contract itself — owner, metric, acceptance, escalation, fail-safe |
| `check_connector` | Whether a connector you supply can carry the guarantees: structure, then per-skill operation fit |
| `tool_allowlist` | Which system categories and operations a skill may use at its effective autonomy |
| `check_tool_call` | Deny-by-default verdict for one skill calling one tool — the gateway's enforcement primitive |
| `score_skills` | The SRD's opportunity heuristic, reproduced exactly |
| `audit_append` / `audit_trace` | Hash-chained decision trail |
| `list_capabilities` | What this server can and cannot do, before you trust an answer |

## Connectors you bring

The package ships none — and ships the interface one must satisfy instead. Describe the connector
you already have (or intend to build) in a manifest, and `check_connector` tells you whether it
can carry the guarantees: audit passthrough, least privilege, no ambient credentials, bounded
retry, and for every write tool an idempotency key, a post-condition and a rollback. Then it
checks fit per skill — an A0/A1 skill needs a read tool, an A2 skill needs a write tool.

```bash
uv run --script tools/check_connector.py my-connector.yaml --skills IT-01,IT-02
```

It validates structure and fit, not correctness: field mapping, process logic and behaviour under
load are G1/G2 release evidence.

**Tool scope is separate from autonomy.** `tool_allowlist` says which system categories and
operations a skill may use; `check_tool_call` gives the deny-by-default verdict for one specific
call, and is what your gateway should apply before dispatch. Both must allow before a write is
legitimate — autonomy says "may this capability write at all", the allowlist says "may it reach
*this* tool". Details in **[docs/CONNECTORS.md](docs/CONNECTORS.md)**.

## What it will not do

- **No system connection.** No HRIS, ERP, ITSM, CRM, EHS, CLM or IAM. The connector is the
  missing piece, and each contract already defines the boundary a connector must respect.
- **No consequential decision.** No hiring, termination, pay release, contract execution,
  safety authorisation, medical or legal determination.
- **No fabricated number.** Every metric in the registry is a hypothesis from the SRD. There
  are no observed results in this repository, because none have been measured.
- **No false completion.** A capability is not validated because it is documented. Ask for its
  acceptance criterion and its gate evidence.

## Install

The repo root **is** the package. Requires [`uv`](https://docs.astral.sh/uv/) for the tools;
without it, skills still load and say the deterministic verdict is unavailable.

```bash
hermes plugins install albanc80/enterprise-business-plugin
hermes plugins enable enterprise-business-plugin
```

```bash
codex plugin marketplace add albanc80/enterprise-business-plugin
codex plugin add enterprise-business-plugin@enterprise-business-plugin
```

```bash
claude plugin marketplace add albanc80/enterprise-business-plugin
claude plugin install enterprise-business-plugin@enterprise-business-plugin
```

Warm the server once so a cold dependency resolve cannot collide with a client's MCP startup
timeout:

```bash
uv run --script servers/enterprise_core/main.py --selftest
```

Full commands, per-client details and verification are in **[docs/INSTALL.md](docs/INSTALL.md)**.

## Harness support

Three states, deliberately distinguished — read the status column before quoting this table:

- **verified** — installed from this repo on this machine, MCP server started, tools actually called
- **validated** — the client's own validator passes against this repo; not installed end-to-end here
- **expected** — a v1 client by specification; this package has not been exercised on it

| Client | Skills | Tools | Install path | Status |
|---|---|---|---|---|
| Hermes | yes | yes | `hermes plugins install` | **verified** — installed from remote, MCP registered, `list_capabilities` called in a fresh session |
| Claude Code | yes | yes | `claude plugin marketplace add` | **verified** — installed from the marketplace; `claude mcp list` shows `plugin:enterprise-business-plugin:enterprise-core` **Connected**; `list_capabilities` returned `93 / A1` in a headless session |
| Codex (CLI and ChatGPT desktop) | yes | expected | `codex plugin marketplace add` | **expected** — v1 client; Codex has no validate-only path, so verifying it means writing to `~/.codex` |
| OpenClaw | yes | expected | plugin bundles, or skills dir + `openclaw mcp set` | **expected** — not exercised |
| Copilot, Cursor, VS Code, Kiro, Antigravity | yes | expected | native v1 clients — point at the repo | **expected** — v1 by specification, not exercised |
| chatgpt.com, ChatGPT mobile | partial | **no** | no local process to spawn | permanent exclusion — skills answer qualitatively and say no verdict was produced |

## Layout

```
plugin.json              Agent Plugins v1 manifest
mcp.json                 governance server declaration
skills/                  16 skills (SKILL.md per decision procedure)
src/registry/            generated contracts: 93 skills, 12 domains, 32 requirements
src/registry/source.json normalized projection of the requirements document + its sha256
src/policies/            autonomy, risk matrix, approval, release gates, safeguards, scoring, connectors
servers/enterprise_core/ registry + policy engine + MCP server
tools/build.py           regenerates the registry from source.json
tools/validate.py        the gate: manifest, registry, policies, skills, mcp
tools/probe_mcp.py       speaks MCP to an install path and verifies the rules hold
tools/check_connector.py validates a connector manifest you supply
tests/                   governance behaviour and SRD parity tests
```

## Provenance

Every one of the 93 contracts derives from a vendor-neutral, industry-neutral requirements
document — **which is not published with this package.** What ships is its normalized projection,
and a hash you can check against the document itself:

| Artefact | What it is |
|---|---|
| `src/registry/source.json` | The normalized source contract set — domains, skills, requirements, waves, metrics, plus `provenance.sha256` |
| `src/registry/*.yaml` | Generated from `source.json` by `tools/build.py`. Never hand-edited. |
| `tools/extract_srd.py` | The only tool that reads the document. You run it locally. |

```bash
uv run --script tools/extract_srd.py path/to/your-copy.html   # local: document -> source.json
uv run --script tools/build.py                                # source.json -> registry
uv run --script tools/build.py --check                        # fail on drift
python tools/validate.py                                      # the gate
```

So the chain is auditable without the document being public: the shipped `sha256` lets anyone
holding it confirm the projection is faithful, and CI fails if the registry drifts from that
projection. If you do not have the document, you can still read every contract, score and
requirement — you just cannot re-derive them from the original, which is the correct trade.

The registry keeps each contract's **requested** autonomy. The shipped ceiling is a runtime
policy decision, so tightening it never rewrites a source contract.

## Status

**Version 0.1.3 — reference implementation, unvalidated in use.**

> **Every release so far has been a security release.** Two external reviews broke the
> package: 0.1.0's approval gate accepted ids it never issued and could mint a token for a
> payment on a drafting-only skill (fixed in 0.1.1); its tools then accepted malformed
> filters, negative scoring weights and unverified approver roles (fixed in 0.1.2–0.1.3). Each fix
> has a regression test written to fail against the version that shipped the defect — see
> [`SECURITY.md`](SECURITY.md). If you installed anything before 0.1.3, update. No adopter, no assigned process
owner, no measured baseline and no golden set exists yet. The version says so deliberately: the
contract format and the governance model are settled enough to distribute, and not settled enough
to promise stability.

The SRD is explicit and so is this package: **all capabilities are proposed and unvalidated.**
What ships here is a governed starting contract plus the machinery to enforce its boundaries —
not evidence that any of it works in your organisation.

## Licence

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Requirements source and standards
references are cited in the SRD.
