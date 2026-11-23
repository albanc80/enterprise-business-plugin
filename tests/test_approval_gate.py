"""The approval gate must refuse these specific attacks.

Each test here is a finding from an external review of v0.1.0, kept as a permanent
regression. The happy path already had a test; none of these did, which is why a gate
that could not tell an issued token from an invented string shipped in a package whose
entire claim is that approvals are verified rather than trusted.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "servers"))

from enterprise_core import governance, registry  # noqa: E402


def evidence(skill_id: str = "FIN-02", risk: str = "Critical") -> dict:
    return {
        "proposed_action": "release payment against invoice INV-4471",
        "skill_id_and_version": f"{skill_id}@1.0.0",
        "cited_evidence": ["GRN-9921", "PO-3310"],
        "risk_tier": risk,
        "reversibility": "irreversible once settled",
        "rollback_path": "reverse the payment instruction with the bank",
    }


@pytest.fixture
def a2_deployment(monkeypatch):
    """A deployment that has opted a skill into A2.

    The shipped package cannot reach A2, so the token lifecycle is only reachable in a
    deployment that has done the opt-in work (owner named, approval gate configured,
    audit on, rollback path defined). Simulating it here keeps the lifecycle tested
    without weakening the shipped ceiling.
    """
    real = registry.resolve_autonomy

    def fake(skill_id, *args, **kwargs):
        resolved = dict(real(skill_id, *args, **kwargs))
        resolved["mode"] = "human_confirm"
        resolved["autonomy_effective"] = "A2"
        return resolved

    monkeypatch.setattr(registry, "resolve_autonomy", fake)
    return fake


def issue(skill_id: str, ledger: dict, action: str | None = None, **kwargs):
    return governance.evaluate_approval(
        skill_id,
        action or evidence(skill_id)["proposed_action"],
        "requester-1",
        "approver-1",
        evidence(skill_id),
        approver_role="finance-controller",
        issued=ledger,
        **kwargs,
    )


# --------------------------------------------------------------- P0: forged tokens
def test_unissued_approval_id_is_refused():
    """An id the server never issued must not be redeemable."""
    ledger: dict = {}
    result = governance.evaluate_approval(
        "FIN-02",
        evidence()["proposed_action"],
        "requester-1",
        "approver-1",
        evidence(),
        approver_role="finance-controller",
        approval_id="apr_deadbeefcafe0001",
        issued=ledger,
    )
    assert result["allowed"] is False
    assert result["rule"] == "unissued_approval"


def test_token_cannot_be_redeemed_from_a_different_ledger(a2_deployment):
    issued: dict = {}
    other: dict = {}
    token = issue("FIN-02", issued)["approval_id"]

    stolen = governance.evaluate_approval(
        "FIN-02",
        evidence()["proposed_action"],
        "requester-1",
        "approver-1",
        evidence(),
        approver_role="finance-controller",
        approval_id=token,
        issued=other,
    )
    assert stolen["allowed"] is False
    assert stolen["rule"] == "unissued_approval"


# --------------------------------------------------- P0: token reused for another action
def test_changed_action_is_refused(a2_deployment):
    ledger: dict = {}
    token = issue("FIN-02", ledger)["approval_id"]

    changed = governance.evaluate_approval(
        "FIN-02",
        "release payment to a different supplier for USD 4,000,000",
        "requester-1",
        "approver-1",
        evidence(),
        approver_role="finance-controller",
        approval_id=token,
        issued=ledger,
    )
    assert changed["allowed"] is False
    assert changed["rule"] == "action_changed"


def test_changed_evidence_is_refused(a2_deployment):
    ledger: dict = {}
    token = issue("FIN-02", ledger)["approval_id"]
    tampered = evidence()
    tampered["cited_evidence"] = ["GRN-0000"]

    result = governance.evaluate_approval(
        "FIN-02",
        evidence()["proposed_action"],
        "requester-1",
        "approver-1",
        tampered,
        approver_role="finance-controller",
        approval_id=token,
        issued=ledger,
    )
    assert result["allowed"] is False
    assert result["rule"] == "action_changed"


def test_token_cannot_cross_skills(a2_deployment):
    ledger: dict = {}
    token = issue("FIN-02", ledger)["approval_id"]

    result = governance.evaluate_approval(
        "IT-01",
        evidence()["proposed_action"],
        "requester-1",
        "approver-1",
        evidence(),
        approver_role="finance-controller",
        approval_id=token,
        issued=ledger,
    )
    assert result["allowed"] is False
    assert result["rule"] == "scope_mismatch"


def test_operation_cannot_be_widened_on_redeem(a2_deployment):
    ledger: dict = {}
    token = issue("FIN-02", ledger, operation="read")["approval_id"]

    result = governance.evaluate_approval(
        "FIN-02",
        evidence()["proposed_action"],
        "requester-1",
        "approver-1",
        evidence(),
        approver_role="finance-controller",
        approval_id=token,
        operation="write",
        issued=ledger,
    )
    assert result["allowed"] is False
    assert result["rule"] == "scope_mismatch"


def test_issued_token_is_single_use(a2_deployment):
    ledger: dict = {}
    granted = issue("FIN-02", ledger)
    assert granted["allowed"] is True
    token = granted["approval_id"]

    common = dict(
        skill_id="FIN-02",
        proposed_action=evidence()["proposed_action"],
        requester_id="requester-1",
        approver_id="approver-1",
        evidence=evidence(),
        approver_role="finance-controller",
        approval_id=token,
        issued=ledger,
    )
    assert governance.evaluate_approval(**common)["allowed"] is True
    replay = governance.evaluate_approval(**common)
    assert replay["allowed"] is False
    assert replay["rule"] == "already_redeemed"


def test_expired_token_is_refused(a2_deployment):
    ledger: dict = {}
    granted = issue("FIN-02", ledger)

    result = governance.evaluate_approval(
        "FIN-02",
        evidence()["proposed_action"],
        "requester-1",
        "approver-1",
        evidence(),
        approver_role="finance-controller",
        approval_id=granted["approval_id"],
        issued=ledger,
        now=granted["expires_at"] + 1,
    )
    assert result["allowed"] is False
    assert result["rule"] == "expired"


# ------------------------------------------------ P1: no token for a draft-only skill
def test_no_token_is_issued_for_a_draft_only_skill():
    """FIN-02 is A1 by contract and by ceiling: it may not release a payment."""
    ledger: dict = {}
    result = governance.evaluate_approval(
        "FIN-02",
        "release payment against invoice INV-4471",
        "requester-1",
        "approver-1",
        evidence(),
        approver_role="finance-controller",
        operation="write",
        issued=ledger,
    )
    assert result["allowed"] is False
    assert "autonomy_ceiling" in result["failed_rules"]
    assert "approval_id" not in result
    assert ledger == {}


def test_every_skill_is_refused_at_the_shipped_ceiling():
    """No skill may be issued a token while the package ships A1."""
    issued: dict = {}
    refused = []
    for skill_id in registry.skills():
        result = governance.evaluate_approval(
            skill_id,
            evidence(skill_id)["proposed_action"],
            "requester-1",
            "approver-1",
            evidence(skill_id),
            approver_role="finance-controller",
            issued=issued,
        )
        if not result["allowed"]:
            refused.append(skill_id)
    assert len(refused) == len(registry.skills()), "every skill must refuse at A1"
    assert issued == {}, "no token may exist for any skill at the shipped ceiling"


# -------------------------------------------------- P1: separation of duties bypass
@pytest.mark.parametrize(
    "approver",
    ["ALICE", "alice ", " Alice", "alice\t", "ALICE  ", "alice\u00a0"],
)
def test_separation_of_duties_ignores_case_and_whitespace(a2_deployment, approver):
    """Same person, different spelling, must still be self-approval."""
    result = governance.evaluate_approval(
        "FIN-02",
        evidence()["proposed_action"],
        "alice",
        approver,
        evidence(),
        approver_role="finance-controller",
        issued={},
    )
    assert result["allowed"] is False
    assert "separation_of_duties" in result["failed_rules"]


def test_a_genuinely_different_approver_is_accepted(a2_deployment):
    """The normalisation must not reject legitimate separation of duties."""
    result = governance.evaluate_approval(
        "FIN-02",
        evidence()["proposed_action"],
        "alice",
        "bob",
        evidence(),
        approver_role="finance-controller",
        issued={},
    )
    assert result["allowed"] is True


def test_separation_of_duties_requires_both_identities(a2_deployment):
    result = governance.evaluate_approval(
        "FIN-02",
        evidence()["proposed_action"],
        "",
        "",
        evidence(),
        approver_role="finance-controller",
        issued={},
    )
    assert result["allowed"] is False
    assert "separation_of_duties" in result["failed_rules"]


# ------------------------------------------------------- issue-time operation guard
def test_autonomy_and_allowlist_refuse_independently():
    """Two separate guards: the ceiling and the per-skill operation allowlist.

    At the shipped ceiling both fire for a write, which is the point — if one were ever
    relaxed by mistake, the other still refuses.
    """
    result = governance.evaluate_approval(
        "FIN-02",
        evidence()["proposed_action"],
        "requester-1",
        "approver-1",
        evidence(),
        approver_role="finance-controller",
        operation="write",
        issued={},
    )
    assert result["allowed"] is False
    assert {"autonomy_ceiling", "operation_permitted"} <= set(result["failed_rules"])
