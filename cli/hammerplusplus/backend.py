"""Real Source 1 tools only. No simulated compile or success from stale files."""

from __future__ import annotations

import json
import mmap
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import time
import uuid

from .project import Project, atomic_write, digest
from .vmf import MapError, validate


class BackendError(MapError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}


def load_config(project: Project, name: str = "mapwright.local.json") -> dict:
    path = project.confined(name)
    if not path.exists() and name == "mapwright.local.json":
        legacy_path = project.confined("hammer-agent.local.json")
        if legacy_path.exists():
            path = legacy_path
    if not path.exists():
        return {}
    config = json.loads(path.read_text("utf-8-sig"))
    if not isinstance(config, dict) or set(config) - {
        "game_dir",
        "hammer",
        "vbsp",
        "vvis",
        "vrad",
        "fgd",
        "rea",
        "bspsrc_java",
    }:
        raise MapError("Invalid configuration keys; see mapwright.example.json")
    if any(
        not isinstance(value, str) or not value
        for key, value in config.items()
        if key != "fgd"
    ) or (
        "fgd" in config
        and not (
            isinstance(config["fgd"], str)
            and config["fgd"]
            or isinstance(config["fgd"], list)
            and config["fgd"]
            and all(isinstance(v, str) and v for v in config["fgd"])
        )
    ):
        raise MapError("Configured paths must be nonempty strings")
    return config


def configured_path(project: Project, config: dict, key: str) -> Path | None:
    value = config.get(key)
    if key == "fgd" and isinstance(value, list):
        value = value[0] if value else None
    if not value:
        return None
    path = Path(value).expanduser()
    return (project.root / path).resolve()


def fgd_paths(project: Project, config: dict) -> list[Path]:
    values = config.get("fgd", [])
    return [
        (project.root / Path(v).expanduser()).resolve()
        for v in ([values] if isinstance(values, str) else values)
    ]


def doctor(project: Project, config: dict) -> dict:
    game = configured_path(project, config, "game_dir")
    reports = {}
    for key in ("hammer", "vbsp", "vvis", "vrad", "fgd", "rea", "bspsrc_java"):
        path = configured_path(project, config, key)
        reports[key] = {
            "path": str(path) if path else None,
            "exists": bool(path and path.is_file()),
        }
    game_ready = bool(game and (game / "gameinfo.txt").is_file())
    editor = configured_path(project, config, "hammer")
    dlls = [
        "tier0.dll",
        "vstdlib.dll",
        "filesystem_stdio.dll",
        "materialsystem.dll",
        "shaderapidx9.dll",
    ]
    dependencies = {
        name: bool(editor and (editor.parent / name).is_file()) for name in dlls
    }
    from .render_capture import PROFILE

    renderer = {}
    for name, expected in PROFILE.items():
        path = editor.parent / name if editor else None
        observed = digest(path.read_bytes()) if path and path.is_file() else None
        renderer[name] = {
            "expected_sha256": expected,
            "sha256": observed,
            "supported": observed == expected,
        }
    candidates = []
    if os.name == "nt":
        base = (
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
            / "Steam/steamapps"
        )
        libraries = [base]
        library_file = base / "libraryfolders.vdf"
        if library_file.exists():
            for value in re.findall(
                r'"path"\s*"([^"\r\n]+)"',
                library_file.read_text("utf-8", errors="replace"),
            ):
                libraries.append(Path(value.replace("\\\\", "\\")) / "steamapps")
        for library in dict.fromkeys(libraries):
            install = library / "common/Counter-Strike Global Offensive"
            if install.is_dir():
                candidates.append(
                    {
                        "install": str(install),
                        "game_dir": str(install / "csgo"),
                        "legacy_sdk_present": all(
                            (install / "bin" / name).is_file()
                            for name in ("vbsp.exe", "vvis.exe", "vrad.exe")
                        ),
                        "hammerplusplus_present": (
                            install / "bin/hammerplusplus.exe"
                        ).is_file(),
                    }
                )
    return {
        "workspace": str(project.root),
        "target": "legacy-csgo-source1",
        "hammerplusplus_build": "8864",
        "game": {"path": str(game) if game else None, "gameinfo_exists": game_ready},
        "tools": reports,
        "editor_dependencies": dependencies,
        "editor_ready": os.name == "nt"
        and game_ready
        and reports["hammer"]["exists"]
        and all(dependencies.values()),
        "compile_ready": game_ready
        and all(reports[key]["exists"] for key in ("vbsp", "vvis", "vrad")),
        "candidates": candidates,
        "decompile_ready": reports["bspsrc_java"]["exists"],
        "viewport_profile": renderer,
        "viewport_profile_ready": os.name == "nt"
        and all(row["supported"] for row in renderer.values()),
        "fgds": [
            {"path": str(p), "exists": p.is_file()} for p in fgd_paths(project, config)
        ],
        "fgd_ready": bool(fgd_paths(project, config))
        and all(p.is_file() for p in fgd_paths(project, config)),
        "readiness_scope": "Paths and prerequisites only; verify actual compilation, decompilation and visible editor rendering separately.",
        "setup": "Follow skills/mapwright-setup/SKILL.md and docs/setup.md native prerequisite checks, then use scripts/setup_agent.py with a verified --runtime. Preserve existing Steam games, launchers and settings; install missing native tools in a fresh workspace. Tools++ supports Source 1 CS:GO. CS2 tools cannot compile VMF.",
    }


