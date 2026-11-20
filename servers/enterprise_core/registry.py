"""Registry and policy engine for enterprise-core.

Everything this module returns is derived from files in the package:

  src/registry/*.yaml   — the 93 skill contracts, domains, requirements, roadmap
  src/policies/*.yaml   — autonomy ceiling, tiers, risk matrix, approval, gates

No thresholds, tier ranks or counts are hard-coded here. That is deliberate: the
skills cite the same files, so a citation and a computation cannot drift apart.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

RANK = {"A0": 0, "A1": 1, "A2": 2, "A3": 3}
LEVEL = {0: "A0", 1: "A1", 2: "A2", 3: "A3"}


def plugin_root() -> Path:
    """PLUGIN_ROOT when the client supplies it, else this file's package root."""
    env = os.environ.get("PLUGIN_ROOT")
    return Path(env) if env else Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    """PLUGIN_DATA when supplied, else a package-local .data directory."""
    root = Path(os.environ.get("PLUGIN_DATA") or (plugin_root() / ".data"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _read(relative: str) -> dict[str, Any]:
    path = plugin_root() / relative
    if not path.exists():
        raise FileNotFoundError(f"missing required package file: {relative}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


@lru_cache(maxsize=1)
def skills() -> dict[str, dict[str, Any]]:
    return {s["id"]: s for s in _read("src/registry/skills.yaml")["skills"]}


@lru_cache(maxsize=1)
def domains() -> list[dict[str, Any]]:
    return _read("src/registry/domains.yaml")["domains"]


@lru_cache(maxsize=1)
def requirements() -> list[dict[str, Any]]:
    return _read("src/registry/requirements.yaml")["requirements"]


@lru_cache(maxsize=1)
def roadmap() -> list[dict[str, Any]]:
    return _read("src/registry/roadmap.yaml")["waves"]


@lru_cache(maxsize=1)
def metrics() -> list[dict[str, Any]]:
    return _read("src/registry/metrics.yaml")["metrics"]


@lru_cache(maxsize=1)
def checklist() -> dict[str, Any]:
    return _read("src/registry/checklist.yaml")


@lru_cache(maxsize=1)
def sources() -> list[dict[str, Any]]:
    return _read("src/registry/sources.yaml")["sources"]


@lru_cache(maxsize=1)
def autonomy_config() -> dict[str, Any]:
    return _read("src/policies/autonomy-config.yaml")


@lru_cache(maxsize=1)
def tiers() -> dict[str, dict[str, Any]]:
    return {t["level"]: t for t in _read("src/policies/autonomy-tiers.yaml")["tiers"]}


@lru_cache(maxsize=1)
def risk_controls() -> dict[str, dict[str, Any]]:
    return {t["risk"]: t for t in _read("src/policies/risk-controls.yaml")["tiers"]}


@lru_cache(maxsize=1)
def approval_rules() -> dict[str, Any]:
    return _read("src/policies/approval.yaml")


@lru_cache(maxsize=1)
def release_gates() -> dict[str, Any]:
    return _read("src/policies/release-gates.yaml")


@lru_cache(maxsize=1)
def safeguards() -> list[dict[str, Any]]:
    return _read("src/policies/safeguards.yaml")["safeguards"]


@lru_cache(maxsize=1)
def scoring_policy() -> dict[str, Any]:
    return _read("src/policies/scoring.yaml")


@lru_cache(maxsize=1)
def connector_policy() -> dict[str, Any]:
    return _read("src/policies/connectors.yaml")


@lru_cache(maxsize=1)
def tool_allowlist_policy() -> dict[str, Any]:
    return _read("src/policies/tool-allowlists.yaml")


@lru_cache(maxsize=1)
def allowlist_registry() -> dict[str, dict[str, Any]]:
    """Generated per-skill categories, keyed by skill id."""
    doc = _read("src/registry/tool-allowlists.yaml")
    return {str(e["skill"]): e for e in doc["skills"]}


def version() -> str:
    """Read from the manifest so the reported version cannot drift from what shipped."""
    try:
        manifest = json.loads((plugin_root() / "plugin.json").read_text(encoding="utf-8"))
        return str(manifest["version"])
    except Exception:  # noqa: BLE001 - a missing manifest must not stop the tools
        return "0.0.0+unknown"


# ------------------------------------------------------------------ autonomy


def pack_ceiling(skill_id: str) -> tuple[str, list[str]]:
    """The ceiling this *package* imposes on a skill, with the reasons why.

    An A2 opt-in is only honoured when the entry supplies every field listed in
    `opt_in.requires`. A bare skill id, or a mapping with a missing field, fails
    closed to the default ceiling and says so — an opt-in that silently does
    nothing is worse than no opt-in, because the operator believes it worked.
    """
    config = autonomy_config()
    opt = config.get("opt_in") or {}
    default_max = str(config.get("ceiling", {}).get("default_max_level", "A1"))
    requires = [str(f) for f in (opt.get("requires") or [])]
    entries = opt.get("a2_skills") or []

    entry = next(
        (e for e in entries if isinstance(e, dict) and str(e.get("skill")) == skill_id),
        None,
    )
    reasons: list[str] = []

    if entry is None:
        if any(isinstance(e, str) and e == skill_id for e in entries):
            reasons.append(
                "opt-in entry is a bare skill id with no evidence; A2 requires "
                f"{', '.join(requires)} — staying at the default ceiling"
            )
        else:
            reasons.append(f"package ceiling is {default_max} (no A2 opt-in for this skill)")
        return default_max, reasons

    missing = [field for field in requires if not entry.get(field)]
    if missing:
        reasons.append(
            f"A2 opt-in is incomplete (missing {', '.join(missing)}) — staying at the "
            "default ceiling"
        )
        return default_max, reasons

    reasons.append(f"A2 opt-in satisfied: {', '.join(requires)}")
    return "A2", reasons


def resolve_autonomy(
    skill_id: str,
    requested: str | None = None,
    approval_present: bool = False,
) -> dict[str, Any]:
    """Resolve what a skill may actually do: package ceiling ∩ risk cap ∩ request.

    Returns the effective level, the execution mode a caller should treat as law,
    and every downgrade that was applied — a silent downgrade is the failure this
    function exists to prevent.
    """
    reg = skills()
    if skill_id not in reg:
        raise KeyError(f"unknown skill_id {skill_id!r}; call list_skills first")
    contract = reg[skill_id]
    requested = (requested or contract["autonomy_requested"]).upper()
    if requested not in RANK:
        raise ValueError(f"requested autonomy {requested!r} is not one of A0..A3")

    downgrades: list[dict[str, str]] = []
    reasons: list[str] = []

    ceiling, ceiling_reasons = pack_ceiling(skill_id)
    reasons.extend(ceiling_reasons)

    risk = risk_controls()[contract["risk"]]
    risk_cap_rank = int(risk["max_rank"])
    risk_cap = LEVEL[risk_cap_rank]
    reasons.append(
        f"{contract['risk']} risk caps autonomy at {risk_cap} "
        f"({risk['permitted_autonomy']})"
    )

    effective_rank = min(RANK[requested], RANK[ceiling], risk_cap_rank)
    effective = LEVEL[effective_rank]

    if RANK[ceiling] > RANK[requested]:
        reasons.append(
            f"the ceiling permits {ceiling}, but the contract declares {requested} — a skill "
            "is never granted more autonomy than its own contract requests"
        )

    if RANK[requested] > RANK[ceiling]:
        downgrades.append(
            {
                "from": requested,
                "to": ceiling,
                "reason": "package autonomy ceiling — A3 is not shipped by this package"
                if requested == "A3"
                else "package autonomy ceiling; raise it per skill in src/policies/autonomy-config.yaml",
            }
        )
    if RANK[requested] > risk_cap_rank and RANK[ceiling] > risk_cap_rank:
        downgrades.append(
            {"from": requested, "to": risk_cap, "reason": f"{contract['risk']} risk tier cap"}
        )

    tier = tiers()[effective]
    mode = tier["mode_result"]
    requires_approval = mode == "human_confirm"

    if requires_approval and approval_present:
        next_action = (
            "Approval presented — validate it with approval_gate before executing. "
            "A2 authorises one action, not a session."
        )
    elif requires_approval:
        next_action = (
            "Prepare the action and route it to an authorised human with approval_gate. "
            "Do not execute."
        )
    elif mode == "draft_only":
        next_action = "Produce the draft and stop. A named human submits or publishes it."
    elif mode == "auto":
        next_action = "Pre-authorised bounded action; audit_append the receipt."
    else:
        next_action = "Read and advise only. Any consequential use of the advice is a human decision."

    return {
        "skill_id": skill_id,
        "skill_name": contract["name"],
        "risk": contract["risk"],
        "autonomy_requested": requested,
        "autonomy_effective": effective,
        "mode": mode,
        "requires_approval": requires_approval,
        "may": tier["allowed"],
        "may_not": tier["prohibited"],
        "approval_rule": tier["approval"],
        "constraints": reasons,
        "downgrades": downgrades,
        "downgrade_applied": bool(downgrades),
        "excluded_final_decisions": autonomy_config().get("excluded_final_decisions", []),
        "side_effects": contract["side_effects"],
        "minimum_controls": risk["minimum_controls"],
        "next_action": next_action,
    }


# ---------------------------------------------------------------- allowlists


def tool_allowlist(skill_id: str) -> dict[str, Any]:
    """What a skill may call: its declared categories, and the operations its level permits.

    Categories come from the generated registry (derived from the contract); the
    permitted operation classes come from the policy by effective autonomy. This is
    the abstract rule. Turning it into concrete tool names needs a connector
    manifest — `governance.evaluate_connector` does that.
    """
    reg = skills()
    if skill_id not in reg:
        raise KeyError(f"unknown skill_id {skill_id!r}; call list_skills first")

    entry = allowlist_registry().get(skill_id)
    if entry is None:
        raise KeyError(
            f"no allowlist entry for {skill_id!r} — run tools/build.py to regenerate the registry"
        )

    policy = tool_allowlist_policy()
    resolution = resolve_autonomy(skill_id)
    effective = resolution["autonomy_effective"]
    allowed_ops = list(policy["operations_by_autonomy"].get(effective, ["read"]))
    requested_ops = list(policy["operations_by_autonomy"].get(resolution["autonomy_requested"], []))

    withheld = [op for op in requested_ops if op not in allowed_ops]

    return {
        "skill_id": skill_id,
        "skill_name": reg[skill_id]["name"],
        "effective_autonomy": effective,
        "autonomy_requested": resolution["autonomy_requested"],
        "mode": resolution["mode"],
        "allowed_categories": list(entry["categories"]),
        "allowed_operations": allowed_ops,
        "withheld_operations": withheld,
        "default_decision": policy["default_decision"],
        "enforcement": (
            "This package does not route tool calls. Apply this allowlist in the gateway or "
            "client that fronts your connectors, before dispatch."
        ),
        "note": (
            "route_autonomy answers 'may this capability write at all'; this answers 'may it "
            "reach this tool'. Both must allow."
        ),
    }


# ------------------------------------------------------------------- scoring


def risk_rank(risk: str) -> int:
    return int(scoring_policy()["risk_rank"][risk])


def score(contract: dict[str, Any], weights: dict[str, float] | None = None) -> int:
    """Reproduce the SRD's opportunity score exactly (0..100)."""
    policy = scoring_policy()
    w = dict(policy["default_weights"])
    if weights:
        for key, value in weights.items():
            if key in w:
                w[key] = float(value)
    total = sum(w.values()) or 1.0
    s = contract["scores"]
    value = (
        s["impact"] * w["impact"]
        + s["readiness"] * w["readiness"]
        + s["reuse"] * w["reuse"]
        + (6 - s["effort"]) * w["effort"]
        + (6 - risk_rank(contract["risk"])) * w["risk"]
    ) / total
    return round(value * 20)


# ------------------------------------------------------------------- lookups


def public_view(contract: dict[str, Any], weights: dict[str, float] | None = None) -> dict[str, Any]:
    """A contract slimmed to what a caller answering a user actually needs."""
    ceiling, _ = pack_ceiling(contract["id"])
    return {
        "id": contract["id"],
        "domain": contract["domain"],
        "name": contract["name"],
        "purpose": contract["purpose"],
        "owner": contract["owner"],
        "wave": contract["wave"],
        "risk": contract["risk"],
        "autonomy_requested": contract["autonomy_requested"],
        "autonomy_available": min(
            (contract["autonomy_requested"], ceiling), key=lambda lvl: RANK[lvl]
        ),
        "metric": contract["metric"],
        "acceptance": contract["acceptance"],
        "score": score(contract, weights),
        "status": contract["status"],
    }


def find(
    domain: str | None = None,
    risk: str | None = None,
    wave: int | None = None,
    autonomy: str | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    out = []
    for contract in skills().values():
        if domain and contract["domain"].lower() != domain.lower():
            continue
        if risk and contract["risk"].lower() != risk.lower():
            continue
        if wave is not None and contract["wave"] != wave:
            continue
        if autonomy and contract["autonomy_requested"].upper() != autonomy.upper():
            continue
        if query:
            haystack = " ".join(
                str(contract.get(k, ""))
                for k in ("id", "name", "purpose", "metric", "owner", "system_categories", "inputs", "outputs")
            ).lower()
            if query.lower() not in haystack:
                continue
        out.append(contract)
    return sorted(out, key=lambda c: (c["wave"], c["domain"], c["id"]))


def domain_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for contract in skills().values():
        counts[contract["domain"]] = counts.get(contract["domain"], 0) + 1
    return counts


def load_ok() -> dict[str, int]:
    """Counts used by --selftest, so a broken install reports what is missing."""
    return {
        "skills": len(skills()),
        "domains": len(domains()),
        "requirements": len(requirements()),
        "waves": len(roadmap()),
        "metrics": len(metrics()),
        "safeguards": len(safeguards()),
        "release_gates": len(release_gates()["gates"]),
    }
