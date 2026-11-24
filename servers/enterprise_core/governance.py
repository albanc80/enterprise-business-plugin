"""Pure governance evaluators.

Split out of the MCP layer on purpose: the approval gate and the release gate are
business logic, and business logic that can only be exercised by starting a server
is business logic that does not get tested.

Nothing here does I/O beyond reading the policy files through `registry`.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from . import registry


def digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _norm_role(value: str) -> str:
    """Roles compare loosely: case, spacing and punctuation are spelling, not authority."""
    spaced = "".join(ch if ch.isalnum() else " " for ch in str(value or ""))
    return " ".join(spaced.split()).casefold()


def _norm_identity(value: str) -> str:
    """Identities compare on their normalised form, never raw strings."""
    return " ".join(str(value or "").split()).casefold()


def evaluate_approval(
    skill_id: str,
    proposed_action: str,
    requester_id: str,
    approver_id: str,
    evidence: dict[str, Any],
    approver_role: str = "",
    approval_age_minutes: float = 0.0,
    approval_id: str | None = None,
    operation: str = "",
    issued: dict[str, dict[str, Any]] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Validate a proposed approval, or redeem one this server actually issued.

    Two modes, and the difference matters:

    * **issue** (no `approval_id`) — runs the policy checks, then, only if the skill's
      *effective* autonomy permits a protected action at all, issues a single-use token
      bound to the digest of this exact action.
    * **redeem** (`approval_id`) — refuses any id it never issued, any token already
      spent, any token whose bound action/evidence/operation has changed, and any token
      past its expiry. A token is not a session, a role, or "someone said fine earlier".

    `issued` is the ledger of live tokens; pass the server's single instance so a restart
    voids outstanding approvals rather than silently honouring them.
    """
    reg = registry.skills()
    if skill_id not in reg:
        return {
            "allowed": False,
            "rule": "unknown_skill",
            "error": f"unknown skill_id {skill_id!r}; call list_skills for the canonical ids",
        }

    contract = reg[skill_id]
    rules = registry.approval_rules()["rules"]
    window = float(rules["expiry"]["default_window_minutes"])
    required = list(rules["evidence_bundle"]["required_fields"])
    ledger = issued if issued is not None else {}
    clock = time.time() if now is None else now

    # ------------------------------------------------------------------ redeem
    if approval_id:
        token = ledger.get(approval_id)
        if token is None:
            return {
                "allowed": False,
                "rule": "unissued_approval",
                "approval_id": approval_id,
                "error": (
                    "this approval_id was never issued by this server. An approval that "
                    "cannot be traced to a validation is not an approval."
                ),
            }
        if token.get("redeemed_at"):
            return {
                "allowed": False,
                "rule": "already_redeemed",
                "approval_id": approval_id,
                "error": "approval already redeemed — approvals are single-use",
            }
        if token["skill_id"] != skill_id:
            return {
                "allowed": False,
                "rule": "scope_mismatch",
                "approval_id": approval_id,
                "error": (
                    f"token was issued for {token['skill_id']!r} and cannot authorise "
                    f"{skill_id!r}"
                ),
            }

        effective_op = operation or token["operation"]
        presented = digest(
            {
                "skill_id": skill_id,
                "operation": effective_op,
                "proposed_action": proposed_action,
                "evidence": evidence,
            }
        )
        if effective_op != token["operation"]:
            return {
                "allowed": False,
                "rule": "scope_mismatch",
                "approval_id": approval_id,
                "error": (
                    f"token authorises the {token['operation']!r} operation, not "
                    f"{effective_op!r}"
                ),
            }
        if presented != token["action_digest"]:
            return {
                "allowed": False,
                "rule": "action_changed",
                "approval_id": approval_id,
                "bound_digest": token["action_digest"],
                "presented_digest": presented,
                "error": (
                    "the action, its evidence or its operation differs from what was "
                    "approved. A changed action needs a new approval."
                ),
            }
        if clock > token["expires_at"]:
            return {
                "allowed": False,
                "rule": "expired",
                "approval_id": approval_id,
                "expired_at": token["expires_at"],
                "error": "approval window elapsed; request a fresh approval",
            }

        token["redeemed_at"] = clock
        return {
            "allowed": True,
            "approval_id": approval_id,
            "skill_id": skill_id,
            "operation": token["operation"],
            "redeemed": True,
            "action_digest": token["action_digest"],
            "note": "One action authorised and now consumed. Any change requires a new approval.",
        }

    # ------------------------------------------------------------------- issue
    checks: list[dict[str, Any]] = []

    def check(rule: str, ok: bool, detail: str) -> None:
        checks.append({"rule": rule, "status": "pass" if ok else "fail", "detail": detail})

    # A ceiling above the caller: refuse before the policy checks, because no set of
    # approvals can authorise an action the skill may not take.
    resolution = registry.resolve_autonomy(skill_id)
    mode = resolution["mode"]
    ceiling_ok = mode in {"human_confirm", "auto"}
    check(
        "autonomy_ceiling",
        ceiling_ok,
        (
            f"effective {resolution['autonomy_effective']} ({mode}) permits a protected action"
            if ceiling_ok
            else (
                f"effective {resolution['autonomy_effective']} ({mode}) does not permit a "
                "protected action — this skill drafts or advises, so no approval can "
                "authorise a write for it"
            )
        ),
    )

    try:
        operations = registry.tool_allowlist(skill_id)["allowed_operations"]
    except KeyError:
        operations = ["read"]  # unknown allowlist entry denies writes, never allows them
    requested_op = operation or ("write" if "write" in operations else operations[-1])
    check(
        "operation_permitted",
        requested_op in operations,
        (
            f"{requested_op!r} is within {resolution['autonomy_effective']}"
            if requested_op in operations
            else f"{requested_op!r} not permitted at {resolution['autonomy_effective']} (allowed: {operations})"
        ),
    )

    missing = [field for field in required if not evidence.get(field)]
    req_norm, appr_norm = _norm_identity(requester_id), _norm_identity(approver_id)
    action_norm = " ".join(proposed_action.split())
    seen_by_approver = " ".join(str(evidence.get("proposed_action") or "").split())
    action_bound = bool(action_norm) and seen_by_approver == action_norm
    check(
        "action_specific",
        action_bound,
        (
            "the approver's copy of the action matches the action being approved"
            if action_bound
            else (
                f"evidence.proposed_action {seen_by_approver!r} is not the action being "
                f"approved ({action_norm!r}); a summary that differs is not an approval "
                "of this action"
                if action_norm
                else "no proposed action was supplied"
            )
        ),
    )
    check(
        "separation_of_duties",
        bool(req_norm) and bool(appr_norm) and appr_norm != req_norm,
        (
            f"approver {appr_norm!r} differs from requester {req_norm!r}"
            if req_norm and appr_norm and appr_norm != req_norm
            else "approver and requester must both be stated and must differ"
        ),
    )
    check(
        "expiry",
        approval_age_minutes <= window,
        f"window is {int(window)} minutes, presented age {approval_age_minutes}",
    )
    check(
        "evidence_bundle",
        not missing,
        "complete" if not missing else f"missing: {', '.join(missing)}",
    )
    role_directory = rules.get("authorised_approver", {}).get("roles_by_risk", {})
    listed_roles = {
        _norm_role(role) for role in role_directory.get(contract["risk"], []) if str(role).strip()
    }
    # The contract names an accountable owner per skill, in the source document. That is
    # delegated authority the pack did not invent, so it is a valid approver without any
    # configuration — and being the owner of the function is the narrowest form of it.
    owner_roles = {
        _norm_role(part) for part in str(contract.get("owner", "")).split("/") if part.strip()
    }
    role_norm = _norm_role(approver_role)
    matches_owner = bool(role_norm) and role_norm in owner_roles
    matches_list = bool(role_norm) and role_norm in listed_roles

    if matches_list:
        approver_ok, approver_basis = True, f"listed for risk tier {contract['risk']}"
        approver_detail = (
            f"role {approver_role.strip()!r} is authorised by roles_by_risk for "
            f"{contract['risk']}"
        )
    elif matches_owner:
        approver_ok, approver_basis = True, "contract owner"
        approver_detail = (
            f"role {approver_role.strip()!r} matches the contract owner "
            f"{contract.get('owner')!r}"
        )
    else:
        approver_ok, approver_basis = False, None
        approver_detail = (
            f"role {approver_role.strip()!r} is neither listed for risk tier "
            f"{contract['risk']!r} nor the contract owner {contract.get('owner')!r}. "
            "Authority comes from the contract's owner or from "
            "rules.authorised_approver.roles_by_risk — not from the role merely existing."
        )
    check("authorised_approver", approver_ok, approver_detail)
    if approver_basis:
        checks[-1]["basis"] = approver_basis

    failed = [c for c in checks if c["status"] != "pass"]
    if failed:
        rules = [c["rule"] for c in failed]
        if "autonomy_ceiling" in rules:
            next_action = (
                "Do not issue a token, and do not retry with different evidence: the "
                "obstacle is the permission ceiling, not the paperwork. Route the "
                "proposed action to the owning system and its authorised operator."
            )
        else:
            next_action = (
                "Deny and route back to the requester with the failed rule named: "
                + ", ".join(rules)
            )
        return {
            "allowed": False,
            "skill_id": skill_id,
            "risk": contract["risk"],
            "operation": requested_op,
            "checks": checks,
            "failed_rules": rules,
            "next_action": next_action,
        }

    new_id = f"apr_{uuid.uuid4().hex[:16]}"
    action_digest = digest(
        {
            "skill_id": skill_id,
            "operation": requested_op,
            "proposed_action": proposed_action,
            "evidence": evidence,
        }
    )
    expires_at = clock + window * 60
    ledger[new_id] = {
        "skill_id": skill_id,
        "operation": requested_op,
        "action_digest": action_digest,
        "requester": req_norm,
        "approver": appr_norm,
        "approver_role": approver_role.strip(),
        "approver_authority": next(
            (c.get("basis") for c in checks if c["rule"] == "authorised_approver"), None
        ),
        "risk": contract["risk"],
        "issued_at": clock,
        "expires_at": expires_at,
        "redeemed_at": None,
    }

    return {
        "allowed": True,
        "skill_id": skill_id,
        "risk": contract["risk"],
        "operation": requested_op,
        "checks": checks,
        "approval_id": new_id,
        "action_digest": action_digest,
        "issued_at": clock,
        "expires_at": expires_at,
        "valid_for_minutes": int(window),
        "next_action": (
            "Execute exactly this action once, then audit_append the receipt with the "
            "approval id. Any change to the action voids this token."
        ),
    }


