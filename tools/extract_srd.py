#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Extract the normalized source contract set from the SRD document.

Run this LOCALLY, against your own copy of the requirements document. The document
itself is deliberately not published with this package; what ships is its normalized
projection (src/registry/source.json) plus a SHA-256 of the original, so anyone who
holds the document can confirm the projection matches it.

    uv run --script tools/extract_srd.py path/to/Enterprise_AI_Skills_SRD.html
    uv run --script tools/build.py            # then regenerate the registry

This is the only tool that reads the HTML. tools/build.py reads source.json, so CI
never needs the document.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "registry" / "source.json"

KEYS = ("domains", "skills", "requirements", "metrics", "roadmap", "sources")


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr)
    raise SystemExit(1)


def js_literal(html: str, name: str) -> str:
    m = re.search(rf"\b{name}\s*=\s*([\[{{].*?[\]}}]);", html, re.S)
    if not m:
        fail(f"could not parse JS constant {name!r}")
    return m.group(1)


def js_array(html: str, name: str) -> list:
    value = ast.literal_eval(js_literal(html, name))
    if not isinstance(value, list):
        fail(f"{name} is not a list")
    return value


def js_object(html: str, name: str) -> dict:
    raw = re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r"\1'\2':", js_literal(html, name))
    value = ast.literal_eval(raw)
    if not isinstance(value, dict):
        fail(f"{name} is not an object")
    return value


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    if not path.exists():
        fail(f"no document at {path}")

    raw = path.read_bytes()
    html = raw.decode("utf-8")
    block = re.search(r'<script id="srd-json" type="application/json">(.*?)</script>', html, re.S)
    if not block:
        fail('no <script id="srd-json"> block — is this the requirements document?')
    data = json.loads(block.group(1))

    missing = [k for k in KEYS if k not in data]
    if missing:
        fail(f"the document is missing blocks: {missing}")

    title = re.search(r"<title>(.*?)</title>", html, re.S)
    version = re.search(r"Version\s*([\d.]+)", html)
    date = re.search(r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d{4})", html)

    payload = {
        "provenance": {
            "document": (title.group(1).strip() if title else "Enterprise AI Skills SRD"),
            "version": (version.group(1) if version else "unknown"),
            "date_label": (date.group(0) if date else "unknown"),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "extracted_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "extracted_by": "tools/extract_srd.py",
            "note": (
                "The source document is not published with this package. This file is its "
                "normalized projection. Verify the sha256 against your copy before trusting "
                "any number here."
            ),
        },
        "checklist": js_array(html, "checklistItems"),
        "weights": js_object(html, "DEFAULT_WEIGHTS"),
        "pilots": js_array(html, "PILOTS"),
    }
    for key in KEYS:
        payload[key] = data[key]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    prov = payload["provenance"]
    print(f"[OK] wrote {OUT.relative_to(ROOT)}")
    print(f"     {prov['document']} v{prov['version']} ({prov['date_label']})")
    print(f"     sha256 {prov['sha256']}")
    print(f"     {len(payload['skills'])} skills, {len(payload['domains'])} domains, "
          f"{len(payload['requirements'])} requirements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
