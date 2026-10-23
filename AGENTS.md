# Mapwright

Target: KZ-first legacy CS:GO Source 1 VMF/VBSP and Hammer++.

## Context

- Local MCP installation, client registration, or setup: read the
  [setup skill](skills/mapwright-setup/SKILL.md). The agent checks/provisions
  missing prerequisites, then uses the existing setup scripts; do not build
  another installer. Follow the [native prerequisite checks](docs/setup.md#native-prerequisite-checks)
  when Hammer/SDK locations are unknown or either is absent.
  On a fresh or moved checkout, satisfy the [machine prerequisites](docs/setup.md#fresh-machine-prerequisites),
  regenerate local paths, and verify setup in an isolated Python environment.
  For native work, complete the skill's compile/render checks before claiming readiness.
- Map authoring: [mapping skill](skills/mapwright/SKILL.md).
- KZ behavior/checks: [KZ contract](docs/kz-mapping.md).
- Backend installation/config: [setup](docs/setup.md).
- References and recovery: [copying](docs/reference-maps.md), [recovery](docs/recovery.md).
- Tool fields: `mapwright schema --index`, then `schema --tool TOOL`; CLI flags: `mapwright COMMAND --help`.

Setup preserves existing settings, Steam games/branches, launchers and editor
installations. Discover them read-only; install missing tools in a fresh
workspace-local directory. Inspect the setup preview before applying it. If an
existing configuration would be replaced, reuse it unchanged or select a fresh
workspace/distinct server name. Do not treat a backup as permission to overwrite
settings or run Steam validation against an existing game. See the setup skill
for the allowed file scope and actual-readiness checks.

## Code

`cli/hammerplusplus/`: `api.py` owns schemas/dispatch; `cli.py` and
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

## Optional REA research lane

`rea-probe` and the opt-in `test_mcp_e2e.py` native research scenario additionally
need REA. The agent provisions this only when that lane is requested: install
a Node version accepted by the pinned REA package's `engines.node`, resolve
`rea-agents@6.7.0` into `.local/rea-runtime` with `npm install --package-lock-only
--ignore-scripts --prefix .local/rea-runtime rea-agents@6.7.0`, run
`npm audit --prefix .local/rea-runtime`, review the result, then install with
`npm ci --prefix .local/rea-runtime`. Configure `rea` to the resolved
`.local/rea-runtime/node_modules/rea-agents/scripts/rea.mjs` and verify
`rea-probe hammer`. Ghidra is unnecessary for this PE resource probe.
Use the [upstream REA installation guide](https://github.com/morluto/rea/blob/main/docs/installation.md) for additional reverse
engineering features; these are separate from mapping setup.
