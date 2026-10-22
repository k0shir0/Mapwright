"""Import real BSP/VMF references, inspect selections and transplant native objects."""

from __future__ import annotations

from collections import Counter
import io
import json
from pathlib import Path
import re
import struct
import subprocess
import uuid
import zipfile

from . import vmf, catalog
from .backend import BackendError, configured_path, require_tool
from .project import Project, atomic_write, decode, digest

# GOKZ interprets these names as an API, rather than ordinary entity labels.
KZ_NAMES = re.compile(
    r"climb_(?:(?:bonus[1-9][0-9]*_)?(?:start|end)(?:button|zone)?|teleport|bhop_reset|anti_(?:pause|checkpoint|bhop|jumpstat))$",
    re.I,
)
ENTITY_INPUTS = {
    "setparent",
    "settarget",
    "setfilter",
    "setlightingorigin",
    "setmeasuretarget",
    "setmeasurereference",
    "settargetreference",
}


def receipt_path(project: Project, path: Path) -> Path:
    return project.confined(
        ".hammer-agent/references/"
        + digest(str(path.relative_to(project.root)).encode())
        + ".json"
    )


def import_map(
    project: Project, config: dict, source: str, output: str, timeout: int = 180
) -> dict:
    original = Path(source).expanduser().resolve(strict=True)
    if original.suffix.lower() not in {".vmf", ".bsp"} or not original.is_file():
        raise vmf.MapError("Reference must be a VMF or Source 1 BSP file")
    if original.stat().st_size > 512 * 1024 * 1024:
        raise vmf.MapError("Reference exceeds the 512 MiB import limit")
    target = project.map_path(output)
    if target.exists():
        raise vmf.MapError("Import output exists; choose a new path")
    raw = original.read_bytes()
    job = project.confined(".hammer-agent/imports/" + uuid.uuid4().hex)
    job.mkdir(parents=True)
    assets = job / "assets"
    warnings = []
    command = None
    if original.suffix.lower() == ".bsp":
        if (
            raw[:4] != b"VBSP"
            or len(raw) < 1036
            or struct.unpack_from("<i", raw, 4)[0] != 21
        ):
            raise vmf.MapError("Expected a legacy CS:GO Source 1 version 21 BSP")
        java = require_tool(project, config, "bspsrc_java")
        staged = job / "reference.bsp"
        atomic_write(staged, raw)
        out = job / "reference.vmf"
        log = job / "decompile.log"
        command = [
            str(java),
            "-m",
            "info.ata4.bspsrc.app/info.ata4.bspsrc.app.src.BspSourceLauncher",
            "--appid",
            "730",
            "--no_lumpfiles",
            "-o",
            str(out),
            str(staged),
        ]
        with log.open("wb") as stream:
            try:
                completed = subprocess.run(
                    command,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    timeout=timeout,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except subprocess.TimeoutExpired as exc:
                raise BackendError("BSPSource timed out", {"log": str(log)}) from exc
        if completed.returncode or not out.is_file():
            raise BackendError(
                "BSPSource did not produce a VMF",
                {"log": str(log), "returncode": completed.returncode},
            )
        data = out.read_bytes()
        offset, size = struct.unpack_from("<ii", raw, 8 + 40 * 16)
        if offset < 0 or size < 0 or offset + size > len(raw):
            raise vmf.MapError("Invalid embedded asset lump")
        if size:
            total = 0
            with zipfile.ZipFile(io.BytesIO(raw[offset : offset + size])) as pack:
                for member in pack.infolist():
                    name = member.filename.replace("\\", "/")
                    if member.is_dir():
                        continue
                    rel = Path(name)
                    destination = (assets / rel).resolve()
                    if (
                        rel.is_absolute()
                        or not destination.is_relative_to(assets.resolve())
                        or ":" in name
                    ):
                        raise vmf.MapError("Unsafe path in BSP embedded assets")
                    if rel.suffix.lower() in {
                        ".exe",
                        ".dll",
                        ".bat",
                        ".cmd",
                        ".ps1",
                        ".com",
                        ".msi",
                    }:
                        warnings.append("Skipped executable embedded asset: " + name)
                        continue
                    total += member.file_size
                    if (
                        member.file_size > 128 * 1024 * 1024
                        or total > 1024 * 1024 * 1024
                    ):
                        raise vmf.MapError("Embedded asset extraction limit exceeded")
                    atomic_write(destination, pack.read(member), exclusive=True)
        warnings.append(
            "BSPSource reconstructs compiled geometry; original instances, consumed compile entities and authoring history may not be recoverable."
        )
    else:
        data = raw
    if len(data) > 64 * 1024 * 1024:
        raise vmf.MapError("Decompiled VMF exceeds the 64 MiB editing limit")
    text, _ = decode(data)
    root = vmf.parse(text)
    if len(root.blocks("world")) != 1:
        raise vmf.MapError("Imported VMF has no unique world block")
    provenance = {
        "source": str(original),
        "source_revision": digest(raw),
        "revision": digest(data),
        "format": original.suffix[1:].lower(),
        "output": str(target.relative_to(project.root)),
        "status": "prepared",
        "decompiler_command": command,
        "assets_dir": str(assets) if assets.exists() else None,
        "warnings": warnings,
        "log": str(job / "decompile.log") if command else None,
    }
    with project.locked():
        # Record provenance before publishing the imported map.
        atomic_write(
            receipt_path(project, target), json.dumps(provenance, indent=2).encode()
        )
        atomic_write(target, data, exclusive=True)
        provenance["status"] = "complete"
        atomic_write(
            receipt_path(project, target), json.dumps(provenance, indent=2).encode()
        )
    return {
        **project.inspect(output, limit=20),
        "provenance": provenance,
        "validation": project.validate(output),
    }


def objects(root: vmf.Node):
    """Select entities and world solids once; entity-owned solids travel with their entity."""

    def descend(parent, owner=None):
        for node in parent.children:
            if node.value is not None:
                continue
            if node.key == "entity":
                yield node
            elif node.key == "solid":
                if owner is None:
                    yield node
            elif node.key in ("__root__", "world", "hidden"):
                yield from descend(node, owner)

    yield from descend(root)


def bounds(node: vmf.Node):
    coordinates = []
    for item in node.walk():
        if item.key == "plane" and item.value is not None:
            try:
                values = vmf.vector(item.value, 9)
                coordinates.extend(values[i : i + 3] for i in (0, 3, 6))
            except vmf.MapError:
                pass
    if not coordinates and node.props("origin"):
        try:
            coordinates = [vmf.vector(node.get("origin"))]
        except vmf.MapError:
            pass
    if not coordinates:
        return None
    return {
        "min": [min(p[i] for p in coordinates) for i in range(3)],
        "max": [max(p[i] for p in coordinates) for i in range(3)],
    }


def search(
    project: Project,
    path: str,
    query: str = "",
    minimum=None,
    maximum=None,
    kind: str = "",
    offset: int = 0,
    limit: int = 100,
) -> dict:
    _, data, text, _, view = project.view(path)
    root = view["root"]
    if (minimum is None) != (maximum is None):
        raise vmf.MapError("Spatial filtering requires both minimum and maximum")
    lo = vmf.vector(minimum) if minimum is not None else None
    hi = vmf.vector(maximum) if maximum is not None else None
    if lo and not all(a <= b for a, b in zip(lo, hi)):
        raise vmf.MapError("Invalid selection bounds")
    tokens = query.casefold().split()
    cache_key = (digest(data), query, tuple(lo or []), tuple(hi or []), kind)
    matches = project._searches.get(cache_key)
    if matches is None:
        matches = search_objects(root, text, tokens, lo, hi, kind)
        project._searches.put(cache_key, matches)
    return {
        "revision": digest(data),
        "total": len(matches),
        "objects": matches[offset : offset + limit],
        "next_offset": offset + limit if offset + limit < len(matches) else None,
        "selection_help": "Interpret the user description using these names, materials, spatial bounds and object sources; do not guess ambiguous unnamed geometry.",
    }


def search_objects(root, text, tokens, lo, hi, kind):
    matches = []
    for node in objects(root):
        if kind and node.key != kind:
            continue
        source = text[node.start : node.end]
        if tokens and not all(token in source.casefold() for token in tokens):
            continue
        box = bounds(node)
        if lo and (
            not box
            or any(box["max"][i] < lo[i] or box["min"][i] > hi[i] for i in range(3))
        ):
            continue
        materials = Counter(
            p.value for p in node.walk() if p.key == "material" and p.value is not None
        )
        matches.append(
            {
                **vmf.describe(node),
                "bounds": box,
                "bounds_kind": "plane-points (conservative for non-axial brushes)",
                "materials": dict(materials),
                "brushes": sum(n.key == "solid" for n in node.walk())
                + (node.key == "solid"),
                "group_ids": sorted(
                    {
                        p.value
                        for p in node.walk()
                        if p.key == "groupid" and p.value is not None
                    }
                ),
            }
        )
    return matches


def translated(source: str, delta: list[float]) -> str:
    root = vmf.parse(source)
    changes = []

    def visit(node):
        if node.key not in (
            "__root__",
            "solid",
            "side",
            "entity",
            "hidden",
            "dispinfo",
            "editor",
        ):
            return
        for prop in node.children:
            if prop.value is None:
                visit(prop)
                continue
            is_origin = node.key == "entity" and prop.key in ("origin", "BasisOrigin")
            is_plane = node.key == "side" and prop.key == "plane"
            is_disp = node.key == "dispinfo" and prop.key == "startposition"
            if is_origin or is_plane or is_disp:
                values = vmf.vector(prop.value, 9 if is_plane else 3)
                moved = [v + delta[i % 3] for i, v in enumerate(values)]
                if any(abs(v) > 16384 for v in moved):
                    raise vmf.MapError(
                        "Copied geometry leaves Source coordinate bounds"
                    )
                value = (
                    " ".join("(" + vmf.fmt(moved[i : i + 3]) + ")" for i in (0, 3, 6))
                    if is_plane
                    else ("[" + vmf.fmt(moved) + "]" if is_disp else vmf.fmt(moved))
                )
                changes.append((prop.value_start, prop.end, vmf.quote(value)))
            elif node.key == "side" and prop.key in ("uaxis", "vaxis"):
                axis = vmf.vector(prop.value, 5)
                if axis[4] == 0:
                    raise vmf.MapError("Zero texture scale")
                axis[3] -= sum(a * b for a, b in zip(axis[:3], delta)) / axis[4]
                changes.append(
                    (
                        prop.value_start,
                        prop.end,
                        vmf.quote("[" + vmf.fmt(axis[:4]) + "] " + vmf.fmt(axis[4:])),
                    )
                )

    visit(root)
    return vmf.replace(source, changes)


def copy_objects(
    project: Project,
    source: str,
    destination: str,
    source_revision: str,
    expected_revision: str,
    selection: list[dict],
    delta=None,
    prefix: str = "",
    include_links: bool = True,
    dry_run: bool = False,
    config=None,
    asset_paths=None,
) -> dict:
    source_path, src_data, src_text, _ = project.read(source)
    _, dst_data, dst_text, _ = project.read(destination)
    if digest(src_data) != source_revision or digest(dst_data) != expected_revision:
        raise vmf.MapError("Revision conflict; inspect both maps again")
    if not selection:
        raise vmf.MapError("Select at least one entity or solid")
    src_root, dst_root = vmf.parse(src_text), vmf.parse(dst_text)
    chosen = []
    chosen_ids = set()
    index = vmf.id_index(src_root)
    for selected in selection:
        node = vmf.find_id(
            src_root,
            selected["id"],
            selected["kind"],
            allowed=("solid", "entity"),
            index=index,
        )
        if id(node) not in chosen_ids:
            chosen.append(node)
            chosen_ids.add(id(node))

    # Copy an entity once if its child brush was explicitly selected too.
    def remove_contained(nodes):
        entities = sorted(
            (n for n in nodes if n.key == "entity"), key=lambda n: n.start
        )
        contained, cursor = set(), 0
        for node in sorted(nodes, key=lambda n: n.start):
            while cursor < len(entities) and entities[cursor].end <= node.start:
                cursor += 1
            if (
                cursor < len(entities)
                and entities[cursor].start
                < node.start
                < node.end
                < entities[cursor].end
            ):
                contained.add(id(node))
        return [n for n in nodes if id(n) not in contained]

    chosen = remove_contained(chosen)
    chosen_ids = {id(n) for n in chosen}
    links = {
        "target",
        "parentname",
        "filtername",
        "landmark",
        "lightingorigin",
        "measuretarget",
        "measurereference",
        "targetreference",
        "teleportfilter",
        "climb_teleport_destination",
    }
    definitions = None
    if config and config.get("fgd"):
        definitions = catalog.entity_definitions(project, config)

    def fields(node, types):
        if definitions is None:
            return set()
        try:
            entity = definitions[node.get("classname")]
        except KeyError:
            return set()
        return {
            key.casefold()
            for key in entity.kv
            if getattr(entity.kv[key].type, "value", None) in types
        }

    def entity_links(node):
        return links | (
            fields(
                node, {"target_destination", "target_name_or_class", "target_source"}
            )
            - {"targetname", "globalname"}
        )

    def face_fields(node):
        fallback = {
            "info_overlay": {"sides"},
            "env_cubemap": {"sides"},
            "info_no_dynamic_shadow": {"sides"},
            "info_overlay_transition": {"sides", "sides2"},
        }
        return fallback.get(node.get("classname"), set()) | fields(node, {"sidelist"})

    entities = [n for n in objects(src_root) if n.key == "entity"]
    named = {}
    for ent in entities:
        if ent.get("targetname"):
            named.setdefault(ent.get("targetname").casefold(), []).append(ent)

    def entity_parameter(parts):
        if len(parts) < 3:
            return False
        if parts[1].casefold() in ENTITY_INPUTS:
            return True
        if definitions is not None:
            for target in named.get(parts[0].casefold(), []):
                try:
                    parameter = definitions[target.get("classname")].inp[
                        parts[1].casefold()
                    ]
                except KeyError:
                    continue
                if getattr(parameter.type, "value", None) in (
                    "target_destination",
                    "target_name_or_class",
                ):
                    return True
        return False

    def references(node):
        found = []
        for p in node.children:
            if p.value is not None and p.key.casefold() in entity_links(node):
                found.append(p.value.split(",")[0])
        for c in node.blocks("connections"):
            for p in c.children:
                if p.value is None:
                    continue
                parts = p.value.split("\x1b" if "\x1b" in p.value else ",")
                found.append(parts[0])
                if entity_parameter(parts):
                    found.append(parts[2])
        return found

    if include_links:
        for node in chosen:
            for name in references(node):
                for ent in named.get(name.casefold(), []):
                    if id(ent) not in chosen_ids:
                        chosen.append(ent)
                        chosen_ids.add(id(ent))
            if len(chosen) > 10000:
                raise vmf.MapError(
                    "Linked selection exceeds 10000 objects; refine the selection"
                )
    chosen = remove_contained(chosen)
    shift = vmf.vector(delta or [0, 0, 0])
    prefix = prefix or "ref_" + uuid.uuid4().hex[:10] + "_"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", prefix):
        raise vmf.MapError(
            "prefix must be an identifier ending or beginning with letters/underscore"
        )
    names = {
        n.get("targetname").casefold(): (
            n.get("targetname")
            if KZ_NAMES.fullmatch(n.get("targetname"))
            else prefix + n.get("targetname")
        )
        for n in chosen
        if n.key == "entity" and n.get("targetname")
    }
    occupied = {
        n.get("targetname").casefold() for n in objects(dst_root) if n.key == "entity"
    }
    repeatable = {
        n.get("targetname").casefold()
        for n in chosen
        if n.key == "entity"
        and n.get("classname") in ("trigger_multiple", "func_button")
        and KZ_NAMES.fullmatch(n.get("targetname"))
    }
    if any(
        n.casefold() in occupied and n.casefold() not in repeatable
        for n in names.values()
    ):
        raise vmf.MapError("Targetname prefix collides with the destination map")
    if any(
        KZ_NAMES.fullmatch(n.get("targetname")) for n in chosen if n.key == "entity"
    ):
        api_version = src_root.blocks("world")[0].get("climb_mapping_api_version")
        current = dst_root.blocks("world")[0].get("climb_mapping_api_version")
        if api_version and current and api_version != current:
            raise vmf.MapError(
                "GOKZ mapping API versions differ; resolve the destination version before copying"
            )
        if api_version and not current:
            dst_text = vmf.set_properties(
                dst_text,
                dst_root.blocks("world")[0],
                {"climb_mapping_api_version": api_version},
            )
            dst_root = vmf.parse(dst_text)
    next_id = vmf.next_id(dst_root)
    id_map = {}
    rows = []
    world_add = []
    entity_add = []
    external = set()
    # Allocate all object/face IDs before rewriting cross-object side references.
    for obj in chosen:
        for node in [obj, *obj.walk()]:
            if (
                node.value is None
                and node.key in ("entity", "solid", "side")
                and node.get("id").isdecimal()
            ):
                key = (node.key, node.get("id"))
                if key not in id_map:
                    id_map[key] = next_id
                    next_id += 1
    for obj in chosen:
        fragment = src_text[obj.start : obj.end]
        root = vmf.parse(fragment)
        changes = []
        for node in root.walk():
            if node.value is None:
                if (node.key, node.get("id")) in id_map:
                    for p in node.props("id"):
                        changes.append(
                            (
                                p.value_start,
                                p.end,
                                vmf.quote(id_map[(node.key, node.get("id"))]),
                            )
                        )
                if node.key == "editor":
                    for p in node.children:
                        if p.value is not None and p.key in ("groupid", "visgroupid"):
                            changes.append((p.start, p.end, ""))
                if node.key == "entity":
                    for p in node.children:
                        if p.value is None:
                            continue
                        if p.key == "targetname" or p.key.casefold() in entity_links(
                            node
                        ):
                            value = p.value
                            head, sep, tail = value.partition(",")
                            if head.casefold() in names:
                                changes.append(
                                    (
                                        p.value_start,
                                        p.end,
                                        vmf.quote(names[head.casefold()] + sep + tail),
                                    )
                                )
                        elif p.key.casefold() in face_fields(node):
                            old = p.value.split()
                            missing = [v for v in old if ("side", v) not in id_map]
                            if missing:
                                raise vmf.MapError(
                                    "Overlay references unselected faces; include its supporting brushes"
                                )
                            changes.append(
                                (
                                    p.value_start,
                                    p.end,
                                    vmf.quote(
                                        " ".join(str(id_map[("side", v)]) for v in old)
                                    ),
                                )
                            )
                    for conn in node.blocks("connections"):
                        for p in conn.children:
                            if p.value is None:
                                continue
                            sep = "\x1b" if "\x1b" in p.value else ","
                            parts = p.value.split(sep)
                            parameter_is_entity = entity_parameter(parts)
                            changed = False
                            if parts[0].casefold() in names:
                                parts[0] = names[parts[0].casefold()]
                                changed = True
                            if parameter_is_entity and parts[2].casefold() in names:
                                parts[2] = names[parts[2].casefold()]
                                changed = True
                            if changed:
                                changes.append(
                                    (p.value_start, p.end, vmf.quote(sep.join(parts)))
                                )

        for name in references(obj):
            if name and not name.startswith("!") and name.casefold() not in names:
                external.add(name)
        fragment = translated(vmf.replace(fragment, changes), shift)
        (entity_add if obj.key == "entity" else world_add).append(fragment + "\n")
        rows.append(
            {
                "kind": obj.key,
                "source_id": int(obj.get("id")),
                "destination_id": id_map[(obj.key, obj.get("id"))],
            }
        )
    if world_add:
        dst_text = vmf.insert(dst_text, dst_root.blocks("world")[0], "".join(world_add))
    if entity_add:
        dst_text = vmf.insert(dst_text, vmf.parse(dst_text), "".join(entity_add))
    preview = project.apply(
        destination,
        expected_revision,
        [{"op": "replace_source", "source": dst_text}],
        True,
    )
    source_info = receipt_path(project, source_path)
    provenance = json.loads(source_info.read_text()) if source_info.exists() else None
    asset_mount = {"required": False, "mounted": False}
    if provenance and provenance.get("assets_dir"):
        assets = project.confined(provenance["assets_dir"])
        incoming_files = sorted(p for p in assets.rglob("*") if p.is_file())
        source_assets = assets
        if asset_paths is not None:
            selected = []
            for virtual in asset_paths:
                candidate = project.confined(assets / virtual)
                if (
                    Path(virtual).is_absolute()
                    or ".." in Path(virtual).parts
                    or not candidate.is_relative_to(assets)
                    or not candidate.is_file()
                ):
                    raise vmf.MapError(f"Invalid imported asset path: {virtual}")
                selected.append(candidate)
            incoming_files = sorted(set(selected))
            manifest = {
                p.relative_to(assets).as_posix(): digest(p.read_bytes())
                for p in incoming_files
            }
            assets = project.confined(
                ".hammer-agent/asset-mounts/"
                + digest(json.dumps(manifest, sort_keys=True).encode())
            )
            if not dry_run:
                for incoming in incoming_files:
                    target = project.confined(
                        assets / incoming.relative_to(source_assets)
                    )
                    data = incoming.read_bytes()
                    if target.exists() and target.read_bytes() != data:
                        raise vmf.MapError(
                            "Selected asset mount changed; inspect before copying"
                        )
                    if not target.exists():
                        atomic_write(target, data, exclusive=True)
        if incoming_files:
            asset_mount = {"required": True, "directory": str(assets), "mounted": False}
            game = configured_path(project, config or {}, "game_dir")
            if game:
                info = project.confined(game / "gameinfo.txt")
                raw = info.read_bytes()
                filesystem = catalog.game_filesystem(game)
                for incoming in incoming_files:
                    virtual = incoming.relative_to(source_assets).as_posix()
                    incoming_hash = digest(incoming.read_bytes())
                    for provider, subfolder in filesystem.systems:
                        try:
                            existing = provider[subfolder + virtual]
                        except FileNotFoundError:
                            continue
                        with existing.open_bin() as stream:
                            existing_hash = digest(stream.read())
                        if existing_hash != incoming_hash:
                            raise vmf.MapError(
                                f"Embedded asset conflict: {virtual}; existing {provider.path} SHA256 {existing_hash}; incoming {incoming} SHA256 {incoming_hash}. Rename/remap the conflicting asset before copying."
                            )
                content, encoding = decode(raw)
                root = vmf.parse(content)
                candidates = [
                    n
                    for n in root.walk()
                    if n.key.casefold() == "searchpaths" and n.value is None
                ]
                if len(candidates) != 1:
                    raise vmf.MapError(
                        "Local gameinfo must contain one SearchPaths block for embedded assets"
                    )
                searchpaths = candidates[0]
                mounted = any(
                    p.value
                    and Path(
                        p.value.replace("|gameinfo_path|", str(game) + "/")
                    ).resolve()
                    == assets
                    for p in searchpaths.children
                    if p.key.casefold() == "game"
                )
                if not mounted and not dry_run:
                    with project.locked():
                        if info.read_bytes() != raw:
                            raise vmf.MapError("Game configuration changed; retry copy")
                        position = (
                            searchpaths.children[0].start
                            if searchpaths.children
                            else searchpaths.close
                        )
                        updated = vmf.replace(
                            content,
                            [
                                (
                                    position,
                                    position,
                                    "\n\tGame " + vmf.quote(str(assets)) + "\n",
                                )
                            ],
                        )
                        atomic_write(info, updated.encode(encoding))
                asset_mount.update(
                    mounted=mounted or not dry_run, restart_editor=not mounted
                )
            else:
                raise vmf.MapError(
                    "Reference has embedded assets; configure a game_dir inside this workspace so they can be mounted safely"
                )
    result = (
        preview
        if dry_run
        else project.apply(
            destination,
            expected_revision,
            [{"op": "replace_source", "source": dst_text}],
            dry_run,
        )
    )
    return {
        **result,
        "copied": rows,
        "targetnames": names,
        "external_references": sorted(external),
        "reference_provenance": provenance,
        "asset_mount": asset_mount,
        "asset_paths": asset_paths,
        "warnings": [
            "Groups and visgroup membership are detached from copied objects. Recreate destination grouping as desired.",
            "BSP decompilation cannot recover every original authoring feature. Inspect and compile the copied section.",
        ],
    }
