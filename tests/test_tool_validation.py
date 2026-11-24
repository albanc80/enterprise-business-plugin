"""Tool inputs are validated, and empty results are never used to mean "invalid".

An empty list and an error look identical to a model reading a JSON payload, so a
filter that silently matched nothing read as "no such skill exists" rather than "that
filter was wrong". Same failure mode for weights: nonsense produced a number.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "servers"))

from enterprise_core import main, registry  # noqa: E402


# --------------------------------------------------------------------- scoring
def test_unknown_weight_key_is_refused():
    result = main.score_skills(weights={"bogus": 3})
    assert result["error"] == "invalid weights"
    assert result["ranked"] == []
    assert any("bogus" in p for p in result["problems"])


def test_negative_weight_is_refused():
    """A negative weight inverts a metric and pushed the score past 100."""
    result = main.score_skills(weights={"risk": -5})
    assert result["error"] == "invalid weights"
    assert any("between 0 and 10" in p for p in result["problems"])


def test_absurd_weight_is_refused():
    result = main.score_skills(weights={"impact": 1e9})
    assert result["error"] == "invalid weights"


def test_zero_total_weights_is_refused():
    result = main.score_skills(weights={key: 0 for key in registry.validate_weights(None)[0]})
    assert result["error"] == "invalid weights"
    assert any("sum to zero" in p for p in result["problems"])


def test_valid_reweighting_stays_in_range():
    result = main.score_skills(weights={"impact": 4, "readiness": 1}, limit=200)
    assert "error" not in result
    assert result["ranked"], "a valid re-weighting must return ranks"
    assert all(0 <= row["score"] <= 100 for row in result["ranked"]), (
        "scores outside 0..100 mean the weighting model is broken"
    )
    assert result["weights_used"]["impact"] == 4


def test_unknown_skill_id_in_shortlist_is_refused():
    result = main.score_skills(skill_ids=["FIN-02", "NOT-A-SKILL"])
    assert result["error"] == "unknown skill_ids"
    assert result["ranked"] == []


def test_default_scoring_is_unchanged():
    """Validation must not perturb the scores the SRD actually specifies."""
    result = main.score_skills(skill_ids=["FIN-02"])
    assert result["ranked"][0]["id"] == "FIN-02"
    assert 0 <= result["ranked"][0]["score"] <= 100


# --------------------------------------------------------------------- filters
def test_invalid_risk_filter_is_an_error_not_an_empty_list():
    result = main.list_skills(risk="Extreme")
    assert result["error"] == "invalid filter"
    assert result["skills"] == []
    assert any("Extreme" in p for p in result["problems"])


def test_invalid_domain_wave_and_autonomy_are_errors():
    for kwargs in ({"domain": "Nonsense"}, {"wave": 9}, {"autonomy": "A9"}):
        result = main.list_skills(**kwargs)
        assert result.get("error") == "invalid filter", kwargs
        assert result["problems"], kwargs


def test_non_positive_limit_is_an_error():
    assert main.list_skills(limit=0).get("error") == "invalid filter"


def test_domain_accepts_id_display_name_or_fragment():
    """Contracts carry ids ("Finance"); the policy carries display names."""
    for spelling in ("Finance", "Finance & accounting", "accounting"):
        result = main.list_skills(domain=spelling)
        assert "error" not in result, spelling
        assert result["matched"] > 0, spelling
        assert all(row["domain"] == "Finance" for row in result["skills"]), spelling


def test_ambiguous_domain_fragment_is_an_error():
    result = main.list_skills(domain="o")
    assert result.get("error") == "invalid filter"
    assert any("ambiguous" in p for p in result["problems"])


def test_query_with_no_match_is_legitimately_empty_not_an_error():
    """A search term matching nothing is an answer; a bad filter is a mistake."""
    result = main.list_skills(query="zzzz-no-such-term")
    assert "error" not in result
    assert result["matched"] == 0


# ---------------------------------------------------------------- side effects
def test_side_effects_report_the_effective_level():
    """FND-06 contracts an approved system write but resolves to A1 draft only."""
    view = main.get_contract("FND-06")["side_effects"]
    assert view["autonomy_requested"] == "A2"
    assert view["autonomy_effective"] == "A1"
    assert view["mode"] == "draft_only"
    assert "No system write is performed" in view["effective"]
    assert view["note"] and "A2" in view["note"]
    assert view["effective"] != view["declared"], (
        "the declared text must not be presented as the effective behaviour"
    )


def test_side_effects_note_absent_when_nothing_was_downgraded():
    view = main.get_contract("FIN-02")["side_effects"]
    assert view["autonomy_requested"] == view["autonomy_effective"]
    assert view["note"] is None


# -------------------------------------------------------------------- protocol
def test_probe_does_not_hardcode_an_obsolete_protocol():
    """The probe must ask for the SDK's version, not a version from last year."""
    source = (ROOT / "tools" / "probe_mcp.py").read_text(encoding="utf-8")
    assert "2024-11-05" not in source
    assert "LATEST_PROTOCOL_VERSION" in source
