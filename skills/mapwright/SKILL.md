---
name: mapwright
description: Author/inspect legacy CS:GO KZ maps via CLI/MCP: VMF edits, GOKZ audits, jumps, reference copying, recovery and Hammer++.
---

# Mapwright

Adjacent `installation.json` identifies the absolute executable, workspace and
checkout. Otherwise use `.venv/Scripts/mapwright.exe` (Windows) or
`.venv/bin/mapwright`. Put `--workspace PATH` before CLI commands. Discover flags
with `COMMAND --help`, fields with `schema`/tools/list, prerequisites with `doctor`.
Missing installation: follow `mapwright-setup`. Check the running schema; edits
in another checkout do not update the installed executable or running server.

Establish timer/movement mode, player/replay capacity and acceptance scope from
the brief/config. Read guides only as needed: [KZ](../../docs/kz-mapping.md),
[references](../../docs/reference-maps.md), [recovery](../../docs/recovery.md),
[native setup](../../docs/setup.md).

1. Inspect revision and typed IDs; qualify reused IDs with `kind`. Use small pages
   (`limit=20` objects, `limit=8000` source/artifacts); follow `next_offset`.
   `object` exposes properties, outputs, sides/source. New KZ map:
   `new PATH --template kz-room`. Resolve fields/materials with `entities`/`assets`;
   preserve exact GOKZ names from the KZ contract.
2. Preview `dry_run`, then write with the same revision; re-inspect on conflict.
   Flat `map_*` tools handle one edit; `edit_map` batches atomically. Room bounds
   are interior, box bounds exterior. Unsupported features require inspected,
   explicit revision-checked `replace_source`: fetch **all** source pages and
   preserve unrelated blocks. Import references into a new VMF, identify actual
   objects, then copy typed IDs with both revisions. Inspect mappings, links,
   dependencies/conflicts and mounts per the reference guide.
3. Run `validate`, `kz-audit`, focused checks and `kz-test-plan`. Inspect `valid`,
   `complete`, findings and `unsupported_geometry` even after success. Check hull
   clearance/support at spawns, seams, turns and recovery points; box checks leave
   other collision unverified.
4. Check **every light**: origin, emitting face and aperture must clear other solid
   objects, including walls, ceilings, props and fixture housings. Move embedded
   lights into clear space; verify illumination after compilation. Inspect
   **every visible block** from all reachable viewpoints for missing/reversed
   faces, missing materials and exposed nodraw/invisible sides. Restore surfaces
   that make a block look incomplete; ordinary boxes need six oriented faces.
   Keep intentional concealed/tool faces. Inspect unsupported shapes/props in
   Hammer and in-game; structural validation alone cannot prove appearance.
5. Run `doctor` before native work; compile fresh and inspect stage logs.
   `open_editor` owns a private desktop/staged VMF. Inspect process/document,
   dialogs and enabled semantic controls before acting. Dispatch is not a commit:
   inspect state and `checkpointed`/`document_reversible`. `save_editor` verifies
   staging and commits against the source revision; re-inspect before file edits.
   `close_editor` releases owned helpers. `capture_editor method=viewport` requires
   GPU pixels; `window` is UI-only; `auto` reports fallback. Inspect image, uniform
   warnings and camera/map state before claiming visible geometry.
6. Compile with packing; embed custom materials, sky and props and resolve missing
   dependencies (editor mounts do not travel). `package_map` verifies matching
   BSP/NAV hashes/archive; empty NAVs prove presence only. Physical timers use
   `timer_profile=buttons`; set server spawn capacity. Follow the
   [verification scope](../../docs/kz-mapping.md#verification-scope): geometry/
   appearance work needs geometry checks, verified packaging and one successful
   in-game render check. Identify the tested build; report rendering, movement,
   gameplay and replay evidence separately. Expand testing for defects/broader
   requests; stop when the agreed checks pass.

Results are `{ok:true,data:...}` or `{ok:false,error:...,details?:...}`; MCP
`isError` marks execution failure. Allow compile progress/timeouts; inspect native
state before retrying timed-out mutations. Log delivery-affecting failures with
preserved artifacts, reproduction, fix and limits in the
[problem log](../../docs/recovery.md#problem-log).

Inspect recovery evidence first. Undo with the recorded revision or restore an
inspected checkpoint. `timeline_status`, `action_history`, `inspect_action` expose
permanent attempts; `checkout_action` restores finalized managed saved files with
current `expected_head`, retaining future history. Inspect preserved external edits
before retrying refusals. Saved-file recovery excludes unsaved GUI memory/undo;
use inspected native Edit/Undo and verify staging for editor-only work. Preserve
unrelated VMF blocks when recovering a change.
