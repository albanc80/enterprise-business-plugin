#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=2,<3", "pyyaml>=6,<7"]
# ///
"""enterprise-core — the deterministic governance spine for the enterprise skills pack.

Speaks MCP over stdio. Every tool is pure computation or append-only bookkeeping:
no network calls, no enterprise system connections, no writes outside the plugin
data directory, no execution of a business action.

What it *does* do is refuse, cap and record. The autonomy ceiling, the risk matrix,
the approval rules and the release gates are loaded from `src/policies/*.yaml` — the
same files the skills cite — so a skill that explains a gate and the tool that
enforces it cannot disagree.

Run:  uv run --script servers/enterprise_core/main.py
Check: uv run --script servers/enterprise_core/main.py --selftest
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from enterprise_core import governance, registry  # noqa: E402

VERSION = registry.version()

# mcp 2.x: FastMCP was renamed to MCPServer; the @tool() decorator and stdio run() are
# the same shape as before.
mcp = MCPServer("enterprise-core", version=VERSION)

# Counts asserted by --selftest and by tools/validate.py. If the SRD gains a skill,
# these move with it — tools/build.py and the tests both read the same two numbers
# from the source document.
EXPECTED = {
    "skills": 93,
    "domains": 12,
    "requirements": 32,
    "waves": 4,
    "metrics": 6,
    "safeguards": 6,
    "release_gates": 3,
}

# In-process ledger of tokens this server issued and has not yet seen redeemed.
# Only ids in here can be redeemed, so a forged id fails closed. A restart empties it,
# which voids outstanding approvals rather than silently honouring them; that is the
# intended failure direction, and it is documented as a limitation in SECURITY.md.
_ISSUED: dict[str, dict[str, Any]] = {}


# --------------------------------------------------------------------- helpers


def _data_dir() -> Path:
    return registry.data_dir()


def _audit_path() -> Path:
    return _data_dir() / "audit.jsonl"


_AUDIT_GENESIS = "genesis"


def _entry_hash(record: dict[str, Any]) -> str:
    """The canonical hash of one entry.

    Defined once and used by both the writer and the verifier: two implementations of
    "what is hashed" is how a chain quietly stops agreeing with itself.
    """
    body = {key: value for key, value in record.items() if key != "entry_hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def verify_chain(path: Path | None = None) -> dict[str, Any]:
    """Walk the whole trail and report the first entry that does not hold up.

    Detects edited content (hash mismatch), an edited entry whose own hash was recomputed
    (the next entry still records the old one), deleted or reordered entries (broken
    previous_hash link), unreadable lines and missing hashes.

    It cannot detect removal of the *newest* entries: the surviving prefix is a valid
    chain. That needs an anchor outside the file — a count or head hash recorded
    elsewhere — and is stated as a limitation rather than implied away.
    """
    path = path or _audit_path()
    report: dict[str, Any] = {
        "verified": True,
        "entries": 0,
        "first_bad_index": None,
        "problems": [],
    }
    if not path.exists():
        return report

    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    report["entries"] = len(lines)
    expected_previous = _AUDIT_GENESIS

    def bad(index: int, message: str) -> None:
        report["verified"] = False
        if report["first_bad_index"] is None:
            report["first_bad_index"] = index
        report["problems"].append(f"entry {index}: {message}")

    for index, line in enumerate(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            bad(index, "unreadable line (not JSON) — cannot be verified")
            continue
        if not isinstance(record, dict):
            bad(index, "unreadable line (not a JSON object)")
            continue

        recorded = record.get("entry_hash")
        if not recorded:
            bad(index, "missing entry_hash")
        elif _entry_hash(record) != recorded:
            bad(index, "content does not match its entry_hash — the entry was edited")

        linked = record.get("previous_hash")
        if linked != expected_previous:
            bad(
                index,
                f"previous_hash {linked!r} does not link to the preceding entry "
                f"{expected_previous!r} — an entry was removed, reordered or rewritten",
            )
        if recorded:
            expected_previous = recorded
    return report


def _last_hash() -> str:
    path = _audit_path()
    if not path.exists():
        return "genesis"
    last = None
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                last = line
    if last is None:
        return "genesis"
    try:
        return json.loads(last).get("entry_hash", "genesis")
    except json.JSONDecodeError:
        return "unverified"


# ---------------------------------------------------------------------- tools


@mcp.tool()
def list_capabilities() -> dict[str, Any]:
    """Report what this server can and cannot do before a caller trusts an answer.

    Read this first in any governance question. It states the shipped autonomy
    ceiling, the counts the package actually contains, and the boundaries that are
    deliberate rather than missing.
    """
    config = registry.autonomy_config()
    counts = registry.load_ok()
    return {
        "server": "enterprise-core",
        "version": VERSION,
        "counts": counts,
        "autonomy": {
            "ceiling_default": config["ceiling"]["default_max_level"],
            "a3_shipped": config["ceiling"]["a3_shipped"],
            "a2_opt_in_skills": [
                e.get("skill") if isinstance(e, dict) else e
                for e in config["opt_in"]["a2_skills"] or []
            ],
            "opt_in_requires": config["opt_in"]["requires"],
            "tiers": {
                level: {"rank": t["rank"], "name": t["name"], "mode": t["mode_result"]}
                for level, t in registry.tiers().items()
            },
        },
        "risk_tiers": {
            risk: {"max_autonomy": f"A{r['max_rank']}", "permitted": r["permitted_autonomy"]}
            for risk, r in registry.risk_controls().items()
        },
        "excluded_final_decisions": config.get("excluded_final_decisions", []),
        "can": [
            "look up any of the skill contracts by id, domain, risk, wave or text",
            "resolve the autonomy a skill may actually reach, and name every downgrade",
            "validate a proposed approval against the approval rules",
            "check release-gate evidence and report exactly what is missing",
            "score and rank candidate skills with the SRD's own weighting",
            "append to and verify a hash-chained audit trail",
        ],
        "cannot": [
            "connect to any enterprise system — no HRIS, ERP, ITSM, CRM, EHS or IAM",
            "execute, submit, publish, book, pay or grant anything",
            "decide a hiring, safety, legal, medical, payroll or contract outcome",
            "produce a measured benefit — every metric in the registry is a hypothesis",
            "make an approval valid; it validates one an authorised human granted",
        ],
        "limitations": [
            "the issued-token ledger is in-process: a restart voids outstanding approvals rather than honouring them",
            "skill contracts are proposed and unvalidated, exactly as the SRD states",
        ],
    }


@mcp.tool()
def list_domains() -> dict[str, Any]:
    """List the 12 business functions with owner and skill count.

    Use this before choosing a skill so the answer names the right function owner
    rather than an invented one.
    """
    return {
        "domains": [
            dict(d, skill_count=registry.domain_counts().get(d["id"], 0))
            for d in registry.domains()
        ],
        "total_skills": len(registry.skills()),
    }


@mcp.tool()
def list_skills(
    domain: str | None = None,
    risk: str | None = None,
    wave: int | None = None,
    autonomy: str | None = None,
    query: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Search the skill registry and get a compact row per capability.

    Filters: `domain` (e.g. Finance, HSE, Foundation — the domain id, its display name
    or an unambiguous fragment of either), `risk` (Low, Moderate, High, Critical), `wave` (0-3), `autonomy`
    (A0-A3 as requested), `query` (free text over name, purpose, metric, owner, systems).
    An invalid filter returns an error naming the valid values; it does not return an
    empty list, because an empty list reads as "no such skill" rather than "bad filter". Call get_contract with an id for the full
    contract before advising on a specific skill.
    """
    problems = registry.validate_filters(
        domain=domain, risk=risk, wave=wave, autonomy=autonomy, limit=limit
    )
    if problems:
        return {
            "error": "invalid filter",
            "problems": problems,
            "matched": 0,
            "returned": 0,
            "truncated": False,
            "skills": [],
            "note": "The filter was rejected rather than run; an empty result would have read as 'no such skill'.",
        }
    canonical_domain, _ = registry.resolve_domain(domain)
    found = registry.find(
        domain=canonical_domain, risk=risk, wave=wave, autonomy=autonomy, query=query
    )
    rows = [registry.public_view(c) for c in found[: max(1, limit)]]
    return {
        "matched": len(found),
        "returned": len(rows),
        "truncated": len(found) > len(rows),
        "skills": rows,
        "note": "Score is a prioritisation hypothesis from the SRD, not measured ROI.",
    }


