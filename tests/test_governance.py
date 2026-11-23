"""Governance behaviour tests.

These exercise the real policy files and the real registry — the same ones the
skills cite — rather than fixtures that could drift from them.

Run:  uv run --with pytest --with "mcp>=2,<3" --with "pyyaml>=6,<7" python -m pytest -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "servers"))

from enterprise_core import governance, registry  # noqa: E402

SOURCE = ROOT / "src" / "registry" / "source.json"


def srd_json() -> dict:
    """The published, normalized projection of the requirements document."""
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    assert data["provenance"]["sha256"], "source.json must carry its document hash"
    return data


# ------------------------------------------------------------------- registry


def test_registry_matches_source_counts():
    data = srd_json()
    assert len(registry.skills()) == len(data["skills"]) == 93
    assert len(registry.domains()) == len(data["domains"]) == 12
    assert len(registry.requirements()) == len(data["requirements"]) == 32
    assert len(registry.roadmap()) == len(data["roadmap"]) == 4


def test_every_contract_has_provenance_and_identity():
    for sid, contract in registry.skills().items():
        assert contract["source"], f"{sid} has no provenance"
        assert contract["id"] == sid
        assert contract["owner"]
        assert contract["acceptance"], f"{sid} has no acceptance criterion"
        assert contract["fail_safe"], f"{sid} has no fail-safe behaviour"


def test_domains_all_have_skills():
    counts = registry.domain_counts()
    for domain in registry.domains():
        assert counts.get(domain["id"], 0) > 0, f"{domain['id']} has no skills"


# ------------------------------------------------------------------- autonomy


def test_shipped_ceiling_is_a1():
    config = registry.autonomy_config()
    assert config["ceiling"]["default_max_level"] == "A1"
    assert config["ceiling"]["a3_shipped"] is False


def test_no_skill_reaches_a2_without_opt_in():
    for sid in registry.skills():
        resolution = registry.resolve_autonomy(sid)
        assert resolution["autonomy_effective"] in {"A0", "A1"}, sid
        assert resolution["mode"] in {"advisory_only", "draft_only"}, sid


def test_a3_request_is_capped_and_reported():
    resolution = registry.resolve_autonomy("IT-08", "A3")
    assert resolution["autonomy_effective"] == "A1"
    assert resolution["downgrade_applied"] is True
    assert any("A3 is not shipped" in d["reason"] for d in resolution["downgrades"])


def test_critical_risk_never_resolves_to_auto():
    for sid, contract in registry.skills().items():
        if contract["risk"] == "Critical":
            assert registry.resolve_autonomy(sid)["mode"] != "auto", sid


def test_downgrade_is_never_silent():
    """Every capped skill must report what it asked for versus what it got."""
    for sid, contract in registry.skills().items():
        resolution = registry.resolve_autonomy(sid)
        if resolution["autonomy_requested"] != resolution["autonomy_effective"]:
            assert resolution["downgrade_applied"], f"{sid} was capped without saying so"
            assert resolution["downgrades"], sid


def test_unknown_skill_is_an_error_not_a_guess():
    with pytest.raises(KeyError):
        registry.resolve_autonomy("XXX-99")


def test_invalid_level_is_rejected():
    with pytest.raises(ValueError):
        registry.resolve_autonomy("HR-01", "A9")


# -------------------------------------------------------------------- scoring


def test_score_matches_the_srd_formula_for_all_93():
    """Parity with the document's own score(), recomputed independently here."""
    risk_rank = {"Low": 1, "Moderate": 2, "High": 4, "Critical": 5}
    data = srd_json()
    for skill in data["skills"]:
        weights = {"impact": 35, "readiness": 25, "reuse": 20, "effort": 10, "risk": 10}
        total = sum(weights.values())
        value = (
            skill["impact"] * weights["impact"]
            + skill["readiness"] * weights["readiness"]
            + skill["reuse"] * weights["reuse"]
            + (6 - skill["effort"]) * weights["effort"]
            + (6 - risk_rank[skill["risk"]]) * weights["risk"]
        ) / total
        expected = round(value * 20)
        assert registry.score(registry.skills()[skill["id"]]) == expected, skill["id"]


def test_score_stays_in_range_when_reweighted():
    for weights in ({"impact": 100}, {"effort": 0, "risk": 0}, {"reuse": 60, "readiness": 40}):
        for sid in list(registry.skills())[:10]:
            assert 0 <= registry.score(registry.skills()[sid], weights) <= 100, sid


# ------------------------------------------------------------------- approval


def good_evidence():
    return {
        "proposed_action": "create ticket in ITSM",
        "skill_id_and_version": "IT-01@1.0.0",
        "cited_evidence": ["runbook#3"],
        "risk_tier": "Moderate",
        "reversibility": "reversible",
        "rollback_path": "delete ticket",
    }


