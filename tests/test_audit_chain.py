"""Does the audit chain actually detect tampering, or only look like it?

The package says "hash-chained" and "tamper-evident". Those are claims about a *verifier*,
and until this file existed there was none: `audit_trace` parsed lines and returned them,
and `_last_hash` trusted whatever the last line said. A chain nobody checks is a chain of
decorative hex.

Each test below is a specific attack on the file on disk.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "servers"))

from enterprise_core import main  # noqa: E402


@pytest.fixture
def audit(tmp_path, monkeypatch):
    """Point the audit trail at a throwaway directory."""
    monkeypatch.setattr(main, "_data_dir", lambda: tmp_path)
    return tmp_path / "audit.jsonl"


def write_three() -> None:
    for n in (1, 2, 3):
        main.audit_append({"skill_id": "FIN-02", "actor": f"actor-{n}", "outcome": "draft"})


def lines_of(path: Path) -> list[str]:
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def rewrite(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ----------------------------------------------------------------- the honest case
def test_a_clean_chain_verifies(audit):
    write_three()
    trace = main.audit_trace()
    assert trace["total"] == 3
    assert trace["verified"] is True
    assert trace["integrity"]["problems"] == []


def test_first_entry_links_to_genesis(audit):
    write_three()
    entries = main.audit_trace()["entries"]
    assert entries[0]["previous_hash"] == "genesis"
    assert entries[1]["previous_hash"] == entries[0]["entry_hash"]
    assert entries[2]["previous_hash"] == entries[1]["entry_hash"]


# ------------------------------------------------------------- editing an entry
def test_edited_entry_content_is_detected(audit):
    """Change what an entry says without touching its hash."""
    write_three()
    raw = lines_of(audit)
    record = json.loads(raw[1])
    record["entry"]["outcome"] = "executed"
    raw[1] = json.dumps(record, sort_keys=True)
    rewrite(audit, raw)

    trace = main.audit_trace()
    assert trace["verified"] is False
    assert trace["integrity"]["first_bad_index"] == 1
    assert any("hash" in p for p in trace["integrity"]["problems"])


def test_edited_entry_with_recomputed_hash_is_still_detected(audit):
    """The subtle attack: fix the entry's own hash so it looks self-consistent.

    It cannot fix the *next* entry, which recorded the old hash as its previous_hash.
    """
    write_three()
    raw = lines_of(audit)
    record = json.loads(raw[1])
    record["entry"]["outcome"] = "executed"
    record.pop("entry_hash")
    record = {
        "timestamp": record["timestamp"],
        "previous_hash": record["previous_hash"],
        "entry": record["entry"],
    }
    import hashlib

    forged = hashlib.sha256(
        json.dumps(record, sort_keys=True, default=str).encode()
    ).hexdigest()
    record["entry_hash"] = forged
    raw[1] = json.dumps(record, sort_keys=True)
    rewrite(audit, raw)

    trace = main.audit_trace()
    assert trace["verified"] is False, "a self-consistent forged entry must still break the link"
    assert trace["integrity"]["first_bad_index"] in (1, 2)


# --------------------------------------------------------- deleting or reordering
def test_deleted_middle_entry_is_detected(audit):
    write_three()
    raw = lines_of(audit)
    rewrite(audit, [raw[0], raw[2]])

    trace = main.audit_trace()
    assert trace["verified"] is False
    assert any("link" in p or "previous" in p for p in trace["integrity"]["problems"])


def test_reordered_entries_are_detected(audit):
    write_three()
    raw = lines_of(audit)
    rewrite(audit, [raw[0], raw[2], raw[1]])

    trace = main.audit_trace()
    assert trace["verified"] is False


def test_corrupt_line_is_detected_not_crashed(audit):
    write_three()
    raw = lines_of(audit)
    raw[1] = raw[1][: len(raw[1]) // 2]
    rewrite(audit, raw)

    trace = main.audit_trace()
    assert trace["verified"] is False
    assert any("unreadable" in p or "JSON" in p for p in trace["integrity"]["problems"])


def test_missing_hash_is_detected(audit):
    write_three()
    raw = lines_of(audit)
    record = json.loads(raw[1])
    record.pop("entry_hash")
    raw[1] = json.dumps(record, sort_keys=True)
    rewrite(audit, raw)

    trace = main.audit_trace()
    assert trace["verified"] is False
    assert any("hash" in p for p in trace["integrity"]["problems"])


# ------------------------------------------------------------- honest limitation
def test_truncating_newest_entries_is_not_detectable_from_inside_the_file(audit):
    """Pinned deliberately: the chain proves the entries it contains, not that none
    were removed from the end. Detecting that needs an external anchor (a count or
    head hash recorded elsewhere). The limitation is documented rather than papered over.
    """
    write_three()
    raw = lines_of(audit)
    rewrite(audit, raw[:2])

    trace = main.audit_trace()
    assert trace["total"] == 2
    assert trace["verified"] is True, "the surviving entries are a valid chain"


# ------------------------------------------------------- appending onto a broken one
def test_append_reports_that_the_existing_chain_is_broken(audit):
    write_three()
    raw = lines_of(audit)
    record = json.loads(raw[1])
    record["entry"]["outcome"] = "executed"
    raw[1] = json.dumps(record, sort_keys=True)
    rewrite(audit, raw)

    result = main.audit_append({"skill_id": "FIN-02", "actor": "actor-4", "outcome": "draft"})
    assert result["appended"] is True
    assert result["chain_intact_before_append"] is False
    assert result.get("integrity_warning"), "appending to a broken trail must say so"
    # and the break is still visible afterwards, not absorbed
    assert main.audit_trace()["verified"] is False


def test_append_on_a_fresh_trail_reports_intact(audit):
    result = main.audit_append({"skill_id": "FIN-02", "actor": "a", "outcome": "draft"})
    assert result["chain_intact_before_append"] is True
    assert "integrity_warning" not in result