@mcp.tool()
def get_contract(skill_id: str) -> dict[str, Any]:
    """Return one skill contract in full, plus the autonomy this package allows.

    Give the user the owner, the acceptance criterion, the escalation path and the
    side effects. Quote the acceptance criterion when asked whether the skill is
    ready — being proposed is not being validated.

    Use `side_effects.effective`, not `contract.side_effects`: the contract states what
    the skill was specified to do, while the package may resolve it to a lower level.
    """
    reg = registry.skills()
    if skill_id not in reg:
        suggestions = [
            s for s in reg if skill_id.upper()[:3] in s
        ][:5]
        return {
            "error": f"unknown skill_id {skill_id!r}",
            "did_you_mean": suggestions or [s for s in reg][:5],
        }
    contract = reg[skill_id]
    resolution = registry.resolve_autonomy(skill_id)
    return {
        "contract": contract,
        "side_effects": registry.side_effects(skill_id),
        "score": registry.score(contract),
        "autonomy_resolution": resolution,
    }


@mcp.tool()
def route_autonomy(
    skill_id: str,
    requested_level: str | None = None,
    approval_present: bool = False,
) -> dict[str, Any]:
    """Decide what a skill may actually do: read, draft, approved action, or auto.

    Three constraints intersect — what the skill requests, what this package's
    ceiling allows, and what its risk tier permits. The result is the binding answer.
    Report `mode` and `may_not` verbatim: a downgrade that is not spoken is the
    failure this tool exists to prevent.

    `approval_present` does not validate an approval. It only tells the resolver
    that one exists; approval_gate is what validates it.
    """
    try:
        return registry.resolve_autonomy(skill_id, requested_level, approval_present)
    except KeyError as exc:
        return {"error": str(exc), "hint": "call list_skills to find a valid skill_id"}
    except ValueError as exc:
        return {"error": str(exc), "valid_levels": list(registry.RANK)}


