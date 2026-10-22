<p align="center">
  <img src="docs/assets/mapwright-banner.png" alt="Mapwright" width="900">
</p>

Local CLI and stdio MCP for KZ mapping in legacy CS:GO Source 1 with Hammer++.
Author VMFs, copy BSP/VMF sections, audit GOKZ entities, measure jumps, compile
maps, and operate the editor all from an any AI agent. CS2 and CSS is unsupported.

## Install

Point your agent at this checkout and ask it to set up local Mapwright MCP.
The [setup skill](skills/mapwright-setup/SKILL.md) checks what is already present,
provisions missing prerequisites, and uses the existing installers to register
MCP, bundle guides and verify the server. From the checkout, the same installer
command works on Windows, Linux and macOS with Python 3.11+:

```sh
python scripts/setup_agent.py --yes
```

Clients: Codex, Claude Code, OpenCode, Google Antigravity, pi and Hermes.
Project scope is the default; Hermes uses `--scope user` for its active profile.
The command detects installed clients; use `--client codex` (or another client
ID) to select just one. Run without `--yes` to preview resolved paths. An agent
selects its current/requested client and checks that preview before applying it.
If Python is missing but `uv` is available, use the same installer through
`uv run --no-project --python 3.13 scripts/setup_agent.py --yes`.
If neither is installed, follow [Python provisioning](docs/setup.md#python-provisioning).
`--help` covers workspace selection and rollback. No shell activation is needed.
See [agent connections](docs/agent-connections.md).

Windows native work also needs compatible legacy CS:GO engine/content.
The [native checklist](docs/setup.md#native-prerequisite-checks) covers missing
tools and unknown install locations. Setup keeps existing settings, Steam games,
branches, launchers and editors intact; new native tools live in the workspace.

For a package-only development install:

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

`compile` / `compile_map` stages matching BSP/NAV files and embeds discovered
material/sky/prop dependencies by default (`source` extra required). Missing
dependencies fail. NAVs are preserved or created empty; presence does not prove
navigation or replay behavior. `mapwright package BUILD_DIR OUTPUT.zip` verifies
build hashes and the archive's BSP/NAV pair. See [delivery and runtime checks](docs/kz-mapping.md).

## Task guides

| Task | Read |
| --- | --- |
| Agent mapping workflow | [Mapping skill](skills/mapwright/SKILL.md) |
| Install/register MCP and skills | [Setup skill](skills/mapwright-setup/SKILL.md) |
| GOKZ entities, geometry, and checks | [KZ contract](docs/kz-mapping.md) |
| Hammer++, compilers, FGD, assets | [Setup](docs/setup.md) |
| Codex, Claude, OpenCode, Antigravity, pi, Hermes | [MCP connections](docs/agent-connections.md) |
| Copy another map's section | [Reference maps](docs/reference-maps.md) |
| Undo, checkpoints, logs, crash recovery | [Recovery](docs/recovery.md) |
| Modify this repository | [AGENTS.md](AGENTS.md) |

## Validate changes

Install development checks with `python -m pip install -e ".[mcp,source,desktop,dev]"`.
For a new machine, use the [setup prerequisites](docs/setup.md#fresh-machine-prerequisites)
and the setup skill; local configuration and environments are regenerated.

With the virtual environment active:

```powershell
$env:MAPWRIGHT_FORCE_INSTALLED = '1'
python -m pip check
python -m compileall -q cli scripts tests
python -m black --check cli scripts tests
python -m unittest discover -s tests -v
python scripts/demo.py
# Configured native compilers required:
python scripts/verify_kz.py
# Configured native Hammer++ / REA required for the real native MCP lane:
$env:MAPWRIGHT_NATIVE_E2E_CONFIG = (Resolve-Path mapwright.local.json).Path
python -m unittest discover -s tests -p test_mcp_e2e.py -v
python scripts/verify_native_session.py --run
```

CI checks and formatter version: [.github/workflows/checks.yml](.github/workflows/checks.yml).
Structural checks and compilation do not prove rendering or playability.
Follow the [verification scope](docs/kz-mapping.md#verification-scope) for map
delivery; geometry and appearance checks do not require a full-course playthrough.
The portable MCP suite exercises every advertised tool, with explicit native
contract fixtures and missing-prerequisite errors. The opt-in native lane uses
the actual configured compiler, REA and private-desktop Hammer++ process,
including guarded save and saved-file checkout with automatic editor reopen.

Native editor operations use an owned private Windows desktop and a staged
VMF. `editor-save` commits verified bytes to the source with a revision check;
`editor-close` cleans up the owned session. The permanent action timeline
supports saved-file recovery. See [setup](docs/setup.md#terminal-controlled-editor-sessions)
and [recovery](docs/recovery.md) for the boundaries.
