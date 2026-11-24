# Install

The repo root **is** the package. Every client below installs it directly; nothing is generated
first.

## Prerequisite for the tools

The governance MCP runs as a PEP 723 script, so it needs [`uv`](https://docs.astral.sh/uv/) on
`PATH`. Its dependencies (`mcp>=2,<3`, `pyyaml>=6,<7`) are declared inside
`servers/enterprise_core/main.py` and resolved on first run. There is no virtualenv to manage and
nothing to `pip install`.

Without `uv`, the skills still load. You lose the deterministic verdicts — permission
resolution, approval validation, gate checks and the audit trail — and every skill says so
instead of guessing.

## First run

Registration is automatic: each verified client reads the package's own manifests, so nothing has
to be wired by hand.

| Client | What registers the server | When it takes effect |
|---|---|---|
| Hermes | `mcp.json` | next session ("deferred: MCP servers") |
| Codex | `mcp.json`, via the plugin | next session — `codex mcp list` shows `enterprise-core` **enabled**, with `PLUGIN_DATA` and `PLUGIN_ROOT` set |
| Claude Code | `.mcp.json`, via `.claude-plugin/` | next session — `claude mcp list` shows the plugin entry |

Dependencies resolve lazily on first boot — roughly 9 s with an empty `uv` cache. Warm them
before a session so a cold start cannot collide with a client's MCP startup timeout:

```bash
uv run --script servers/enterprise_core/main.py --selftest
```

Expect `selftest OK` after the `[OK]` lines. It verifies the install as well as warming it —
93 contracts, 12 domains, 32 requirements, the policy YAML, a permission resolution, the
ceiling holding and the scoring path — and exits non-zero if anything is missing. If a client
still times out on its very first launch, raise its startup allowance (Codex:
`startup_timeout_sec` in `config.toml`).

## Hermes

```bash
hermes plugins install albanc80/enterprise-business-plugin
hermes plugins enable enterprise-business-plugin
```

Portable v1 packages install **disabled** by design; enabling is the trust decision. Verify what
you are trusting first:

```bash
hermes plugins validate .          # from a clone; the strictest of the client validators
hermes plugins show enterprise-business-plugin
```

## Codex

```bash
codex plugin marketplace add albanc80/enterprise-business-plugin
codex plugin add enterprise-business-plugin@enterprise-business-plugin
```

Codex needs a **marketplace**, not just a plugin: it reads
`.agents/plugins/marketplace.json` or, as here, a Claude-compatible
`.claude-plugin/marketplace.json` at the repository root. The `add` step requires the
`<plugin>@<marketplace>` form — a bare name fails with "plugin requires --marketplace".
`codex plugin list` shows the version and status.

For a local working copy during development, `codex plugin marketplace add ./` from the repo
root works too, and `~/.codex/skills` accepts the skill folders directly.

## Claude (Code, Desktop)

Claude is **not** an Agent Plugins v1 client, so the package ships a shim at
`.claude-plugin/plugin.json` plus a `.mcp.json` that points at the same server, and declares
itself as a marketplace in `.claude-plugin/marketplace.json` (which also carries the required
`owner`).

```bash
claude plugin validate .
claude plugin marketplace add albanc80/enterprise-business-plugin
claude plugin install enterprise-business-plugin@enterprise-business-plugin -y
```

`claude plugin list` reports the version, source and enabled state:

```
❯ enterprise-business-plugin@enterprise-business-plugin
  Version: 0.1.8
  Scope: user
  Status: ✔ enabled
```

`claude mcp list` must show the server **Connected**, with the plugin root resolved to the cache:

```
plugin:enterprise-business-plugin:enterprise-core: uv run --quiet --script
  C:/Users/<you>/.claude/plugins/cache/enterprise-business-plugin/enterprise-business-plugin/0.1.8/servers/enterprise_core/main.py
  - ✔ Connected
```

### If you open the repo folder directly, instead of installing it

Claude Code picks up the repo's `.mcp.json` as a **project-scoped** server, which looks like a
broken install and is not one:

```
enterprise-core: uv run --quiet --script ${CLAUDE_PLUGIN_ROOT}/servers/enterprise_core/main.py
  - ⏸ Pending approval
  └ [Warning] Missing environment variables: CLAUDE_PLUGIN_ROOT
```

`${CLAUDE_PLUGIN_ROOT}` is only defined for **plugin-scoped** servers, so a project-scope pickup can
never resolve it. Do not approve it and do not try to fix it — install the plugin (above), which
expands the variable to the installed path. The same file serves both roles, and only the plugin
install has the context to fill it in.

## ChatGPT desktop / Codex runtime

The ChatGPT desktop app runs the Codex runtime, so it **can** host the bundled server. Register
it once in `~/.codex/config.toml`:

```toml
[mcp_servers.enterprise-core]
command = 'C:\Users\<you>\.local\bin\uv.exe'        # run `where uv` to find yours
args = ["run", "--quiet", "--script", 'C:\Users\<you>\.codex\plugins\cache\enterprise-business-plugin\<version>\servers\enterprise_core\main.py']

[mcp_servers.enterprise-core.env]
UV_CACHE_DIR = 'C:\Users\<you>\AppData\Local\Codex\enterprise-core\uv-cache'
```

Two details make this robust: an **absolute path to `uv.exe`**, because a GUI-launched app may
not inherit your shell's `PATH`, and a **dedicated `UV_CACHE_DIR`**, so resolution is isolated
and can be pre-warmed. Confirm with `codex mcp list` → `enterprise-core … enabled`.

## chatgpt.com and mobile

Not supported, and not a packaging gap: a browser tab or a phone has no local process to spawn.
There the skills answer qualitatively and state that no deterministic verdict was produced —
the designed refusal, not a failure.

Putting the tools in a browser session means hosting `servers/enterprise_core` as a remote
HTTPS MCP endpoint: streamable-HTTP transport, TLS, authentication, rate limiting, logging and
a kill switch. That is a deployment and security decision, not a packaging one.

## OpenClaw

OpenClaw is a v1 client and should work through its plugin bundles path; it was not tested against
(`docs.openclaw.ai/plugins/bundles`), or point it at the skill folders in `skills/` and register
the MCP server with `openclaw mcp set`.

## Copilot, Cursor, VS Code, Kiro, Antigravity

All are v1 clients. Point them at this repository through their own plugin UI; no additional
files are needed.

## Verifying an install

```bash
python tools/validate.py                                             # manifest, registry, policies, skills, mcp
uv run --with pytest --with "mcp>=2,<3" --with "pyyaml>=6,<7" -- python -m pytest tests -q
uv run --script servers/enterprise_core/main.py --selftest
uv run --script tools/probe_mcp.py                                   # speaks MCP itself
```

`probe_mcp.py` is the check that separates "the client said Installed" from "the tools work". It
performs the `initialize` handshake, lists the tools, calls `list_capabilities` and asserts the
served contract count matches the registry, then confirms the ceiling holds for an A3 request.
Point it at an installed copy to verify that specific location:

```bash
uv run --script tools/probe_mcp.py ~/.hermes/profiles/<profile>/plugins/enterprise-business-plugin
```

Then confirm registration **in a new session**, because Hermes registers plugin MCP servers at
session start. A one-shot prompt is the cheapest way to prove it without opening a chat:

```bash
hermes -z "Use the enterprise-core MCP tool list_capabilities. Report counts.skills, autonomy.ceiling_default and autonomy.a3_shipped."
```

Expect `93`, `A1`, `false`. Values that specific can only come from the server — if the model
answers from memory or reports the server as unavailable, registration did not take effect.

Finally, in any client, ask what the pack can do: `list_capabilities` should report 93 contracts,
12 domains, `ceiling_default: A1` and `a3_shipped: false`.

That `false` is the point. The package cannot write to any system, and no configuration inside a
session changes it — only an edit to `src/policies/autonomy-config.yaml`, with the opt-in
evidence it requires.