def test_approval_is_refused_for_a_draft_only_skill():
    """The shipped ceiling is A1, so no token exists for any skill.

    The token lifecycle (issue -> redeem -> replay, changed action, expiry) is covered in
    tests/test_approval_gate.py, which simulates a deployment that has opted into A2.
    """
    result = governance.evaluate_approval(
        "IT-01", "create ticket in ITSM", "requester-1", "approver-1", good_evidence(),
        approver_role="service-desk-lead",
    )
    assert result["allowed"] is False
    assert "autonomy_ceiling" in result["failed_rules"]
    assert "approval_id" not in result


def test_approval_rejects_self_approval():
    result = governance.evaluate_approval(
        "IT-01", "create ticket", "same-person", "same-person", good_evidence(),
        approver_role="lead",
    )
    assert result["allowed"] is False
    rules = [c["rule"] for c in result["checks"] if c["status"] == "fail"]
    assert "separation_of_duties" in rules


def test_approval_rejects_expired_window():
    result = governance.evaluate_approval(
        "IT-01", "create ticket", "r", "a", good_evidence(),
        approver_role="lead", approval_age_minutes=10_000,
    )
    assert result["allowed"] is False
    assert any(c["rule"] == "expiry" and c["status"] == "fail" for c in result["checks"])


def test_approval_rejects_incomplete_evidence():
    result = governance.evaluate_approval(
        "IT-01", "create ticket", "r", "a", {"proposed_action": "x"},
        approver_role="lead",
    )
    assert result["allowed"] is False
    detail = next(c for c in result["checks"] if c["rule"] == "evidence_bundle")
    assert "rollback_path" in detail["detail"]


def test_approval_denies_rather_than_degrades():
    """Missing evidence must deny; it must never quietly allow."""
    result = governance.evaluate_approval("IT-01", "", "", "", {}, approver_role="")
    assert result["allowed"] is False
    failed = {c["rule"] for c in result["checks"] if c["status"] == "fail"}
    # Expiry legitimately passes at age 0; every substantive rule must fail.
    assert {"action_specific", "separation_of_duties", "evidence_bundle", "authorised_approver"} <= failed


# -------------------------------------------------------------------- release


def test_release_blocked_without_evidence():
    result = governance.evaluate_release("FIN-01", {})
    assert result["decision"] == "blocked"
    assert all(g["status"] == "incomplete" for g in result["gates"])


def test_release_pilot_ready_when_g1_g2_pass():
    policy = registry.release_gates()["gates"]
    evidence = {item: True for gate in policy[:2] for item in gate["required"]}
    result = governance.evaluate_release("FIN-01", evidence)
    assert result["decision"] == "pilot_ready"


def test_release_expansion_ready_when_all_gates_pass():
    policy = registry.release_gates()["gates"]
    evidence = {item: True for gate in policy for item in gate["required"]}
    result = governance.evaluate_release("FIN-01", evidence)
    assert result["decision"] == "expansion_ready"


def test_never_waivable_item_is_rejected_even_with_a_waiver():
    waiver = {
        "item": "privacy_review",
        "owner": "someone",
        "justification": "pressed for time",
        "expiry": "2026-12-31",
    }
    result = governance.evaluate_release("FIN-01", {}, waivers=[waiver])
    gate = next(g for g in result["gates"] if "privacy_review" in g["missing"])
    assert any(r["item"] == "privacy_review" for r in gate["rejected_waivers"])
    assert result["decision"] == "blocked"


def test_every_never_waivable_item_is_actually_checked_by_a_gate():
    """A never-waivable item no gate requires is a control that does nothing."""
    policy = registry.release_gates()
    gate_items = {i for g in policy["gates"] for i in g["required"]}
    for item in policy["waivers"]["never_waivable"]:
        assert item in gate_items, f"{item} is never waivable but no gate checks it"


def test_valid_waiver_is_reported_as_waiver_not_pass():
    policy = registry.release_gates()["gates"]
    evidence = {item: True for gate in policy for item in gate["required"]}
    evidence["workflow_baseline"] = False
    waiver = {
        "item": "workflow_baseline",
        "owner": "finance-owner",
        "justification": "baseline in progress, pilot only",
        "expiry": "2026-12-31",
    }
    result = governance.evaluate_release("FIN-01", evidence, waivers=[waiver])
    gate = next(g for g in result["gates"] if g["id"] == "G1")
    assert gate["waived"] and gate["status"] == "pass"
    assert result["caveat"]


# ---------------------------------------------------------------------- audit


