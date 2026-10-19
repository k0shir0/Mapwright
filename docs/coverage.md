# Mapping access and verification

Both interfaces expose the same tool schema. Specialized helpers cover common
edits; native source editing and the actual editor provide access to other
Hammer++ features. This is not a claim that every editor command has been
individually tested.

| Area | Access | Verified behavior |
| --- | --- | --- |
| Map files | create, list, inspect, source, delete, restore | Revision checks, recovery snapshots, overwrite refusal |
| Brushes, entities, faces, UVs, outputs | Structured edits or full `replace_source` transaction | Native parser, independent srctools checks, real compiler/editor |
| Displacements, overlays, instances, custom blocks | Native VMF source and real editor controls | Preservation; displacement-copy translation regression; inspect special dependencies |
| Reference BSPs | BSPSource import, text/spatial search, object copy | Real installed KZ BSP imported and its two-part tile section copied |
| Reference dependencies | Outgoing links, ID/name/face remapping, embedded assets | Link/output regressions and safe extraction/mount tests |
| Materials/models/entities | FGD and asset catalogs, native browsers and property dialogs | Real VPK material lookup and complete CS:GO FGD parse |
| Live editor | `inspect_editor`, `editor_action`, `capture_editor` | Real menu discovery, dialogs, text, keys, button interaction, selection, save and render |
| Compilation | VBSP/VVIS/VRAD, fresh staging, HDR lighting, logs | Real Tools++ pipeline, fresh version-21 BSP, no leak |
| KZ contracts/measurements | Ten KZ tools/CLI commands, per-face materials, kz-room | GOKZ rule regressions, 240u measurement, actual MCP KZ authoring and BSP entity checks; exact box geometry only |
| Workspace recovery | Operation logs, artifacts/resources, named file/folder checkpoints | Revision/checksum refusal, reverse checkpoints, interrupted-batch resume and source-redaction tests |
| Runtime KZ mechanics | Run map using the editor or the intended server | Not yet verified in-game; no jumpability or GOKZ compatibility certification |

Read `read_map_source` in pages and use `edit_map` with
`{"op":"replace_source","source":"COMPLETE_VMF"}` for native features that
lack a helper. The revision check, structural validation and undo apply to
the complete source transaction. This avoids reducing the VMF to a fixed
subset of fields. Editing is limited to 64 MiB per VMF.

For live work, inspect the configured editor PID. Use the returned exact menu
labels or owned window/control handles with `editor_action`. Text, combo/tree
selection, keys, clicks, wheel scrolling and drags allow dialogs and viewport tools to be used.
`keys` uses pywinauto notation, for example `{ENTER}`, `^s`, or `%{F4}`.
Mouse coordinates are local to the selected control. Native GUI actions can
change unsaved state and save files; they do not participate in the bridge's
map transaction lock or undo journal. Inspect the active dialog first.

Use `capture_editor` with `method: "screen"` for visible GPU viewports.
The MCP response includes an image as well as its saved PNG path.
`method: "window"` uses PrintWindow and may capture black GPU regions.
An updater/modal prompt, minimized window, loading renderer or obscured
viewport cannot establish rendering success. Read state and inspect another
capture after the editor finishes drawing.

The importer accepts explicit external files but writes only within the
workspace. GUI access is restricted to the configured Hammer++ executable
and handles belonging to its PID. Embedded asset mounts require a local
gameinfo inside the workspace, avoiding edits to Steam's game configuration.
