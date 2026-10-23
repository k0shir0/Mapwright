# Native tools

Use [automatic agent setup](agent-connections.md) to install the local Python
environment, persistent MCP registration and mapping skills. The agent runs
`setup_agent.py` for the requested client, checks missing prerequisites and
resolves real paths itself. Keep the existing installers; agent guidance fills
the gaps before and after them.
Hammer++ needs compatible legacy CS:GO engine DLLs and `csgo/gameinfo.txt`;
CS2 files cannot replace them. Use Hammer++ CS:GO build 8864.

Keep map workspaces outside the checkout. From the checkout, pass
`--workspace ../Mapwright-workspace` to `setup_agent.py` and `mapwright`.
Without that option, setup uses the checkout. Keep research notes, corpus data,
captures and investigation reports in that workspace or ignored `.local/`.

## Fresh-machine prerequisites

The agent owns installation and verification using the
[setup skill](../skills/mapwright-setup/SKILL.md). Read this checklist on a new
machine rather than copying a previous machine's configuration or environment.

| Requirement | Provisioning and verification |
| --- | --- |
| Checkout | Reuse the checkout or clone this repository, including `scripts/`, `skills/` and `docs/`. If Git is absent, retrieve the repository's source archive through authorized GitHub access. Git is not needed to run an extracted checkout. |
| Python 3.11+ with `venv` and `pip` | The agent resolves or installs Python as directed by the setup skill. Use 64-bit Python on Windows. Setup creates an isolated `.venv`, repairs system-package inheritance and runs `pip check`. Activation and global packages are unnecessary. |
| Python packages | Setup installs the declared `[mcp,source,desktop]` extras from `pyproject.toml`; pip installs transitive dependencies and build-time setuptools. Hermes additionally installs setup-only PyYAML. |
| Network | First install needs the configured Python package index and, for native tools, the pinned GitHub releases/raw file in `setup_local.py`. Allow their download redirects. Preserve TLS verification; report proxy, certificate or policy failures explicitly. Cached reruns need no new downloads when dependencies are already satisfied. |
| Legacy CS:GO runtime/content | Native authoring requires owned Source 1 `bin` engine DLLs, `csgo/gameinfo.txt`, and stock `csgo/pak01_dir.vpk` plus its VPK chunks. Follow the native prerequisite checks below for discovery or a separate download; do not change an existing Steam game/branch. Steam credentials and entitlement cannot be supplied by the repo. |
| Native tools and assets | Setup downloads hash-verified Hammer++ 8864, Tools++, HammerAddons, GOKZ FGD and BSPSource with bundled Java. It generates editor settings, content mounts and workspace config. No separate Java, Node, REA, Ghidra or Visual Studio installation is needed for ordinary mapping. |
| Windows graphics session | Native editing needs a logged-in Windows desktop session with access to `WinSta0`, usable Direct3D 9 and permission to start owned processes/private desktops. A service, session 0, headless container or WSL terminal does not establish this support. Run native verification in the actual agent session. VMF/MCP tools work on Linux/macOS without an editor. |
| Client and workspace | Use the installed client's supported version and an existing writable map workspace. Setup writes only the selected registration/skills and local artifacts. Client trust/approval stays client-controlled; the agent uses the installed CLI immediately when the current chat cannot reload MCP. |

Python installation, package installation and native-tool downloads are agent
tasks. User action is needed only for unavailable credentials/entitlement,
OS elevation or installation policy, client trust, or access to a suitable
Windows graphics session. Report the exact blocker and working capabilities;
offline setup is not a claim of native readiness.

### Python provisioning

Resolve and verify Python 3.11+ with `python`, `python3`, `py -3`, or an available
`uv` managed interpreter. Reuse a working installation; resolve its absolute
executable rather than assuming PATH or a Windows Store alias works. With `uv`,
run the existing installer from the checkout even when Python is absent:

```sh
uv run --no-project --python 3.13 scripts/setup_agent.py
```