def _tool_categories(tool: dict[str, Any], manifest_categories: set[str]) -> set[str]:
    """A tool's categories: its own `category` if declared, else the whole connector's."""
    if tool.get("category"):
        return {str(tool["category"]).strip().lower()}
    return manifest_categories


def _norm_token(value: Any) -> str:
    """Operation and status tokens compare on case and padding, never on content."""
    return str(value or "").strip().lower()


def evaluate_tool_call(
    skill_id: str,
    tool_name: str,
    operation: str,
    category: str,
    connector_status: str = "",
) -> dict[str, Any]:
    """Decide whether one skill may call one tool. Deny-by-default.

    This is the enforcement primitive a gateway calls before dispatch. It answers a
    different question from route_autonomy: that one says whether the capability may
    write at all, this one says whether it may reach this tool. Both have to allow.

    The verdict is **category-scoped**, not tool-name-scoped: the allowlist says a skill
    may reach ITSM tools at `read`, and this function has no tool directory to check a
    concrete name against. `tool_name` is echoed and marked `tool_name_verified: false`
    so an allow is never mistaken for "this specific tool is permitted" — resolving a
    name needs a connector manifest and `check_connector`.

    `connector_status` must be the verdict from `check_connector`. There is deliberately
    no default: silence is not evidence the connector was checked, and defaulting to
    "ready" made the gate fail open on the one argument that proves it was.
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

    if not str(tool_name or "").strip():
        return {**base, "allowed": False, "rule": "missing_tool", "reason": "no tool name supplied"}

    connector = _norm_token(connector_status)
    if not connector:
        return {
            **base,
            "allowed": False,
            "rule": "connector_unverified",
            "reason": (
                "connector_status was not supplied. A gateway that has not checked the "
                "connector is not authorised to dispatch: call check_connector and pass "
                "its decision here."
            ),
        }
    if connector != "ready":
        return {
            **base,
            "allowed": False,
            "rule": "connector_not_conformant",
            "reason": (
                f"connector decision is {connector_status!r}; run check_connector and fix "
                "it first"
            ),
        }

    allowed_operations = [_norm_token(op) for op in allow["allowed_operations"]]
    if _norm_token(operation) not in allowed_operations:
        return {
            **base,
            "allowed": False,
            "rule": "operation_not_permitted",
            "reason": (
                f"{operation!r} is not permitted at {allow['effective_autonomy']} "
                f"(allowed: {allow['allowed_operations']})"
            ),
        }

    declared_categories = [_norm_token(c) for c in allow["allowed_categories"]]
    if _norm_token(category) not in declared_categories:
        return {
            **base,
            "allowed": False,
            "rule": "category_not_declared",
            "reason": (
                f"category {category!r} is not declared by this skill "
                f"(declared: {allow['allowed_categories']})"
            ),
        }

    return {
        **base,
        "allowed": True,
        "rule": "allowlist",
        "reason": (
            f"{_norm_token(operation)!r} on category {_norm_token(category)!r} is within "
            f"{allow['effective_autonomy']} and declared by the contract"
        ),
        "scope": "category",
        "tool_name_verified": False,
        "note": (
            "This verdict covers the category and operation, not the concrete tool name. "
            "Resolve the name against a connector manifest with check_connector before "
            "treating a specific tool as permitted."
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
    if not isinstance(manifest, dict):
        return {
            "decision": "rejected",
            "error": "invalid manifest",
            "reason": (
                "a connector manifest must be an object with tools, operations and the "
                f"conformance flags; got {type(manifest).__name__}"
            ),
            "structural_checks": [],
            "tools": [],
            "available_operations": [],
        }

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

    if evidence is not None and not isinstance(evidence, dict):
        return {
            "skill_id": skill_id,
            "decision": "blocked",
            "error": "invalid evidence",
            "reason": (
                "evidence must be an object mapping gate item -> true; got "
                f"{type(evidence).__name__}. A malformed bundle cannot be evaluated, so it "
                "blocks rather than passing."
            ),
        }
    if waivers is not None:
        if not isinstance(waivers, list) or any(not isinstance(w, dict) for w in waivers):
            return {
                "skill_id": skill_id,
                "decision": "blocked",
                "error": "invalid waivers",
                "reason": (
                    "waivers must be a list of objects with item, owner, justification and "
                    "expiry"
                ),
            }

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
