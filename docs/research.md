# Upstream evidence, 2026-10-18

The initial discovery below predates the completed local installation.
[verification.md](verification.md) records current editor/compiler results.

## CLI-Anything

Read and locally checked out the
[HARNESS.md workflow](https://github.com/HKUDS/CLI-Anything/blob/34f519533bc175d2fe287ab8316b0dd99bb9cc43/cli-anything-plugin/HARNESS.md)
at commit `34f519533bc175d2fe287ab8316b0dd99bb9cc43`.
Applied backend/data-model inspection, structured command discovery, native
intermediate files, transactional state, a test plan before test implementation,
installed CLI tests, actual MCP tests and an agent-consumable mapping skill.
The generation/plugin workflow is guidance for agents, not a Hammer++ adapter.

Adaptations: one explicit `repl` command rather than entering interactive mode
with no arguments; argparse and plain JSON rather than copying the upstream
terminal skin; official MCP SDK for transport. No upstream source was copied
into the shipping Python package. Publishing to PyPI is outside this private
repository task. The missing backend lane is a reported failure, not skipped
and treated as a successful real-software test.

## Hammer++

The [official download page](https://ficool2.github.io/HammerPlusPlus-Website/download.html)
identifies the CS:GO branch as unsupported and frozen on build 8864. Downloaded
its official `hammerplusplus_csgo_build8864.zip` into ignored `.local/` storage.
Archive SHA-256:

```text
b57639a591730e950d0b33c1804b6098e79ebcef8e4cb36e9d489a094c9789cc
```

The archive README requires a separately installed and previously launched
CS:GO SDK. It directs installation into the CS:GO `bin` folder and says that
Hammer++ keeps its own GameConfig.txt under `bin/hammerplusplus`.
This is an archive/prerequisite observation, not a successful editor launch.

Local Steam discovery found CS:GO content but no `hammerplusplus.exe`,
`vbsp.exe`, `vvis.exe`, `vrad.exe` or CS:GO FGD in that install. The user
confirmed no legacy SDK or Hammer++ installation elsewhere. No game files
were changed. The archive alone is insufficient to run the editor.

## REA

Installed `rea-agents@6.7.0` locally under `.local/rea-runtime` after a lockfile
audit reported zero vulnerabilities. Install scripts were disabled. Node
24.14.0 satisfies its published runtime requirement. Did not run REA setup or
modify any agent's configuration.

Executed `rea inspect-pe-resources` against the official `hammerplusplus.exe`.
REA returned an x86 PE32 identity with SHA-256:

```text
6d4c3f82a36c00bd7767ab8afbb41dca1f267d6dd94919094c6ae1672c430912
```

The PE-resource parser reported 25 examined entries and 11 resources with
complete resource-inventory coverage. This does not establish complete native
analysis or an editor RPC API. Detailed local Evidence is ignored by Git.

Executed `rea capabilities` and `rea doctor --provider ghidra --json`.
Ghidra readiness failed with `missing_analysis_engine` because
`GHIDRA_INSTALL_DIR` is unset. No native decompilation was performed.
Upstream [process capture documentation](https://github.com/morluto/rea/blob/main/docs/process-capture.md)
states native Windows capture is unsupported. Resource inspection uses a
separate static parser and does not need that capture adapter or Ghidra.

The implementation uses the documented
[VMF data model](https://developer.valvesoftware.com/wiki/VMF_(Valve_Map_Format))
as its authoring boundary. This work did not discover or verify a live
Hammer++ editing protocol. Future live integration needs exact-build evidence
and actual editor tests; no offsets or unsupported command IDs are assumed.
The follow-up uses observed native Win32 menus, controls and input with
PID/executable checks, without undocumented binary offsets.

## Bridge integration checks

The bridge itself successfully invoked the local REA CLI against the archive
executable and returned its canonical Evidence. Its asset catalog queried the
installed CS:GO VPK directories and located `dev/dev_measuregeneric01` and
`dev/dev_measuregeneric01b` in `pak01_dir.vpk`; no assets were extracted.
The generated test-room material therefore exists in the inspected local
content. This is an inventory check, not a texture-rendering test.

## Follow-up installation and reference maps

Verified [standalone Tools++ installation and CS:GO support](https://ficool2.github.io/HammerPlusPlus-Website/tools.html).
The local pinned Windows archive is dated 2026-10-03. Actual VBSP++/VVIS++/VRAD++
compilation, including CS:GO HDR lighting, succeeded. These binaries are not
redistributed in Git.

Installed [BSPSource 1.4.8](https://github.com/ata4/bspsrc/releases/tag/v1.4.8)
with bundled Java, exercised its actual CLI and decompiled an installed KZ BSP.
This reconstructs authoring data without perfectly recovering the original VMF.
The importer retains provenance and safely extracts embedded assets.

The first generated srctools engine FGD lacked editor model/icon helpers.
Replaced it with the maintainer's complete published
[HammerAddons 2.6.0 FGD and editor assets](https://github.com/TeamSpen210/HammerAddons/releases/tag/v2.6.0).
Actual Hammer++ capture then showed the CS:GO team spawn models. The installer
does not install or run HammerAddons' optional postcompiler.

Consulted [GOKZ's Mapping API](https://github.com/KZGlobalTeam/gokz/wiki/Mapping-API)
to preserve reserved trigger/course names and teleport destinations when copying.
Regressions cover these transfer semantics; an actual GOKZ server playtest
has not been performed.
