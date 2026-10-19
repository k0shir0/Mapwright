# MCP connections

Launch the installed executable with an absolute workspace:

```text
C:/path/to/Mapwright/.venv/Scripts/mapwright.exe --workspace C:/maps mcp
```

Transport: stdio. Configuration: `C:/maps/mapwright.local.json`.
Replace paths below; on Linux/macOS use `.venv/bin/mapwright`.

## Codex

```toml
[mcp_servers.mapwright]
command = 'C:/path/to/Mapwright/.venv/Scripts/mapwright.exe'
args = ['--workspace', 'C:/maps', 'mcp']
startup_timeout_sec = 30
tool_timeout_sec = 3700
```

## Claude Code / mcpServers clients

```json
{
  "mcpServers": {
    "mapwright": {
      "command": "C:/path/to/Mapwright/.venv/Scripts/mapwright.exe",
      "args": ["--workspace", "C:/maps", "mcp"]
    }
  }
}
```

## OpenCode

```json
{
  "mcp": {
    "mapwright": {
      "type": "local",
      "command": ["C:/path/to/Mapwright/.venv/Scripts/mapwright.exe", "--workspace", "C:/maps", "mcp"],
      "enabled": true,
      "timeout": 3700000
    }
  }
}
```

Set client call timeouts above the requested tool timeout. Progress events
require a client progress token and do not extend every client's hard timeout.
Use tools/list for schemas, `kz_mapping_workflow` for the mapping prompt, and
`hammer://guide/kz` for guidance. Completed checks return findings in `data`;
`isError` indicates execution failure. Read [recovery](recovery.md) for artifacts.

For shell-only agents, use the same CLI. To install its workflow skill, copy
`skills/mapwright` into the client's configured skills directory. Resolve its
linked guides from the Mapwright checkout.
