# Agent connections

Use an absolute executable path and an absolute map workspace. Example paths
below assume the checkout is `D:/Projects/.personal/Hammerplusplus`. Replace
both paths for other installations. Configuration examples are supplied for
review; installing this package does not alter client configurations.

## Codex

Using the [official stdio MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli):

```powershell
codex mcp add hammerplusplus -- D:/Projects/.personal/Hammerplusplus/.venv/Scripts/hammer-agent.exe --workspace D:/Projects/.personal/Hammerplusplus mcp
codex mcp list
```

Or add this server table to the intended Codex configuration:

```toml
[mcp_servers.hammerplusplus]
command = 'D:/Projects/.personal/Hammerplusplus/.venv/Scripts/hammer-agent.exe'
args = ['--workspace', 'D:/Projects/.personal/Hammerplusplus', 'mcp']
startup_timeout_sec = 30
tool_timeout_sec = 180
```

Use a tool timeout longer than the requested compile timeout. Restart the
client after registration so it can discover the tools.

## Claude Code

Following [Claude Code's stdio configuration](https://code.claude.com/docs/en/mcp):

```powershell
claude mcp add --transport stdio hammerplusplus -- D:/Projects/.personal/Hammerplusplus/.venv/Scripts/hammer-agent.exe --workspace D:/Projects/.personal/Hammerplusplus mcp
```

Equivalent stdio server entry for clients using `mcpServers`:

```json
{
  "mcpServers": {
    "hammerplusplus": {
      "command": "D:/Projects/.personal/Hammerplusplus/.venv/Scripts/hammer-agent.exe",
      "args": ["--workspace", "D:/Projects/.personal/Hammerplusplus", "mcp"]
    }
  }
}
```

## OpenCode

Merge a local server entry into your intended OpenCode project configuration,
using its [documented local MCP format](https://opencode.ai/docs/mcp-servers/):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "hammerplusplus": {
      "type": "local",
      "command": ["D:/Projects/.personal/Hammerplusplus/.venv/Scripts/hammer-agent.exe", "--workspace", "D:/Projects/.personal/Hammerplusplus", "mcp"],
      "enabled": true,
      "timeout": 180000
    }
  }
}
```

## Initial task for an agent

> Use Hammer++ tools to create maps/agent_room.vmf with the csgo-room template.
> Inspect it, add a 128-unit-wide central platform using a revision-checked edit,
> then validate it. If the actual legacy CS:GO SDK is available, compile it and
> open it in Hammer++. Inspect an editor-window capture before claiming the
> map rendered. Report missing tools and retain the VMF if backend checks fail.

The `schema` command and MCP tools/list are the command reference. Start with
`doctor` and `inspect_map`. `inspect_object` exposes geometry source and side
IDs. `edit_map` advertises a tagged JSON schema for all operations. Each result
contains `ok` and either `data` or `error`; tool failures set MCP `isError`.

Agents can also use the CLI through their normal shell without MCP. Read
`skills/cli-anything-hammerplusplus/SKILL.md` for map-specific constraints.
