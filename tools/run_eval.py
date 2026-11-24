"""Answer the evaluation cases with a real client, in batches, and record the result.

Each batch is a separate client call so one bad answer cannot poison the whole run, and
every batch is appended to disk so a timeout loses nothing. Answers are collected into
eval_answers_full.json, then graded by tools/grade_answers.py — this script never sees
the expected values, so it cannot accidentally leak them into the prompt.

    uv run --quiet --script tools/run_eval.py 0 2    # batches 0 and 1
    uv run --quiet --script tools/run_eval.py        # every batch
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path(os.environ["LOCALAPPDATA"]) / "hermes/profiles/beto-cos/cache/scratch"
ANSWERS = SCRATCH / "eval_answers_full.json"
BATCH = 8

TOOLS = ",".join(
    f"mcp__plugin_enterprise-business-plugin_enterprise-core__{tool}"
    for tool in ("get_contract", "route_autonomy", "tool_allowlist", "approval_gate",
                 "list_skills", "list_requirements")
)

FIELDS = {
    "autonomy": "autonomy_effective (string), mode (string)",
    "owner": "owner (string)",
    "quote": "acceptance (the exact acceptance text, copied)",
    "allowlist": "allowed_operations (array of operation names)",
    "refusal": "allowed (boolean), rule (the name of the rule that decided it)",
    "unknown": "error (the error text the tool returned)",
}


def build_prompt(batch: list[dict]) -> str:
    lines = [
        "Answer each question using the enterprise-business-plugin MCP tools. Call the tools;",
        "do not answer from memory. Do not guess an identifier you have not looked up.",
        "",
        "Reply with ONLY a JSON object — no prose, no code fences — keyed by id, each value an",
        "object with exactly the keys listed.",
        "",
    ]
    for case in batch:
        lines.append(f'- id: {case["id"]}')
        lines.append(f'  question: {case["prompt"]}')
        lines.append(f'  keys: {FIELDS[case["kind"]]}')
        lines.append("")
    return "\n".join(lines)


def claude_argv() -> list[str]:
    exe = shutil.which("claude")
    if not exe:
        raise SystemExit("claude CLI not found on PATH")
    if exe.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", exe]
    return [exe]


def strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end != -1 else text


def main(argv: list[str]) -> int:
    cases = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))["cases"]
    batches = [cases[i : i + BATCH] for i in range(0, len(cases), BATCH)]
    lo = int(argv[0]) if argv else 0
    hi = int(argv[1]) if len(argv) > 1 else len(batches)

    answers = json.loads(ANSWERS.read_text(encoding="utf-8")) if ANSWERS.exists() else {}
    base = claude_argv()

    for index in range(lo, min(hi, len(batches))):
        batch = [c for c in batches[index] if c["id"] not in answers]
        if not batch:
            print(f"batch {index}: already answered", flush=True)
            continue

        prompt = build_prompt(batch)
        got: dict = {}
        for attempt in (1, 2):
            proc = subprocess.run(
                base + ["-p", prompt, "--allowedTools", TOOLS],
                capture_output=True, text=True, timeout=420,
            )
            try:
                parsed = json.loads(strip_fences(proc.stdout))
                if isinstance(parsed, dict) and parsed:
                    got = parsed
                    break
            except json.JSONDecodeError:
                print(f"batch {index}: attempt {attempt} unparseable "
                      f"({proc.stdout[:120]!r})", flush=True)

        if not got:
            print(f"batch {index}: FAILED after 2 attempts", flush=True)
            continue

        for case in batch:
            if case["id"] in got:
                answers[case["id"]] = got[case["id"]]
        ANSWERS.write_text(json.dumps(answers, indent=2), encoding="utf-8")
        print(f"batch {index}: {len(batch)} asked, {len(got)} answered, "
              f"{len(answers)} total", flush=True)

    print(f"DONE {len(answers)} answers at {ANSWERS}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
