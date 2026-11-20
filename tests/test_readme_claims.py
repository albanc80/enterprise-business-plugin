"""Guard the README's numbers against the registry.

Prose counts go stale silently. These assertions fail the build instead, so a
threshold edit or a new contract cannot leave the README confidently wrong.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "servers"))

from enterprise_core import registry  # noqa: E402

README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_skill_and_domain_counts_in_readme():
    n_skills = len(registry.skills())
    n_domains = len(registry.domains())
    assert f"{n_skills} skill contracts" in README, f"README must say {n_skills} skill contracts"
    assert f"{n_domains} business functions" in README, f"README must say {n_domains} business functions"


def test_published_skill_count_matches_the_skills_directory():
    published = len(list((ROOT / "skills").glob("*/SKILL.md")))
    match = re.search(r"served by (\d+) skills", README)
    assert match, "README must state how many skills serve the contracts"
    assert int(match.group(1)) == published, f"README says {match.group(1)}, tree has {published}"


def test_requirement_and_wave_counts():
    assert len(registry.requirements()) == 32
    assert len(registry.roadmap()) == 4


def test_readme_does_not_claim_a3_is_available():
    """A3 may be described as a level; it must never read as configurable here."""
    lowered = README.lower()
    assert "not implemented by this package" in lowered, (
        "README must state that A3 is not implemented here"
    )
    assert "no switch" in lowered, "README must say there is no switch for A3"
    for phrase in ("enable a3 by", "turn on a3", "set a3 to", "a3_skills:", "a3 is available"):
        assert phrase not in lowered, f"README reads as if A3 were configurable: {phrase!r}"


def test_readme_states_the_shipped_ceiling():
    assert registry.autonomy_config()["ceiling"]["default_max_level"] == "A1"
    assert "ships at A1" in README or "ships at **A1**" in README


def test_every_skill_named_in_readme_exists():
    known = {p.parent.name for p in (ROOT / "skills").glob("*/SKILL.md")}
    cited = set(re.findall(r"`([a-z][a-z0-9-]{5,})`", README))
    # Only assert on citations that look like skill directory names.
    apparent = {c for c in cited if c.endswith(("-ops", "-operations", "-controls", "-privacy",
                                                "-assurance", "-foundation", "-quality",
                                                "-services", "-compliance", "-excellence",
                                                "-knowledge"))}
    unknown = apparent - known
    assert not unknown, f"README cites skills that do not exist: {sorted(unknown)}"


def test_install_commands_point_at_the_declared_repository():
    manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    slug = manifest["repository"].split("github.com/")[-1]
    assert slug in README, "README install commands must use the manifest's repository slug"
    assert manifest["name"] in README


def test_no_measured_results_are_claimed():
    """The pack has no measured outcomes; it must never imply any."""
    forbidden = ["we measured", "reduced by", "saved us", "achieved", "observed improvement"]
    lowered = README.lower()
    for phrase in forbidden:
        assert phrase not in lowered, f"README implies measured results: {phrase!r}"


def test_published_source_projection_is_present():
    """The document stays private; its normalized projection ships and carries a hash."""
    data = json.loads((ROOT / "src" / "registry" / "source.json").read_text(encoding="utf-8"))
    prov = data["provenance"]
    assert len(prov["sha256"]) == 64, "the projection must carry a sha256 of the document"
    assert prov["bytes"] > 0
    assert len(data["skills"]) == len(registry.skills())
    assert "not published" in prov["note"].lower()


def test_build_does_not_depend_on_the_private_document():
    build = (ROOT / "tools" / "build.py").read_text(encoding="utf-8")
    assert "source.json" in build
    assert "Enterprise_AI_Skills_SRD.html" not in build


@pytest.mark.parametrize("doc", ["docs/INSTALL.md", "docs/BOUNDARIES.md"])
def test_docs_exist(doc):
    assert (ROOT / doc).exists(), f"{doc} is referenced but missing"
