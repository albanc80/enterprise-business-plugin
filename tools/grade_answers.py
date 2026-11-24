"""Score a client's answers against the evaluation cases.

Answers are whatever the skill produced for each case's prompt, keyed by case id:

    {
      "eval.FIN-02.autonomy": {"autonomy_effective": "A1", "mode": "draft_only"},
      "eval.FIN-02.owner":    {"owner": "Finance Controller"},
      ...
    }

Grading is exact after normalisation — whitespace collapsed, case folded. Strings must
match the contract, not a plausible restatement of it, because "quote it verbatim" is the
instruction and paraphrasing a threshold is the failure mode this package exists to stop.

    uv run --script tools/grade_answers.py                       # evals/answers.json
    uv run --script tools/grade_answers.py my-answers.json
    uv run --script tools/grade_answers.py --goldens             # self-check the grader
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "evals" / "cases.json"
ANSWERS_PATH = ROOT / "evals" / "answers.json"


def normalise(value: object) -> str:
    return " ".join(str(value).split()).casefold()


def compare(expected: object, actual: object) -> bool:
    if isinstance(expected, bool):
        return isinstance(actual, bool) and actual == expected
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        return sorted(normalise(v) for v in actual) == sorted(normalise(v) for v in expected)
    return normalise(expected) == normalise(actual)


def grade(cases: dict, answers: dict) -> dict:
    failures: list[dict] = []
    missing: list[str] = []
    passed = 0

    for case in cases["cases"]:
        answer = answers.get(case["id"])
        if answer is None:
            missing.append(case["id"])
            continue
        if not isinstance(answer, dict):
            failures.append(
                {"id": case["id"], "field": "*", "expected": "an object", "got": repr(answer)[:80]}
            )
            continue

        case_ok = True
        for field, expected in case["expect"].items():
            if field.endswith("_contains"):
                # A rule name should appear in the answer; demanding the exact string
                # failed correct answers that named the rule and then explained it.
                base = field[: -len("_contains")]
                subject = answer.get(base)
                haystack = normalise(subject) if subject is not None else ""
                if not haystack:
                    haystack = " ".join(normalise(v) for v in answer.values())
                if normalise(expected) not in haystack:
                    case_ok = False
                    failures.append(
                        {"id": case["id"], "field": field, "expected": expected,
                         "got": " ".join(f"{k}={v}" for k, v in answer.items())[:120]}
                    )
                continue
            actual = answer.get(field)
            if not compare(expected, actual):
                case_ok = False
                failures.append(
                    {"id": case["id"], "field": field, "expected": expected,
                     "got": repr(actual)[:120]}
                )
        if case_ok:
            passed += 1

    total = len(cases["cases"])
    answered = total - len(missing)
    return {
        "total": total,
        "answered": answered,
        "passed": passed,
        "failed": len(failures),
        "missing": len(missing),
        "score": round(passed / total, 4) if total else 0.0,
        "score_of_answered": round(passed / answered, 4) if answered else 0.0,
        "failures": failures,
        "missing_ids": missing,
    }


def main(argv: list[str]) -> int:
    if not CASES_PATH.exists():
        print(f"[FAIL] {CASES_PATH} is missing; run tools/eval_cases.py first")
        return 1
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))

    if "--goldens" in argv:
        answers = {case["id"]: dict(case["expect"]) for case in cases["cases"]}
        label = "goldens"
    else:
        path = Path(argv[0]) if argv and not argv[0].startswith("-") else ANSWERS_PATH
        if not path.exists():
            print(f"[FAIL] no answers at {path}")
            print("       Produce one answer per case prompt with your client, then re-run:")
            print(f"       uv run --script tools/grade_answers.py {path}")
            return 1
        answers = json.loads(path.read_text(encoding="utf-8"))
        label = str(path)

    report = grade(cases, answers)
    print(f"EVAL {label}")
    print(f"  cases      {report['total']}")
    print(f"  answered   {report['answered']}")
    print(f"  passed     {report['passed']}")
    print(f"  failed     {report['failed']}")
    print(f"  missing    {report['missing']}")
    print(f"  score      {report['score']}  (of answered: {report['score_of_answered']})")

    for failure in report["failures"][:15]:
        print(f"  [FAIL] {failure['id']} {failure['field']}: "
              f"expected {failure['expected']!r}, got {failure['got']}")
    if len(report["failures"]) > 15:
        print(f"  ... {len(report['failures']) - 15} more")
    if report["missing_ids"]:
        print(f"  [MISSING] {', '.join(report['missing_ids'][:8])}"
              + (" ..." if len(report["missing_ids"]) > 8 else ""))

    if "--goldens" in argv:
        ok = report["score"] == 1.0
        print("\nGRADER SELF-CHECK", "OK — feeding the expected values scores 100%"
              if ok else "FAILED — the grader cannot even pass its own answers")
        return 0 if ok else 1

    return 0 if not report["failures"] and not report["missing"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
