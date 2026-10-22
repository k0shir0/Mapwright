"""Pack discovered Source dependencies and verify a staged BSP/NAV archive."""

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
import struct
import threading
import zipfile

from . import catalog
from .backend import BackendError
from .project import digest
from .streams import BUFFER, copy_hash, file_digest
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


def zip_hash(archive, name):
    with archive.open(name) as source:
        return copy_hash(source)


def pack_assets(bsp_path: Path, game: Path) -> dict:
    catalog.source_tools()
    from srctools.bsp import BSP
    from srctools.filesys import ZipFileSystem
    from srctools.packlist import LOGGER as pack_logger, PackList

    original_revision = file_digest(bsp_path)
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
        name.casefold(): zip_hash(bsp.pakfile, name) for name in bsp.pakfile.namelist()
    }
    for dependency in pack:
        if dependency.data is not None:
            required[dependency.filename.casefold()] = digest(dependency.data)
        elif dependency.filename in filesystem:
            with filesystem.open_bin(dependency.filename) as stream:
                required[dependency.filename.casefold()] = copy_hash(stream)
    logger.addHandler(handler)
    try:
        pack.pack_into_zip(bsp, ignore_vpk=False)
    finally:
        logger.removeHandler(handler)
    expected = {name: zip_hash(bsp.pakfile, name) for name in bsp.pakfile.namelist()}
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
    fd, temporary = tempfile.mkstemp(prefix=".hammer-agent-", dir=bsp_path.parent)
    try:
        with tempfile.TemporaryFile() as packed:
            with zipfile.ZipFile(
                packed, "w", compression=zipfile.ZIP_STORED
            ) as archive:
                for name in bsp.pakfile.namelist():
                    with (
                        bsp.pakfile.open(name) as source,
                        archive.open(name, "w", force_zip64=True) as output,
                    ):
                        shutil.copyfileobj(source, output, BUFFER)
            packed_size = packed.tell()
            with os.fdopen(fd, "w+b") as output, bsp_path.open("rb") as source:
                if copy_hash(source, output) != original_revision:
                    raise BackendError("BSP changed during dependency packing")
                output.write(bytes(-output.tell() % 4))
                pak_offset = output.tell()
                packed.seek(0)
                shutil.copyfileobj(packed, output, BUFFER)
                output.seek(8 + 40 * 16)
                output.write(
                    struct.pack("<iii4s", pak_offset, packed_size, 0, bytes(4))
                )
                output.flush()
                os.fsync(output.fileno())
        saved = BSP(Path(temporary))
        observed = {
            name: zip_hash(saved.pakfile, name) for name in saved.pakfile.namelist()
        }
        if observed != expected:
            raise BackendError("Embedded BSP assets failed readback verification")
        if file_digest(bsp_path) != original_revision:
            raise BackendError("BSP changed before packed output publication")
        os.replace(temporary, bsp_path)
    finally:
        Path(temporary).unlink(missing_ok=True)
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
        members["maps/" + path.name] = (path, info["revision"])
    if Path(receipt["nav"]["path"]).stem != Path(receipt["bsp"]["path"]).stem:
        raise MapError("BSP and NAV basenames must match")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".hammer-agent-", dir=destination.parent)
    try:
        expected = {}
        with os.fdopen(fd, "w+b") as output_stream:
            with zipfile.ZipFile(
                output_stream, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                for name, (path, revision) in members.items():
                    with (
                        path.open("rb") as source,
                        archive.open(name, "w", force_zip64=True) as output_member,
                    ):
                        observed = copy_hash(source, output_member)
                    if observed != revision:
                        raise MapError(
                            "Build revision changed; compile again before packaging"
                        )
                    expected[name] = revision
                raw_receipt = json.dumps(receipt, indent=2).encode()
                archive.writestr("mapwright-receipt.json", raw_receipt)
                expected["mapwright-receipt.json"] = digest(raw_receipt)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        with zipfile.ZipFile(temporary) as archive:
            if set(archive.namelist()) != set(expected) or any(
                zip_hash(archive, name) != revision
                for name, revision in expected.items()
            ):
                raise MapError("Package content verification failed")
        for path, revision in members.values():
            if file_digest(path) != revision:
                raise MapError("Build changed before package publication")
        revision = file_digest(temporary)
        size = Path(temporary).stat().st_size
        os.link(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {
        "path": str(destination),
        "bytes": size,
        "revision": revision,
        "verified": True,
        "entries": sorted(expected),
        "verification": receipt.get("verification", {}),
    }
