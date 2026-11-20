#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6,<7"]
# ///
"""Validate a user-supplied connector manifest against the package's guarantees.

    uv run --script tools/check_connector.py examples/connectors/mock-itsm.yaml
    uv run --script tools/check_connector.py my-connector.yaml --skills IT-01,IT-02
    uv run --script tools/check_connector.py my-connector.yaml --all-skills

Exit 0 = ready, 1 = partial or rejected, 2 = cannot run.

This is the same evaluation the `check_connector` MCP tool performs, so a result
you get on the command line and a result you get in a session cannot disagree.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "servers"))

from enterprise_core import governance, registry  # noqa: E402


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args:
        print(__doc__)
        return 2

    path = Path(args[0])
    if not path.exists():
        print(f"[FAIL] no manifest at {path}", file=sys.stderr)
        return 2
    manifest = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    skill_ids: list[str] = []
    if "--all-skills" in flags:
        skill_ids = sorted(registry.skills())
    for flag in flags:
        if flag.startswith("--skills="):
            skill_ids = [s.strip() for s in flag.split("=", 1)[1].split(",") if s.strip()]
    for arg in args[1:]:
        skill_ids += [s.strip() for s in arg.split(",") if s.strip()]

    print(f"\nCONNECTOR  {manifest.get('connector', '<unnamed>')}")
    print(f"SOURCE     {path}")
    print(f"TRANSPORT  {manifest.get('transport', '<none>')}")
    print(f"CATEGORIES {manifest.get('system_categories') or '<none>'}\n")

    result = governance.evaluate_connector(manifest, skill_ids)

    failures = [c for c in result["structural_checks"] if c["status"] != "pass"]
    print(f"STRUCTURE — {len(result['structural_checks']) - len(failures)}/"
          f"{len(result['structural_checks'])} checks pass")
    for c in failures:
        print(f"  [FAIL] {c['rule']}: {c['detail']}")
    if not failures:
        print("  [OK] manifest, obligations and tool declarations are complete")

    print(f"\nTOOLS — {len(result['tools'])} declared, "
          f"usable operation classes: {result['available_operations'] or 'none'}")
    for tool in result["tools"]:
        mark = "OK  " if not tool["problems"] else "FAIL"
        print(f"  [{mark}] {tool['name']} ({tool['operation']})", end="")
        if tool["problems"]:
            print(" — " + "; ".join(tool["problems"]), end="")
        print()

    if result["skills"]:
        print(f"\nSKILL FIT — {result['skills_satisfied']}/{result['skills_requested']} satisfied")
        for row in result["skills"]:
            if row["satisfied"]:
                print(f"  [OK ] {row['skill_id']}: may call "
                      f"{row.get('allowed_tools') or 'nothing (no tool in its categories)'}")
                continue
            print(f"  [GAP] {row['skill_id']} {row.get('skill_name', '')}: {row['reason']}")
            covered = row.get("categories_covered") or []
            if not covered:
                print(f"        contract expects categories "
                      f"{row.get('categories_declared_by_contract')} — connector declares none of them")

    print(f"\nDECISION  {result['decision'].upper()}")
    print(f"  {result['next_action']}")
    print(f"  {result['caveat']}\n")

    return 0 if result["decision"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
