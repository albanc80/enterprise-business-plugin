"""Malformed input must produce a refusal, never an exception.

A tool that raises gives the caller a stack trace instead of a decision, and a model
reading that learns nothing about what was wrong. Every case here was found by calling
the tools with plausible-but-wrong arguments and watching what happened.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "servers"))

from enterprise_core import main, registry  # noqa: E402


@pytest.fixture
def audit(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_data_dir", lambda: tmp_path)
    return tmp_path / "audit.jsonl"


# ------------------------------------------- G1: release_gate must not raise on junk
@pytest.mark.parametrize("evidence", ["garbage", 42, ["a"], True])
def test_release_gate_refuses_non_object_evidence(evidence):
    result = main.release_gate("FND-06", evidence)
    assert result["decision"] == "blocked"
    assert result["error"] == "invalid evidence"
    assert "object mapping gate item" in result["reason"]


@pytest.mark.parametrize("waivers", ["garbage", {"item": "x"}, [1], ["str"]])
def test_release_gate_refuses_malformed_waivers(waivers):
    result = main.release_gate("FND-06", {"named_process_owner": True}, waivers)
    assert result["decision"] == "blocked"
    assert result["error"] == "invalid waivers"


def test_release_gate_still_works_with_a_real_bundle():
    result = main.release_gate("FND-06", {})
    assert result["decision"] in {"blocked", "conditional", "ready"}
    assert "error" not in result


def test_release_gate_accepts_omitted_evidence():
    assert "error" not in main.release_gate("FND-06")


# ------------------------------------------ G2: check_connector must not raise on junk
@pytest.mark.parametrize("manifest", [None, "garbage", 42, ["a"]])
def test_check_connector_refuses_non_object_manifest(manifest):
    result = main.check_connector(manifest)
    assert result["decision"] == "rejected"
    assert result["error"] == "invalid manifest"
    assert result["structural_checks"] == []


def test_check_connector_still_rejects_an_empty_manifest_without_crashing():
    result = main.check_connector({})
    assert result["decision"] == "rejected"


# -------------------------------------- G3: list_requirements validates its vocabulary
@pytest.mark.parametrize(
    "kwargs", [{"priority": "Bogus"}, {"type": "bogus"}, {"type": "Functional "}]
)
def test_list_requirements_refuses_unknown_filters(kwargs):
    result = main.list_requirements(**kwargs)
    if kwargs.get("type") == "Functional ":
        assert "error" not in result, "a padded valid value must still resolve"
        return
    assert result["error"] == "invalid filter"
    assert result["requirements"] == []
    assert result["problems"]


def test_list_requirements_states_the_valid_vocabulary():
    result = main.list_requirements(type="bogus")
    assert result["valid"]["type"] == ["Functional", "Non-functional"]
    assert result["valid"]["priority"] == ["Must", "Should"]


def test_list_requirements_accepts_valid_filters():
    assert main.list_requirements(priority="Must")["matched"] > 0
    assert main.list_requirements(type="Functional")["matched"] > 0


def test_list_requirements_returns_all_32_by_default():
    result = main.list_requirements()
    assert result["matched"] == 32
    assert result["returned"] == 32
    assert result["truncated"] is False


def test_list_requirements_query_with_no_match_is_not_an_error():
    result = main.list_requirements(query="zzzz-nothing")
    assert "error" not in result
    assert result["matched"] == 0


def test_list_requirements_rejects_a_non_positive_limit():
    assert main.list_requirements(limit=0)["error"] == "invalid filter"


# ------------------------------------------------- G4: one limit rule, everywhere
def test_limits_are_rejected_not_clamped():
    assert main.score_skills(limit=0)["error"] == "invalid limit"
    assert main.score_skills(limit=-3)["error"] == "invalid limit"
    assert main.list_skills(limit=0)["error"] == "invalid filter"


def test_audit_trace_rejects_a_non_positive_limit(audit):
    main.audit_append({"skill_id": "FIN-02", "outcome": "draft"})
    result = main.audit_trace(limit=0)
    assert result["error"] == "invalid limit"
    assert result["entries"] == []


def test_valid_limits_still_bound_the_output(audit):
    for n in range(5):
        main.audit_append({"skill_id": "FIN-02", "n": n, "outcome": "draft"})
    assert len(main.audit_trace(limit=2)["entries"]) == 2
    assert len(main.score_skills(limit=3)["ranked"]) == 3
    assert len(main.list_skills(limit=2)["skills"]) == 2


# --------------------------------------------- G5: whitespace is not a new autonomy
@pytest.mark.parametrize("level", [" A2 ", "a2", "A2", "  a2  "])
def test_route_autonomy_tolerates_padding_and_case(level):
    result = main.route_autonomy("IT-01", level)
    assert not result.get("error"), level
    assert result["autonomy_requested"] == "A2"


def test_route_autonomy_still_rejects_a_nonsense_level():
    assert main.route_autonomy("IT-01", "A5")["error"]


def test_route_autonomy_treats_blank_as_omitted():
    blank = main.route_autonomy("IT-01", "   ")
    defaults = main.route_autonomy("IT-01")
    assert blank["autonomy_requested"] == defaults["autonomy_requested"]


# --------------------------------------- G6: an audit entry must describe something
@pytest.mark.parametrize("entry", [None, "string", 42, [], {}])
def test_audit_append_refuses_an_entry_that_describes_nothing(audit, entry):
    result = main.audit_append(entry)
    assert result["appended"] is False
    assert result["rule"] == "invalid_entry"
    assert not audit.exists(), "a rejected entry must not touch the trail"


def test_audit_append_still_accepts_a_real_entry(audit):
    result = main.audit_append({"skill_id": "FIN-02", "actor": "a", "outcome": "draft"})
    assert result["appended"] is True
    assert audit.exists()
