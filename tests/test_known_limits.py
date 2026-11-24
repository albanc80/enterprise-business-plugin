"""Six limits are accepted by design. These tests assert the gaps still exist.

A limitation that is only described in prose is a belief. Pinning each one as an assertion
means a green suite cannot be read as completeness: if a future change closes a gap, these
fail and the entry in docs/LIMITATIONS.md must be updated rather than quietly going stale.

Each test is written to PASS while the limitation is present.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "servers"))

from enterprise_core import main  # noqa: E402


@pytest.fixture
def audit(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_data_dir", lambda: tmp_path)
    return tmp_path / "audit.jsonl"


def _check(result: dict, rule: str) -> dict:
    for check in result.get("checks", []):
        if check.get("rule") == rule:
            return check
    raise AssertionError(f"no {rule!r} check in the response: {result}")


def _evidence(action: str = "release payment against invoice INV-4471") -> dict:
    return {
        "proposed_action": action,
        "skill_id_and_version": "FIN-02@1.0.0",
        "cited_evidence": ["GRN-9921", "PO-3310"],
        "risk_tier": "Critical",
        "reversibility": "irreversible once settled",
        "rollback_path": "reverse the payment instruction with the bank",
    }


# ------------------------------------------------- L1: the ledger does not survive a restart
def test_l1_restart_voids_outstanding_tokens():
    """A token from a previous process is unknown here — which is the safe direction."""
    result = main.approval_gate(
        skill_id="FIN-02",
        proposed_action="release payment against invoice INV-4471",
        requester_id="alice",
        approver_id="bob",
        evidence=_evidence(),
        approver_role="Finance Controller",
        approval_id="apr_issued_before_the_restart",
        operation="read",
    )
    assert result["allowed"] is False
    assert result.get("rule") == "unissued_approval", result

    # Prove the ledger decided it, not the ceiling: seed the same id and the rule changes.
    main._ISSUED["apr_issued_before_the_restart"] = {
        "skill_id": "FIN-02",
        "operation": "read",
        "action_digest": "not-the-presented-digest",
        "requester": "alice",
        "approver": "bob",
        "approver_role": "Finance Controller",
        "risk": "Critical",
        "issued_at": 0.0,
        "expires_at": 9e9,
        "redeemed_at": None,
    }
    try:
        seeded = main.approval_gate(
            skill_id="FIN-02",
            proposed_action="release payment against invoice INV-4471",
            requester_id="alice",
            approver_id="bob",
            evidence=_evidence(),
            approver_role="Finance Controller",
            approval_id="apr_issued_before_the_restart",
            operation="read",
        )
    finally:
        main._ISSUED.pop("apr_issued_before_the_restart", None)

    assert seeded.get("rule") != "unissued_approval", (
        "if this fails the token path changed shape and L1's description is stale"
    )


# ------------------------------------- L2: nothing outside the file anchors the chain
def test_l2_a_consistently_rewritten_chain_verifies(audit):
    """Rewrite every entry and rehash the whole chain: verification passes.

    Detecting this needs a record of the head kept somewhere the writer cannot reach.
    """
    for n in range(3):
        main.audit_append({"n": n, "outcome": "draft"})

    lines = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 3

    rebuilt, previous = [], main._AUDIT_GENESIS if hasattr(main, "_AUDIT_GENESIS") else "genesis"
    for record in lines:
        forged = {
            "timestamp": record["timestamp"],
            "previous_hash": previous,
            "entry": {"outcome": "rewritten"},
        }
        forged["entry_hash"] = main._entry_hash(forged)
        previous = forged["entry_hash"]
        rebuilt.append(forged)
    audit.write_text(
        "".join(json.dumps(record, sort_keys=True, default=str) + "\n" for record in rebuilt),
        encoding="utf-8",
    )

    trace = main.audit_trace(limit=10)
    assert trace["verified"] is True, "L2 is now closed — update docs/LIMITATIONS.md"
    assert trace["entries"][0]["entry"] == {"outcome": "rewritten"}


def test_l2_tail_truncation_is_still_undetectable(audit):
    for n in range(4):
        main.audit_append({"n": n})
    lines = audit.read_text(encoding="utf-8").splitlines()
    audit.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")
    trace = main.audit_trace(limit=10)
    assert trace["verified"] is True
    assert trace["total"] == 2


# --------------------------------------- L3: the role is authorised, the person is not
def test_l3_role_authorises_but_the_person_is_not_proven():
    """Two different names, the same role: both pass. Identity is the caller's claim."""
    def approved_by(approver_id: str) -> dict:
        return main.approval_gate(
            skill_id="FIN-02",
            proposed_action="release payment against invoice INV-4471",
            requester_id="alice",
            approver_id=approver_id,
            evidence=_evidence(),
            approver_role="Finance Controller",
            operation="read",
        )

    insider = _check(approved_by("bob"), "authorised_approver")
    stranger = _check(approved_by("someone-who-does-not-work-here"), "authorised_approver")

    assert insider["status"] == "pass"
    assert stranger["status"] == "pass", "L3 is now closed — update docs/LIMITATIONS.md"


# ------------------------------------------------- L4: stdio, no auth, no credentials
def test_l4_the_server_speaks_stdio_with_no_auth_layer():
    source = (ROOT / "servers" / "enterprise_core" / "main.py").read_text(encoding="utf-8")
    assert 'mcp.run("stdio")' in source
    assert "socket" not in source and "HTTPServer" not in source

    for name in ("list_skills", "get_contract", "approval_gate", "audit_append", "check_tool_call"):
        params = set(inspect.signature(getattr(main, name)).parameters)
        assert not params & {"token", "api_key", "credential", "password", "session"}, name


# --------------------------------------------- L5: the verdict is category-scoped
def test_l5_tool_name_is_not_resolved():
    """A tool name that cannot exist is still allowed, because the name is not compared."""
    result = main.check_tool_call(
        skill_id="IT-01",
        tool_name="this-tool-cannot-exist-anywhere",
        operation="read",
        category="itsm",
        connector_status="ready",
    )
    assert result["allowed"] is True
    assert result["scope"] == "category"
    assert result["tool_name_verified"] is False


# ---------------------------------------- L6: the operation is the caller's word
def test_l6_operation_is_whatever_the_caller_declares():
    """Declaring `read` over an action described as a payment release passes the check."""
    result = main.approval_gate(
        skill_id="FIN-02",
        proposed_action="release payment against invoice INV-4471",
        requester_id="alice",
        approver_id="bob",
        evidence=_evidence(),
        approver_role="Finance Controller",
        operation="read",
    )
    permitted = _check(result, "operation_permitted")
    assert permitted["status"] == "pass"
    assert "read" in permitted["detail"]