def require_tool(project: Project, config: dict, key: str) -> Path:
    path = configured_path(project, config, key)
    if not path or not path.is_file():
        raise BackendError(
            f"{key} is missing; configure its Source 1 path in mapwright.local.json"
        )
    if path.suffix.lower() in (".bat", ".cmd", ".ps1"):
        raise BackendError("Backend tools must be executables, not shell scripts")
    return path


def require_game(project: Project, config: dict) -> Path:
    path = configured_path(project, config, "game_dir")
    if not path or not (path / "gameinfo.txt").is_file():
        raise BackendError("game_dir must point to legacy csgo with gameinfo.txt")
    return path


def bsp_info(path: Path) -> dict:
    from .streams import file_digest

    size = path.stat().st_size
    if size < 1036:
        raise BackendError("Compiler did not produce a complete VBSP header")
    with path.open("rb") as stream:
        header = stream.read(1036)
    magic, version = struct.unpack_from("<4si", header)
    if magic != b"VBSP" or version != 21:
        raise BackendError(
            f"Expected legacy CS:GO VBSP version 21, got {magic!r} version {version}"
        )
    lumps = []
    for index in range(64):
        offset, length, lump_version, fourcc = struct.unpack_from(
            "<iii4s", header, 8 + index * 16
        )
        if (
            offset < 0
            or length < 0
            or (length and (offset < 1036 or offset + length > size))
        ):
            raise BackendError(f"Invalid BSP lump {index}")
        lumps.append(
            {
                "index": index,
                "offset": offset,
                "length": length,
                "version": lump_version,
            }
        )
    if not all(lumps[i]["length"] > 0 for i in (0, 1, 5)):
        raise BackendError("BSP is missing entities, planes or nodes")
    return {
        "path": str(path),
        "bytes": size,
        "version": version,
        "revision": file_digest(path),
        "lumps": lumps,
    }


