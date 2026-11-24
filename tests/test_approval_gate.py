"""The approval gate must refuse these specific attacks.

Each test here is a finding from an external review of v0.1.0, kept as a permanent
regression. The happy path already had a test; none of these did, which is why a gate
that could not tell an issued token from an invented string shipped in a package whose
entire claim is that approvals are verified rather than trusted.
"""

from __future__ import annotations

import copy
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
def a2_ceiling(monkeypatch):
    """Only the ceiling opted in — the role table is left exactly as it ships."""
    real_resolve = registry.resolve_autonomy

    def fake(skill_id, *args, **kwargs):
        resolved = dict(real_resolve(skill_id, *args, **kwargs))
        resolved["mode"] = "human_confirm"
        resolved["autonomy_effective"] = "A2"
        return resolved

    monkeypatch.setattr(registry, "resolve_autonomy", fake)
    return fake


@pytest.fixture
def a2_deployment(a2_ceiling, monkeypatch):
    """A full A2 opt-in: ceiling plus a delegated role table.

    The shipped package can reach neither, so the token lifecycle only exists in a
    deployment that has named an owner, configured the gate, turned on auditing,
    defined a rollback path and — if the owner delegates — populated the approver
    roles for the skill's risk tier. Simulating all of that keeps the lifecycle
    tested without weakening the shipped defaults, which are asserted separately.
    """
    real_rules = registry.approval_rules

    def opted_in_rules():
        rules = copy.deepcopy(real_rules())
        directory = rules["rules"]["authorised_approver"]["roles_by_risk"]
        for tier in directory:
            directory[tier] = ["finance-controller", "service-desk-lead"]
        return rules

    monkeypatch.setattr(registry, "approval_rules", opted_in_rules)
    return a2_ceiling


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


# ------------------------------------------- E6: the approver must approve THIS action
def test_evidence_action_must_match_the_action(a2_deployment):
    """A summary that differs from the action is not an approval of the action."""
    misleading = evidence()
    misleading["proposed_action"] = "something else entirely"

    result = governance.evaluate_approval(
        "FIN-02",
        "release payment against invoice INV-4471",
        "requester-1",
        "approver-1",
        misleading,
        approver_role="finance-controller",
        issued={},
    )
    assert result["allowed"] is False
    assert "action_specific" in result["failed_rules"]


def test_evidence_action_matching_ignores_spacing_only(a2_deployment):
    """Whitespace differences are tolerated; content differences are not."""
    same = evidence()
    same["proposed_action"] = "release   payment against invoice INV-4471"

    result = governance.evaluate_approval(
        "FIN-02",
        "release payment against invoice INV-4471",
        "requester-1",
        "approver-1",
        same,
        approver_role="finance-controller",
        issued={},
    )
    assert result["allowed"] is True


def test_an_unlisted_role_is_not_authority(a2_deployment):
    """`intern` states a role; it does not hold one."""
    result = governance.evaluate_approval(
        "FIN-02",
        evidence()["proposed_action"],
        "requester-1",
        "approver-1",
        evidence(),
        approver_role="intern",
        issued={},
    )
    assert result["allowed"] is False
    assert "authorised_approver" in result["failed_rules"]


def test_shipped_policy_configures_no_approver_roles():
    """The package must not invent an authority model on the adopter's behalf."""
    directory = registry.approval_rules()["rules"]["authorised_approver"]["roles_by_risk"]
    assert set(directory) == {"Low", "Moderate", "High", "Critical"}
    assert all(roles == [] for roles in directory.values()), (
        "shipping populated approver roles would grant authority no one in the "
        "adopting organisation delegated"
    )


def test_contract_owner_is_an_authorised_approver(a2_ceiling):
    """FIN-02's owner is Finance Controller; that authority needs no configuration."""
    result = governance.evaluate_approval(
        "FIN-02",
        evidence()["proposed_action"],
        "requester-1",
        "approver-1",
        evidence(),
        approver_role="Finance Controller",
        issued={},
    )
    assert result["allowed"] is True
    basis = [c for c in result["checks"] if c["rule"] == "authorised_approver"][0]
    assert basis["basis"] == "contract owner"


@pytest.mark.parametrize(
    "role", ["finance controller", "FINANCE CONTROLLER", "finance-controller", " Finance  Controller "]
)
def test_owner_role_tolerates_spelling_variants(a2_ceiling, role):
    result = governance.evaluate_approval(
        "FIN-02",
        evidence()["proposed_action"],
        "requester-1",
        "approver-1",
        evidence(),
        approver_role=role,
        issued={},
    )
    assert result["allowed"] is True, role


def test_a_co_owner_segment_is_authorised(a2_ceiling):
    """IT-01's owner is "IT Operations / Security": both halves hold that authority."""
    for role in ("IT Operations", "Security"):
        result = governance.evaluate_approval(
            "IT-01",
            evidence("IT-01")["proposed_action"],
            "requester-1",
            "approver-1",
            evidence("IT-01"),
            approver_role=role,
            issued={},
        )
        assert result["allowed"] is True, role


@pytest.mark.parametrize("role", ["Controller", "Finance", "AP controller", "intern", ""])
def test_a_fragment_of_the_owner_title_is_not_authority(a2_ceiling, role):
    """Substring matching would make every plausible-looking title an approver."""
    result = governance.evaluate_approval(
        "FIN-02",
        evidence()["proposed_action"],
        "requester-1",
        "approver-1",
        evidence(),
        approver_role=role,
        issued={},
    )
    assert result["allowed"] is False
    assert "authorised_approver" in result["failed_rules"]


def test_denial_names_the_owner_and_the_unconfigured_tier(a2_ceiling):
    result = governance.evaluate_approval(
        "FIN-02",
        evidence()["proposed_action"],
        "requester-1",
        "approver-1",
        evidence(),
        approver_role="intern",
        issued={},
    )
    detail = [c["detail"] for c in result["checks"] if c["rule"] == "authorised_approver"][0]
    assert "Finance Controller" in detail, "the denial must name who can approve"
    assert "roles_by_risk" in detail, "and where to delegate"


def test_a_delegated_role_is_accepted_with_its_basis(a2_deployment):
    result = governance.evaluate_approval(
        "FIN-02",
        evidence()["proposed_action"],
        "requester-1",
        "approver-1",
        evidence(),
        approver_role="service-desk-lead",
        issued={},
    )
    assert result["allowed"] is True
    basis = [c for c in result["checks"] if c["rule"] == "authorised_approver"][0]
    assert basis["basis"] == "listed for risk tier Critical"


def test_issued_token_records_how_authority_was_established(a2_ceiling):
    ledger: dict = {}
    granted = governance.evaluate_approval(
        "FIN-02",
        evidence()["proposed_action"],
        "requester-1",
        "approver-1",
        evidence(),
        approver_role="Finance Controller",
        issued=ledger,
    )
    assert granted["allowed"] is True
    assert ledger[granted["approval_id"]]["approver_authority"] == "contract owner"
