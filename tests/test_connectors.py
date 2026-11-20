"""Connector conformance tests.

The manifests under examples/connectors are fixtures, not decoration: the good one
must pass and the bad one must fail, or the gate is lying about what it checks.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "servers"))

from enterprise_core import governance, registry  # noqa: E402

CONNECTORS = ROOT / "examples" / "connectors"
SHIPPED_CONFIG = json.loads(json.dumps(registry.autonomy_config()))


def load(name: str) -> dict:
    return yaml.safe_load((CONNECTORS / name).read_text(encoding="utf-8"))


def failing_rules(result: dict) -> set[str]:
    return {c["rule"] for c in result["structural_checks"] if c["status"] != "pass"}


# --------------------------------------------------------------- positive case


def test_conforming_manifest_is_ready_for_read_skills():
    result = governance.evaluate_connector(load("mock-itsm.yaml"), ["IT-01", "IT-02", "IT-04"])
    assert result["decision"] == "ready", result["next_action"]
    assert failing_rules(result) == set()
    assert result["skills_satisfied"] == 3


def test_conforming_connector_serves_only_its_own_categories():
    """An ITSM connector serves the IT skills and cannot serve finance ones."""
    itsm_skills = [
        sid for sid, c in registry.skills().items()
        if "itsm" in str(c["system_categories"]).lower()
    ]
    result = governance.evaluate_connector(load("mock-itsm.yaml"), itsm_skills)
    assert result["skills_satisfied"] == len(itsm_skills)
    assert result["decision"] == "ready"

    finance = governance.evaluate_connector(load("mock-itsm.yaml"), ["FIN-01", "FIN-03"])
    assert finance["skills_satisfied"] == 0
    assert finance["decision"] == "partial"
    row = finance["skills"][0]
    assert row["allowed_tools"] == []
    assert "none in this skill's categories" in row["reason"]


def test_operation_classes_are_reported():
    result = governance.evaluate_connector(load("mock-itsm.yaml"))
    assert result["available_operations"] == ["propose", "read", "write"]
    assert all(not t["problems"] for t in result["tools"])


# --------------------------------------------------------------- negative case


def test_non_conforming_manifest_is_rejected():
    result = governance.evaluate_connector(load("bad-time-entry.yaml"), ["FIN-03"])
    assert result["decision"] == "rejected"
    rules = failing_rules(result)
    assert "connector.no_ambient_credentials" in rules
    assert "connector.bounded_retry" in rules
    assert "connector.least_privilege" in rules
    assert "forbidden.ambient_credentials" in rules
    assert "forbidden.unbounded_retry" in rules


def test_write_without_rollback_is_caught():
    manifest = load("mock-itsm.yaml")
    for tool in manifest["tools"]:
        if tool["operation"] == "write":
            tool.pop("rollback")
    result = governance.evaluate_connector(manifest)
    assert result["decision"] == "rejected"
    assert "tools.well_formed" in failing_rules(result)
    bad = next(t for t in result["tools"] if t["operation"] == "write")
    assert any("rollback" in p for p in bad["problems"])


def test_write_with_declared_no_rollback_is_caught():
    manifest = load("mock-itsm.yaml")
    for tool in manifest["tools"]:
        if tool["operation"] == "write":
            tool["rollback"] = "none"
    result = governance.evaluate_connector(manifest)
    assert result["decision"] == "rejected"
    bad = next(t for t in result["tools"] if t["operation"] == "write")
    assert any("irreversible" in p for p in bad["problems"])


def test_write_without_idempotency_key_is_caught():
    manifest = load("mock-itsm.yaml")
    for tool in manifest["tools"]:
        if tool["operation"] == "write":
            tool.pop("idempotency_key")
    result = governance.evaluate_connector(manifest)
    assert result["decision"] == "rejected"
    bad = next(t for t in result["tools"] if t["operation"] == "write")
    assert any("idempotency_key" in p for p in bad["problems"])


def test_unknown_operation_is_caught():
    manifest = load("mock-itsm.yaml")
    manifest["tools"].append(
        {"name": "itsm.mutate", "operation": "mutate", "resource": "x", "schema_version": "1"}
    )
    result = governance.evaluate_connector(manifest)
    assert result["decision"] == "rejected"


def test_missing_connector_obligation_is_caught():
    manifest = load("mock-itsm.yaml")
    manifest.pop("audit_passthrough")
    result = governance.evaluate_connector(manifest)
    assert result["decision"] == "rejected"
    assert "connector.audit_passthrough" in failing_rules(result)


# --------------------------------------------------------------- read-only gap


def test_read_only_connector_is_partial_for_an_a2_skill(monkeypatch):
    """An opted-in A2 skill needs a write tool; reads alone must be reported as a gap."""
    cfg = json.loads(json.dumps(SHIPPED_CONFIG))
    cfg["opt_in"]["a2_skills"] = [
        {
            "skill": "IT-01",
            "named_process_owner": "service-desk-lead",
            "approval_gate_configured": True,
            "audit_trail_enabled": True,
            "rollback_path": "close the created ticket",
        }
    ]
    monkeypatch.setattr(registry, "autonomy_config", lambda: cfg)

    manifest = load("mock-itsm.yaml")
    manifest["tools"] = [t for t in manifest["tools"] if t["operation"] == "read"]

    result = governance.evaluate_connector(manifest, ["IT-01"])
    assert result["decision"] == "partial"
    row = result["skills"][0]
    assert row["required_operation"] == "write"
    assert row["satisfied"] is False
    assert "needs a write tool" in row["reason"]


def test_unknown_skill_id_is_reported_not_guessed():
    result = governance.evaluate_connector(load("mock-itsm.yaml"), ["ZZZ-99"])
    assert result["skills"][0]["satisfied"] is False
    assert "unknown skill" in result["skills"][0]["reason"]
    assert result["decision"] == "partial"


# ------------------------------------------------------------------- fixtures


def test_shipped_connector_fixtures_encode_their_intent():
    """The examples must stay honest: good passes, bad fails."""
    assert governance.evaluate_connector(load("mock-itsm.yaml"), ["IT-01"])["decision"] == "ready"
    assert governance.evaluate_connector(load("bad-time-entry.yaml"), [])["decision"] == "rejected"


def test_no_connector_ships_with_the_package():
    """The policy declares the interface; no connector is bundled as if it were real."""
    shipped = [p for p in (ROOT / "servers").rglob("*") if p.suffix in {".py", ".yaml"}]
    assert shipped, "servers should exist"
    for path in shipped:
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        assert "requests." not in text and "urllib.request" not in text, (
            f"{path} appears to make network calls; this package ships no connector"
        )
