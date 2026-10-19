# Native tools

Install Mapwright's extras as in the [README](../README.md#install).
Hammer++ needs compatible legacy CS:GO engine DLLs and `csgo/gameinfo.txt`;
CS2 files cannot replace them. Use Hammer++ CS:GO build 8864.

## Isolated installation

From the repository, with an owned legacy runtime:

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

Copy [mapwright.example.json](../mapwright.example.json) to
`mapwright.local.json` in the map workspace, then set its paths.
Configuration paths resolve against that workspace; the config file must
remain inside it. Missing configuration permits offline authoring.

- `game_dir`: legacy `csgo` directory containing `gameinfo.txt`.
- `hammer`, `vbsp`, `vvis`, `vrad`: compatible executable paths.
- `fgd`: one path or an ordered array; base CS:GO first, GOKZ second.
  Later fields override earlier fields; inspect catalog compatibility warnings.
- `bspsrc_java`: BSPSource's bundled Java executable for BSP imports.
- Optional `rea`: REA's JavaScript CLI entrypoint for `rea-probe`; Node required.
  [REA installation](https://github.com/morluto/rea/blob/main/docs/installation.md).

Set the editor's GameData to the complete merged FGD when using the installer.
`doctor` checks prerequisites. Confirm native behavior with a fresh compile,
editor state/capture and in-game testing. Builds stay in `.hammer-agent/builds/`;
Mapwright does not install them into the game or publish to Workshop.