Append the usual `--client`, `--workspace` and other setup flags, inspect the
preview, then repeat with `--yes`. `--no-project` leaves package bootstrapping
to `setup_agent.py`; [uv provisions Python](https://docs.astral.sh/uv/guides/scripts/#using-different-python-versions)
when needed. If neither Python nor uv exists, get the matching official
[standalone uv release archive](https://docs.astral.sh/uv/getting-started/installation/#github-releases)
and its published checksum, extract into a new checkout-local `.local/bootstrap`
directory and invoke its absolute executable. No shell profile, PATH edit,
global Python replacement or downloaded installer script is required. Use
command-scoped `UV_PYTHON_INSTALL_DIR` and `UV_CACHE_DIR` under that directory
when all bootstrap files must stay local; preserve existing proxy/index/TLS
configuration. On Windows, the alternative, if package-managed installation is
appropriate, is 64-bit per-user Python with the installed WinGet client:

```powershell
winget install --id Python.Python.3.13 --exact --source winget --scope user --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
```

Resolve and verify the installed executable; the current shell may retain its
old PATH. See [WinGet installation flags](https://learn.microsoft.com/en-us/windows/package-manager/winget/install).
On Linux/macOS use an available `uv` managed Python or the system package manager
to install Python, `venv` and `pip` (some distributions split these packages).
Verify `python -m venv` and pip. Report concrete policy, elevation or package
infrastructure failures and retain the usable terminal/offline path.

Setup first reuses the workspace's `mapwright.local.json` (or the legacy
`hammer-agent.local.json`), then the checkout configuration with relative paths
resolved. Otherwise it searches known local installs and Steam libraries for
an owned legacy runtime and invokes the isolated installer. `--native off`
skips this; `--native required` reports a missing runtime as a failure. Without
one, automatic mode still installs offline VMF tools and MCP. It does not
acquire Steam entitlement or substitute another engine branch.

Inspect the preview before applying: the installer can repair stale native
configuration, and an explicit `--runtime` requests a new native installation
followed by backed-up configuration replacement. For preservation-only setup,
reuse valid configuration unchanged or choose a fresh workspace instead of
triggering replacement. Keep malformed configuration and unknown local files
intact. A separate checkout also avoids reusing conflicting checkout config,
skills or `.venv`. Partial native installs are retained; retries choose a fresh
editor directory and reuse verified downloads. Rollback restores managed
registration, skills and configuration; it retains downloaded tools and maps.

## Native prerequisite checks

Use this checklist before accepting an automatic `offline` result. No SDK,
Hammer, Steam, Java or Node is needed for portable VMF/MCP setup. Native work
requires Windows and compatible legacy CS:GO engine/content; a separate SDK
installation is unnecessary if those files already exist, because
`setup_local.py` supplies Hammer++ 8864, Tools++ and the editor definitions.

| Starting state | Agent action using existing setup infrastructure |
| --- | --- |
| Valid workspace config and tools | Run `doctor`, reuse settings unchanged, then verify actual compilation/rendering. |
| Hammer/SDK exists at an unknown location | Discover read-only as below. Verify the files rather than guessing a path or declaring them absent. |
| Runtime/content exists, no Hammer or SDK | Preview `setup_agent.py --client CLIENT --workspace WORKSPACE --runtime RUNTIME`, then apply with `--yes`. It invokes `setup_local.py` to install isolated native tools. |
| Hammer exists, runtime/content is missing | Inspect its config/mounts and source runtime first. Hammer alone, an empty generated game directory or a server-only package does not prove complete client content. Obtain only the missing prerequisite separately. |
| Neither runtime/SDK nor Hammer exists | Provision an isolated entitled legacy runtime below, verify it, then use `--runtime`. Do not stop at offline setup when native setup was requested and provisioning remains possible. |
| Linux/macOS/WSL, missing entitlement, or unavailable Windows graphics session | Complete `--native off` in a usable workspace; report the precise native blocker and resume point. Do not claim full native readiness. |

**Locate existing tools.** Read workspace and checkout native config, installed
skill `installation.json`, and `.local/csgo-editor*/installation.json` first.
For custom Hammer installs, read `hammerplusplus_gameconfig.txt` or
`GameConfig.txt` to find `GameDir`, compiler paths and content mounts. Do not
change these files or launch an existing editor to initialize them.

The script's automatic search covers conventional Steam/local locations, not
every disk. If it misses an install, inspect the Windows Steam registry values
`HKCU\Software\Valve\Steam` (`SteamPath`) and
`HKLM\SOFTWARE\WOW6432Node\Valve\Steam` (`InstallPath`) read-only, then each
discovered `steamapps/libraryfolders.vdf` and app manifests' `installdir`.
Check both legacy CS:GO and CS:GO SDK locations. Read known shortcuts/process
executable paths if needed; never edit launchers. Search the resulting install
roots/user-supplied directories for `hammerplusplus.exe`, `hammer.exe` and
`gameinfo.txt`; avoid an unbounded whole-drive scan. Ask for a location only
when this evidence is exhausted. Pass a verified absolute `--runtime` when
automatic discovery is insufficient.

**Verify a runtime.** Its `bin` directory must contain `tier0.dll`, `vstdlib.dll`,
`filesystem_stdio.dll`, `materialsystem.dll` and `shaderapidx9.dll`; also require
`csgo/gameinfo.txt`, `csgo/pak01_dir.vpk` and the referenced VPK chunks. Check
that it is the Windows legacy Source 1 branch, with 32-bit engine DLLs for
Hammer++ 8864. Validate catalog/compile use, not just filename presence. CS2,
Source SDK 2013 and other Hammer++ branches are not substitutes. Renderer
capture additionally requires the exact [supported DLL profile](#terminal-controlled-editor-sessions).

**Obtain missing runtime/SDK files without modifying installed games.** On
Windows, use a fresh workspace-local SteamCMD directory and a separate fresh
`.local/csgo-sdk` download destination. Obtain the Windows archive from the
[official SteamCMD guide](https://developer.valvesoftware.com/wiki/SteamCMD)
and extract there, not into the user's Steam directory. Run it from its own
directory so its bootstrap/cache files stay there. Before login, set
`force_install_dir` to the absolute new download destination. The interactive
SteamCMD sequence for an account entitled to the legacy client is:

```text
force_install_dir "ABSOLUTE_NEW_RUNTIME_DIRECTORY"
login STEAM_ACCOUNT_NAME
app_update 730 -beta csgo_legacy validate
quit
```

These are SteamCMD console commands, not a new setup script. Have the user
complete password/Steam Guard prompts in the authentication flow; never put
secrets in commands, config or receipts. Check current branch availability and
account access before the large download. Run `validate` only against this new
owned destination: it overwrites files. Never change the user's Steam beta
selection, validate/update their installed game, or install a substitute game.
Do not terminate games or log out an active Steam session to make login work.
If Steam reports no subscription, a missing branch or authentication failure,
retain the evidence and report that exact prerequisite rather than promising
the repo can supply it.

If additional SDK files are actually needed, check access to the
[CS:GO Authoring Tools / SDK](https://developer.valvesoftware.com/wiki/Counter-Strike:_Global_Offensive/Authoring_Tools)
(app 745); availability depends on the account. Download into its own fresh
destination with the same SteamCMD approach (`app_update 745 validate`). Inspect
Hammer++'s bundled README, but do not follow its in-place copy/SDK-launch steps
against the user's install. The installer generates its own isolated Hammer
gameconfig instead. SDK files alone do not establish stock content or
renderer compatibility. Recheck the runtime checklist and resume the existing
installer with the verified runtime root; do not concatenate game/SDK folders
or repair their original settings in place.

Before applying native setup, inspect the destination `.local` directories,
`assets` and `mapwright.local.json` for conflicts. Use a fresh workspace when
they contain unknown files. The native installer copies runtime files and
writes mounts, Hammer gameconfig and INI settings only in its isolated editor
copy; original runtime/content remain read-only. Keep partial downloads and
installs; rerun using the previewed fresh destination rather than deleting
unknown files. After setup, inspect the receipt and `doctor`, then run the
skill's actual compile/render checks. Paths and successful downloads alone
are not native verification.

## Isolated installation

Automatic setup invokes this after runtime discovery. For an owned runtime in
another location, the agent can pass `--runtime` to `setup_agent.py`. The
underlying installer also works directly:

```powershell
python scripts/setup_local.py --runtime $runtime
mapwright doctor
python scripts/verify_backend.py
```

Here `$runtime` is the absolute owned runtime discovered by the agent.
The installer creates workspace-local editor/configuration files and mounts
existing game content. It refuses existing install/config targets. Use
`--help` for alternate locations. Downloads and hashes are pinned in
[setup_local.py](../scripts/setup_local.py).

Prefer `setup_agent.py` for retries. Configuration repair must be explicitly
requested; preservation-only setup uses a fresh workspace as above. Direct
`setup_local.py` calls require an unused `--install-dir` and `--output-config`.

It includes Hammer++, Tools++ compilers, BSPSource with Java, HammerAddons
editor definitions/assets, and GOKZ fields merged into `csgo_kz.fgd`.
Ordinary CS:GO entities work without HammerAddons' optional postcompiler;
FGD presence alone does not establish engine support.

## Existing installation

Automatic setup reuses an existing working configuration. For custom tools,
[mapwright.example.json](../mapwright.example.json) describes supported fields;
the agent resolves actual paths and preserves a valid existing workspace
configuration. Preserve stale settings unless their repair was requested;
otherwise use a fresh workspace as above.
Configuration paths resolve against that workspace; the config file must
remain inside it. Missing configuration permits offline authoring.

- `game_dir`: legacy `csgo` directory containing `gameinfo.txt`.
- `hammer`, `vbsp`, `vvis`, `vrad`: compatible executable paths.
- `fgd`: one path or an ordered array; base CS:GO first, GOKZ second.
  Later fields override earlier fields; inspect catalog compatibility warnings.
- `bspsrc_java`: BSPSource's bundled Java executable for BSP imports.
- Optional `rea`: REA's runnable `scripts/rea.mjs` entrypoint for `rea-probe`;
  Node required. Current REA uses `--format json`; Mapwright resolves an older
  configured `dist/cli.js` to its sibling wrapper when available.
  [REA installation](https://github.com/morluto/rea/blob/main/docs/installation.md).

REA is an optional development/research tool. Neither Node nor a
decompiler is required for Mapwright's VMF tools, Source compilers, or MCP.
Hermes setup can install pinned PyYAML into the local environment for its
configuration merge; this is an installer dependency.

### Optional REA research lane

`rea-probe` and the opt-in `test_mcp_e2e.py` native research scenario additionally
need REA. The agent provisions this only when that lane is requested: install
a Node version accepted by the pinned REA package's `engines.node`, resolve
`rea-agents@6.7.0` into `.local/rea-runtime` with `npm install --package-lock-only
--ignore-scripts --prefix .local/rea-runtime rea-agents@6.7.0`, run
`npm audit --prefix .local/rea-runtime`, review the result, then install with
`npm ci --prefix .local/rea-runtime`. Configure `rea` to the resolved
`.local/rea-runtime/node_modules/rea-agents/scripts/rea.mjs` and verify
`rea-probe hammer`. Ghidra is unnecessary for this PE resource probe.
Use the linked upstream REA installation guide for additional reverse
engineering features; these are separate from mapping setup.

Set the editor's GameData to the complete merged FGD when using the installer.
`doctor` checks prerequisites. Confirm native behavior with a fresh compile
and editor state/capture; use the [requested verification scope](kz-mapping.md#verification-scope)
for game checks. Builds stay in `.hammer-agent/builds/`;
Mapwright does not install them into the game or publish to Workshop.

## Runtime test troubleshooting

Read the existing launcher/shortcut and game configuration before requesting
server details already present locally. Identify the actual legacy client,
server executable, `-game` directory, search paths, tick rate and installed
SourceMod/GOKZ plugins. A tool schema from another checkout or an editor mount
does not describe the running game. Keep test configs, databases, replay fixtures
and harnesses in an isolated workspace; retain existing server versions for
acceptance evidence.

For an isolated legacy overlay, account for resources resolved through both
`GAME` and `MOD`. One observed overlay required separate search-path entries
`Game "<base>/csgo"` and `MOD "<base>/csgo"`; a `GAME` fallback alone failed
during player entry. Verify a known working control map before attributing such
a crash to the candidate. SourceMod raw file access may also require maps/NAVs
inside the overlay itself. A client version-string edit does not prove binary
compatibility or fix a crash.

If a client reports `Failed to connect with local Steam Client process`, check
whether Steam is signed in and whether the same legacy executable launches
normally. Use the user's existing Steam session; credentials remain with the
user. Confirm the launched executable: an app launch request can select CS2
despite an intended legacy test. For connection timeouts, inspect the actual
bound address/port and test the configured LAN endpoint before changing network
settings.

Bound test sessions, retain console/capture evidence, and close their owned
processes when the requested checks finish. Preserve the user's Steam/editor
sessions. Keep failed probes and inconclusive results in the
[problem log](recovery.md#problem-log), separate from successful acceptance.

## Terminal-controlled editor sessions

`editor-open` / `open_editor` starts the real Hammer++ process on an owned
private Windows desktop and opens a staged VMF copy. The user's desktop is not
switched and no user keyboard/mouse input is needed. Inspect the returned
session, enabled controls and native action results. Known startup dialogs are
handled by the broker; unresolved dialogs are reported for diagnosis.

The broker waits on Windows events while idle. Its owned editor job uses an
idle CPU hard cap of approximately 5% of one logical CPU; bounded commands lift
the cap until they finish. Each session copies mutable settings and shares
immutable runtime files by hardlink when possible. No REA, Node, decompiler or
continuous screen-capture loop runs during ordinary authoring.
Sessions created by an MCP host also wait on that host's process handle and
close if it crashes. One-shot CLI sessions persist until explicitly closed.

`editor-capture --method viewport` requires actual Hammer render-thread RGB
readback; `--method window` uses PrintWindow for UI chrome. The default `auto`
tries viewport readback and reports any UI-only fallback as
`viewport_capture_error`. GPU capture checks the loaded x86 material-system and
shader DLL hashes against an observed ABI profile before making interface
calls. Unknown profiles are refused; do not guess offsets for other SDK builds.

The verified profile is Steam `csgo_legacy` build `12426195`, patch `1.38.8.1`,
Source revision `8413246` (October 12, 2023). Exact renderer hashes live in
`render_capture.PROFILE`; `doctor` reports observed/expected hashes and
`viewport_profile_ready`. Hammer++ 8864 alone does not pin the engine DLLs.
`--native required` checks this profile as well as editor, compiler, FGD and
decompiler paths. It still needs a real render/compile verification in the
current Windows session. A new engine profile requires a separately verified
ABI before adding support; retain the working VMF/compiler path meanwhile.
Uniform actual pixels are retained with a warning, since an empty/off-map
camera can produce an empty view. Inspect the image before claiming geometry.
Capture skips cleared helper panes, with a limit of eight owned frame events
and eight megapixels per image. Generated room templates include a saved camera.

The desktop extra installs Python Frida for this bounded capture operation.
It runs in a disposable worker, detaches, and exits before the tool returns;
the broker does not retain the instrumentation controller. No Vulkan wrapper,
Node, REA or foreground desktop access is required for capture.

`editor-save` / `save_editor` saves that staged document, verifies its bytes,
and commits them to the source VMF against the inspected source revision.
`editor-close` / `close_editor` closes only the owned session and its helpers,
retaining staged files and receipts. Close sessions when the task no longer
needs them. These tools do not attach to or close a user's existing editor.

Requests are recorded in the permanent action timeline. Native actions capture
staged documents before/after supported edits; inspect `checkpointed` and
`document_reversible`. Saved-file timeline checkout excludes editor memory and
undo stacks. A ready map title or successful dispatch does not prove viewport
rendering or playability. See [recovery](recovery.md) for saved-file recovery.
