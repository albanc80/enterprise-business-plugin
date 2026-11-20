# Public release notes

This package is published publicly under Apache-2.0. This file records what was checked before
that decision, so the reasoning survives the session that made it.

## Provenance

| Item | Origin | Confidential? |
|---|---|---|
| 93 capability contracts | Author's own requirements document — **not published**; only `src/registry/source.json` + its SHA-256 ships | No |
| 32 testable requirements | Same SRD | No |
| Autonomy tiers, risk matrix, safeguards | Same SRD, itself aligned to public standards | No |
| 16 skills | Written for this package | No |
| Governance server and policies | Written for this package | No |
| Referenced standards (NIST, ISO, OWASP) | Public documents, cited only | No |

The SRD was written to be vendor-neutral and industry-neutral. It names no employer, no customer,
no product and no internal system. Verified by search before publishing: no organisation name, no
internal hostname, no document ID and no proprietary threshold appears anywhere in the tree.

## What was deliberately excluded

- Any reference to the tool or platform that generated the SRD.
- Any branch name, commit reference or internal project path.
- Any real process metric. Every number in the registry is a target from the source document;
  no observed baseline, no customer figure, no internal cost is included.
- Screenshots and listing assets. They matter only for directory submission, which is a separate
  decision.

## Reproducibility

`src/registry/` is generated, and the document that starts the chain stays private:

```
requirements document (local only)  ->  tools/extract_srd.py  ->  src/registry/source.json (+ sha256)
                                                              ->  tools/build.py     ->  src/registry/*.yaml
```

The document is excluded via `.gitignore` (`docs/srd/`). What ships is the normalized projection
and the hash, so a reader can verify fidelity without the source being in the repo — and CI still
fails if the registry drifts from the projection.

`tools/build.py --check` fails if the tree drifts from the document, and CI runs it on every
push. The source document ships with the package precisely so this stays auditable: anyone
receiving the repo can regenerate the contracts and confirm the published numbers.

## Deliberate limitations of the release

- **No connectors.** The package installs and is useful for drafting and governance reasoning;
  it cannot act on a live system. Anyone integrating their own system is doing so under their own
  threat model.
- **Unvalidated.** All 93 capabilities are marked `Proposed / unvalidated`. Publishing them is
  not a claim that they work — it is a claim that the contracts are well-formed, governed and
  worth adopting.
- **Reference implementation.** The governance server enforces the model's rules but is not a
  hardened service: no authentication layer, in-process approval ledger, no external audit
  anchor. See `SECURITY.md`.

## Licence reasoning

Apache-2.0, consistent with the pack this was built alongside. The permissive choice is deliberate:
the artefact's value is in the contract format and the governance model, and adoption matters more
than control. A copyleft licence would have been the alternative, and it would have been wrong here
— enterprises cannot adopt a governance template they cannot adapt.
