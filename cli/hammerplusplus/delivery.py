"""Pack discovered Source dependencies and verify a staged BSP/NAV archive."""

import io
import json
import logging
from pathlib import Path
import struct
import threading
import zipfile

from . import catalog
from .backend import BackendError
from .project import atomic_write, digest
from .vmf import MapError

GOKZ_SCALAR_KEYS = {
    "worldspawn": ("climb_mapping_api_version",),
    "trigger_multiple": (
        "climb_teleport_type",
        "climb_teleport_destination",
        "climb_teleport_delay",
        "climb_teleport_use_dest_angles",
        "climb_teleport_reset_speed",
        "climb_teleport_reorient_player",
        "climb_teleport_relative",
        "climb_anti_bhop_time",
    ),
}


def pack_assets(bsp_path: Path, game: Path) -> dict:
    catalog.source_tools()
    from srctools.bsp import BSP
    from srctools.filesys import ZipFileSystem
    from srctools.packlist import LOGGER as pack_logger, PackList

    bsp = BSP(bsp_path)
    filesystem = catalog.game_filesystem(game)
    filesystem.add_sys(ZipFileSystem(bsp_path, bsp.pakfile), priority=True)
    pack = PackList(filesystem)
    warnings = []
    owner = threading.get_ident()
    ignored_warnings = {
        f'Unknown keyvalue "{key}" for ent of type "{classname}"!'
        for classname, keys in GOKZ_SCALAR_KEYS.items()
        for key in keys
    }

    class DependencyWarnings(logging.Handler):
        def emit(self, record):
            if record.thread == owner and record.getMessage() not in ignored_warnings:
                warnings.append(record.getMessage())

    logger = pack_logger.logger
    handler = DependencyWarnings(logging.WARNING)
    logger.addHandler(handler)
    try:
        if "scripts/game_sounds_manifest.txt" in filesystem:
            pack.load_soundscript_manifest()
        try:
            pack.pack_from_bsp(bsp)
        except KeyError as exc:
            # srctools 2.7 assumes a detail-prop game lump even when VBSP omits it.
            # Materials/static props have already been queued before this lookup.
            if exc.args != (b"dprp",):
                raise
        pack.pack_from_ents(bsp.ents, bsp_path.stem, tags=("CSGO",))
        pack.eval_dependencies()
    finally:
        logger.removeHandler(handler)
    from srctools.const import FileType
    from srctools.vmt import Material

    for dependency in pack:
        if dependency.type is FileType.MATERIAL and dependency.filename in filesystem:
            try:
                with filesystem.open_str(dependency.filename) as stream:
                    Material.parse(stream, dependency.filename).apply_patches(
                        filesystem
                    )
            except (ValueError, OSError) as exc:
                raise BackendError(
                    f"Cannot verify material dependencies: {dependency.filename}"
                ) from exc
    missing = [
        f.filename
        for f in pack
        if not f.optional and f.data is None and f.filename not in filesystem
    ]
    if missing:
        raise BackendError(
            "Unresolved BSP dependencies; no portable package produced",
            {"unresolved": sorted(missing), "bsp": str(bsp_path)},
        )
    if warnings:
        raise BackendError(
            "Dependency analysis was incomplete; inspect packing warnings",
            {"warnings": warnings, "bsp": str(bsp_path)},
        )
    # Include VPK dependencies too: a custom VPK mounted by the editor is no more
    # portable than a loose import mount. Engine shaders/runtime are still required.
    required = {
        name.casefold(): digest(bsp.pakfile.read(name))
        for name in bsp.pakfile.namelist()
    }
    for dependency in pack:
        if dependency.data is not None:
            required[dependency.filename.casefold()] = digest(dependency.data)
        elif dependency.filename in filesystem:
            with filesystem.open_bin(dependency.filename) as stream:
                required[dependency.filename.casefold()] = digest(stream.read())
    logger.addHandler(handler)
    try:
        pack.pack_into_zip(bsp, ignore_vpk=False)
    finally:
        logger.removeHandler(handler)
    expected = {name: digest(bsp.pakfile.read(name)) for name in bsp.pakfile.namelist()}
    packed_hashes = {name.casefold(): revision for name, revision in expected.items()}
    mismatched = sorted(
        name
        for name, revision in required.items()
        if packed_hashes.get(name) != revision
    )
    if mismatched or warnings:
        raise BackendError(
            "Required BSP assets failed packing verification",
            {"mismatched": mismatched, "warnings": warnings, "bsp": str(bsp_path)},
        )
    # Append only the PAK lump. Preserve every other byte and absolute game-lump
    # offset instead of round-tripping collision/entities through another parser.
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in bsp.pakfile.namelist():
            archive.writestr(name, bsp.pakfile.read(name))
    raw = bytearray(bsp_path.read_bytes())
    raw.extend(bytes(-len(raw) % 4))
    struct.pack_into(
        "<iii4s", raw, 8 + 40 * 16, len(raw), len(packed.getvalue()), 0, bytes(4)
    )
    raw.extend(packed.getvalue())
    atomic_write(bsp_path, bytes(raw))
    saved = BSP(bsp_path)
    observed = {
        name: digest(saved.pakfile.read(name)) for name in saved.pakfile.namelist()
    }
    if observed != expected:
        raise BackendError("Embedded BSP assets failed readback verification")
    return {
        "complete": True,
        "scope": "Discovered BSP materials, sky, static props and known entity dependencies; dynamic/plugin resources require runtime verification.",
        "unresolved": [],
        "embedded": [
            {"path": name, "revision": revision}
            for name, revision in sorted(observed.items())
        ],
    }


def package_map(project, build_dir: str, output: str) -> dict:
    build = project.confined(build_dir)
    destination = project.confined(output)
    if destination.suffix.lower() != ".zip" or destination.exists():
        raise MapError("Package output must be a new ZIP inside the workspace")
    receipt = json.loads(project.confined(build / "receipt.json").read_text("utf-8"))
    if not receipt.get("assets", {}).get("complete"):
        raise MapError(
            "Build assets have not been verified; compile with pack_assets enabled"
        )
    members = {}
    for kind in ("bsp", "nav"):
        info = receipt[kind]
        path = project.confined(info["path"])
        if path.parent != build or path.suffix.lower() != "." + kind:
            raise MapError(
                "Build receipt must name BSP/NAV files inside its build directory"
            )
        raw = path.read_bytes()
        if digest(raw) != info["revision"]:
            raise MapError(
                f"Build {kind} revision changed; compile again before packaging"
            )
        members["maps/" + path.name] = raw
    if Path(receipt["nav"]["path"]).stem != Path(receipt["bsp"]["path"]).stem:
        raise MapError("BSP and NAV basenames must match")
    members["mapwright-receipt.json"] = json.dumps(receipt, indent=2).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in members.items():
            archive.writestr(name, raw)
    data = buffer.getvalue()
    atomic_write(destination, data, exclusive=True)
    with zipfile.ZipFile(destination) as archive:
        if set(archive.namelist()) != set(members) or any(
            archive.read(name) != raw for name, raw in members.items()
        ):
            raise MapError("Package content verification failed")
    return {
        "path": str(destination),
        "bytes": len(data),
        "revision": digest(data),
        "verified": True,
        "entries": sorted(members),
        "verification": receipt.get("verification", {}),
    }
