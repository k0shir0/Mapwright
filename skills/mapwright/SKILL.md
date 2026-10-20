---
name: mapwright
description: Author and inspect legacy CS:GO KZ maps through CLI or MCP. Use for VMF edits, GOKZ audits, jump measurement, reference copying, recovery, or Hammer++ control.
---

# Mapwright workflow

Use the installed Mapwright CLI or equivalent MCP tools. When this skill was
installed by setup, read the adjacent `installation.json` for the absolute
`command`, `workspace`, and checkout paths; invoke that executable directly
instead of assuming it is on PATH. In the checkout, use `.venv/Scripts/mapwright.exe`
on Windows or `.venv/bin/mapwright` on Linux/macOS. Run `COMMAND --help` for flags,
`schema` or MCP tools/list for the shared contract, and `doctor` for prerequisites.
Every CLI call puts `--workspace PATH` before the command.

If installation or MCP is missing, follow the repository's `mapwright-setup`
skill or run `python scripts/setup_agent.py --help` from the checkout. Setup
installs this skill with the linked guides bundled alongside it.

1. Inspect the map revision and typed IDs. Use `object` for properties, outputs,
   side IDs and source; qualify reused IDs with `kind`. For a new KZ map, use
   `new PATH --template kz-room`.
2. Resolve entity fields/materials with `entities` and `assets`. Read the
   [KZ contract](../../docs/kz-mapping.md) for exact GOKZ semantics.
3. Preview with `dry_run`, then write against the same revision. Use flat `map_*`
   tools for single edits; `edit_map` for atomic batches. After a conflict,
   inspect again. `add_room` bounds are interior; `add_box` bounds are exterior.
4. Use `source` and explicit `replace_source` for unsupported native VMF features.
   Native `open_editor` opens a staged copy on an owned private Windows desktop.
   `save_editor` verifies that staged save and commits against the source map's
   revision; `close_editor` closes only the owned session/helpers. Close it when
   no longer needed. For saved-file/multi-file recovery, read
   [recovery](../../docs/recovery.md). For editor-only undo, invoke the inspected
   native Edit/Undo command and verify the staged document afterward.
5. For another map, import to a new VMF, identify objects from source/spatial/
   visual evidence, then copy typed IDs with both revisions. Inspect mappings,
   dependencies and mounts; see [reference copying](../../docs/reference-maps.md).
6. Run `validate`, `kz-audit`, focused KZ checks and `kz-test-plan`. Read findings
   and unsupported geometry even when the call succeeds.
7. Run `doctor` before native work. Compile a fresh BSP and inspect stage logs.
   For GUI work, inspect the selected process/document, handle modal dialogs,
   and choose an enabled native action by its inspected identity. Actions report
   dispatch, so read state and verify the saved VMF afterward; an acknowledgement
   alone does not establish a committed edit. Keep file transactions and native
   saves separate, with a fresh revision before the next file mutation.
   Use `capture_editor method=viewport` for actual native render-thread pixels,
   or `method=window` for UI controls. Default `auto` reports any UI-only fallback
   explicitly. Read uniform-frame warnings; inspect the image and camera/map
   state before claiming visible geometry. Native actions checkpoint staged documents
   where supported; inspect `checkpointed` and `document_reversible`.
8. Test the compiled BSP on the intended server/mode before claiming playability.

Transport results are `{ok:true,data:...}` or `{ok:false,error:...,details?:...}`.
Completed checks can return findings despite success: inspect `valid`, `complete`,
and `unsupported_geometry`. MCP `isError` marks an execution failure. Use progress
notifications and appropriate client timeouts for long compiles. If a native
request times out, inspect state before retrying a mutation.

For recovery, inspect operation logs and artifacts first. Undo against the
recorded revision, or restore a named saved-file checkpoint; neither restores
unsaved editor memory. Never overwrite a map or its unrelated VMF blocks to
recover one change. Unsupported geometry requires source inspection and explicit
revision-checked replacement rather than a claimed successful geometric edit.
The permanent action history retains rejected/read-only requests too. Use
`timeline_status`, `action_history` and `inspect_action`; `checkout_action`
restores a finalized action's managed saved files against the current HEAD.
Inspect preserved external edits before retrying a refused checkout.
