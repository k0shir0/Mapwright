# Actual local verification, 2026-10-18

This machine now has an isolated Hammer++ CS:GO installation, standalone
Tools++ compilers, BSPSource 1.4.8 with bundled Java, and complete HammerAddons
2.6.0 CS:GO FGD/editor assets. `scripts/setup_local.py` was run successfully
in a fresh local directory using owned installed CS:GO runtime files.
The earlier anonymous SDK app 745 download failed with `Missing configuration`;
the SDK itself is not claimed as installed. Steam's files were not changed.

## Real MCP reference workflow

`scripts/verify_reference.py` completed these actual stdio MCP calls:
import_reference_map, search_reference_map, create_map,
copy_reference_objects, inspect_map, compile_map.

Source: installed `kz_za_tileblock.bsp`, SHA-256
`7938af523b2b26324fb5ffc51c4e6e73c71bd81da6f7bb5eb7cf757c830f0088`.
BSPSource reconstructed it into a native VMF. Two world solids, source IDs
2 and 9, formed the inspected tile section. Translation `[-84,-460,-208]`
placed their combined 40-by-40-by-40 shape on the destination room's floor.
Copied IDs were 47 and 54. The destination contained 8 solids and 3 entities.
Embedded assets were extracted and mounted locally.

VBSP++, VVIS++ and VRAD++ each exited zero and produced a fresh version-21
BSP without a leak. HDR lighting and HDR faces lumps were populated. The
workflow was repeated after independent-review fixes with the complete
installed FGD/configuration.

Local final receipt:
`.local/reference-verification/c12018aabb4f4f0b8e488b1cc3f1cb29/verification.json`.
Its fresh build and logs are under
`.hammer-agent/builds/402d007e253749b388bb072374c299ae/`.
These are ignored machine-local evidence, not artifacts in a fresh clone.

## Real editor

Opened the generated VMF in Hammer++ 8864. Discovered actual menus and control
handles, selected copied brush 47 via the real brush-ID dialog, and centered
the view. Inspected native visible-window captures showing the textured tile
section inside the authored room. Initial black/loading views were not counted
as success. A capture with the complete FGD also shows actual team spawn models.
The earlier editor run displayed working 2D grids and selections.

Hammer++ Map Information independently reported: 8 solids, 3 point entities,
0 solid entities, 48 faces, 3 unique textures. Used the actual File Open and
Save As dialogs. The separately saved VMF was read back and structurally
validated with the expected 8 solids and 3 entities, then reopened in the
complete installation.

Local screenshots and state:
`.local/research/copied-kz-selected.png`,
`.local/research/copied-kz-final.png`,
`.local/research/copied-map-info.json`,
`.local/research/copied-room-editor-saved.vmf`.

The isolated setup configuration also passed `scripts/verify_backend.py`.
Mounted asset catalog lookup found the real `dev/dev_measuregeneric01` and
`dev/dev_measuregeneric01b` materials in the owned CS:GO VPK. Complete FGD
catalog lookup succeeded. A stale editor PID returned structured JSON failure.

In-game movement, GOKZ plugin behavior, and every individual Hammer++ command
have not been exhaustively tested. Compilation and visible editor evidence
establish the tested authoring workflow, not universal gameplay correctness.

## Reproduce

Install and configure tools as in [setup.md](setup.md). Import/search your
source first to choose actual solid IDs and a placement. Then run:

```powershell
python scripts/verify_reference.py C:/maps/reference.bsp --solid 2 --solid 9 --delta -84 -460 -208
```

The script fails on missing tools or failed actual MCP/compiler operations.
It retains the generated VMF, build logs and verification receipt. Editor
rendering still requires opening and inspecting its actual window.

## KZ research follow-up

The KZ implementation was verified with 69 passing tests on Windows/Python
3.11.9 in 42.439 seconds, with the installed Mapwright executable required.
This includes real MCP resource/template/prompt discovery, progress callbacks,
flat edit tools, structured invalid-check results, multi-FGD integration,
geometry limits, file/folder checkpoints, revision/checksum refusal and
interrupted restore/resume. Syntax compilation, Black formatting and packaged
skill validation also completed. CI additions have not been published/run yet.

`scripts/verify_kz.py` ran actual MCP calls to create `kz-room`, add two blocks,
an anti-bhop volume, destination and delayed multi-bhop trigger, audit them,
measure a 240u aligned gap and compile with VBSP++/VVIS++/VRAD++.
All compiler stages exited 0 and produced a fresh version-21 BSP. Direct
entity-lump inspection confirmed the KZ version, timer/course names,
anti-bhop, teleport destination and delay values survived compilation.

Local evidence:

- `.local/research/kz-regressions-final.txt`
- `.local/kz-verification/aeb8711fd1ae49878b0c81f7eb3c1503/verification.json`
- `.hammer-agent/builds/0a37028fcd83435a8624ee2197eab199/receipt.json`
- `.local/research/kz-bsp-entities.json`
- `.local/research/kz-fgd-verification.json`

The official pinned GOKZ FGD was installed locally. The real combined catalog
retains CS:GO fields and exposes all eight KZ trigger fields plus the world API
version. Hammer uses a complete `csgo_kz.fgd` preserving the original editor
helpers; this resolves absent stock base names in HammerAddons. Configuration
was checkpointed before modification.

Hammer loaded the new map with the merged FGD, confirmed by its native window
title/state. The user requested keeping it behind their fullscreen application.
A passive PrintWindow capture showed editor UI with black GPU viewports and
does not establish rendering. The earlier first-load 2D viewport concern and
visual verification of this new KZ map remain pending a foreground check.
The task-owned editor and stalled test/formatter helpers were closed. In-game
GOKZ movement behavior remains unverified.

Reproduce the KZ native compile lane with `python scripts/verify_kz.py`.
