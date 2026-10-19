# Copy an item from another KZ map

Tell the connected agent which BSP or VMF to inspect, which destination VMF
to edit, what item you want, and where to put it. For example:

> Inspect C:/maps/kz_reference.bsp. Copy the two-part tiled platform near the
> start into maps/my_kz.vmf, centered at 0 0 with its bottom on the floor.
> Include linked entities, inspect the result, and compile it.

The agent interprets the description using tool results and editor images.
The CLI does not run a hidden language model or guess what unnamed geometry
means. Ambiguous selections need another inspection or clarification.

1. `import_reference_map` accepts an explicit external `source` file and a new
   workspace `output` VMF. BSPSource reconstructs a CS:GO BSP into VMF; Hammer++
   opens that VMF. The original stays untouched. Results include the source
   hash, decompiler command, log and embedded asset directory.
2. `search_reference_map` searches names, properties and materials. Optional
   `minimum`/`maximum` filter spatial bounds. Page results with `offset`/`limit`.
   Bounds use face plane points and are approximate for non-axial geometry.
   `inspect_object` returns the complete native object, outputs and side IDs.
   Use the real editor to resolve visual selections when needed.
3. `copy_reference_objects` takes source and destination revisions, typed
   selections, a translation `delta`, and optionally a targetname `prefix`.
   It copies world brushes or complete entities, remaps object/face IDs and
   names, follows exact outgoing entity links by default, preserves repeated
   outputs, moves displacement starts, and locks textures during translation.
   Configured FGD reference types supplement common links and entity-valued
   input parameters. GOKZ's reserved API names stay intact; ordinary teleport
   destinations are renamed with their links. Conflicting mapping API versions
   and duplicate unique course-start names are refused.
   `dry_run` validates without changing either the map or asset mounts.
4. Read the returned copied-ID mapping, external references and asset mount.
   Embedded assets are mounted automatically in the workspace-local gameinfo
   made by the installer. Restart an already open editor after a new mount.
   Undo restores the map transaction; it retains reusable asset mounts.
   Differing assets at an already mounted virtual path are refused with both
   source paths and hashes, preventing changes to existing destination content.
5. Validate, compile, open in Hammer++, inspect the visible GPU capture, and
   check entity behavior in the intended game/server before publishing.

CLI entry points:

```powershell
mapwright import-reference C:/maps/kz_reference.bsp references/kz.vmf
mapwright find references/kz.vmf --query tile --kind solid
mapwright object references/kz.vmf 2 --kind solid
mapwright call copy_reference_objects '@copy-request.json'
```

Example `copy-request.json` (replace both hashes and IDs with inspected values):

```json
{
  "source": "references/kz.vmf",
  "destination": "maps/my_kz.vmf",
  "source_revision": "SOURCE_SHA256",
  "expected_revision": "DESTINATION_SHA256",
  "selection": [{"id": 2, "kind": "solid"}, {"id": 9, "kind": "solid"}],
  "delta": [-84, -460, -208],
  "include_links": true,
  "dry_run": true
}
```

BSP decompilation cannot reconstruct original instances, consumed compile
entities or authoring history perfectly. Copied objects detach from source
groups/visgroups. Wildcards, incoming links and unusual game-specific reference
keys need inspection and native source editing. Overlay copies require their
supporting brushes. VMF instances can still depend on separate VMF files.
Loose external assets that were never packed into the BSP are not conjured
by decompilation. Keep source attribution/provenance and use material you can
reuse. Imported third-party geometry and assets stay out of this repository.
