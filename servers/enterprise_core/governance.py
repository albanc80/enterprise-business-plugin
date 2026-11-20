"""Pure governance evaluators.

Split out of the MCP layer on purpose: the approval gate and the release gate are
business logic, and business logic that can only be exercised by starting a server
is business logic that does not get tested.

Nothing here does I/O beyond reading the policy files through `registry`.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from . import registry


def digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def evaluate_approval(
    skill_id: str,
    proposed_action: str,
    requester_id: str,
    approver_id: str,
    evidence: dict[str, Any],
    approver_role: str = "",
    approval_age_minutes: float = 0.0,
    approval_id: str | None = None,
    redeemed: set[str] | None = None,
) -> dict[str, Any]:
    """Validate an approval, or redeem a previously issued one exactly once."""
    reg = registry.skills()
    if skill_id not in reg:
        return {"allowed": False, "error": f"unknown skill_id {skill_id!r}"}

    contract = reg[skill_id]
    rules = registry.approval_rules()["rules"]
    window = float(rules["expiry"]["default_window_minutes"])
    required = list(rules["evidence_bundle"]["required_fields"])
    redeemed = redeemed if redeemed is not None else set()

    # Redeem mode: the token, not the proposal, is what is checked.
    if approval_id:
        if approval_id in redeemed:
            return {
                "allowed": False,
                "approval_id": approval_id,
                "error": "approval already redeemed — approvals are single-use",
            }
        redeemed.add(approval_id)
        return {
            "allowed": True,
            "approval_id": approval_id,
            "redeemed": True,
            "note": "One action authorised. Any change to the action requires a new approval.",
        }

    missing = [field for field in required if not evidence.get(field)]
    checks = [
        {
            "rule": "action_specific",
            "status": "pass" if proposed_action.strip() else "fail",
            "detail": "approval binds to the exact proposed action digest",
        },
        {
            "rule": "separation_of_duties",
            "status": "pass" if approver_id and approver_id != requester_id else "fail",
            "detail": "approver must differ from the requester",
        },
        {
            "rule": "expiry",
            "status": "pass" if approval_age_minutes <= window else "fail",
            "detail": f"window is {int(window)} minutes, presented age {approval_age_minutes}",
        },
        {
            "rule": "evidence_bundle",
            "status": "pass" if not missing else "fail",
            "detail": "complete" if not missing else f"missing: {', '.join(missing)}",
        },
        {
            "rule": "authorised_approver",
            "status": "pass" if approver_role.strip() else "fail",
            "detail": "approver role must be stated so delegation is auditable",
        },
    ]
    failed = [c for c in checks if c["status"] != "pass"]
    if failed:
        return {
            "allowed": False,
            "skill_id": skill_id,
            "risk": contract["risk"],
            "checks": checks,
            "next_action": (
                "Deny and route back to the requester with the failed rule named: "
                + ", ".join(c["rule"] for c in failed)
            ),
        }

    return {
        "allowed": True,
        "skill_id": skill_id,
        "risk": contract["risk"],
        "checks": checks,
        "approval_id": f"apr_{uuid.uuid4().hex[:16]}",
        "action_digest": digest(
            {"skill_id": skill_id, "proposed_action": proposed_action, "evidence": evidence}
        ),
        "valid_for_minutes": int(window),
        "next_action": (
            "Execute exactly this action once, then audit_append the receipt with the approval id."
        ),
    }


def _tool_categories(tool: dict[str, Any], manifest_categories: set[str]) -> set[str]:
    """A tool's categories: its own `category` if declared, else the whole connector's."""
    if tool.get("category"):
        return {str(tool["category"]).strip().lower()}
    return manifest_categories


def evaluate_tool_call(
    skill_id: str,
    tool_name: str,
    operation: str,
    category: str,
    connector_status: str = "ready",
) -> dict[str, Any]:
    """Decide whether one skill may call one specific tool.

    This is the enforcement primitive a gateway calls before dispatch. It answers a
    different question from route_autonomy: that one says whether the capability may
    write at all, this one says whether it may reach *this* tool. Both have to allow.

    Deliberately simple and deny-by-default: an unknown skill, an undeclared
    category, an operation above the skill's level or a non-conformant connector all
    produce a refusal with the rule that fired.
    """
    policy = registry.tool_allowlist_policy()

    try:
        allow = registry.tool_allowlist(skill_id)
    except KeyError as exc:
        return {"allowed": False, "rule": "unknown_skill", "reason": str(exc)}

    base = {
        "skill_id": skill_id,
        "tool_name": tool_name,
        "operation": operation,
        "category": category,
        "effective_autonomy": allow["effective_autonomy"],
    }

    if connector_status != "ready":
        return {
            **base,
            "allowed": False,
            "rule": "connector_not_conformant",
            "reason": f"connector decision is {connector_status!r}; run check_connector and fix it first",
        }

    if operation not in allow["allowed_operations"]:
        return {
            **base,
            "allowed": False,
            "rule": "operation_not_permitted",
            "reason": (
                f"{operation!r} is not permitted at {allow['effective_autonomy']} "
                f"(allowed: {allow['allowed_operations']})"
            ),
        }

    if str(category).strip().lower() not in allow["allowed_categories"]:
        return {
            **base,
            "allowed": False,
            "rule": "category_not_declared",
            "reason": (
                f"category {category!r} is not declared by this skill "
                f"(declared: {allow['allowed_categories']})"
            ),
        }

    if not str(tool_name).strip():
        return {**base, "allowed": False, "rule": "missing_tool", "reason": "no tool name supplied"}

    return {
        **base,
        "allowed": True,
        "rule": "allowlist",
        "reason": (
            f"{operation!r} on category {category!r} is within {allow['effective_autonomy']} "
            f"and declared by the contract"
        ),
        "default_decision": policy["default_decision"],
        "enforcement": allow["enforcement"],
    }


def evaluate_connector(
    manifest: dict[str, Any],
    skill_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Check whether a user-supplied connector can carry this package's guarantees.

    Structural first (is the manifest complete, are writes idempotent and
    reversible, is audit passed through), then per-skill (does it expose the
    operation class each requested skill needs at its *effective* autonomy).

    Deliberately not attempted: whether the connector maps your fields correctly or
    behaves under load. Passing here means "capable of carrying the guarantees",
    not "correct".
    """
    policy = registry.connector_policy()
    reg = registry.skills()
    checks: list[dict[str, Any]] = []
    failed: list[str] = []

    def check(rule: str, ok: bool, detail: str) -> None:
        checks.append({"rule": rule, "status": "pass" if ok else "fail", "detail": detail})
        if not ok:
            failed.append(rule)

    # --- manifest completeness
    for field in policy["manifest"]["required_fields"]:
        value = manifest.get(field)
        ok = bool(value)
        if field == "tools":
            ok = isinstance(value, list) and len(value) > 0
        check(f"manifest.{field}", ok, "present" if ok else f"missing or empty {field!r}")

    # --- connector-level obligations
    for key, statement in policy["connector"]["requires"].items():
        check(f"connector.{key}", manifest.get(key) is True, statement)
    for forbidden in policy["connector"]["forbidden"]:
        present = bool(manifest.get(forbidden))
        check(
            f"forbidden.{forbidden}",
            not present,
            "not declared" if not present else f"declares forbidden property {forbidden!r}",
        )

    # --- tool declarations
    operations = policy["tool"]["operations"]
    write_requires = policy["tool"]["write_requires"]
    name_counts: dict[str, int] = {}
    for tool in manifest.get("tools") or []:
        name_counts[str(tool.get("name"))] = name_counts.get(str(tool.get("name")), 0) + 1

    tool_rows: list[dict[str, Any]] = []
    for tool in manifest.get("tools") or []:
        problems: list[str] = []
        for field in policy["tool"]["required_fields"]:
            if not tool.get(field):
                problems.append(f"missing {field}")
        op = tool.get("operation")
        if op not in operations:
            problems.append(f"operation {op!r} not in {sorted(operations)}")
        if name_counts.get(str(tool.get("name")), 0) > 1:
            problems.append("duplicate tool name")
        if op == "write":
            for req in write_requires:
                value = tool.get(req)
                if not value:
                    problems.append(f"write tool must declare {req}")
                elif req == "rollback" and str(value).strip().lower() in {"none", "n/a"}:
                    problems.append("write declares no rollback — an irreversible write needs explicit approval")
        tool_rows.append(
            {
                "name": tool.get("name"),
                "operation": op,
                "resource": tool.get("resource"),
                "category": tool.get("category"),
                "problems": problems,
            }
        )
    if tool_rows:
        bad = [t["name"] for t in tool_rows if t["problems"]]
        check(
            "tools.well_formed",
            not bad,
            "all tool declarations complete" if not bad else f"problems in {bad}",
        )

    usable = [t for t in tool_rows if not t["problems"]]
    available_ops = {t["operation"] for t in usable}

    # --- per-skill fit
    declared_categories = {
        str(c).strip().lower() for c in (manifest.get("system_categories") or [])
    }
    skill_rows: list[dict[str, Any]] = []
    for sid in skill_ids or []:
        if sid not in reg:
            skill_rows.append(
                {"skill_id": sid, "satisfied": False, "reason": "unknown skill id"}
            )
            continue
        resolution = registry.resolve_autonomy(sid)
        required_op = policy["operation_by_mode"].get(resolution["mode"], "read")
        contract_categories = {
            c.strip().lower()
            for c in str(reg[sid]["system_categories"]).split(",")
            if c.strip()
        }
        overlap = sorted(contract_categories & declared_categories)

        # Turn the abstract allowlist into concrete tool names for THIS connector:
        # the list a gateway should enforce before dispatch.
        try:
            allow = registry.tool_allowlist(sid)
        except KeyError:
            allow = {"allowed_operations": [], "allowed_categories": []}
        allowed_ops = set(allow["allowed_operations"])
        allowed_rows, withheld = [], []
        for tool in usable:
            cats = _tool_categories(tool, declared_categories)
            if tool["operation"] in allowed_ops and (cats & contract_categories):
                allowed_rows.append(tool)
            else:
                withheld.append(tool["name"])

        # "Satisfied" means the connector can actually serve this skill: it must expose
        # a tool of the required operation class AND in a category the contract
        # declares. An operation class on its own proves nothing — an ITSM read tool
        # does not serve a finance skill.
        satisfied = any(t["operation"] == required_op for t in allowed_rows)
        if satisfied:
            reason = f"may call a usable {required_op} tool in a declared category"
        elif required_op in available_ops:
            reason = (
                f"exposes {required_op} tools, but none in this skill's categories "
                f"({sorted(contract_categories)})"
            )
        else:
            reason = (
                f"needs a {required_op} tool at {resolution['autonomy_effective']} "
                f"({resolution['mode']}); connector provides {sorted(available_ops) or 'nothing usable'}"
            )

        skill_rows.append(
            {
                "skill_id": sid,
                "skill_name": reg[sid]["name"],
                "effective_autonomy": resolution["autonomy_effective"],
                "mode": resolution["mode"],
                "required_operation": required_op,
                "satisfied": satisfied,
                "reason": reason,
                "categories_declared_by_contract": sorted(contract_categories),
                "categories_covered": overlap,
                "allowed_tools": sorted(t["name"] for t in allowed_rows),
                "withheld_tools": sorted(withheld),
            }
        )

    unsatisfied = [r for r in skill_rows if not r["satisfied"]]
    if failed:
        decision = "rejected"
        next_action = (
            "Fix the connector before use: "
            + ", ".join(failed)
            + ". These are structural — a skill cannot compensate for them."
        )
    elif unsatisfied:
        decision = "partial"
        next_action = (
            f"{len(unsatisfied)} requested skill(s) lack a usable operation: "
            + ", ".join(r["skill_id"] for r in unsatisfied)
            + ". Add the missing tool class, or accept that those skills stop at drafting."
        )
    else:
        decision = "ready"
        next_action = (
            "Structurally able to carry the guarantees. Category fit and field mapping "
            "are still yours to prove under G1/G2."
        )

    return {
        "connector": manifest.get("connector"),
        "transport": manifest.get("transport"),
        "decision": decision,
        "structural_checks": checks,
        "tools": tool_rows,
        "available_operations": sorted(available_ops),
        "skills": skill_rows,
        "skills_satisfied": len(skill_rows) - len(unsatisfied),
        "skills_requested": len(skill_rows),
        "next_action": next_action,
        "caveat": (
            "Structural conformance only. This does not validate your field mapping, "
            "your process logic, or behaviour under load — those are release evidence, "
            "not a manifest check."
        ),
    }


