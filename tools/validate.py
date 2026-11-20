#!/usr/bin/env python3
"""Gate for the Enterprise Business Plugin.

Five checks, ordered by what actually breaks a client:

  1. plugin.json      — required fields, closed top-level schema, name rules.
  2. registry         — 93 contracts, required keys, valid risk/autonomy values,
                        provenance on every row, and agreement with the SRD source.
  3. policies         — the shipped ceiling is A1, A3 is disabled, and every skill
                        requesting above the ceiling is a declared opt-in candidate.
  4. skills           — frontmatter, directory/name agreement, and every skill id
                        cited in a SKILL.md exists in the registry (catches typos).
  5. mcp.json         — the server is declared and reserved variables are not set.

Exit code 0 = pass, 1 = failures, 2 = cannot run.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

MANIFEST_KEYS = {
    "$schema", "name", "version", "description", "author", "homepage",
    "repository", "license", "keywords", "extensions",
}
MANIFEST_REQUIRED = {"$schema", "name", "version", "description", "license"}
SCHEMA_URI = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
AUTHOR_KEYS = {"name", "email", "url"}
RESERVED_ENV = {"PLUGIN_ROOT", "PLUGIN_DATA"}

CONTRACT_REQUIRED = {
    "id", "domain", "name", "purpose", "owner", "wave", "risk",
    "autonomy_requested", "side_effects", "trigger", "inputs", "preconditions",
    "outputs", "output_contract", "metric", "acceptance", "escalation",
    "fail_safe", "data_handling", "execution_mode", "system_categories",
    "status", "scores", "source",
}
RISKS = {"Low", "Moderate", "High", "Critical"}
LEVELS = {"A0", "A1", "A2", "A3"}
# Closed schema for the autonomy config. A3 has no opt-in slot by design, and an
# unknown key here is a build failure rather than a dormant setting — otherwise a
# future edit can add an inert `a3_skills` list and believe it did something.
AUTONOMY_KEYS = {"schema", "id", "ceiling", "opt_in", "downgrade_reporting", "excluded_final_decisions"}
AUTONOMY_CEILING_KEYS = {"default_max_level", "a3_shipped", "rationale"}
AUTONOMY_OPT_IN_KEYS = {"a2_skills", "requires"}
EXPECTED_COUNTS = {"skills": 93, "domains": 12, "requirements": 32, "waves": 4}
SKILL_ID_RE = re.compile(r"\b([A-Z]{2,3})-(\d{2})\b")

failures: list[str] = []
warnings: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def read_yaml(relative: str) -> dict:
    path = ROOT / relative
    if not path.exists():
        fail(f"missing required file: {relative}")
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


# ------------------------------------------------------------------ 1. manifest


def check_manifest() -> None:
    path = ROOT / "plugin.json"
    if not path.exists():
        fail("plugin.json is missing — nothing can install this repo")
        return
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"plugin.json is not valid JSON: {exc}")
        return

    for key in sorted(MANIFEST_REQUIRED - set(manifest)):
        fail(f"plugin.json: missing required field {key!r}")

    unknown = set(manifest) - MANIFEST_KEYS
    if unknown:
        fail(f"plugin.json: unknown top-level keys {sorted(unknown)} (client data belongs under 'extensions')")

    if manifest.get("$schema") != SCHEMA_URI:
        fail(f"plugin.json: $schema must be {SCHEMA_URI}")

    name = str(manifest.get("name", ""))
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name):
        fail(f"plugin.json: name {name!r} must be lowercase alphanumerics separated by single hyphens")
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(manifest.get("version", ""))):
        fail(f"plugin.json: version {manifest.get('version')!r} is not semver")

    author = manifest.get("author")
    if not isinstance(author, dict) or "name" not in author:
        fail("plugin.json: author must be an object with a name")
    elif set(author) - AUTHOR_KEYS:
        fail(f"plugin.json: author has unknown keys {sorted(set(author) - AUTHOR_KEYS)}")

    if str(manifest.get("license", "")) != "Apache-2.0":
        warn(f"plugin.json: license is {manifest.get('license')!r}, expected Apache-2.0")


# ------------------------------------------------------------------ 2. registry


def check_registry() -> tuple[dict, dict]:
    skills_doc = read_yaml("src/registry/skills.yaml")
    domains_doc = read_yaml("src/registry/domains.yaml")
    skills = skills_doc.get("skills") or []
    domains = domains_doc.get("domains") or []

    if len(skills) != EXPECTED_COUNTS["skills"]:
        fail(f"registry: {len(skills)} skill contracts, expected {EXPECTED_COUNTS['skills']}")
    if len(domains) != EXPECTED_COUNTS["domains"]:
        fail(f"registry: {len(domains)} domains, expected {EXPECTED_COUNTS['domains']}")

    for name, key, expected in (
        ("requirements", "requirements", EXPECTED_COUNTS["requirements"]),
        ("roadmap", "waves", EXPECTED_COUNTS["waves"]),
    ):
        doc = read_yaml(f"src/registry/{name}.yaml")
        if len(doc.get(key) or []) != expected:
            fail(f"registry/{name}.yaml: {len(doc.get(key) or [])} entries, expected {expected}")

    ids = [s.get("id") for s in skills]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        fail(f"registry: duplicate skill ids {sorted(duplicates)}")

    domain_ids = {d.get("id") for d in domains}
    for skill in skills:
        sid = skill.get("id", "<no id>")
        missing = CONTRACT_REQUIRED - set(skill)
        if missing:
            fail(f"registry: {sid} missing keys {sorted(missing)}")
        extra = set(skill) - CONTRACT_REQUIRED - {"autonomy_exceeds_pack_ceiling"}
        if extra:
            warn(f"registry: {sid} has unexpected keys {sorted(extra)}")
        if skill.get("domain") not in domain_ids:
            fail(f"registry: {sid} has unknown domain {skill.get('domain')!r}")
        if skill.get("risk") not in RISKS:
            fail(f"registry: {sid} has invalid risk {skill.get('risk')!r}")
        if skill.get("autonomy_requested") not in LEVELS:
            fail(f"registry: {sid} has invalid autonomy {skill.get('autonomy_requested')!r}")
        if skill.get("wave") not in {0, 1, 2, 3}:
            fail(f"registry: {sid} has invalid wave {skill.get('wave')!r}")
        if not skill.get("source"):
            fail(f"registry: {sid} has no provenance")
        scores = skill.get("scores") or {}
        for key in ("impact", "readiness", "reuse", "effort"):
            if not isinstance(scores.get(key), int) or not 1 <= scores[key] <= 5:
                fail(f"registry: {sid} score {key} must be an integer 1..5")

    covered = {s.get("domain") for s in skills}
    for missing in sorted(domain_ids - covered):
        fail(f"registry: domain {missing!r} has no skills")

    # Tool allowlists must cover every contract, or a skill can reach nothing and
    # nobody notices until a gateway refuses at runtime.
    allowlists = (read_yaml("src/registry/tool-allowlists.yaml").get("skills")) or []
    by_skill = {str(e.get("skill")): e for e in allowlists}
    ids = {s.get("id") for s in skills}
    if set(by_skill) != ids:
        missing = sorted(ids - set(by_skill))
        extra = sorted(set(by_skill) - ids)
        if missing:
            fail(f"tool-allowlists: no entry for {len(missing)} skill(s), e.g. {missing[:5]}")
        if extra:
            fail(f"tool-allowlists: entries for unknown skills {extra[:5]}")
    for sid, entry in by_skill.items():
        if not entry.get("categories"):
            fail(f"tool-allowlists: {sid} declares no system categories")
        if entry.get("autonomy_requested") not in LEVELS:
            fail(f"tool-allowlists: {sid} has invalid autonomy {entry.get('autonomy_requested')!r}")

    # The generated tree must match the source document.
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "build.py"), "--check"],
            capture_output=True, text=True, cwd=ROOT,
        )
    except OSError as exc:
        fail(f"could not run tools/build.py: {exc}")
    else:
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()
            fail("registry drifted from the SRD: " + (detail[-1] if detail else "build --check failed"))

    return skills_doc, domains_doc


# ------------------------------------------------------------------ 3. policies


def check_policies(skills: list[dict]) -> None:
    config = read_yaml("src/policies/autonomy-config.yaml")
    unknown = set(config) - AUTONOMY_KEYS
    if unknown:
        fail(f"autonomy-config: unknown top-level keys {sorted(unknown)}")
    unknown = set(config.get("ceiling") or {}) - AUTONOMY_CEILING_KEYS
    if unknown:
        fail(f"autonomy-config: unknown ceiling keys {sorted(unknown)}")
    unknown = set(config.get("opt_in") or {}) - AUTONOMY_OPT_IN_KEYS
    if unknown:
        fail(
            f"autonomy-config: unknown opt_in keys {sorted(unknown)} — this package has no A3 "
            "opt-in path, and a dormant setting is worse than none"
        )

    ceiling = str((config.get("ceiling") or {}).get("default_max_level", ""))
    if ceiling != "A1":
        fail(f"autonomy-config: shipped ceiling is {ceiling!r}, expected 'A1'")
    if (config.get("ceiling") or {}).get("a3_shipped") is not False:
        fail("autonomy-config: a3_shipped must be false — this package does not ship A3")

    opt_in = config.get("opt_in") or {}

    known = {s.get("id") for s in skills}
    requires = [str(f) for f in (opt_in.get("requires") or [])]
    if not requires:
        fail("autonomy-config: opt_in.requires must list the evidence an A2 opt-in has to supply")

    a2: set[str] = set()
    for entry in opt_in.get("a2_skills") or []:
        if not isinstance(entry, dict):
            fail(
                f"autonomy-config: a2_skills entry {entry!r} must be a mapping — a bare skill "
                "id is an opt-in with no evidence, and would silently do nothing"
            )
            continue
        sid = str(entry.get("skill"))
        a2.add(sid)
        if sid not in known:
            fail(f"autonomy-config: a2_skills names unknown skill {sid!r}")
            continue
        missing = [f for f in requires if not entry.get(f)]
        if missing:
            fail(f"autonomy-config: A2 opt-in for {sid} is missing evidence {missing}")

    above = {s["id"] for s in skills if s.get("autonomy_requested") in {"A2", "A3"}}
    not_declared = above - a2
    if not_declared:
        warn(
            f"autonomy-config: {len(not_declared)} skills request above the ceiling and are not "
            "opt-in candidates — they resolve to A1, which is the intended default"
        )

    tiers = read_yaml("src/policies/autonomy-tiers.yaml").get("tiers") or []
    if {t.get("level") for t in tiers} != LEVELS:
        fail("autonomy-tiers: must define exactly A0, A1, A2 and A3")

    controls = read_yaml("src/policies/risk-controls.yaml").get("tiers") or []
    if {t.get("risk") for t in controls} != RISKS:
        fail("risk-controls: must define exactly Low, Moderate, High and Critical")
    for tier in controls:
        rank = tier.get("max_rank")
        if not isinstance(rank, int) or not 0 <= rank <= 3:
            fail(f"risk-controls: {tier.get('risk')} has invalid max_rank {rank!r}")
        if not tier.get("minimum_controls"):
            fail(f"risk-controls: {tier.get('risk')} has no minimum_controls")

    gates = read_yaml("src/policies/release-gates.yaml")
    ids = [g.get("id") for g in gates.get("gates") or []]
    if ids != ["G1", "G2", "G3"]:
        fail(f"release-gates: expected G1, G2, G3 in order, found {ids}")

    # A never-waivable item that no gate checks is a control that silently does
    # nothing. Cross-reference rather than trusting the list.
    gate_items = {i for g in gates.get("gates") or [] for i in g.get("required") or []}
    for item in (gates.get("waivers") or {}).get("never_waivable") or []:
        if item not in gate_items:
            fail(f"release-gates: never_waivable item {item!r} is not required by any gate")

    # Tool allowlist policy: deny by default, and A0/A1 read-only. The whole point is
    # that a draft-only capability cannot reach a write tool at all.
    allow = read_yaml("src/policies/tool-allowlists.yaml")
    if str(allow.get("default_decision")) != "deny":
        fail(f"tool-allowlists: default_decision is {allow.get('default_decision')!r}, expected 'deny'")
    ops = allow.get("operations_by_autonomy") or {}
    if set(ops) != LEVELS:
        fail(f"tool-allowlists: operations_by_autonomy must define {sorted(LEVELS)}, found {sorted(ops)}")
    for level in ("A0", "A1"):
        if list(ops.get(level) or []) != ["read"]:
            fail(f"tool-allowlists: {level} must permit read only, found {ops.get(level)}")
    if not {"read", "propose", "write"} <= set(ops.get("A2") or []):
        fail("tool-allowlists: A2 must permit read, propose and write")
    for key in ("enforcement_contract", "never_permitted"):
        if not allow.get(key):
            fail(f"tool-allowlists: {key} is required — an allowlist without an enforcement story is a suggestion")

    safeguards = read_yaml("src/policies/safeguards.yaml").get("safeguards") or []
    if len(safeguards) != 6:
        fail(f"safeguards: {len(safeguards)} defined, expected 6")

    scoring = read_yaml("src/policies/scoring.yaml")
    if not scoring.get("default_weights"):
        fail("scoring: default_weights missing")
    if not (ROOT / "src/policies/approval.yaml").exists():
        fail("approval.yaml is missing — the approval gate has no rules")


# ------------------------------------------------------------------ 4. skills


def check_skills(skills: list[dict]) -> None:
    files = sorted((ROOT / "skills").glob("*/SKILL.md"))
    if len(files) < 12:
        fail(f"skills: only {len(files)} skills found, expected at least 12")

    known_ids = {s.get("id") for s in skills}
    prefixes = {i.split("-")[0] for i in known_ids if i}

    for path in files:
        text = path.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        if not m:
            fail(f"skills/{path.parent.name}: missing YAML frontmatter")
            continue
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError as exc:
            fail(f"skills/{path.parent.name}: frontmatter is not valid YAML: {exc}")
            continue

        for key in ("name", "description"):
            if not meta.get(key):
                fail(f"skills/{path.parent.name}: frontmatter missing {key!r}")
        extra = set(meta) - {"name", "description"}
        if extra:
            warn(f"skills/{path.parent.name}: extra frontmatter keys {sorted(extra)}")
        if meta.get("name") != path.parent.name:
            fail(
                f"skills/{path.parent.name}: frontmatter name {meta.get('name')!r} "
                "does not match its directory"
            )
        desc = str(meta.get("description", ""))
        if len(desc) > 700:
            fail(f"skills/{path.parent.name}: description is {len(desc)} chars, keep it under 700")

        # Every skill id cited must exist, and its prefix must be a real domain code.
        for prefix, number in SKILL_ID_RE.findall(text):
            sid = f"{prefix}-{number}"
            if sid not in known_ids:
                fail(f"skills/{path.parent.name}: cites unknown skill id {sid}")
            elif prefix not in prefixes:
                fail(f"skills/{path.parent.name}: cites {sid} with an unknown domain prefix")

    # Each of the 12 domains should be reachable from at least one domain skill.
    covered_prefixes = set()
    for path in files:
        covered_prefixes |= {p for p, _ in SKILL_ID_RE.findall(path.read_text(encoding="utf-8"))}
    missing = prefixes - covered_prefixes
    if missing:
        fail(f"skills: no skill cites capabilities from prefix(es) {sorted(missing)}")


# ------------------------------------------------------------------ 5. mcp.json


def check_mcp() -> None:
    path = ROOT / "mcp.json"
    if not path.exists():
        fail("mcp.json is missing — the governance server would never be declared")
        return
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"mcp.json is not valid JSON: {exc}")
        return

    servers = doc.get("mcpServers") or {}
    if not servers:
        fail("mcp.json declares no servers")
    for name, spec in servers.items():
        if not spec.get("command"):
            fail(f"mcp.json: {name} has no command")
        env = spec.get("env") or {}
        reserved = RESERVED_ENV & set(env)
        if reserved:
            fail(f"mcp.json: {name} sets reserved variable(s) {sorted(reserved)} — the client supplies them")
        args = " ".join(str(a) for a in (spec.get("args") or []))
        if "servers/enterprise_core/main.py" not in args:
            fail(f"mcp.json: {name} does not point at servers/enterprise_core/main.py")

    shim = ROOT / ".mcp.json"
    if not shim.exists():
        warn(".mcp.json shim missing — Claude Code reads its own copy")
    else:
        shim_doc = json.loads(shim.read_text(encoding="utf-8"))
        for name, spec in (shim_doc.get("mcpServers") or {}).items():
            reserved = RESERVED_ENV & set(spec.get("env") or {})
            if reserved:
                fail(f".mcp.json: {name} sets reserved variable(s) {sorted(reserved)}")

    marketplace = ROOT / ".claude-plugin" / "marketplace.json"
    if not marketplace.exists():
        fail(".claude-plugin/marketplace.json missing — 'plugin add' has no target")
    else:
        doc = json.loads(marketplace.read_text(encoding="utf-8"))
        if not doc.get("owner"):
            fail("marketplace.json: 'owner' is required")
        if not doc.get("plugins"):
            fail("marketplace.json: at least one plugin entry is required")


def main() -> int:
    if not (ROOT / "plugin.json").exists() and not (ROOT / "src").exists():
        print("[FAIL] cannot run: not at the package root", file=sys.stderr)
        return 2

    check_manifest()
    skills_doc, _ = check_registry()
    skills = skills_doc.get("skills") or []
    check_policies(skills)
    check_skills(skills)
    check_mcp()

    for msg in warnings:
        print(f"[WARN] {msg}")
    if failures:
        for msg in failures:
            print(f"[FAIL] {msg}", file=sys.stderr)
        print(f"\n{len(failures)} failure(s), {len(warnings)} warning(s)", file=sys.stderr)
        return 1

    print(
        f"[OK] {len(skills)} contracts, {len(list((ROOT / 'skills').glob('*/SKILL.md')))} skills, "
        f"{len(warnings)} warning(s) — package validates"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
