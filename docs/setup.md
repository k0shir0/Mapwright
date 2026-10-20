# Native tools

Use [automatic agent setup](agent-connections.md) to install the local Python
environment, persistent MCP registration and mapping skills. The agent runs
`setup_agent.py` for the requested client and resolves all real paths itself.
Hammer++ needs compatible legacy CS:GO engine DLLs and `csgo/gameinfo.txt`;
CS2 files cannot replace them. Use Hammer++ CS:GO build 8864.

Setup first reuses the workspace's `mapwright.local.json` (or the legacy
`hammer-agent.local.json`), then the checkout configuration with relative paths
resolved. Otherwise it searches known local installs and Steam libraries for
an owned legacy runtime and invokes the isolated installer. `--native off`
skips this; `--native required` reports a missing runtime as a failure. Without
one, automatic mode still installs offline VMF tools and MCP. It does not
acquire Steam entitlement or substitute another engine branch.

## Isolated installation

Automatic setup invokes this after runtime discovery. For an owned runtime in
another location, the agent can pass `--runtime` to `setup_agent.py`. The
underlying installer also works directly:

```powershell
python scripts/setup_local.py --runtime 'C:/path/to/legacy-csgo'
mapwright doctor
python scripts/verify_backend.py
```

The installer creates workspace-local editor/configuration files and mounts
existing game content. It refuses existing install/config targets. Use
`--help` for alternate locations. Downloads and hashes are pinned in
[setup_local.py](../scripts/setup_local.py).

It includes Hammer++, Tools++ compilers, BSPSource with Java, HammerAddons
editor definitions/assets, and GOKZ fields merged into `csgo_kz.fgd`.
Ordinary CS:GO entities work without HammerAddons' optional postcompiler;
FGD presence alone does not establish engine support.

## Existing installation

Automatic setup reuses an existing working configuration. For custom tools,
[mapwright.example.json](../mapwright.example.json) describes supported fields;
the agent resolves actual paths and creates the workspace configuration without
overwriting an existing file.
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

REA and CLI-Anything are development/research tools. Neither Node nor a
decompiler is required for Mapwright's VMF tools, Source compilers, or MCP.
Hermes setup can install pinned PyYAML into the local environment for its
configuration merge; this is an installer dependency.

Set the editor's GameData to the complete merged FGD when using the installer.
`doctor` checks prerequisites. Confirm native behavior with a fresh compile,
editor state/capture and in-game testing. Builds stay in `.hammer-agent/builds/`;
Mapwright does not install them into the game or publish to Workshop.

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
