#!/usr/bin/env python3
"""Generate the registry from the normalized source contract set.

Nothing in `src/registry/` is hand-edited. Every value comes from
`src/registry/source.json` — the published, normalized projection of the requirements
document — so a regenerated tree either matches it or `tools/validate.py` fails.

The requirements document itself is NOT published with this package. source.json
carries its SHA-256, so anyone holding the document can confirm the projection
matches. Regenerating source.json from the document is a local step:
`tools/extract_srd.py`.

    uv run --script tools/build.py            # regenerate
    uv run --script tools/build.py --check    # fail if the tree drifted

The registry keeps the SRD's *requested* autonomy (`A0`..`A3`). It does not
downgrade anything: the shipped ceiling is a runtime policy decision taken by
`servers/enterprise_core` from `src/policies/autonomy-config.yaml`, so changing
the ceiling never rewrites the source contract.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "src" / "registry" / "source.json"
REGISTRY = ROOT / "src" / "registry"
SOURCE_REF = "src/registry/source.json"

HEADER = """\
# GENERATED FILE — do not edit by hand.
# Source: {source}
# Regenerate: uv run --script tools/build.py
"""

# SRD field -> registry field. Order is the reading order of a contract.
FIELD_MAP = [
    ("id", "id"),
    ("domain", "domain"),
    ("name", "name"),
    ("description", "purpose"),
    ("owner", "owner"),
    ("wave", "wave"),
    ("risk", "risk"),
    ("autonomy", "autonomy_requested"),
    ("sideEffects", "side_effects"),
    ("trigger", "trigger"),
    ("inputs", "inputs"),
    ("preconditions", "preconditions"),
    ("outputs", "outputs"),
    ("outputContract", "output_contract"),
    ("kpi", "metric"),
    ("accept", "acceptance"),
    ("exceptions", "escalation"),
    ("failure", "fail_safe"),
    ("privacy", "data_handling"),
    ("mode", "execution_mode"),
    ("systems", "system_categories"),
    ("status", "status"),
]


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr)
    raise SystemExit(1)


REQUIRED_BLOCKS = ("domains", "skills", "requirements", "metrics", "roadmap", "sources")


def load_source() -> dict:
    if not SOURCE.exists():
        fail(
            f"missing {SOURCE.relative_to(ROOT)} — run `uv run --script tools/extract_srd.py "
            "<path-to-srd.html>` with your local copy of the document"
        )
    try:
        data = json.loads(SOURCE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"{SOURCE.name} is not valid JSON: {exc}")
    missing = [k for k in REQUIRED_BLOCKS if k not in data]
    if missing:
        fail(f"{SOURCE.name} is missing blocks: {missing}")
    if "provenance" not in data or not data["provenance"].get("sha256"):
        fail(f"{SOURCE.name} has no provenance / sha256 — re-extract from the document")
    return data


def contract(skill: dict) -> dict:
    out: dict = {}
    for src_key, dst_key in FIELD_MAP:
        if src_key not in skill:
            fail(f"skill {skill.get('id')} is missing SRD field {src_key!r}")
        out[dst_key] = skill[src_key]
    out["scores"] = {
        "impact": skill["impact"],
        "readiness": skill["readiness"],
        "reuse": skill["reuse"],
        "effort": skill["effort"],
    }
    out["autonomy_exceeds_pack_ceiling"] = skill["autonomy"] in {"A2", "A3"}
    out["source"] = SOURCE_REF
    return out


def dump(name: str, payload: dict | list) -> str:
    body = yaml.safe_dump(
        payload,
        sort_keys=False,
        allow_unicode=True,
        width=88,
        default_flow_style=False,
    )
    return HEADER.format(source=SOURCE_REF) + body


def build(data: dict) -> dict[str, str]:
    skills = [contract(s) for s in data["skills"]]
    skills.sort(key=lambda s: (s["wave"], s["domain"], s["id"]))

    domains = [
        {
            "id": d["id"],
            "name": d["name"],
            "description": d["desc"],
            "owner": d["owner"],
            "skill_count": sum(1 for s in data["skills"] if s["domain"] == d["id"]),
        }
        for d in data["domains"]
    ]

    # Per-skill tool allowlists, derived from the contract's own system categories.
    # The categories say what a capability touches; the allowed operation classes are
    # a function of its effective autonomy and live in src/policies/tool-allowlists.yaml.
    allowlists = [
        {
            "skill": s["id"],
            "categories": sorted(
                {c.strip().lower() for c in str(s["system_categories"]).split(",") if c.strip()}
            ),
            "autonomy_requested": s["autonomy_requested"],
        }
        for s in sorted(skills, key=lambda s: s["id"])
    ]

    return {
        "skills.yaml": dump("skills.yaml", {"schema": "enterprise-business-plugin/registry/skills/v1", "skills": skills}),
        "domains.yaml": dump("domains.yaml", {"schema": "enterprise-business-plugin/registry/domains/v1", "domains": domains}),
        "requirements.yaml": dump("requirements.yaml", {"schema": "enterprise-business-plugin/registry/requirements/v1", "requirements": data["requirements"]}),
        "roadmap.yaml": dump("roadmap.yaml", {"schema": "enterprise-business-plugin/registry/roadmap/v1", "waves": data["roadmap"]}),
        "metrics.yaml": dump("metrics.yaml", {"schema": "enterprise-business-plugin/registry/metrics/v1", "metrics": data["metrics"], "note": "Hypothesis targets from the SRD. Not benchmarks and not observed results."}),
        "checklist.yaml": dump("checklist.yaml", {
            "schema": "enterprise-business-plugin/registry/checklist/v1",
            "note": "Production release readiness. Self-marked boxes are not independent validation.",
            "items": [{"id": f"R{i + 1}", "name": c[0], "evidence": c[1]} for i, c in enumerate(data["checklist"])],
            "suggested_pilot": data["pilots"],
            "default_weights": data["weights"],
        }),
        "sources.yaml": dump("sources.yaml", {"schema": "enterprise-business-plugin/registry/sources/v1", "sources": data["sources"]}),
        "tool-allowlists.yaml": dump("tool-allowlists.yaml", {
            "schema": "enterprise-business-plugin/registry/tool-allowlists/v1",
            "note": "Derived from each contract's system_categories. Enforcement is delegated — see src/policies/tool-allowlists.yaml.",
            "skills": allowlists,
        }),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if on-disk files differ")
    args = ap.parse_args()

    data = load_source()
    REGISTRY.mkdir(parents=True, exist_ok=True)
    files = build(data)

    drifted = []
    for name, text in files.items():
        path = REGISTRY / name
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != text:
            drifted.append(name)
            if not args.check:
                path.write_text(text, encoding="utf-8", newline="\n")

    if args.check:
        if drifted:
            print(f"[FAIL] registry drifted: {', '.join(drifted)}", file=sys.stderr)
            return 1
        print(f"[OK] registry matches the SRD ({len(data['skills'])} skills, {len(data['domains'])} domains)")
        return 0

    for name in files:
        mark = "updated" if name in drifted else "unchanged"
        print(f"[{'OK' if name not in drifted else '~~'}] {name} ({mark})")
    print(
        f"[OK] {len(data['skills'])} skill contracts, {len(data['domains'])} domains, "
        f"{len(data['requirements'])} requirements, {len(data['roadmap'])} waves"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
