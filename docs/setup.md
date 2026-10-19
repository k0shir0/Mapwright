# Set up Mapwright for legacy CS:GO

The bridge can edit native VMF files without Steam, Hammer++ or a compiler.
Editor and compile operations require actual compatible Source 1 tools.

## Isolated local installation (tested)

Install the Python package with `.[mcp,source,desktop]`, then run:

```powershell
python scripts/setup_local.py --runtime 'C:/Program Files (x86)/Steam/steamapps/common/Counter-Strike Global Offensive'
mapwright doctor
python scripts/verify_backend.py
```

The runtime must contain compatible Source 1 engine DLLs and legacy game
content. `--content` can point at a separate `csgo` directory. The installer
copies engine DLLs into `.local/csgo-editor`, downloads checksum-pinned
Hammer++ 8864, standalone Tools++, BSPSource 1.4.8 with bundled Java, and the
CS:GO FGD/editor assets from HammerAddons 2.6.0. No global Java is needed.
It also fetches the checksum-pinned official GOKZ Version 1 FGD and generates
`csgo_kz.fgd` for the editor by adding only KZ fields to the complete CS:GO
definitions. This preserves editor models/helpers and avoids missing stock
base-class names in HammerAddons. The catalog accepts an ordered `fgd` array,
combines base/addon fields, and reports missing addon-base compatibility notes.
Upstream URLs and hashes are in the script and installation receipt.
The Tools++ release URL is mutable: a checksum mismatch intentionally stops
installation until the updated upstream package is reviewed.

The installer creates a workspace-local gameinfo that mounts owned game
content, project assets and editor helpers. It writes
`bin/hammerplusplus/hammerplusplus_gameconfig.txt` with SDKVersion 5 and the
configured compiler paths. It disables the frozen build's updater prompt,
Discord presence and the file-dialog hook documented as problematic on Windows.
Existing installations and output config files are refused; select a fresh
`--install-dir` and `--output-config` to verify another installation.

HammerAddons supplies additional entities requiring its optional postcompiler.
This installation uses its FGD/assets only; use the ordinary CS:GO entities
unless you separately configure that postcompiler. Source-aware catalogs can
inspect the configured FGD; existence there is not proof of game support.

The official SDK is another option:

1. In Steam, install the legacy CS:GO game/tool content and CS:GO SDK if your
   account has access. Launch the SDK at least once. Availability depends on
   account access; this bridge cannot provide the proprietary SDK.
2. Download [Hammer++ CS:GO build 8864 from the official page](https://ficool2.github.io/HammerPlusPlus-Website/download.html).
   Follow the archive's README: copy its `bin` contents into the SDK/game's
   `bin` directory. This version is unsupported upstream and frozen.
3. Launch `hammerplusplus.exe` normally and configure the CS:GO game. Its
   config is `hammerplusplus/hammerplusplus_gameconfig.txt`, separate from
   stock Hammer's `GameConfig.txt`.
4. Copy `mapwright.example.json` to `mapwright.local.json` in the map
   workspace and set paths to the game directory, editor, compilers and FGD.
   Paths may be absolute or relative to the workspace. Keep the local file
   out of Git. Run `mapwright --workspace YOUR_WORKSPACE doctor`.

Do not substitute CS2 executables. CS2's Source 2 VMAP pipeline cannot compile
the Source 1 VMF files generated here. The presence of a folder named
`Counter-Strike Global Offensive` does not establish a legacy SDK installation.

`doctor` checks configured files and selected engine DLLs. This is a
prerequisite check, not a guarantee the editor can start. The opt-in installer
downloads into this workspace; ordinary CLI/MCP calls do not install tools.
Steam files and antivirus settings are not changed. Use `editor-open`,
`editor-state`, and `editor-capture PID OUTPUT.png --method screen`, then
inspect the actual map rendering. For file dialogs, set the inspected filename
Edit control and press `{ENTER}` or invoke the actual Save/Open button.

The local machine's anonymous SDK app 745 installation attempt returned
`Missing configuration`. The tested isolated runtime/Tools++ installation
resolved editor and compilation prerequisites without claiming that the
proprietary SDK itself was installed.

## Optional REA

REA is for investigation, not routine map creation. Its CLI can inspect PE
resources without executing the binary or requiring Ghidra. Use a compatible
Node runtime and follow [REA installation](https://github.com/morluto/rea/blob/main/docs/installation.md).
Audit npm dependencies before installing. A local package avoids changing
global agent registrations:

```powershell
New-Item -ItemType Directory -Path .local/rea-runtime -Force
npm install --prefix .local/rea-runtime --package-lock-only --ignore-scripts rea-agents@6.7.0
npm audit --prefix .local/rea-runtime --omit=dev
npm ci --prefix .local/rea-runtime --ignore-scripts
.local/rea-runtime/node_modules/.bin/rea.cmd inspect-pe-resources PATH_TO_HAMMER_EXE --json
```

For `rea-probe`, set the optional `rea` config path to
`.local/rea-runtime/node_modules/rea-agents/dist/cli.js`, then run
`mapwright rea-probe hammer`. The bridge invokes Node directly and retains
REA's evidence object. Decompilation needs a configured analysis engine:
`rea doctor --provider ghidra --json` reports readiness. Native Windows
process capture is unsupported by REA 6.7.0. Provider installation and agent
registration are separate setup choices; the bridge does neither.
