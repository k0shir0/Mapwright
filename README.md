# Mapwright

Mapwright is a local CLI and stdio MCP server for KZ mapping in legacy
CS:GO Source 1, using Hammer++'s native VMF format.

Agents can inspect and copy sections from other KZ maps, build brushes and
enclosed rooms, create entities, edit properties and outputs, control the
actual editor, and undo transactions. Both
interfaces use the same validated command contract. Edits retain unmodified
VMF text, comments, repeated outputs and unknown Hammer++ blocks.

KZ-specific tools audit GOKZ timers, anti-bhop, teleports, bhop routes,
ladders, water, headroom and spawns, and measure selected jump blocks.
Named checkpoints protect files/folders; workspace logs and artifacts expose
recovery evidence. See [KZ mapping](docs/kz-mapping.md) and
[recovery](docs/recovery.md). The [research follow-up](docs/research-followup.md)
tracks the owner's complete research inventory.

**Verified locally:** actual Hammer++ loading/rendering and Save As, real KZ
BSP decompilation and object copying through MCP, and fresh HDR compilation
with VBSP++/VVIS++/VRAD++. See [the evidence](docs/verification.md).
Native source editing and editor controls cover features without dedicated
helpers; individual editor commands and in-game KZ behavior are not all
tested. CS2 / Source 2 VMAP is outside this project's target.

## Install