@mcp.tool()
def approval_gate(
    skill_id: str,
    proposed_action: str,
    requester_id: str,
    approver_id: str,
    evidence: dict[str, Any],
    approver_role: str = "",
    approval_age_minutes: float = 0.0,
    approval_id: str | None = None,
    operation: str = "",
) -> dict[str, Any]:
    """Validate an approval against the package's approval rules, or redeem one.

    Two modes. Without `approval_id` this evaluates a proposed approval and, if every
    rule passes, issues a single-use token bound to that exact action. With
    `approval_id` it redeems that token once — a second redemption is rejected.

    Rules enforced (src/policies/approval.yaml): action-specific binding, expiry,
    single use, separation of duties, and a complete evidence bundle. Missing or
    malformed evidence denies; it never degrades to allow.

    Redemption is checked against the tokens this server issued: an id it never issued,
    a spent token, a changed action, evidence or operation, or an expired token all
    deny. A token cannot authorise an action the skill's effective autonomy forbids —
    issuance is refused for drafting-only skills, so no approval exists for them.
    """
    return governance.evaluate_approval(
        skill_id=skill_id,
        proposed_action=proposed_action,
        requester_id=requester_id,
        approver_id=approver_id,
        evidence=evidence,
        approver_role=approver_role,
        approval_age_minutes=approval_age_minutes,
        approval_id=approval_id,
        operation=operation,
        issued=_ISSUED,
    )

