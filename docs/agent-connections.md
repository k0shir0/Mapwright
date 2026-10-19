# Mapwright agent connections

Use an absolute executable path and an absolute map workspace. Example paths
below assume the checkout is `C:/path/to/Mapwright`. Replace
both paths for other installations. Configuration examples are supplied for
review; installing this package does not alter client configurations.

## Codex

Using the [official stdio MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli):

```powershell
codex mcp add mapwright -- C:/path/to/Mapwright/.venv/Scripts/mapwright.exe --workspace C:/path/to/Mapwright mcp
codex mcp list
```

Or add this server table to the intended Codex configuration:

```toml
[mcp_servers.mapwright]
command = 'C:/path/to/Mapwright/.venv/Scripts/mapwright.exe'
args = ['--workspace', 'C:/path/to/Mapwright', 'mcp']
startup_timeout_sec = 30
tool_timeout_sec = 3700
```

Use a tool timeout longer than the requested compile timeout. Restart the
client after registration so it can discover the tools.

## Claude Code

Following [Claude Code's stdio configuration](https://code.claude.com/docs/en/mcp):

```powershell
claude mcp add --transport stdio mapwright -- C:/path/to/Mapwright/.venv/Scripts/mapwright.exe --workspace C:/path/to/Mapwright mcp
```

Equivalent stdio server entry for clients using `mcpServers`:

```json
{
  "mcpServers": {
    "mapwright": {
      "command": "C:/path/to/Mapwright/.venv/Scripts/mapwright.exe",
      "args": ["--workspace", "C:/path/to/Mapwright", "mcp"]
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
    "mapwright": {
      "type": "local",
      "command": ["C:/path/to/Mapwright/.venv/Scripts/mapwright.exe", "--workspace", "C:/path/to/Mapwright", "mcp"],
      "enabled": true,
      "timeout": 3700000
    }
  }
}
```

## Mapping workflow

Read [KZ mapping](kz-mapping.md), then use the `kz_mapping_workflow` MCP prompt
or the packaged `skills/mapwright/SKILL.md`.

The `schema` command and MCP tools/list are the command reference. Start with
`doctor` and `inspect_map`. `inspect_object` exposes geometry source and side
IDs. `edit_map` advertises a tagged JSON schema for all operations. Each result
contains `ok` and either `data` or `error`; tool failures set MCP `isError`.

Agents can also use the CLI through their normal shell without MCP. Read
`skills/mapwright/SKILL.md` for map-specific constraints.

For KZ reuse, give the agent the source BSP/VMF, destination VMF, desired item
and placement. It can import, search and inspect the source, copy identified
objects and their dependencies, then compile and inspect a rendered capture.
See [reference maps](reference-maps.md) for the exact workflow. The user's
description is interpreted by the connected agent; this server needs no
separate language-model account.

MCP uses the installed Python SDK v1.x contract. Tool results declare a JSON
output schema and return identical structured/text envelopes. Completed
structural/KZ checks use `ok:true`; inspect `data.valid`, findings and unsupported
geometry. The CLI exits 1 for invalid checks while retaining that result.

Progress notifications accompany long calls when the client supplies a progress
token. Set the client call timeout above the server tool timeout (up to 3600s);
progress does not extend every client hard timeout. Resources expose KZ guidance
and recovery artifacts; tools provide paginated log/history/snapshot access.

To install the mapping skill into a client, copy `skills/mapwright` to that
client's configured skills directory. The repository AGENTS.md also points at
the same skill; package installation does not modify global client settings.
