# Contributing

This package makes claims it has to keep. Before changing anything, know which layer you are in —
each has a different gate and a different reviewer.

## Run the gates first

```bash
uv run --script tools/build.py --check     # registry still matches source.json
python tools/validate.py                   # manifest, registry, policies, skills, mcp
uv run --with pytest --with "pyyaml>=6,<7" -- python -m pytest tests -q
uv run --script tools/probe_mcp.py         # the server actually speaks MCP and holds its rules
```

All four must pass. CI runs the same set, so a green PR is one where you already ran them.

## Which layer are you changing?

| Layer | Path | Rule |
|---|---|---|
| **Skill** — decision procedure, refusals | `skills/<name>/SKILL.md` | Must say what it will not do and where it escalates. A skill that never refuses is incomplete. |
| **Contract** — capability, owner, metric, acceptance | `src/registry/` | **Generated. Never edit by hand.** Change `src/registry/source.json` (or the document behind it) and rebuild. |
| **Governance rule** | `src/policies/` | Changes here change what the pack *permits*. See below. |
| **Server** | `servers/enterprise_core/` | Every tool needs a test that proves it refuses the wrong thing, not only that it allows the right one. |
| **Docs** | `README.md`, `docs/` | Claims must match code. `tests/test_readme_claims.py` enforces the ones that are countable. |

## Governance changes need an argument, not a diff

Any PR that widens autonomy, adds an operation class, introduces a connector, or relaxes a release
gate must state in the description:

1. **What consequence** the change makes reachable that is not reachable today.
2. **What evidence** would justify it — named process owner, approval gate, audit trail, rollback.
3. **What still refuses** after the change. If nothing does, it is not governance, it is a switch.

The pack ships at **A1 (draft only)** deliberately. Requests to raise the default ceiling will be
declined without a named deployment that requires it and a control that survives an audit.

## Contracts derive from a document that is not in this repo

`src/registry/source.json` is the normalized projection of a requirements document that is
deliberately unpublished; it carries that document's SHA-256. If you change contract data, change
the projection and rebuild — do not hand-edit the generated YAML, and do not add the document.

## What will not be merged

- A connector that holds ambient credentials or a shared service account.
- A skill that invents an identifier, threshold, score or acceptance criterion instead of calling a
  tool for it.
- An "autonomous" path with no approval, no quota and no kill switch.
- Fabricated metrics. If it was not measured, it is a target and must be labelled as one.
- A silent downgrade. Every reduction in what a skill may do must be reported to the caller.

## Reporting instead of fixing

Security issues: see [`SECURITY.md`](SECURITY.md) — do not open a public issue.
Behaviour that contradicts a contract: open an issue with the client, version, install path and
`probe_mcp.py` output. Issues missing those are hard to act on.

## Licence

Contributions are accepted under Apache-2.0 (see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE)).
