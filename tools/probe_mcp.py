#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6,<7"]
# ///
"""Prove the package speaks MCP from a given install location.

This is the check that distinguishes "the client said Installed" from "the tools
actually work". It speaks the protocol directly over stdio — no client, no
session deferral, no model — so a failure is the package's.

    uv run --script tools/probe_mcp.py                    # probe this repo
    uv run --script tools/probe_mcp.py <path-to-install>  # probe an installed copy

Verifies, in order: initialize handshake, tool count, a real tools/call against
the installed registry, and that the governance ceiling actually holds.

Exit 0 = the server is a working MCP server at that path.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import yaml

# The server's advertised tool surface. Kept here so adding a tool without updating
# the probe is a visible diff rather than a silent gap.
EXPECTED_TOOLS = {
    "approval_gate", "audit_append", "audit_trace", "check_connector", "check_tool_call",
    "get_contract", "get_roadmap", "list_capabilities", "list_domains",
    "list_requirements", "list_skills", "release_gate", "route_autonomy",
    "score_skills", "tool_allowlist",
}
TIMEOUT = 120.0


def expected_skill_count(plugin: Path) -> int:
    doc = yaml.safe_load((plugin / "src/registry/skills.yaml").read_text(encoding="utf-8"))
    return len(doc["skills"])


def expected_ceiling(plugin: Path) -> str:
    doc = yaml.safe_load((plugin / "src/policies/autonomy-config.yaml").read_text(encoding="utf-8"))
    return str(doc["ceiling"]["default_max_level"])


def main() -> int:
    plugin = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    server = plugin / "servers" / "enterprise_core" / "main.py"
    if not server.exists():
        print(f"[FAIL] no server at {server}", file=sys.stderr)
        return 2

    want_skills = expected_skill_count(plugin)
    want_ceiling = expected_ceiling(plugin)

    proc = subprocess.Popen(
        ["uv", "run", "--quiet", "--script", str(server)],
        cwd=str(plugin),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", bufsize=1,
    )
    stderr: list[str] = []
    threading.Thread(target=lambda: [stderr.append(ln) for ln in proc.stderr], daemon=True).start()

    def send(payload: dict) -> None:
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()

    def reply(want_id: int) -> dict | None:
        deadline = time.time() + TIMEOUT
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == want_id:
                return msg
        return None

    def payload_of(msg: dict) -> dict:
        return json.loads(msg["result"]["content"][0]["text"])

    print(f"PROBE  {plugin}")
    failures: list[str] = []

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "probe-mcp", "version": "1"}}})
    init = reply(1)
    if not init:
        print("[FAIL] no initialize response", file=sys.stderr)
        print("".join(stderr[-12:]), file=sys.stderr)
        proc.kill()
        return 1
    info = init["result"]["serverInfo"]
    print(f"  [OK] initialize -> {info['name']} v{info['version']} (protocol {init['result']['protocolVersion']})")
    if info["name"] != "enterprise-core":
        failures.append(f"serverInfo.name is {info['name']!r}, expected 'enterprise-core'")

    send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    listing = reply(2)
    if not listing:
        failures.append("no tools/list response")
        proc.kill()
        print("\n".join(f"[FAIL] {f}" for f in failures), file=sys.stderr)
        return 1
    names = {t["name"] for t in listing["result"]["tools"]}
    print(f"  [{'OK' if names == EXPECTED_TOOLS else 'FAIL'}] tools/list -> {len(names)} tools")
    if names != EXPECTED_TOOLS:
        failures.append(f"tool set differs: missing {sorted(EXPECTED_TOOLS - names)}, extra {sorted(names - EXPECTED_TOOLS)}")

    send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
          "params": {"name": "list_capabilities", "arguments": {}}})
    called = reply(3)
    if not called:
        failures.append("no tools/call response")
    else:
        caps = payload_of(called)
        got_skills = caps["counts"]["skills"]
        got_ceiling = caps["autonomy"]["ceiling_default"]
        got_a3 = caps["autonomy"]["a3_shipped"]
        print(f"  [{'OK' if got_skills == want_skills else 'FAIL'}] contracts served: {got_skills} (registry has {want_skills})")
        print(f"  [{'OK' if got_ceiling == want_ceiling else 'FAIL'}] ceiling: {got_ceiling}")
        print(f"  [{'OK' if got_a3 is False else 'FAIL'}] a3_shipped: {got_a3}")
        if got_skills != want_skills:
            failures.append(f"server serves {got_skills} contracts, registry has {want_skills}")
        if got_ceiling != want_ceiling:
            failures.append(f"ceiling {got_ceiling} disagrees with policy {want_ceiling}")
        if got_a3 is not False:
            failures.append("a3_shipped is not false")

    send({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
          "params": {"name": "route_autonomy", "arguments": {"skill_id": "IT-08", "requested_level": "A3"}}})
    routed = reply(4)
    if not routed:
        failures.append("no route_autonomy response")
    else:
        res = payload_of(routed)
        holds = res["autonomy_effective"] in {"A0", "A1"} and res["mode"] != "auto"
        print(f"  [{'OK' if holds else 'FAIL'}] A3 request on IT-08 -> {res['autonomy_effective']}/{res['mode']} "
              f"downgraded={res['downgrade_applied']}")
        if not holds:
            failures.append("the ceiling did not hold for an A3 request")

    send({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
          "params": {"name": "tool_allowlist", "arguments": {"skill_id": "IT-01"}}})
    allow_msg = reply(5)
    if not allow_msg:
        failures.append("no tool_allowlist response")
    else:
        allow = payload_of(allow_msg)
        ok = allow["allowed_operations"] == ["read"] and "write" in allow["withheld_operations"]
        print(f"  [{'OK' if ok else 'FAIL'}] tool_allowlist(IT-01) -> {allow['allowed_operations']} "
              f"withheld {allow['withheld_operations']}")
        if not ok:
            failures.append("A1 skill did not report read-only with write withheld")

    send({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
          "params": {"name": "check_tool_call", "arguments": {
              "skill_id": "IT-01", "tool_name": "itsm.create_ticket",
              "operation": "write", "category": "itsm"}}})
    call_msg = reply(6)
    if not call_msg:
        failures.append("no check_tool_call response")
    else:
        verdict = payload_of(call_msg)
        denied = verdict["allowed"] is False and verdict["rule"] == "operation_not_permitted"
        print(f"  [{'OK' if denied else 'FAIL'}] check_tool_call write at A1 -> denied "
              f"({verdict['rule']})")
        if not denied:
            failures.append("a write at A1 was not denied by the tool allowlist")

    proc.stdin.close()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()

    if failures:
        print("\nPROBE FAILED")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nPROBE OK — server speaks MCP and the governance rules hold at this path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