def compile_map(
    project: Project,
    config: dict,
    name: str,
    expected_revision: str,
    mode: str = "fast",
    timeout: int = 120,
    pack_assets: bool = True,
) -> dict:
    if (
        mode not in ("bsp", "fast", "full")
        or not isinstance(pack_assets, bool)
        or isinstance(timeout, bool)
        or not 1 <= timeout <= 3600
    ):
        raise MapError(
            "mode must be bsp, fast or full; pack_assets must be boolean; timeout between 1 and 3600 seconds"
        )
    source, data, text, _ = project.read(name)
    if digest(data) != expected_revision:
        raise MapError("Revision conflict; inspect the map again before compiling")
    validation = validate(text)
    if not validation["valid"]:
        raise MapError("Cannot compile structurally invalid VMF")
    game = require_game(project, config)
    stages = ["vbsp"] if mode == "bsp" else ["vbsp", "vvis", "vrad"]
    tools = {key: require_tool(project, config, key) for key in stages}
    # Every invocation uses a fresh directory, so an old BSP cannot pass verification.
    build = project.confined(f".hammer-agent/builds/{uuid.uuid4().hex}")
    build.mkdir(parents=True)
    staged = build / source.name
    atomic_write(staged, data)
    bsp = staged.with_suffix(".bsp")
    results = []
    start = time.monotonic()
    for key in stages:
        args = [str(tools[key])]
        if mode == "fast" and key in ("vvis", "vrad"):
            args.append("-fast")
        if key == "vrad":
            args.append("-hdr")
        args.extend(["-game", str(game), str(staged if key == "vbsp" else bsp)])
        log = build / f"{key}.log"
        with log.open("wb") as output:
            process = subprocess.Popen(
                args,
                cwd=tools[key].parent,
                stdout=output,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                remaining = max(0.01, timeout - (time.monotonic() - start))
                returncode = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                process.wait()
                raise BackendError(
                    f"{key} exceeded the build timeout",
                    {"build_dir": str(build), "log": str(log), "stages": results},
                ) from exc
        log_bytes = log.stat().st_size
        leaked = staged.with_suffix(".lin").exists()
        fatal = False
        output_tail = ""
        if log_bytes:
            # Search the complete log without copying it into a Python string.
            # Errors beyond the former 1 MiB read limit must still fail the build.
            with (
                log.open("rb") as stream,
                mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as output,
            ):
                leaked |= bool(re.search(rb"(?i)\*+\s*leaked\s*\*+", output))
                fatal = bool(
                    re.search(
                        rb"(?im)^\s*(?:error:|fatal error|error!|vbsp: error)", output
                    )
                )
                output_tail = output[-6000:].decode("utf-8", errors="replace")
        result = {
            "stage": key,
            "command": args,
            "returncode": returncode,
            "log": str(log),
            "leaked": leaked,
            "log_truncated": log_bytes > 6000,
        }
        results.append(result)
        if returncode or leaked or fatal:
            raise BackendError(
                f"{key} failed" + (" with a map leak" if leaked else ""),
                {
                    "build_dir": str(build),
                    "stages": results,
                    "output_tail": output_tail,
                },
            )
        if not bsp.is_file():
            raise BackendError(
                f"{key} did not produce a BSP",
                {"build_dir": str(build), "stages": results},
            )
    info = bsp_info(bsp)
    if pack_assets:
        from .delivery import pack_assets as pack

        assets = pack(bsp, game)
        info = bsp_info(bsp)
    else:
        assets = {"complete": False, "status": "not_checked", "unresolved": None}
    nav = bsp.with_suffix(".nav")
    from .streams import file_digest, publish_stream

    if not nav.exists():
        source_nav = project.confined(source.with_suffix(".nav"))
        if source_nav.exists():
            with source_nav.open("rb") as stream:
                publish_stream(nav, stream, exclusive=True)
        else:
            atomic_write(nav, b"", exclusive=True)
    nav_size = nav.stat().st_size
    receipt = {
        "source": str(source),
        "source_revision": expected_revision,
        "build_dir": str(build),
        "mode": mode,
        "stages": results,
        "bsp": info,
        "nav": {
            "path": str(nav),
            "bytes": nav_size,
            "revision": file_digest(nav),
            "empty": not nav_size,
            "validation": "empty_placeholder" if not nav_size else "not_parsed",
            "pathfinding_verified": False,
        },
        "assets": assets,
        "verification": {
            "compilation_succeeded": True,
            "assets_verified": assets["complete"],
            "nav_present": True,
            "nav_parsed": False,
            "editor_rendering_verified": False,
            "gameplay_verified": False,
            "replay_bots_verified": False,
        },
        "elapsed_seconds": round(time.monotonic() - start, 3),
        "limitations": "Compile success does not establish editor rendering or in-game playability; build outputs are staged, not installed into the game.",
    }
    atomic_write(build / "receipt.json", json.dumps(receipt, indent=2).encode())
    return receipt


def open_editor(project: Project, config: dict, name: str, timeout: int = 30) -> dict:
    from . import native_session

    report = doctor(project, config)
    if not report["editor_ready"]:
        raise BackendError("Hammer++ SDK dependencies are missing", report)
    return native_session.open_editor(project, config, name, timeout)


def close_editor(project: Project, config: dict, pid: int) -> dict:
    from .native_session import close_editor as close

    return close(project, config, pid)


def save_editor(
    project: Project, config: dict, pid: int, expected_revision: str
) -> dict:
    from .native_session import save_editor as save

    return save(project, config, pid, expected_revision)


def rea_probe(project: Project, config: dict, target: str) -> dict:
    """Read-only PE resource inspection, without a decompiler or executing target code."""
    rea = configured_path(project, config, "rea")
    if not rea or not rea.is_file():
        raise BackendError(
            "Configure rea to REA's runnable JavaScript CLI entrypoint (scripts/rea.mjs); see docs/setup.md"
        )
    artifact = (
        configured_path(project, config, target)
        if target in ("hammer", "vbsp", "vvis", "vrad")
        else None
    )
    if not artifact or not artifact.is_file():
        raise MapError(
            "target must name an existing configured hammer, vbsp, vvis or vrad"
        )
    node = shutil.which("node")
    if not node:
        raise BackendError("REA requires a compatible Node.js runtime")
    wrapper = rea.parent.parent / "scripts" / "rea.mjs"
    if rea.parent.name == "dist" and wrapper.is_file():
        rea = wrapper
    result = subprocess.run(
        [node, str(rea), "inspect-pe-resources", str(artifact), "--format", "json"],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        text=True,
        timeout=60,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if result.returncode:
        raise BackendError(
            "REA resource inspection failed",
            {
                "returncode": result.returncode,
                "stderr": result.stderr[-4000:],
                "stdout": result.stdout[-4000:],
            },
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise BackendError(
            "REA returned no valid JSON; configure its runnable CLI entrypoint",
            {
                "entrypoint": str(rea),
                "stderr": result.stderr[-4000:],
                "stdout": result.stdout[-4000:],
            },
        ) from exc
