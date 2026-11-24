"""Attack `check_tool_call` with valid-looking arguments.

`check_tool_call` is the enforcement primitive a gateway calls before dispatching. Its
whole value is the refusal, so the tests that matter are the ones that try to get an
`allowed: true` they should not have. Three concrete holes were found this way:

1. `connector_status` defaulted to "ready", so a gateway that never called
   `check_connector` got an allow verdict. Deny-by-default, except for the one argument
   that says "the connector was checked".
2. `tool_name` was never compared to anything, yet the response said `allowed: true` for
   it — a caller reasonably reads that as "this tool is permitted".
3. Case and padding in `operation` / `connector_status` produced denials for a legitimate
   intent, which invites argument-fishing until something is accepted.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "servers"))

from enterprise_core import governance, registry  # noqa: E402

READ_ONLY = dict(
    skill_id="IT-01",
    tool_name="open_ticket",
    operation="read",
    category="itsm",
    connector_status="ready",
)


@pytest.fixture
def a2(monkeypatch):
    """Simulate an A2 opt-in so `write` is on the table and lookalikes can be tested."""
    real = registry.resolve_autonomy
    monkeypatch.setattr(
        registry,
        "resolve_autonomy",
        lambda sid, *a, **kw: {**dict(real(sid, *a, **kw)), "mode": "human_confirm",
                               "autonomy_effective": "A2"},
    )


def call(**overrides) -> dict:
    args = {**READ_ONLY, **overrides}
    return governance.evaluate_tool_call(**args)


# --------------------------------------------------------- F1: the fail-open default
def test_omitting_connector_status_refuses():
    """The caller must prove the connector was checked; silence is not proof."""
    args = dict(READ_ONLY)
    args.pop("connector_status")
    result = governance.evaluate_tool_call(**args)
    assert result["allowed"] is False
    assert result["rule"] == "connector_unverified"
    assert "check_connector" in result["reason"]


@pytest.mark.parametrize("status", ["", "  ", None, "unchecked", "unknown", "failed", "partial"])
def test_anything_but_ready_refuses(status):
    result = call(connector_status=status)
    assert result["allowed"] is False, status
    assert result["rule"] in {"connector_unverified", "connector_not_conformant"}


@pytest.mark.parametrize("status", ["ready", "READY", " ready ", "Ready"])
def test_ready_tolerates_case_and_padding(status):
    result = call(connector_status=status)
    assert result["allowed"] is True, status


# ------------------------------------------- F2: the verdict is category-scoped
def test_any_tool_name_inside_a_declared_category_is_allowed_but_marked_unverified():
    """The rule is category-level. Saying so is the difference between a boundary and a bug."""
    result = call(tool_name="delete_everything_in_the_estate")
    assert result["allowed"] is True
    assert result["scope"] == "category"
    assert result["tool_name_verified"] is False
    assert "check_connector" in result["note"]


def test_missing_tool_name_is_refused_first():
    result = call(tool_name="   ")
    assert result["allowed"] is False
    assert result["rule"] == "missing_tool"


# ------------------------------- F3: spelling is not a different operation
@pytest.mark.parametrize("operation", ["write", "WRITE", " Write ", "wRiTe"])
def test_write_is_recognised_whatever_the_casing(a2, operation):
    result = call(operation=operation)
    assert result["allowed"] is True, operation


@pytest.mark.parametrize(
    "operation",
    [
        "wr ite",
        "writ\u200be",           # zero-width space
        "wr\u0456te",            # cyrillic i
        "\uff57\uff52\uff49\uff54\uff45",  # fullwidth
        "write\x00",
        "write;",
        "write()",
        "writes",
        "write_all",
        "read,write",
    ],
)
def test_operation_lookalikes_are_refused(a2, operation):
    """None of these may be treated as `write` — that is the whole attack surface."""
    result = call(operation=operation)
    assert result["allowed"] is False, f"{operation!r} was accepted as an operation"


def test_read_only_skill_still_refuses_write(a2):
    """IT-01's allowlist is read-only at A1; A2 must not widen it for this skill."""
    result = governance.evaluate_tool_call(
        skill_id="FND-06", tool_name="post_entry", operation="write",
        category="finance", connector_status="ready",
    )
    assert result["allowed"] is False
    assert result["rule"] in {"operation_not_permitted", "category_not_declared"}


# ------------------------------------------------------------- the ordinary refusals
def test_write_at_a1_refuses():
    result = call(operation="write")
    assert result["allowed"] is False
    assert result["rule"] == "operation_not_permitted"


def test_propose_at_a1_refuses():
    assert call(operation="propose")["allowed"] is False


def test_undeclared_category_refuses():
    result = call(category="payroll")
    assert result["allowed"] is False
    assert result["rule"] == "category_not_declared"


def test_category_tolerates_case_and_padding():
    assert call(category=" ITSM ")["allowed"] is True


def test_unknown_skill_refuses():
    result = call(skill_id="NOPE-99")
    assert result["allowed"] is False
    assert result["rule"] == "unknown_skill"


def test_missing_category_refuses():
    for value in ("", None, "   "):
        assert call(category=value)["allowed"] is False


# --------------------------------------------- no allow verdict without all three
def test_every_refusal_names_a_rule_and_a_reason():
    cases = [
        call(operation="write"),
        call(category="payroll"),
        call(tool_name=""),
        call(skill_id="NOPE-99"),
        call(connector_status="failed"),
    ]
    for result in cases:
        assert result["allowed"] is False
        assert result["rule"] and result["reason"]
