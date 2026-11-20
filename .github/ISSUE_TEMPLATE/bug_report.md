---
name: Bug report
about: Something behaves differently than the contract or policy says it should
title: "[bug] "
labels: bug
---

## Where

- **Client and version** (e.g. Hermes 2.x, Claude Code 2.1.322, Codex 0.147.0):
- **Install method** (`hermes plugins install …` / `claude plugin marketplace add …` / local clone):
- **Plugin version** (`plugin.json` -> `version`):
- **OS**:

## What happened

<!-- What did you ask for, and what came back? Paste the response. -->

## What the contract or policy says

<!--
This pack states its rules in files, so quote the one that was violated:
  - skill behaviour  -> skills/<name>/SKILL.md
  - permission level -> src/policies/autonomy-config.yaml or autonomy-tiers.yaml
  - approval rules   -> src/policies/approval.yaml
  - release gates    -> src/policies/release-gates.yaml
  - tool scope       -> src/policies/tool-allowlists.yaml
-->

## Diagnostics

```bash
uv run --script tools/probe_mcp.py      # protocol handshake + governance rules
python tools/validate.py                # manifest, registry, policies, skills, mcp
```

Paste the failing lines. If the MCP server was reported unavailable, say which applies - no local
process (chatgpt.com / mobile), session started before enabling, first-run resolution timeout, or
`uv` not on `PATH`. They have different fixes.

## Connector involved?

<!-- If yes: the check_connector decision (rejected / partial / ready) and which rule failed. -->
