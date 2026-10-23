# Agent setup and MCP connections

Point the agent at this checkout and ask it to set up Mapwright MCP for its
client. The [setup skill](../skills/mapwright-setup/SKILL.md) directs it to
resolve paths, install the local Python environment, register the server,
install both skills with bundled guides, and verify stdio MCP. No hand-written
configuration or manually copied skill links are needed.

From the checkout, this applies project setup for Codex:

```powershell
python scripts/setup_agent.py --client codex --yes
```

Other client IDs are `claude`, `opencode`, `antigravity`, `pi`, and `hermes`.
Hermes uses an active profile rather than a project MCP file:

```powershell
python scripts/setup_agent.py --client hermes --scope user --yes
```

Without `--yes`, setup prints a read-only plan. Repeat `--client` to select
several clients; `--client auto` detects installed clients and reports Hermes
as skipped when project scope was requested. `--scope user`
registers across projects. `--home` selects an isolated home and ignores
environment profile overrides. `--workspace` selects the map workspace and
project configuration root. `--help` describes every flag.

Setup writes the absolute installed executable and workspace. Transport is
local stdio; no account, hosted endpoint, Node, or REA is required
by Mapwright at runtime. See [native setup](setup.md) for the separate owned
legacy CS:GO requirement.

## Configuration and portable skills

The installer merges the named server while preserving unrelated servers,
settings, trust and permissions. JSONC comments and unrelated source text
remain intact. TOML replacement requires a standard `[mcp_servers.mapwright]`
table; inline/quoted representations are refused. Hermes YAML aliases/anchors
are refused rather than flattened. Malformed or duplicate managed mappings
are reported before configuration writes. Unmanaged skill folders are preserved.

| Client | Project MCP configuration | User/profile configuration | Project skills |
| --- | --- | --- | --- |
| Codex | `.codex/config.toml` | `$CODEX_HOME/config.toml`, otherwise `~/.codex/config.toml` | `.agents/skills/` |
| Claude Code | `.mcp.json` | `~/.claude.json` | `.claude/skills/` |
| OpenCode | `opencode.jsonc` or `opencode.json` | `$OPENCODE_CONFIG_DIR`, otherwise `~/.config/opencode/` | `.opencode/skills/` |
| Antigravity | `.agents/mcp_config.json` | `~/.gemini/config/mcp_config.json` | `.agents/skills/` |
| pi | `.pi/mcp.json` | `~/.pi/agent/mcp.json` | `.pi/skills/` |
| Hermes | Active profile only | `$HERMES_HOME/config.yaml` | Profile `skills/` |

User skills use the corresponding user directory. Antigravity user setup
installs skills for both App/IDE (`~/.gemini/config/skills`) and CLI
(`~/.gemini/antigravity-cli/skills`). Native Windows Hermes defaults to
`%LOCALAPPDATA%/hermes`; Linux/macOS/WSL defaults to `~/.hermes`.

Installed skills contain `installation.json` with the concrete executable,
workspace and checkout. The mapping skill owns the KZ, copying, recovery and native guides; the setup
skill owns this client guide and links to the sibling mapping skill. Install both.
Their resolver checks machine paths before use; guide links resolve outside this repository.
Rerunning setup is idempotent and updates managed files.

