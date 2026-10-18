---
name: cli-anything-hammerplusplus
description: Create, inspect and edit legacy CS:GO Source 1 VMF maps through the Hammer++ agent CLI or MCP server. Use for brushes, entities, outputs, revisions, map history and actual Source compiler/editor verification. CS2 VMAP is outside this target.
---

# Hammer++ mapping

Use the installed `hammer-agent` or `cli-anything-hammerplusplus` command.
Run `--workspace ABSOLUTE_MAP_DIRECTORY --json` before the subcommand.
Installation from the checkout: `python -m pip install -e ".[mcp,source]"`.
`schema` returns all tool fields and edit operations. `--help` lists commands.

Inspect `doctor` before editor/compiler work. Hammer++ CS:GO is frozen at build
8864 and requires the legacy CS:GO SDK. VMF edits work without the SDK; report
missing tools accurately. Use the configured FGD and asset catalogs to select
entity keyvalues, inputs, outputs and local materials/models when available.

For an existing map, use `inspect PATH` to obtain its current revision and
object IDs. `object PATH ID` returns properties, repeated outputs and original
source, including side IDs. If an imported map reuses IDs between kinds,
qualify inspection with `--kind solid` and edits with `"kind":"solid"`.
Use `parent_kind` to qualify a brush parent when needed. Apply an edit with:

```text
hammer-agent --workspace MAP_DIRECTORY --json edit maps/example.vmf --expect CURRENT_HASH --ops @operations.json --dry-run
hammer-agent --workspace MAP_DIRECTORY --json edit maps/example.vmf --expect CURRENT_HASH --ops @operations.json
```

Operations are `add_box`, `add_room`, `add_entity`, `set_properties`,
`add_output`, `translate` and `delete`. Read their exact fields from `schema`.
Use `new PATH --template csgo-room` for a sealed test fixture with team spawns
and a light. Coordinates are Source units, Z up. Room min/max are interior
bounds. A brush entity is an entity with child solids added using `parent_id`.

After a revision conflict, inspect again before forming a new transaction.
Undo/redo require the current revision. Keep a workspace copy of existing
maps and coordinate editor saves; bridge locks do not lock Hammer++.
Move displacements, overlays and instances in the actual editor. Preserve
unsupported existing data through targeted edits.

Validate the resulting map. Structural validity cannot prove sealing,
convexity, material availability or game compatibility. When the SDK exists,
use `compile PATH --expect HASH --mode fast`, read the returned stage logs
and receipt, then `editor-open PATH`. Use `editor-capture PID OUTPUT.png`
and inspect the image before claiming a rendered result. A process launch
does not prove map loading. Compilation does not prove in-game playability.

For MCP, launch `hammer-agent --workspace ABSOLUTE_MAP_DIRECTORY mcp` and use
the advertised equivalent tools. The result envelope is `ok` plus `data` or
`error`. See the checkout's `docs/agents.md` for client configuration and
`docs/setup.md` for legacy SDK and optional REA investigation.
