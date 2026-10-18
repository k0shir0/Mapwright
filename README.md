# Hammer++ agent bridge

A local CLI and stdio MCP server for agents to create and edit **legacy CS:GO
Source 1 maps** in Hammer++'s native VMF format.

Agents can inspect maps, build brushes and enclosed rooms, create entities,
edit properties and outputs, move geometry, and undo transactions. Both
interfaces use the same validated command contract. Edits retain unmodified
VMF text, comments, repeated outputs and unknown Hammer++ blocks.

**Current limit:** native VMF workflows are tested. The real Hammer++ editor,
Windows window capture and Valve compiler pipeline need a legacy CS:GO SDK
installation and have not been verified on this machine. This is not full
live editor control. CS2 / Source 2 VMAP is outside this project's target.

## Install

Requires Python 3.11 or newer. Run in this checkout:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[mcp,source]"
.\.venv\Scripts\hammer-agent.exe --json doctor
```

The core CLI needs JSON Schema validation; `mcp` adds the official MCP SDK,
and `source` adds srctools for FGD and VPK catalogs. On Linux/macOS use
`.venv/bin/python` and `.venv/bin/hammer-agent`. File editing and MCP work
cross-platform; Hammer++ itself is a Windows application.

## Make a map

```powershell
$cli = '.\.venv\Scripts\hammer-agent.exe'
& $cli --json new maps/agent_room.vmf --template csgo-room
$map = (& $cli --json inspect maps/agent_room.vmf | ConvertFrom-Json).data
& $cli --json edit maps/agent_room.vmf --expect $map.revision --ops '@examples/edit.json' --dry-run
& $cli --json edit maps/agent_room.vmf --expect $map.revision --ops '@examples/edit.json'
& $cli --json validate maps/agent_room.vmf
```

`csgo-room` creates six enclosing world brushes, one spawn per team and a
light. This is a mapping test fixture, not a complete competitive map.
`add_room` uses interior bounds; `add_box` uses exterior bounds. Distances
are Source units and Z points up.

Use `--workspace ABSOLUTE_PATH` before the command to work outside the current
directory. Every map and generated artifact stays inside that workspace.
`--ops` accepts an inline JSON array or an `@file`. `schema` returns all
tools and operation fields. JSON is the default output; `--json` makes it
compact. A failed command exits 1 with `ok: false`.

| Command | Purpose |
| --- | --- |
| `doctor` | Inspect configuration, Steam candidates and SDK readiness |
| `new PATH --template empty\|csgo-room` | Create a VMF without overwriting |
| `inspect PATH [--offset N --limit N]` | Read revision, counts and objects |
| `object PATH ID` | Read properties, outputs, side IDs and source text |
| `edit PATH --expect HASH --ops @FILE` | Apply or preview one transaction |
| `validate PATH` | Check IDs, planes, key fields and coordinates |
| `history PATH`, `undo PATH --expect HASH`, `redo PATH --expect HASH` | Inspect and restore transactions |
| `entities --query TEXT [--classname NAME]` | Query local FGD definitions and inherited fields |
| `assets --kind material\|model --query TEXT` | Search loose files and VPK directories |
| `compile PATH --expect HASH --mode bsp\|fast\|full` | Run actual Valve tools in a fresh build directory |
| `editor-open PATH` | Launch a configured Hammer++ editor |
| `editor-capture PID OUTPUT.png` | Capture a selected editor window on Windows |
| `rea-probe hammer` | Run optional local REA PE-resource inspection |
| `schema`, `call TOOL JSON`, `repl`, `mcp` | Discovery, direct calls, interactive shell and MCP |

Every edit batch requires the revision from the last inspection. A stale
hash fails without changing the map. History and checksummed snapshots live
in `.hammer-agent/`. Undo refuses to overwrite external changes. Locks
coordinate bridge writers; they cannot lock Hammer++ itself. Edit a copy and
avoid saving it simultaneously from the editor. After a crash, verify the
PID in `.hammer-agent/write.lock` has stopped before removing that lock.

Translation supports ordinary brushes and entities with texture locking.
Displacements, overlays and instances must be moved in the editor. Existing
unsupported blocks are preserved. Structural validation does not establish
convexity, sealing, material existence, entity compatibility or playability.

## Connect an agent

Launch `hammer-agent --workspace ABSOLUTE_MAP_DIRECTORY mcp` using the absolute
executable path from this virtual environment. The server listens on stdio
only and advertises tool schemas and read/write annotations. It uses the
workspace's `hammer-agent.local.json`. No model API key is needed.

Examples for Codex, Claude Code and OpenCode are in
[docs/agents.md](docs/agents.md). The
[mapping skill](skills/cli-anything-hammerplusplus/SKILL.md) supplies the
inspect, edit, validate, compile and visual verification workflow.

## Set up Hammer++ and the real backend

Follow [docs/setup.md](docs/setup.md), then copy
`hammer-agent.example.json` to `hammer-agent.local.json` and correct its paths.
The official [CS:GO Hammer++ build is frozen at 8864](https://ficool2.github.io/HammerPlusPlus-Website/download.html).
Its archive requires the legacy CS:GO SDK; downloading Hammer++ alone does
not supply Valve's engine DLLs, FGD or VBSP/VVIS/VRAD.

Builds preserve the VMF and retain stage logs and a receipt in a fresh
`.hammer-agent/builds/` directory. Leaks, timeouts, missing outputs and invalid
VBSP headers fail. Outputs stay staged for review. This bridge does not
install maps into the game or publish to Workshop.

## Verify

```powershell
$env:PATH = "$PWD\.venv\Scripts;$env:PATH"
$env:CLI_ANYTHING_FORCE_INSTALLED = '1'
python -m unittest discover -s tests -v
python scripts/demo.py
# Requires the actual legacy SDK; missing tools fail this check:
python scripts/verify_backend.py
```

Use the virtual environment's Python if it is not activated. Tests cover
VMF editing/history, failure recovery, an independent srctools geometry
oracle, installed CLI calls and an actual MCP stdio session. See
[tests/TEST.md](tests/TEST.md) for the plan and measured results.

## Upstream tools

Built using [CLI-Anything's harness methodology](https://github.com/HKUDS/CLI-Anything)
and [REA](https://github.com/morluto/rea) for local binary evidence.
[docs/research.md](docs/research.md) records versions, observations and limits.
Neither upstream tool is needed for routine map edits. All implementation
work was done in Codex. No Hammer++, Valve binaries or game assets are
included in this repository.