def test_audit_trail_is_hash_chained(tmp_path, monkeypatch):
    """Skips only if mcp is not installed; the chain logic lives in the server."""
    pytest.importorskip("mcp")
    monkeypatch.setenv("PLUGIN_DATA", str(tmp_path))

    from enterprise_core import main as server  # noqa: PLC0415

    first = server.audit_append({"skill_id": "HR-01", "mode": "draft_only"})
    second = server.audit_append({"skill_id": "HR-01", "mode": "draft_only"})
    trace = server.audit_trace(limit=10)

    assert trace["total"] == 2
    assert trace["entries"][0]["previous_hash"] == "genesis"
    assert trace["entries"][1]["previous_hash"] == first["entry_hash"]
    assert second["entry_hash"] != first["entry_hash"]


# ----------------------------------------------------------- A2 opt-in semantics


def opt_in_config(entries):
    """A copy of the shipped config with the given a2_skills entries.

    Snapshotted at import: reading `registry.autonomy_config()` here would call the
    patched function and recurse.
    """
    import json as _json

    cfg = _json.loads(_json.dumps(SHIPPED_CONFIG))
    cfg["opt_in"]["a2_skills"] = entries
    return cfg


SHIPPED_CONFIG = json.loads(json.dumps(registry.autonomy_config()))


FULL_EVIDENCE = {
    "named_process_owner": "service-desk-lead",
    "approval_gate_configured": True,
    "audit_trail_enabled": True,
    "rollback_path": "close or delete the created ticket",
}


def test_bare_skill_id_opt_in_does_not_unlock_a2(monkeypatch):
    """A bare id is not evidence. It must fail closed and say why."""
    monkeypatch.setattr(registry, "autonomy_config", lambda: opt_in_config(["IT-01"]))
    resolution = registry.resolve_autonomy("IT-01")
    assert resolution["autonomy_effective"] == "A1"
    assert any("bare skill id" in r for r in resolution["constraints"])


def test_incomplete_opt_in_does_not_unlock_a2(monkeypatch):
    partial = dict(FULL_EVIDENCE)
    partial.pop("rollback_path")
    monkeypatch.setattr(
        registry, "autonomy_config", lambda: opt_in_config([dict(skill="IT-01", **partial)])
    )
    resolution = registry.resolve_autonomy("IT-01")
    assert resolution["autonomy_effective"] == "A1"
    assert any("incomplete" in r and "rollback_path" in r for r in resolution["constraints"])


def test_complete_opt_in_unlocks_a2(monkeypatch):
    monkeypatch.setattr(
        registry,
        "autonomy_config",
        lambda: opt_in_config([dict(skill="IT-01", **FULL_EVIDENCE)]),
    )
    resolution = registry.resolve_autonomy("IT-01")
    assert resolution["autonomy_effective"] == "A2"
    assert resolution["mode"] == "human_confirm"
    assert resolution["requires_approval"] is True


def test_opt_in_never_exceeds_the_contracts_own_request(monkeypatch):
    """FIN-01 requests A1; a ceiling of A2 must not inflate it."""
    monkeypatch.setattr(
        registry,
        "autonomy_config",
        lambda: opt_in_config([dict(skill="FIN-01", **FULL_EVIDENCE)]),
    )
    resolution = registry.resolve_autonomy("FIN-01")
    assert resolution["autonomy_effective"] == "A1"
    assert any("never granted more autonomy" in r for r in resolution["constraints"])


def test_a3_contract_opted_in_caps_at_a2(monkeypatch):
    """IT-08 requests A3. Opt-in may reach A2, never A3, and a3 stays unshipped."""
    monkeypatch.setattr(
        registry,
        "autonomy_config",
        lambda: opt_in_config([dict(skill="IT-08", **FULL_EVIDENCE)]),
    )
    resolution = registry.resolve_autonomy("IT-08")
    assert resolution["autonomy_effective"] == "A2"
    assert resolution["mode"] == "human_confirm"
    assert registry.autonomy_config()["ceiling"]["a3_shipped"] is False


def test_shipped_config_grants_no_a2():
    """The package as published must not have any A2 opt-in configured."""
    assert registry.autonomy_config()["opt_in"]["a2_skills"] == []


def test_there_is_no_a3_opt_in_slot():
    """A3 is unreachable by construction, not by an empty-but-present key."""
    opt_in = registry.autonomy_config()["opt_in"]
    assert "a3_skills" not in opt_in
    assert "a3_requires_additionally" not in opt_in
    assert registry.autonomy_config()["ceiling"]["a3_shipped"] is False


# ----------------------------------------------------------------- safeguards


def test_all_six_safeguards_present_with_attestation():
    guards = registry.safeguards()
    assert len(guards) == 6
    for guard in guards:
        assert guard["statement"] and guard["attestation"], guard["id"]
