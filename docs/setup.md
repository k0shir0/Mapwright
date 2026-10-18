# Legacy CS:GO setup

The bridge can edit native VMF files without Steam, Hammer++ or a compiler.
Editor and compile operations require actual compatible Source 1 tools.

1. In Steam, install the legacy CS:GO game/tool content and CS:GO SDK if your
   account has access. Launch the SDK at least once. Availability depends on
   account access; this bridge cannot provide the proprietary SDK.
2. Download [Hammer++ CS:GO build 8864 from the official page](https://ficool2.github.io/HammerPlusPlus-Website/download.html).
   Follow the archive's README: copy its `bin` contents into the SDK/game's
   `bin` directory. This version is unsupported upstream and frozen.
3. Launch `hammerplusplus.exe` normally and configure the CS:GO game. Its
   GameConfig.txt lives in the `hammerplusplus` subdirectory, separate from
   stock Hammer's config.
4. Copy `hammer-agent.example.json` to `hammer-agent.local.json` in the map
   workspace and set paths to the game directory, editor, compilers and FGD.
   Paths may be absolute or relative to the workspace. Keep the local file
   out of Git. Run `hammer-agent --workspace YOUR_WORKSPACE doctor`.

Do not substitute CS2 executables. CS2's Source 2 VMAP pipeline cannot compile
the Source 1 VMF files generated here. The presence of a folder named
`Counter-Strike Global Offensive` does not establish a legacy SDK installation.

`doctor` checks configured files and selected engine DLLs. This is a
prerequisite check, not a guarantee the editor can start. No backend tools
are automatically downloaded, installed into Steam or added to antivirus
exceptions. Use `editor-open`, inspect the actual window and then use
`editor-capture` with that editor PID for visual evidence.

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
`hammer-agent rea-probe hammer`. The bridge invokes Node directly and retains
REA's evidence object. Decompilation needs a configured analysis engine:
`rea doctor --provider ghidra --json` reports readiness. Native Windows
process capture is unsupported by REA 6.7.0. Provider installation and agent
registration are separate setup choices; the bridge does neither.
