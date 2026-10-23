---
name: mapwright
description: Author and inspect legacy CS:GO KZ maps: VMF edits, GOKZ audits, jumps, reference copying, recovery and Hammer++ through CLI or MCP.
compatibility: Python 3.11+ and an installed Mapwright checkout. Offline VMF tools work cross-platform; native Hammer++ and rendering require Windows and owned legacy CS:GO content.
---

# Mapwright

Mapwright edits VMF source maps and produces compiled BSP maps with matching NAV
files. KZ is movement-course mapping; GOKZ is the server plugin whose exact entity
names and settings define timer behavior. CS2 and CSS are unsupported.

Resolve installed paths with this skill's [resolver](scripts/resolve_installation.py),
using any Python 3.11+ interpreter. It reads adjacent `installation.json` and reports
stale paths. Keep the checkout; after relocation rerun setup from its new location.
In an uninstalled checkout use `.venv/Scripts/mapwright.exe` (Windows) or
`.venv/bin/mapwright`, relative to the **checkout root**. Missing executable:
follow [setup](../mapwright-setup/SKILL.md). No shell activation is required.

Use the resolved executable and put `--workspace PATH --json` before CLI commands.
Map/output paths are workspace-relative; `@request.json` is process-CWD-relative.
Use `schema --index`, then `schema --tool TOOL` (or `--group mapping|kz|native|reference|recovery`)
for fields; use `COMMAND --help` for CLI flags. The running server's schema is
binding; another checkout's edits do not update a running server.

Choose the branch matching the request; load only its linked guides:

| Task | Workflow |
| --- | --- |
| Inspect | `inspect` / `inspect_map` for revision, counts and typed IDs; `object` / `inspect_object` for details. Use `limit=20` and follow `next_offset`. Stop when the requested information is established. |
| Create or edit | `new PATH --template kz-room`; resolve entities/materials with `entities`/`assets`. Preview `dry_run`, then write with the same `expected_revision`; re-inspect conflicts. Use flat `map_*` for one edit, `edit_map` for an atomic batch. Read [KZ rules and geometry](../../docs/kz-mapping.md). |
| Copy a reference | Import into a new VMF, inspect actual objects, then copy typed IDs with both source/destination revisions. Review mappings, links, dependencies, conflicts and mounts using the [copying guide](../../docs/reference-maps.md). |
| Compile, editor or delivery | Run `doctor`, then follow [native sessions](../../docs/setup.md#terminal-controlled-editor-sessions) and [verification scope](../../docs/kz-mapping.md#verification-scope). Compile fresh with packing, inspect stage logs and verify `package_map`. |
| Recover | Inspect evidence first; use [recovery](../../docs/recovery.md) to select map undo, checkpoints, saved-file timeline checkout or native UI undo. Preserve unrelated blocks and external edits. |

For edits, qualify reused IDs with `kind`. Room bounds are interior; box bounds
are exterior. Unsupported authoring features require explicit revision-checked
`replace_source`: retrieve **all** source pages using the same `expected_revision`
and preserve unrelated blocks. Source/artifact byte pages default to 8000.

After edits run `validate`, `kz-audit` and the focused checks relevant to the change.
Inspect `valid`, `complete`, findings and `unsupported_geometry`; execution success
alone does not establish validity. Apply the KZ guide's lighting/surface checks
and agreed acceptance scope. Establish timer/movement mode and player/replay
capacity from the brief/config; physical timers use `timer_profile=buttons`.
Report geometry, packaging, rendering, movement and replay evidence separately,
with the tested build. Empty NAVs prove presence only. Stop when agreed checks pass.

Results use `{ok:true,data:...}` or `{ok:false,error:...,details:...}`; MCP `isError`
marks execution failure. Errors include a code and recovery hint. If
`response.truncated`, inspect totals/omitted fields and use `read_artifact` with
`field=NAME` for needed detail, following `next_offset`. Read all relevant findings
before verification claims; raw byte pages or `response_mode=full` reconstruct the
full result. Inspect native state before retrying timed-out mutations.
Record delivery-affecting failures in the [problem log](../../docs/recovery.md#problem-log).
