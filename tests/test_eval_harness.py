"""Foundation of the accuracy claim: the cases are real, current, and the grader bites.

The package could prove its gates held and could say nothing about whether its skills
answered correctly. These tests keep the evaluation honest — cases cannot drift from the
registry, the grader must pass its own answers, and a paraphrase must fail.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "servers"))


def _load(relative: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {relative}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


eval_cases = _load("tools/eval_cases.py", "eval_cases")
grade_answers = _load("tools/grade_answers.py", "grade_answers")


@pytest.fixture(scope="module")
def cases() -> dict:
    return json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------- the cases are real
def test_cases_file_is_current_with_the_registry(cases):
    """A stale case file measures a package that no longer exists."""
    assert cases == eval_cases.build_cases(), (
        "evals/cases.json is stale — regenerate with `uv run --script tools/eval_cases.py`"
    )


def test_case_ids_are_unique(cases):
    ids = [case["id"] for case in cases["cases"]]
    assert len(ids) == len(set(ids))


def test_every_case_is_answerable_and_graded(cases):
    for case in cases["cases"]:
        assert case["prompt"].strip()
        assert case["expect"], case["id"]
        assert case["skill_id"]


def test_cases_cover_the_contracts_that_request_above_the_ceiling(cases):
    covered = {case["skill_id"] for case in cases["cases"]}
    for skill_id in ("IT-08", "CSP-04", "OFC-04"):
        assert skill_id in covered


def test_cases_state_what_they_do_not_measure(cases):
    assert "advice" in cases["does_not_measure"].lower()


def test_the_unknown_skill_case_expects_a_refusal_not_an_answer(cases):
    unknown = [c for c in cases["cases"] if c["kind"] == "unknown"]
    assert unknown, "the package must be tested on a skill that does not exist"
    assert "error_contains" in unknown[0]["expect"]


# ---------------------------------------------------------- the grader actually bites
def test_goldens_score_one(cases):
    report = grade_answers.grade(
        cases, {case["id"]: dict(case["expect"]) for case in cases["cases"]}
    )
    assert report["score"] == 1.0
    assert report["failed"] == 0


def test_no_answers_scores_zero(cases):
    report = grade_answers.grade(cases, {})
    assert report["passed"] == 0
    assert report["score"] == 0.0
    assert report["missing"] == report["total"]


def test_a_wrong_ceiling_fails(cases):
    answers = {case["id"]: dict(case["expect"]) for case in cases["cases"]}
    target = next(c for c in cases["cases"] if c["kind"] == "autonomy")
    answers[target["id"]]["autonomy_effective"] = "A2"
    report = grade_answers.grade(cases, answers)
    assert report["score"] < 1.0
    assert any(f["field"] == "autonomy_effective" for f in report["failures"])


def test_a_paraphrased_acceptance_criterion_fails(cases):
    """The instruction is "quote verbatim"; a plausible restatement is the failure mode."""
    answers = {case["id"]: dict(case["expect"]) for case in cases["cases"]}
    target = next(c for c in cases["cases"] if c["kind"] == "quote")
    answers[target["id"]]["acceptance"] = "The system should generally do the right thing."
    report = grade_answers.grade(cases, answers)
    assert any(f["id"] == target["id"] for f in report["failures"])


def test_whitespace_and_case_differences_are_tolerated(cases):
    answers = {case["id"]: dict(case["expect"]) for case in cases["cases"]}
    target = next(c for c in cases["cases"] if c["kind"] == "quote")
    answers[target["id"]]["acceptance"] = "  " + target["expect"]["acceptance"].upper() + "  "
    assert grade_answers.grade(cases, answers)["score"] == 1.0


def test_list_comparison_ignores_order(cases):
    answers = {case["id"]: dict(case["expect"]) for case in cases["cases"]}
    target = next(c for c in cases["cases"] if c["kind"] == "allowlist")
    answers[target["id"]]["allowed_operations"] = list(
        reversed(target["expect"]["allowed_operations"])
    )
    assert grade_answers.grade(cases, answers)["score"] == 1.0


def test_a_widened_allowlist_fails(cases):
    answers = {case["id"]: dict(case["expect"]) for case in cases["cases"]}
    target = next(c for c in cases["cases"] if c["kind"] == "allowlist")
    answers[target["id"]]["allowed_operations"] = list(
        target["expect"]["allowed_operations"]
    ) + ["write"]
    assert any(f["id"] == target["id"] for f in grade_answers.grade(cases, answers)["failures"])


def test_a_non_object_answer_is_a_failure_not_a_crash(cases):
    target = cases["cases"][0]
    report = grade_answers.grade(cases, {target["id"]: "I think it's A1"})
    assert any(f["id"] == target["id"] for f in report["failures"])


def test_the_recorded_run_still_scores(cases):
    """The committed answers are evidence, so they must keep matching the cases.

    If a contract changes an owner, a threshold or an acceptance line, this fails and the
    run has to be repeated. That is the intent: a published score that no longer
    reproduces is worse than no score.
    """
    recorded = ROOT / "evals" / "answers.claude-2026-11-24.json"
    if not recorded.exists():
        pytest.skip("no recorded run in this checkout")
    answers = json.loads(recorded.read_text(encoding="utf-8"))
    report = grade_answers.grade(cases, answers)
    assert report["score"] == 1.0, report["failures"][:3]
    assert report["answered"] == report["total"]