Requires Python 3.11 or newer. Run in this checkout:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[mcp,source,desktop]"
.\.venv\Scripts\mapwright.exe --json doctor
```

The core CLI needs JSON Schema validation; `mcp` adds the official MCP SDK,
`source` adds srctools for FGD and VPK catalogs, and `desktop` adds Windows
editor interaction and GPU viewport capture. On Linux/macOS use
`.venv/bin/python` and `.venv/bin/mapwright`. File editing and MCP work
cross-platform; Hammer++ itself is a Windows application.

## Make a KZ map

```powershell
$cli = '.\.venv\Scripts\mapwright.exe'
& $cli --json new maps/agent_room.vmf --template kz-room
$map = (& $cli --json inspect maps/agent_room.vmf | ConvertFrom-Json).data
& $cli --json edit maps/agent_room.vmf --expect $map.revision --ops '@examples/edit.json' --dry-run
& $cli --json edit maps/agent_room.vmf --expect $map.revision --ops '@examples/edit.json'
& $cli --json validate maps/agent_room.vmf
& $cli --json kz-audit maps/agent_room.vmf
& $cli --json kz-test-plan maps/agent_room.vmf
```

`kz-room` adds GOKZ main timer zones, a course start and API version to the
enclosed `csgo-room` fixture. It is a starting room, not a complete course.
`add_room` uses interior bounds; `add_box` uses exterior bounds. Distances
are Source units and Z points up.

Single edits also have flat commands/tools (`add-box` / `map_add_box`,
`set-properties` / `map_set_properties`, etc.). Keep `edit` for atomic batches.
Successful checks return `ok:true` with findings; inspect `data.valid` and
`unsupported_geometry`. The CLI exits 1 when a completed check is invalid.

Use `--workspace ABSOLUTE_PATH` before the command to work outside the current
directory. Bridge file operations write inside that workspace. Reference
imports can read an explicitly supplied external map; real editor actions
operate through Hammer++ and its own dialogs.
`--ops` accepts an inline JSON array or an `@file`. `schema` returns all
tools and operation fields. JSON is the default output; `--json` makes it
compact. Failed execution exits 1 with `ok: false`. A completed invalid
check also exits 1 and retains `ok: true` with its findings in `data`.

Imported VMFs can reuse IDs across entity/world, solid, side and group
namespaces. For ambiguous IDs, use `object PATH ID --kind solid` or add
`"kind": "solid"` to the edit operation. `add_output` infers entity kind;
`add_box` can qualify its parent with `parent_kind`. Imported IDs are retained.

| Command | Purpose |
| --- | --- |
| `doctor` | Inspect configuration, Steam candidates and SDK readiness |
| `new PATH --template empty\|csgo-room` | Create a VMF without overwriting |
| `files`, `source PATH` | Discover map files and read the complete native VMF |
| `delete-file PATH --expect HASH`, `restore-file TOKEN` | Delete and recover VMF files |
| `import-reference SOURCE OUTPUT.vmf`, `find PATH --query TEXT` | Decompile/import and inspect reference maps |
| `call copy_reference_objects @REQUEST.json` | Transplant identified geometry and linked entities |
| `inspect PATH [--offset N --limit N]` | Read revision, counts and objects |
| `object PATH ID` | Read properties, outputs, side IDs and source text |
| `edit PATH --expect HASH --ops @FILE` | Apply or preview one transaction |
| `validate PATH` | Check IDs, planes, key fields and coordinates |
| `history PATH`, `undo PATH --expect HASH`, `redo PATH --expect HASH` | Inspect and restore transactions |
| `entities --query TEXT [--classname NAME]` | Query local FGD definitions and inherited fields |
| `assets --kind material\|model --query TEXT` | Search loose files and VPK directories |
| `compile PATH --expect HASH --mode bsp\|fast\|full` | Run actual Source compilers in a fresh build directory |
| `editor-open PATH` | Launch a configured Hammer++ editor |
| `editor-state PID`, `call editor_action @REQUEST.json` | Discover and operate real menus, dialogs and viewport tools |
| `editor-capture PID OUTPUT.png --method screen` | Capture visible GPU viewports on Windows |
| `rea-probe hammer` | Run optional local REA PE-resource inspection |
| `schema`, `call TOOL JSON`, `repl`, `mcp` | Discovery, direct calls, interactive shell and MCP |

Every edit batch requires the revision from the last inspection. A stale
hash fails without changing the map. History and checksummed snapshots live
in `.hammer-agent/`. Undo refuses to overwrite external changes. Locks
coordinate bridge writers; they cannot lock Hammer++ itself. Edit a copy and
avoid saving it simultaneously from the editor. After a crash, verify the
PID in `.hammer-agent/write.lock` has stopped before removing that lock.

Translation supports ordinary brushes and entities with texture locking.
For other features, use full `replace_source` transactions or the native
editor controls. Existing unknown blocks are preserved. Structural validation does not establish
convexity, sealing, material existence, entity compatibility or playability.

## Reuse another KZ map

Point your agent at a BSP/VMF and describe the desired section and placement.
The agent imports it, searches object names/materials/bounds, inspects native
source or editor images, and copies the identified objects with new IDs and
targetnames. Embedded assets mount into the local game configuration.
See [reference-map usage](docs/reference-maps.md) and
[feature access and limits](docs/coverage.md).

## Connect an agent

Launch `mapwright --workspace ABSOLUTE_MAP_DIRECTORY mcp` using the absolute
executable path from this virtual environment. The server listens on stdio
only and advertises tool schemas and read/write annotations. It uses the
workspace's `mapwright.local.json`. No model API key is needed.

Examples for Codex, Claude Code and OpenCode are in
[docs/agent-connections.md](docs/agent-connections.md). The
[mapping skill](skills/mapwright/SKILL.md) supplies the
inspect, edit, validate, compile and visual verification workflow.

## Set up Mapwright's Hammer++ backend

Follow [docs/setup.md](docs/setup.md). The local installer uses an existing
owned legacy CS:GO runtime and downloads pinned official editor/compiler and
BSPSource releases, plus the FGD maintainer's complete editor definitions.
It creates an isolated toolchain and `mapwright.local.json` in the workspace.
The official [CS:GO Hammer++ build is frozen at 8864](https://ficool2.github.io/HammerPlusPlus-Website/download.html).
Downloading Hammer++ alone does not supply Valve's engine DLLs. The tested
setup uses existing CS:GO DLLs with the standalone Tools++ compilers.

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
# Requires actual configured Source 1 compilers; missing tools fail:
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
