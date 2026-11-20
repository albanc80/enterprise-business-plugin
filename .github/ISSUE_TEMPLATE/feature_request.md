---
name: Feature request
about: A capability, a client, or a governance rule that is missing
title: "[feature] "
labels: enhancement
---

## Problem

<!-- The operational situation, not the solution. Who is blocked, on what, and what it costs. -->

## Proposed change

## Which layer

- [ ] a **skill** - `skills/<name>/SKILL.md` (decision procedure, refusals)
- [ ] a **contract** - `src/registry/` (generated from the source document, which is not published)
- [ ] a **governance rule** - `src/policies/` (autonomy, approval, gates, allowlists)
- [ ] a **client or install path** - `plugin.json`, `mcp.json`, `.claude-plugin/`
- [ ] the **governance server** - `servers/enterprise_core/`
- [ ] documentation only

## Governance impact

<!-- Answer these or the request cannot be assessed: -->

- Does this widen autonomy (A1 -> A2), add an operation class, or introduce a connector?
- If yes, what evidence would it need? (named owner, approval gate, audit, rollback path)
- Does it let a skill reach a system category its contract does not declare?
- Does it need a change to the source requirements document, or only to this pack?

## Anything cheaper that would do

<!-- The pack prefers deterministic rules and the simplest architecture. Say what you ruled out. -->