@mcp.tool()
def release_gate(
    skill_id: str,
    evidence: dict[str, bool] | None = None,
    waivers: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Check whether a skill has the evidence to deploy, expand, or not yet.

    `evidence` maps gate item -> true when the evidence exists. `waivers` entries need
    `item`, `owner`, `justification` and `expiry`; anything in the never-waivable list
    is rejected regardless. A waiver is reported as a waiver, never as a pass.
    """
    return governance.evaluate_release(skill_id=skill_id, evidence=evidence, waivers=waivers)

@mcp.tool()
def check_connector(
    connector_manifest: dict[str, Any],
    skill_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Check whether a connector the user supplies can carry this package's guarantees.

    Pass a manifest describing the connector — its system categories, transport and
    tool declarations — and the skills it is meant to serve. The check is structural:
    manifest completeness, audit passthrough, least privilege, no ambient
    credentials, bounded retry, and for every write tool an idempotency key, a
    post-condition and a rollback.

    Then it checks fit per skill: an A0/A1 skill needs a read tool, an A2 skill needs
    a write tool. A connector that is structurally sound but exposes only reads will
    give you drafting, and says so.

    It cannot tell you whether your connector maps the right fields or behaves under
    load. Passing means "capable of carrying the guarantees", not "correct".
    """
    return governance.evaluate_connector(connector_manifest, skill_ids)


@mcp.tool()
def tool_allowlist(skill_id: str) -> dict[str, Any]:
    """What a skill may call: its declared system categories and permitted operations.

    This is the abstract rule, derived from the contract's `system_categories` and the
    skill's *effective* autonomy. An A0/A1 skill may only read — drafting happens in
    the conversation, and `propose` creates a record. A2 adds propose and write.

    This package does not route tool calls, so it cannot enforce this. It gives you
    the rule; the gateway or client that fronts your connectors has to apply it before
    dispatch. Use check_tool_call for the per-call decision, or check_connector to turn
    the rule into concrete tool names for a specific connector.
    """
    try:
        return registry.tool_allowlist(skill_id)
    except KeyError as exc:
        return {"error": str(exc), "hint": "call list_skills to find a valid skill_id"}


@mcp.tool()
def check_tool_call(
    skill_id: str,
    tool_name: str,
    operation: str,
    category: str,
    connector_status: str = "",
) -> dict[str, Any]:
    """Decide whether one skill may call one tool. Deny-by-default.

    The enforcement primitive for a gateway: call this before dispatching a tool, and
    refuse on any non-allow verdict. It is a different question from route_autonomy —
    that answers "may this capability write at all", this answers "may it reach this
    tool". Both must allow.

    `operation` must be read, propose or write; `category` is the system category the
    tool belongs to, as declared in the connector manifest.

    `connector_status` must be the verdict you got from check_connector. There is no
    default on purpose: omitting it returns `connector_unverified` and refuses, because
    a gateway that has not checked the connector is not authorised to dispatch.

    The verdict is category-scoped. `tool_name` is echoed and marked
    `tool_name_verified: false` — resolve a concrete name with check_connector before
    treating that specific tool as permitted.
    """
    return governance.evaluate_tool_call(
        skill_id=skill_id,
        tool_name=tool_name,
        operation=operation,
        category=category,
        connector_status=connector_status,
    )


@mcp.tool()
def score_skills(
    skill_ids: list[str] | None = None,
    weights: dict[str, float] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Rank skills with the SRD's opportunity score, or re-weight it.

    Pass ids to score a shortlist, or omit to rank the whole registry. `weights`
    accepts impact, readiness, reuse, effort and risk and is normalised, so the
    numbers do not have to sum to anything in particular.
    """
    merged, weight_errors = registry.validate_weights(weights)
    if weight_errors:
        return {
            "error": "invalid weights",
            "problems": weight_errors,
            "valid_keys": sorted(merged),
            "range": [registry.WEIGHT_MIN, registry.WEIGHT_MAX],
            "ranked": [],
            "total_scored": 0,
        }
    if skill_ids is not None:
        unknown = [i for i in skill_ids if i not in registry.skills()]
        if unknown:
            return {
                "error": "unknown skill_ids",
                "problems": [f"{i!r} is not in the registry" for i in unknown],
                "ranked": [],
                "total_scored": 0,
            }

    reg = registry.skills()
    candidates = (
        [reg[i] for i in skill_ids] if skill_ids else list(reg.values())
    )
    ranked = sorted(
        ({"id": c["id"], "name": c["name"], "domain": c["domain"], "wave": c["wave"],
          "risk": c["risk"], "score": registry.score(c, merged)} for c in candidates),
        key=lambda r: (-r["score"], r["wave"], r["id"]),
    )
    return {
        "ranked": ranked[: max(1, limit)],
        "total_scored": len(ranked),
        "weights_used": merged,
        "caveat": registry.scoring_policy()["caveat"],
    }


@mcp.tool()
def list_requirements(
    type: str | None = None,
    priority: str | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    """Look up the SRD's 32 testable requirements by type, priority or text.

    Use this to answer "what does the platform have to prove", and quote the
    acceptance line rather than paraphrasing it.
    """
    found = []
    for req in registry.requirements():
        if type and req["type"].lower() != type.lower():
            continue
        if priority and req["priority"].lower() != priority.lower():
            continue
        if query:
            hay = " ".join(str(req[k]) for k in ("id", "name", "statement", "accept")).lower()
            if query.lower() not in hay:
                continue
        found.append(req)
    return {"matched": len(found), "requirements": found}


@mcp.tool()
def get_roadmap() -> dict[str, Any]:
    """Return the four delivery waves, their exit gates and the suggested pilot.

    The sequence is a recommendation from the SRD, not a delivery promise. Every
    gate needs named evidence before the next wave starts.
    """
    return {
        "waves": registry.roadmap(),
        "suggested_pilot": registry.checklist().get("suggested_pilot", []),
        "safeguards": registry.safeguards(),
        "caveat": "Waves are sequencing guidance. Each exit gate requires observed evidence.",
    }


@mcp.tool()
def audit_append(entry: dict[str, Any]) -> dict[str, Any]:
    """Append a decision record to the tamper-evident audit trail.

    Include skill_id, actor, mode, risk, approval_id (when one was redeemed),
    downgrades applied, and the outcome. Each entry is chained to the previous by
    hash; `audit_trace` recomputes the chain on read and reports the first break.
    The response also states whether the trail verified *before* this append.
    """
    path = _audit_path()
    inherited = verify_chain(path)
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "previous_hash": _last_hash(),
        "entry": entry,
    }
    record["entry_hash"] = _entry_hash(record)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")

    result: dict[str, Any] = {
        "appended": True,
        "path": str(path),
        "entry_hash": record["entry_hash"],
        "chain_intact_before_append": inherited["verified"],
        "entries": inherited["entries"] + 1,
    }
    if not inherited["verified"]:
        # Appending is still correct — refusing would destroy the record of what just
        # happened — but the caller must not be told the trail is sound.
        result["integrity_warning"] = (
            "the trail did not verify before this append ("
            + inherited["problems"][0]
            + "). This entry is chained to the record as written, but the trail is already "
            "broken there; audit_trace reports where."
        )
        result["integrity"] = inherited
    return result


@mcp.tool()
def audit_trace(limit: int = 20) -> dict[str, Any]:
    """Read the most recent audit entries, oldest first, with chain verification.

    `verified` is the answer to "has this trail been tampered with". When it is false,
    `integrity.problems` names the first entry that does not hold up and why — quote it
    rather than summarising. It cannot detect truncation of the newest entries.
    """
    path = _audit_path()
    integrity = verify_chain(path)
    if not path.exists():
        return {
            "entries": [],
            "total": 0,
            "path": str(path),
            "verified": True,
            "integrity": integrity,
        }
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    entries: list[Any] = []
    for line in lines[-max(1, limit):]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            entries.append({"unreadable": line[:120]})
    return {
        "entries": entries,
        "total": len(lines),
        "path": str(path),
        "verified": integrity["verified"],
        "integrity": integrity,
    }


# -------------------------------------------------------------------- selftest


def selftest() -> int:
    """Verify the install without starting a session: deps resolved, registry intact,
    policies load, and the governance path actually answers.

    Also the cheapest way to warm the uv cache before a first session, which keeps a
    cold start from colliding with a client's MCP startup timeout.
    """
    root = registry.plugin_root()
    checks: list[tuple[str, bool, str]] = []

    manifest = root / "plugin.json"
    checks.append(("plugin.json", manifest.exists(), str(manifest)))

    counts = registry.load_ok()
    for key, expected in EXPECTED.items():
        checks.append(
            (key, counts.get(key) == expected, f"{counts.get(key)} found, {expected} expected")
        )

    skill_files = sorted((root / "skills").glob("*/SKILL.md"))
    checks.append(("skills/SKILL.md", len(skill_files) >= 12, f"{len(skill_files)} found"))

    # Exercises the policy-load and resolution path, where a bad install fails first.
    try:
        resolution = registry.resolve_autonomy("FND-01")
        checks.append(
            (
                "autonomy resolution",
                resolution["mode"] in {"advisory_only", "draft_only"},
                f"FND-01 -> {resolution['autonomy_effective']}/{resolution['mode']}",
            )
        )
    except Exception as exc:  # noqa: BLE001 - report, do not raise
        checks.append(("autonomy resolution", False, str(exc)))

    # A2 must not be reachable out of the box.
    try:
        capped = registry.resolve_autonomy("IT-01", "A3")
        checks.append(
            (
                "ceiling holds",
                capped["autonomy_effective"] in {"A0", "A1"},
                f"A3 request resolved to {capped['autonomy_effective']}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(("ceiling holds", False, str(exc)))

    try:
        sample = registry.skills()["FND-01"]
        value = registry.score(sample)
        checks.append(("opportunity scoring", 0 <= value <= 100, f"FND-01 score {value}"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("opportunity scoring", False, str(exc)))

    failed = [name for name, ok, _ in checks if not ok]
    for name, ok, detail in checks:
        print(f"  [{'OK' if ok else 'FAIL'}] {name}: {detail}")
    print(
        f"\n{'selftest FAILED' if failed else 'selftest OK'} — enterprise-core {VERSION}, "
        f"{counts['skills']} contracts, {counts['domains']} domains, plugin root {root}"
    )
    return 1 if failed else 0


def main() -> None:
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    mcp.run("stdio")


if __name__ == "__main__":
    main()
