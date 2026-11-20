#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6,<7"]
# ///
"""Data-driven walkthrough of the governed path — and therefore an integration test.

Runs a scenario file against the real registry, the real policies and the real
approval/release evaluators. Exits non-zero when reality disagrees with the
scenario's stated expectations, so CI can fail on it.

    uv run --script examples/governance_walkthrough.py
    uv run --script examples/governance_walkthrough.py examples/ap-exception-scenario.json

No server, no network, no enterprise connection: this exercises governance logic only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "servers"))

from enterprise_core import governance, registry  # noqa: E402

SCENARIO = ROOT / "examples" / "ap-exception-scenario.json"

failures: list[str] = []


def check(label: str, actual, expected, note: str = "") -> None:
    ok = actual == expected
    print(f"  [{'OK' if ok else 'FAIL'}] {label}: {actual!r}" + (f" (expected {expected!r})" if not ok else ""))
    if note and ok:
        print(f"         {note}")
    if not ok:
        failures.append(label)


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else SCENARIO
    scenario = json.loads(path.read_text(encoding="utf-8"))
    exp = scenario["expectations"]
    skill_id = scenario["skill_id"]

    print(f"\nSCENARIO  {scenario['name']}")
    print(f"SOURCE    {path.name}")
    print(f"WHY       {scenario['why']}\n")

    contract = registry.skills()[skill_id]
    print(f"CONTRACT  {skill_id} — {contract['name']}")
    print(f"          owner: {contract['owner']} | risk: {contract['risk']} | "
          f"requests: {contract['autonomy_requested']} | wave: {contract['wave']}")
    print(f"          metric: {contract['metric']}")
    print(f"          acceptance: {contract['acceptance']}\n")

    print("1. PERMISSION — package ceiling ∩ risk cap ∩ request")
    resolution = registry.resolve_autonomy(skill_id, scenario["requested_level"])
    check("effective level", resolution["autonomy_effective"], exp["effective_level"])
    check("mode", resolution["mode"], exp["mode"])
    check("downgrade reported", resolution["downgrade_applied"], exp["downgrade_reported"])
    for downgrade in resolution["downgrades"]:
        print(f"         {downgrade['from']} -> {downgrade['to']}: {downgrade['reason']}")
    print(f"         may:     {resolution['may']}")
    print(f"         may not: {resolution['may_not']}")
    print(f"         next:    {resolution['next_action']}\n")
    assert resolution["mode"] != "auto", "a Critical-risk capability must never resolve to auto"

    print("2. APPROVAL — incomplete evidence must deny, never degrade")
    denied = governance.evaluate_approval(
        skill_id, scenario["proposed_action"], scenario["requester"], scenario["approver"],
        {"proposed_action": scenario["proposed_action"]},
        approver_role=scenario["approver_role"],
    )
    check("approval without evidence", "denied" if not denied["allowed"] else "granted",
          exp["approval_without_evidence"])
    for check_row in denied["checks"]:
        if check_row["status"] != "pass":
            print(f"         {check_row['rule']}: {check_row['detail']}")
    print(f"         next: {denied['next_action']}\n")

    print("3. APPROVAL — complete evidence issues a one-shot token")
    redeemed: set[str] = set()
    granted = governance.evaluate_approval(
        skill_id, scenario["proposed_action"], scenario["requester"], scenario["approver"],
        scenario["evidence"], approver_role=scenario["approver_role"], redeemed=redeemed,
    )
    check("approval with evidence", "granted" if granted["allowed"] else "denied",
          exp["approval_with_evidence"])
    token = granted.get("approval_id")
    print(f"         token: {token}")
    print(f"         bound to action digest: {str(granted.get('action_digest'))[:16]}…")
    print(f"         next: {granted['next_action']}\n")

    print("4. REDEMPTION — an approval authorises one action, once")
    first = governance.evaluate_approval(
        skill_id, scenario["proposed_action"], scenario["requester"], scenario["approver"],
        scenario["evidence"], approver_role=scenario["approver_role"],
        approval_id=token, redeemed=redeemed,
    )
    second = governance.evaluate_approval(
        skill_id, scenario["proposed_action"], scenario["requester"], scenario["approver"],
        scenario["evidence"], approver_role=scenario["approver_role"],
        approval_id=token, redeemed=redeemed,
    )
    check("first redemption", "granted" if first["allowed"] else "denied", "granted")
    check("second redemption", "denied" if not second["allowed"] else "granted",
          exp["second_redemption"])
    print(f"         {second.get('error', '')}\n")

    print("5. RELEASE — evidence gaps block deployment, pilot included")
    release = governance.evaluate_release(skill_id, scenario["release_evidence"])
    check("release decision", release["decision"], exp["release_decision"])
    for gate in release["gates"]:
        print(f"         {gate['id']} {gate['name']}: {gate['status']}")
        if gate["missing"]:
            print(f"            missing: {', '.join(gate['missing'])}")
    print(f"         {release['next_action']}")
    print(f"         caveat: {release['caveat']}\n")

    print("6. SCORING — a hypothesis, and it says so")
    ranked = registry.score(contract)
    print(f"         opportunity score {ranked}/100 — {registry.scoring_policy()['caveat']}\n")

    if failures:
        print(f"WALKTHROUGH FAILED — {len(failures)} disagreement(s): {', '.join(failures)}")
        return 1
    print("WALKTHROUGH OK — governance path behaves as the scenario states")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
