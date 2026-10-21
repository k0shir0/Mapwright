# Copy a reference section

Input: source BSP/VMF, destination VMF, requested objects and placement.

1. `import-reference SOURCE references/source.vmf`: external reads are allowed;
   output is a new workspace VMF. BSP inputs require configured BSPSource Java.
2. `find references/source.vmf --query TEXT`: inspect text/spatial matches,
   then `object PATH ID --kind solid|entity`. Search bounds use plane points
   and can be approximate. Use source/editor images to resolve ambiguity.
3. Inspect the destination. Call `copy-reference-objects @request.json` with
   both revisions and typed IDs; preview with `dry_run:true`.
4. Review copied IDs, targetname mappings, external references and asset mounts.
   Validate/audit, compile, inspect the editor, then test the intended server.

Request shape; replace hashes and selection with inspected values:

```json
{
  "source": "references/source.vmf",
  "destination": "maps/kz_example.vmf",
  "source_revision": "SOURCE_SHA256",
  "expected_revision": "DESTINATION_SHA256",
  "selection": [{"id": 123, "kind": "solid"}],
  "delta": [0, 0, 0],
  "dry_run": true
}
```

The copier remaps IDs/faces and generic targetnames, follows outgoing links
by default, preserves reserved GOKZ names and locks textures during translation.
It supports displacement-start translation and overlay face remapping; select
supporting brushes. Groups/visgroups are detached. Review incoming links,
wildcards, external instances and unusual reference fields manually.

Embedded assets mount through workspace-local `gameinfo.txt`; conflicting
virtual paths with different bytes are refused. Restart an open editor after
a new mount. Map undo retains mounts: [checkpoint](recovery.md) the destination,
local gameinfo and assets together before copying. Preview changes neither.

Use `asset_paths` for an exact game-relative allowlist when an import contains
unrelated NAVs or stock assets. Only selected files are conflict-checked and
mounted in an isolated directory; include transitive VMT/VTF and sky dependencies.
An empty list copies geometry without assets. Omitting it retains the full-import
mount and its conflict checks. Compilation checks and packs discovered runtime
dependencies separately; an editor mount is not a game installation.

BSP decompilation cannot recover every original entity, instance, asset or
authoring detail. Keep provenance; inspect dependencies rather than guessing.