def evaluate_release(
    skill_id: str,
    evidence: dict[str, bool] | None = None,
    waivers: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Check whether a skill has the evidence to deploy, expand, or not yet."""
    reg = registry.skills()
    if skill_id not in reg:
        return {"error": f"unknown skill_id {skill_id!r}", "hint": "call list_skills"}

    evidence = evidence or {}
    policy = registry.release_gates()
    never = set(policy["waivers"]["never_waivable"])
    waiver_items = {str(w.get("item")): w for w in (waivers or []) if w.get("item")}

    gates_out = []
    for gate in policy["gates"]:
        missing, waived, rejected = [], [], []
        for item in gate["required"]:
            if evidence.get(item):
                continue
            waiver = waiver_items.get(item)
            if not waiver:
                missing.append(item)
                continue
            incomplete = [f for f in policy["waivers"]["require"] if not waiver.get(f)]
            if item in never or incomplete:
                rejected.append(
                    {
                        "item": item,
                        "reason": "not waivable" if item in never else f"waiver missing: {', '.join(incomplete)}",
                    }
                )
                missing.append(item)
            else:
                waived.append({"item": item, "owner": waiver["owner"], "expiry": waiver["expiry"]})
        gates_out.append(
            {
                "id": gate["id"],
                "name": gate["name"],
                "status": "pass" if not missing else "incomplete",
                "satisfied": [i for i in gate["required"] if evidence.get(i)],
                "missing": missing,
                "waived": waived,
                "rejected_waivers": rejected,
            }
        )

    g1, g2, g3 = (g["status"] == "pass" for g in gates_out[:3])
    if not (g1 and g2):
        decision, next_action = "blocked", "Close G1 and G2 before any deployment, pilot included."
    elif not g3:
        decision, next_action = "pilot_ready", "Deploy to the pilot only. G3 evidence is required to expand."
    else:
        decision, next_action = "expansion_ready", "Evidence complete. Expansion still needs a fresh threat model and owner approval."

    return {
        "skill_id": skill_id,
        "skill_name": reg[skill_id]["name"],
        "risk": reg[skill_id]["risk"],
        "decision": decision,
        "gates": gates_out,
        "next_action": next_action,
        "caveat": "Self-marked evidence is not independent validation.",
    }