Recreate the environment and rerun setup after cloning or relocating a checkout.
Executable paths, configuration, installed skills and receipts describe one
machine; generated project files are ignored by Git. The complete dependency
and native-session checklist is in [fresh-machine prerequisites](setup.md#fresh-machine-prerequisites).

Each changed file has a backup and digest in the receipt under
`.local/agent-setup/`. The agent can restore the exact returned receipt with
`python scripts/setup_agent.py --rollback RECEIPT_PATH --yes`. Rollback refuses
files edited afterward. It restores registration/skill files; installed Python
packages and downloaded native tools remain available.

## Compatibility and reload

Official configuration formats were checked on 2026-10-19. This establishes
upstream support, not a successful integration run in every client/version.

- **Codex:** Project MCP loads in trusted projects. Restart/new session may be
  needed for the server and skills; setup does not grant trust.
  [MCP](https://developers.openai.com/codex/mcp),
  [skills](https://developers.openai.com/codex/build-skills).
- **Claude Code:** Project `.mcp.json` servers can require approval in Claude;
  user servers use `mcpServers` in `~/.claude.json`. Inspect `/mcp` after reload.
  [MCP scopes](https://code.claude.com/docs/en/mcp),
  [skills](https://code.claude.com/docs/en/skills).
- **OpenCode:** Local servers use `mcp.NAME.type="local"`, a command array,
  and timeout in milliseconds. Reload/restart to inspect the current catalog.
  [MCP](https://opencode.ai/docs/mcp-servers/),
  [configuration](https://opencode.ai/docs/config/),
  [skills](https://opencode.ai/docs/skills/).
- **Antigravity:** Current App, IDE and CLI use `mcpServers` command/args and
  support `.agents/mcp_config.json`. Use its MCP manager to reload connections.
  Older builds used different paths; verify the installed version.
  [MCP](https://antigravity.google/docs/mcp/),
  [skills](https://antigravity.google/docs/skills/).
- **pi:** Current upstream, formerly `badlogic/pi-mono`, now
  `earendil-works/pi`, has built-in MCP with `mcpServers` in `mcp.json`.
  Project servers require project trust. `pi mcp list` tests connections;
  `/reload` reloads skills. An extension registering `/mcp` can replace the
  built-in session integration. Older releases may need an extension or the
  CLI fallback; setup does not silently install an extension.
  [MCP](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/mcp.md),
  [skills](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/skills.md).
- **Hermes:** Current upstream supports native Windows and WSL2. MCP uses
  `mcp_servers` in active-profile YAML, with timeouts in seconds. Use
  `/reload-mcp` or a new session. Its optional Windows features have separate
  limits; they do not require Mapwright to run in WSL.
  [Windows native support](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/windows-native.md),
  [MCP](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/mcp.md).

## Verification and CLI fallback

Applied setup runs the registered executable through MCP initialize,
tools/list, resources/list, prompts/list and a read-only `doctor` call.
The agent separately checks whether its current client session loaded that
registration and skills; an existing conversation may need a new session.
When the conversation cannot reload MCP, the agent continues through the
installed CLI immediately. Persistent registration serves future sessions;
the user does not need to restart the client to finish the mapping task.

Use tools/list for schemas, `kz_mapping_workflow` for the mapping prompt, and
`hammer://guide/kz` for guidance. Long builds need client timeouts above the
requested tool timeout. Progress requires a client progress token and does
not extend every client's hard deadline. Completed checks return findings in
`data`; `isError` indicates execution failure.

Any terminal-capable agent can use the installed CLI from the skill's
`installation.json`, even if an old client lacks MCP or cannot reload it.
Run `schema --index` then `schema --tool TOOL` for tool fields and `COMMAND --help` for flags. Read
[recovery](recovery.md) for operation logs, checkpoints and artifacts.

## Missing tools or startup failures

An installed `.venv` does not register an MCP server. If Mapwright is absent
from the client's tool catalog, run the setup workflow above for that client
and scope, then inspect its receipt and verification result. For Codex,
project registration is `.codex/config.toml`, with skills in `.agents/skills/`;
the absence of a user-scoped skill receipt does not rule out project setup.
Codex loads project configuration only in trusted projects, as described in
its [configuration documentation](https://developers.openai.com/codex/config-file/config-basic).
Report current-chat discovery separately from a successful stdio smoke test.

For a server that exits before initialize, capture stderr and the exit code.
MCP startup errors go to stderr and exit with code 1; stdout is reserved for
protocol messages, following the [stdio transport contract](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#stdio).
Non-MCP CLI commands continue to return their JSON envelope on stdout.

On Windows, `WinError 5` during workspace resolution can occur in a restricted
child process even when reading repository files succeeds. Compare the exact
registered executable and workspace in the intended client context, using
the environment's approved permission mechanism when required. If that
initializes successfully while the restricted launch fails, repair client
registration or process access rather than changing map code. The CLI fallback
also needs filesystem access; it cannot bypass a denied workspace. Preserve
canonical workspace resolution and junction/symlink confinement checks.
