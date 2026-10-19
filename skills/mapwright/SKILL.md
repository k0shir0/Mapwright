---
name: mapwright
description: Author and inspect legacy CS:GO KZ maps through CLI or MCP. Use for VMF edits, GOKZ audits, jump measurement, reference copying, recovery, or Hammer++ control.
---

# Mapwright workflow

Use `mapwright --workspace ABSOLUTE_DIRECTORY COMMAND` or equivalent MCP tools.
Discover arguments with `schema` / tools/list; MCP guidance: `hammer://guide/kz`.

1. Inspect the map revision and typed IDs. Use `object` for properties, outputs,
   side IDs and source; qualify reused IDs with `kind`. For a new KZ map, use
   `new PATH --template kz-room`.
2. Resolve entity fields/materials with `entities` and `assets`. Read the
   repository's [KZ contract](../../docs/kz-mapping.md) for GOKZ semantics.
3. Preview with `dry_run`, then write against the same revision. Use flat `map_*`
   tools for single edits; `edit_map` for atomic batches. After a conflict,
   inspect again. `add_room` bounds are interior; `add_box` bounds are exterior.
4. Use `source` and explicit `replace_source` for unsupported native VMF features.
   Before GUI saves or multi-file changes, checkpoint saved maps/config/assets;
   see [recovery](../../docs/recovery.md). Unsaved state uses Hammer undo.
5. For another map, import to a new VMF, identify objects from source/spatial/
   visual evidence, then copy typed IDs with both revisions. Inspect mappings,
   dependencies and mounts; see [reference copying](../../docs/reference-maps.md).
6. Run `validate`, `kz-audit`, focused KZ checks and `kz-test-plan`. Read findings
   and unsupported geometry even when the call succeeds.
7. Run `doctor` before native work. Compile a fresh BSP and inspect stage logs.
   For GUI work, use inspected enabled menus/owned handles; handle modal dialogs
   first. Actions report dispatch, so inspect state and a capture afterward.
   `screen` capture can activate the editor; `window` may omit GPU viewports.
8. Test the compiled BSP on the intended server/mode before claiming playability.
