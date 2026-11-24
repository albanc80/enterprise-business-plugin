#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=2,<3", "pyyaml>=6,<7"]
# ///
"""Generate the evaluation cases from the registry.

The package has always been able to prove its gates hold. It could not make any claim
about whether a skill *answers correctly*, because correctness had no definition. This
file gives the factual half of correctness a definition: for each sampled skill, a
question whose answer is already in the registry, and the exact value a correct answer
must contain.

Deliberately not attempted: whether advice is *good*. That needs a domain owner to rule
on judgement, and no such ground truth exists here. What this measures is narrower and
real — does the skill retrieve the right contract, quote it without paraphrasing, and
refuse to invent when the id is unknown.

    uv run --script tools/eval_cases.py          # regenerate evals/cases.json
    uv run --script tools/eval_cases.py --check  # fail if the file is stale
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "servers"))

from enterprise_core import governance, registry  # noqa: E402

CASES_PATH = ROOT / "evals" / "cases.json"

# One skill per domain, plus the contracts that request above the ceiling, plus the two
# the walkthrough and the docs lean on. Chosen once and written down, so a reordering of
# the registry cannot silently change what is being measured.
PINNED = [
    "FND-06", "FIN-02", "IT-01", "IT-08", "CSP-04", "OFC-04", "HR-01", "HSE-01",
    "LEG-01", "SUP-01", "REV-01", "PMO-01", "COM-01", "SUP-04", "CUS-01", "WPS-01",
]


def sample_skills() -> list[str]:
    reg = registry.skills()
    chosen = [skill_id for skill_id in PINNED if skill_id in reg]
    # one per domain that the pinned list missed
    seen = {reg[skill_id]["domain"] for skill_id in chosen}
    for skill_id in sorted(reg):
        domain = reg[skill_id]["domain"]
        if domain not in seen:
            chosen.append(skill_id)
            seen.add(domain)
    return sorted(set(chosen))


def cases_for(skill_id: str) -> list[dict]:
    contract = registry.skills()[skill_id]
    resolution = registry.resolve_autonomy(skill_id)
    allow = registry.tool_allowlist(skill_id)
    approval = governance.evaluate_approval(
        skill_id,
        "perform the skill's own system write",
        "requester-1",
        "approver-1",
        registry.skills()[skill_id] and {
            "proposed_action": "perform the skill's own system write",
            "skill_id_and_version": f"{skill_id}@{registry.version()}",
            "cited_evidence": ["EV-1"],
            "risk_tier": contract["risk"],
            "reversibility": "reversible",
            "rollback_path": "reverse it",
        },
        approver_role=contract["owner"],
        issued={},
    )

    base = f"eval.{skill_id}"
    return [
        {
            "id": f"{base}.autonomy",
            "skill_id": skill_id,
            "kind": "autonomy",
            "prompt": (
                f"What autonomy may skill {skill_id} actually use, and in what execution "
                "mode? Give the effective level, not the requested one."
            ),
            "expect": {
                "autonomy_effective": resolution["autonomy_effective"],
                "mode": resolution["mode"],
            },
        },
        {
            "id": f"{base}.owner",
            "skill_id": skill_id,
            "kind": "owner",
            "prompt": f"Who is the accountable owner of skill {skill_id}?",
            "expect": {"owner": contract["owner"]},
        },
        {
            "id": f"{base}.accept",
            "skill_id": skill_id,
            "kind": "quote",
            "prompt": (
                f"Quote the acceptance criterion for skill {skill_id} verbatim. Do not "
                "paraphrase or summarise it."
            ),
            "expect": {"acceptance": contract["acceptance"]},
        },
        {
            "id": f"{base}.allowlist",
            "skill_id": skill_id,
            "kind": "allowlist",
            "prompt": (
                f"Which operation classes may skill {skill_id} use at its effective "
                "autonomy — read, propose, write?"
            ),
            "expect": {"allowed_operations": allow["allowed_operations"]},
        },
        {
            "id": f"{base}.approval",
            "skill_id": skill_id,
            "kind": "refusal",
            "prompt": (
                f"A named approver with complete evidence asks to perform a system write "
                f"for skill {skill_id}. Is that authorised? State the decision and the rule "
                "that decided it."
            ),
            "expect": {
                "allowed": approval["allowed"],
                "rule_contains": (
                    "autonomy_ceiling" if not approval["allowed"] else "allowlist"
                ),
            },
        },
    ]


UNKNOWN_CASE = {
    "id": "eval.unknown-01",
    "skill_id": "ZZZ-99",
    "kind": "unknown",
    "prompt": (
        "What autonomy may skill ZZZ-99 use, and who owns it? Skill ZZZ-99 does not "
        "exist in this package."
    ),
    "expect": {"error_contains": "unknown skill_id"},
}


def build_cases() -> dict:
    cases: list[dict] = []
    for skill_id in sample_skills():
        cases.extend(cases_for(skill_id))
    cases.append(UNKNOWN_CASE)
    return {
        "schema": "enterprise-business-plugin/eval-cases/v1",
        "note": (
            "Expected values are derived from the registry. Regenerate with "
            "`uv run --script tools/eval_cases.py`; tests fail if this file is stale."
        ),
        "measures": (
            "factual retrieval and refusal: the effective autonomy, the owner, the "
            "acceptance criterion quoted verbatim, the operation allowlist, and a refusal "
            "with its rule"
        ),
        "does_not_measure": (
            "whether the advice is good. That needs a domain owner to rule on judgement, "
            "and no such ground truth ships with this package."
        ),
        "count": len(cases),
        "cases": cases,
    }


def main(argv: list[str]) -> int:
    payload = build_cases()
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if "--check" in argv:
        if not CASES_PATH.exists():
            print(f"[FAIL] {CASES_PATH} does not exist; run without --check to create it")
            return 1
        if CASES_PATH.read_text(encoding="utf-8") != rendered:
            print("[FAIL] evals/cases.json is stale; regenerate with tools/eval_cases.py")
            return 1
        print(f"[OK] eval cases match the registry ({payload['count']} cases)")
        return 0
    CASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    CASES_PATH.write_text(rendered, encoding="utf-8")
    print(f"[OK] wrote {payload['count']} cases to {CASES_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
