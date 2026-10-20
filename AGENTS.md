# Mapwright

Target: KZ-first legacy CS:GO Source 1 VMF/VBSP and Hammer++.

## Context

- Local MCP installation, client registration, or setup: read the
  [setup skill](skills/mapwright-setup/SKILL.md) and run its automatic workflow.
- Map authoring: [mapping skill](skills/mapwright/SKILL.md).
- KZ behavior/checks: [KZ contract](docs/kz-mapping.md).
- Backend installation/config: [setup](docs/setup.md).
- References and recovery: [copying](docs/reference-maps.md), [recovery](docs/recovery.md).
- Tool fields: `mapwright schema`; CLI flags: `mapwright COMMAND --help`.

## Code

`cli_anything/hammerplusplus/`: `api.py` owns schemas/dispatch; `cli.py` and
`mcp_server.py` are transports. `vmf.py` parses/edits source spans; `project.py`
owns workspace boundaries, revisions and map history. `kz.py` analyzes maps;
`workspace.py` handles logs/checkpoints. `backend.py`, `catalog.py`,
`reference.py`, `desktop.py`, and `windows.py` integrate native tools/data.
`timeline.py` owns permanent action history; `native_session.py` owns private
desktops/jobs. `render_capture.py` runs bounded, DLL-profile-checked GPU readback
in a disposable worker. Verify new native ABI profiles before enabling calls.

Preserve untouched VMF bytes, duplicate keys and unknown blocks. Keep whole-source
replacement explicit and revision-checked. Update both transports when changing
the shared contract. Preserve exact GOKZ API names; report unsupported geometry.
Coordinate editor saves with file transactions; the bridge cannot lock Hammer.

Run the [README checks](README.md#validate-changes) and the relevant
[CI commands](.github/workflows/checks.yml). Native build, rendering and gameplay
claims need corresponding evidence. Keep binaries, assets, local configuration,
logs and captures out of Git.
