"""Tool allowlist tests — the FR-04 gap this package had.

The rule these lock in: at A0/A1 a capability may read, and nothing else. A write
tool is unreachable until a skill is deliberately opted into A2. If that stops
being true, these fail.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "servers"))

from enterprise_core import governance, registry  # noqa: E402

SHIPPED_CONFIG = json.loads(json.dumps(registry.autonomy_config()))
ITSM = yaml.safe_load(
    (ROOT / "examples" / "connectors" / "mock-itsm.yaml").read_text(encoding="utf-8")
)


# ------------------------------------------------------------------- coverage


def test_every_contract_has_an_allowlist_entry():
    entries = registry.allowlist_registry()
    assert set(entries) == set(registry.skills())
    for sid, entry in entries.items():
        assert entry["categories"], f"{sid} has no categories"


def test_no_skill_allows_write_at_the_shipped_ceiling():
    for sid in registry.skills():
        allow = registry.tool_allowlist(sid)
        assert allow["allowed_operations"] == ["read"], sid


def test_a2_requesting_skill_reports_withheld_operations():
    """IT-01 asks for A2; at the shipped ceiling it reads only, and says what it lost."""
    allow = registry.tool_allowlist("IT-01")
    assert allow["effective_autonomy"] == "A1"
    assert allow["allowed_operations"] == ["read"]
    assert allow["withheld_operations"] == ["propose", "write"]


def test_unknown_skill_raises_rather_than_guessing():
    try:
        registry.tool_allowlist("ZZZ-99")
    except KeyError as exc:
        assert "unknown skill_id" in str(exc)
    else:
        raise AssertionError("an unknown skill must not produce an allowlist")


# --------------------------------------------------------------- call decisions


def test_read_call_in_a_declared_category_is_allowed():
    verdict = governance.evaluate_tool_call("IT-01", "itsm.get_incident", "read", "ITSM")
    assert verdict["allowed"] is True
    assert verdict["rule"] == "allowlist"


def test_write_call_at_a1_is_denied():
    verdict = governance.evaluate_tool_call("IT-01", "itsm.create_ticket", "write", "ITSM")
    assert verdict["allowed"] is False
    assert verdict["rule"] == "operation_not_permitted"
    assert "A1" in verdict["reason"]


def test_call_in_an_undeclared_category_is_denied():
    """IT-01's contract covers ITSM/IAM/CMDB — not payroll."""
    verdict = governance.evaluate_tool_call("IT-01", "hr.get_salary", "read", "HRIS")
    assert verdict["allowed"] is False
    assert verdict["rule"] == "category_not_declared"


def test_rejected_connector_blocks_every_call():
    verdict = governance.evaluate_tool_call(
        "IT-01", "itsm.get_incident", "read", "ITSM", connector_status="rejected"
    )
    assert verdict["allowed"] is False
    assert verdict["rule"] == "connector_not_conformant"


def test_unknown_skill_denies():
    verdict = governance.evaluate_tool_call("ZZZ-99", "x", "read", "ITSM")
    assert verdict["allowed"] is False
    assert verdict["rule"] == "unknown_skill"


def test_empty_tool_name_denies():
    verdict = governance.evaluate_tool_call("IT-01", "  ", "read", "ITSM")
    assert verdict["allowed"] is False
    assert verdict["rule"] == "missing_tool"


# --------------------------------------------------- the A2 path, once opted in


def a2_opt_in(skill_id: str):
    cfg = json.loads(json.dumps(SHIPPED_CONFIG))
    cfg["opt_in"]["a2_skills"] = [
        {
            "skill": skill_id,
            "named_process_owner": "service-desk-lead",
            "approval_gate_configured": True,
            "audit_trail_enabled": True,
            "rollback_path": "close the created ticket",
        }
    ]
    return cfg


def test_write_becomes_permitted_only_after_a2_opt_in(monkeypatch):
    assert not governance.evaluate_tool_call(
        "IT-01", "itsm.create_ticket", "write", "ITSM"
    )["allowed"]

    monkeypatch.setattr(registry, "autonomy_config", lambda: a2_opt_in("IT-01"))
    verdict = governance.evaluate_tool_call("IT-01", "itsm.create_ticket", "write", "ITSM")
    assert verdict["allowed"] is True
    assert verdict["effective_autonomy"] == "A2"


def test_a2_still_denies_an_undeclared_category(monkeypatch):
    monkeypatch.setattr(registry, "autonomy_config", lambda: a2_opt_in("IT-01"))
    verdict = governance.evaluate_tool_call("IT-01", "hr.set_salary", "write", "HRIS")
    assert verdict["allowed"] is False
    assert verdict["rule"] == "category_not_declared"


# ------------------------------------------------- concrete tools per connector


def test_connector_turns_the_rule_into_tool_names():
    result = governance.evaluate_connector(ITSM, ["IT-01"])
    row = result["skills"][0]
    assert row["allowed_tools"] == ["itsm.get_incident", "itsm.list_assets"]
    assert "itsm.create_ticket" in row["withheld_tools"]
    assert "itsm.propose_assignment" in row["withheld_tools"]


def test_connector_tools_outside_the_skills_categories_are_withheld():
    """FIN-03 is AP/AR, ERP and expense — an ITSM connector reaches nothing."""
    result = governance.evaluate_connector(ITSM, ["FIN-03"])
    row = result["skills"][0]
    assert row["allowed_tools"] == []
    assert set(row["withheld_tools"]) == {
        "itsm.get_incident", "itsm.list_assets", "itsm.propose_assignment", "itsm.create_ticket"
    }


def test_per_tool_category_overrides_the_connector_default():
    manifest = json.loads(json.dumps(ITSM))
    manifest["system_categories"] = ["ITSM"]
    manifest["tools"].append(
        {
            "name": "erp.get_invoice",
            "operation": "read",
            "resource": "invoice",
            "schema_version": "1",
            "category": "erp",
        }
    )
    result = governance.evaluate_connector(manifest, ["FIN-01", "IT-01"])
    rows = {r["skill_id"]: r for r in result["skills"]}
    assert rows["FIN-01"]["allowed_tools"] == ["erp.get_invoice"]
    assert "erp.get_invoice" not in rows["IT-01"]["allowed_tools"]


# ------------------------------------------------------------------ policy shape


def test_policy_denies_by_default_and_a1_is_read_only():
    policy = registry.tool_allowlist_policy()
    assert policy["default_decision"] == "deny"
    assert policy["operations_by_autonomy"]["A0"] == ["read"]
    assert policy["operations_by_autonomy"]["A1"] == ["read"]
    assert "enforcement_contract" in policy
