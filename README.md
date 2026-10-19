# Mapwright

Local CLI and stdio MCP for KZ mapping in legacy CS:GO Source 1 with Hammer++.
Author VMFs, copy BSP/VMF sections, audit GOKZ entities, measure jumps, compile
maps, operate the editor, and recover changes. CS2/Source 2 is unsupported.

## Install

Python 3.11+. In PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[mcp,source,desktop]"
mapwright --json doctor
```

On Linux/macOS, activate `.venv/bin/activate`; VMF tools and MCP work without
the Windows editor. Extras: `mcp` adds the server, `source` adds FGD/VPK
catalogs, `desktop` adds Windows editor control. Configure native tools using
[setup](docs/setup.md); offline authoring needs no game installation.

## Use

```powershell
mapwright new maps/kz_example.vmf --template kz-room
$map = (mapwright --json inspect maps/kz_example.vmf | ConvertFrom-Json).data
mapwright edit maps/kz_example.vmf --expect $map.revision --ops '@examples/edit.json' --dry-run
mapwright edit maps/kz_example.vmf --expect $map.revision --ops '@examples/edit.json'
mapwright validate maps/kz_example.vmf
mapwright kz-audit maps/kz_example.vmf
mapwright kz-test-plan maps/kz_example.vmf
```

- Put `--workspace PATH`, `--config FILE`, and `--json` before the command.
- Map/output paths are workspace-relative; `@JSON` files are process-CWD-relative.
- `mapwright schema` defines tool arguments; `mapwright COMMAND --help` defines CLI flags.
- Single edits use flat commands/tools such as `add-box` / `map_add_box`;
  `edit` / `edit_map` applies atomic batches. Writes require the inspected revision.
- Results are `{ok:true,data:...}` or `{ok:false,error:...,details?:...}`.
  Completed invalid checks retain `ok:true` and return CLI exit 1; inspect
  `data.valid`, findings, `complete`, and `unsupported_geometry`.

## Task guides

| Task | Read |
| --- | --- |
| Agent mapping workflow | [Mapping skill](skills/mapwright/SKILL.md) |
| GOKZ entities, geometry, and checks | [KZ contract](docs/kz-mapping.md) |
| Hammer++, compilers, FGD, assets | [Setup](docs/setup.md) |
| Codex, Claude Code, OpenCode | [MCP connections](docs/agent-connections.md) |
| Copy another map's section | [Reference maps](docs/reference-maps.md) |
| Undo, checkpoints, logs, crash recovery | [Recovery](docs/recovery.md) |
| Modify this repository | [AGENTS.md](AGENTS.md) |

## Validate changes

With the virtual environment active:

```powershell
$env:CLI_ANYTHING_FORCE_INSTALLED = '1'
python -m unittest discover -s tests -v
python scripts/demo.py
# Configured native compilers required:
python scripts/verify_kz.py
```

CI checks and formatter version: [.github/workflows/checks.yml](.github/workflows/checks.yml).
Structural checks and compilation do not prove rendering or playability.
Inspect editor captures and test the compiled map on the intended KZ server.
