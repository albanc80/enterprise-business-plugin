"""Two writers, one trail: does `audit_append` fork the chain?

`audit_append` read the last hash, then wrote. Two concurrent appends read the same
previous_hash and both chain to it, so the trail forks and every later read reports
tampering — a false alarm on a trail nobody tampered with, which is worse than no
detection because it destroys trust in the only evidence there is.

The chain here is the package's central claim, so the writer has to be serialised.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "servers"))

from enterprise_core import main  # noqa: E402


@pytest.fixture
def audit(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_data_dir", lambda: tmp_path)
    return tmp_path / "audit.jsonl"


def test_concurrent_threads_do_not_fork_the_chain(audit):
    def write(n: int) -> None:
        main.audit_append({"skill_id": "FIN-02", "actor": f"a{n}", "outcome": "draft"})

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(24)))

    trace = main.audit_trace(limit=100)
    assert trace["total"] == 24
    assert trace["verified"] is True, trace["integrity"]["problems"][:3]


def test_no_lost_entries_under_concurrency(audit):
    def write(n: int) -> None:
        main.audit_append({"skill_id": "FIN-02", "n": n, "outcome": "draft"})

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(write, range(30)))

    seen = sorted(entry["entry"]["n"] for entry in main.audit_trace(limit=100)["entries"])
    assert seen == list(range(30)), "every append must land exactly once"


def test_two_processes_writing_the_same_trail_do_not_fork_it(audit, tmp_path):
    """The real case: two MCP servers, or a client and a gateway, on one data dir."""
    script = (
        "import os, sys\n"
        f"sys.path.insert(0, {str(ROOT / 'servers')!r})\n"
        "from enterprise_core import main\n"
        "tag = sys.argv[1]\n"
        "for n in range(12):\n"
        "    main.audit_append({'skill_id': 'FIN-02', 'writer': tag, 'n': n, 'outcome': 'draft'})\n"
    )
    env = {**os.environ, "ENTERPRISE_DATA_DIR": str(tmp_path)}
    procs = [
        subprocess.Popen([sys.executable, "-c", script, tag], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for tag in ("alpha", "beta")
    ]
    for proc in procs:
        _, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, err.decode()[-400:]

    trace = main.audit_trace(limit=100)
    assert trace["total"] == 24
    assert trace["verified"] is True, trace["integrity"]["problems"][:3]


def test_the_chain_is_still_verifiable_after_concurrent_writes(audit):
    """Belt and braces: the file on disk, not just the tool's own report."""
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n: main.audit_append({"n": n}), range(10)))

    lines = [ln for ln in audit.read_text(encoding="utf-8").splitlines() if ln.strip()]
    hashes = [json.loads(ln)["entry_hash"] for ln in lines]
    prevs = [json.loads(ln)["previous_hash"] for ln in lines]
    assert prevs[0] == "genesis"
    assert prevs[1:] == hashes[:-1], "each entry must link to the one before it"
