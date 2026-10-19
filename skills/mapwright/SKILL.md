---
name: mapwright
description: Author legacy CS:GO KZ maps, audit GOKZ contracts, measure jumps, copy BSP/VMF sections, recover workspace changes and operate Hammer++ through CLI or MCP. Use for KZ geometry, triggers, timers, teleports, native mapping or verification.
---

# Mapwright mapping

Use the installed `mapwright` command.
Run `--workspace ABSOLUTE_MAP_DIRECTORY --json` before the subcommand.
Installation from the checkout: `python -m pip install -e ".[mcp,source,desktop]"`.
`schema` returns all tool fields and edit operations. `--help` lists commands.

Read `docs/kz-mapping.md` for KZ behavior; it is the maintained contract derived
from the owner's complete `.local/research/research.md`. Start new KZ maps with
`new PATH --template kz-room`. Run `kz-audit` after edits, then the focused
checks and `kz-test-plan`. Inspect `valid`, findings, `complete` and unsupported
geometry; geometry checks do not prove movement feasibility. KZ names are an
exact plugin API. LJ blocks are geometry; anti-bhop adds a separate named
trigger. Prefer flat `map_*` tools for single edits and atomic `edit_map` batches
for related changes. `add_box.face_materials` handles top-only water and ladders.

Create a checkpoint of saved map/config/asset files before GUI saves or
multi-file operations. Use `inspect_checkpoint` revisions to preview/restore;
retain the reverse checkpoint and recovery token. GUI undo handles unsaved
state. Read operation_log/list_artifacts/read_artifact for lost tokens,
snapshots and receipts. Read `docs/recovery.md` for interruption recovery.

Inspect `doctor` before editor/compiler work. Hammer++ CS:GO is frozen at build
8864 and requires compatible legacy engine DLLs. The tested isolated installer
uses owned CS:GO files, Tools++, BSPSource and complete HammerAddons definitions.
VMF edits work without these tools; report
missing tools accurately. Use the configured FGD and asset catalogs to select
entity keyvalues, inputs, outputs and local materials/models when available.

For an existing map, use `inspect PATH` to obtain its current revision and
object IDs. `object PATH ID` returns properties, repeated outputs and original
source, including side IDs. If an imported map reuses IDs between kinds,
qualify inspection with `--kind solid` and edits with `"kind":"solid"`.
Use `parent_kind` to qualify a brush parent when needed. Apply an edit with:

```text
mapwright --workspace MAP_DIRECTORY --json edit maps/example.vmf --expect CURRENT_HASH --ops @operations.json --dry-run
mapwright --workspace MAP_DIRECTORY --json edit maps/example.vmf --expect CURRENT_HASH --ops @operations.json
```

Operations are `add_box`, `add_room`, `add_entity`, `set_properties`,
`add_output`, `translate`, `delete` and `replace_source`. Read their fields from `schema`.
Use `new PATH --template csgo-room` for a sealed test fixture with team spawns
and a light. Coordinates are Source units, Z up. Room min/max are interior
bounds. A brush entity is an entity with child solids added using `parent_id`.

After a revision conflict, inspect again before forming a new transaction.
Undo/redo require the current revision. Keep a workspace copy of existing
maps and coordinate editor saves; bridge locks do not lock Hammer++.
Use `source PATH` and revision-checked `replace_source` for any native VMF
feature without a helper. Use `editor-state PID`, then `editor_action` with
the discovered exact menu labels or owned handles for native dialogs and
viewport operations. Act on enabled modal dialogs before their parent window.
Use text controls, `{ENTER}` keys or physical button invocation for file dialogs.
Native saves use Hammer++ undo, separately from bridge transactions.

For another map, import the explicitly supplied BSP/VMF into a new workspace
VMF. Search names, materials and approximate bounds, then inspect object source
and editor images to resolve the requested item. Copy typed IDs with both map
revisions. Review linked entities, external references, face dependencies and
the embedded asset mount. Preserve GOKZ reserved names; the copier remaps
ordinary targetnames and teleport destinations. Resolve differing asset-path
collisions explicitly. Read `docs/reference-maps.md` in the checkout for the
workflow and BSP reconstruction limits. Recheck copied trigger semantics in
the intended KZ server before claiming functional compatibility.

Use `files`, `delete-file PATH --expect HASH` and `restore-file TOKEN` for
workspace map lifecycle; deletion keeps a recovery snapshot.

Validate the resulting map. Structural validity cannot prove sealing,
convexity, material availability or game compatibility. When the SDK exists,
use `compile PATH --expect HASH --mode fast`, read the returned stage logs
and receipt, then `editor-open PATH`. Use `editor-capture PID OUTPUT.png --method screen`
and inspect the image before claiming a rendered result. A process launch
does not prove map loading. Compilation does not prove in-game playability.

For MCP, launch `mapwright --workspace ABSOLUTE_MAP_DIRECTORY mcp` and use
the advertised equivalent tools. The result envelope is `ok` plus `data` or
`error`. See the checkout's `docs/agent-connections.md` for client configuration and
`docs/setup.md` for legacy SDK and optional REA investigation.
