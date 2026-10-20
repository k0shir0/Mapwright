"""Install an isolated CS:GO Hammer++ toolchain using an owned Source 1 runtime."""

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import urllib.request
import zipfile

from cli.hammerplusplus import vmf
from cli.hammerplusplus.project import Project, atomic_write, decode

ARCHIVES = {
    "hammerplusplus_csgo_build8864.zip": (
        "https://github.com/ficool2/HammerPlusPlus-Website/releases/download/8864/hammerplusplus_csgo_build8864.zip",
        "b57639a591730e950d0b33c1804b6098e79ebcef8e4cb36e9d489a094c9789cc",
    ),
    "toolsplusplus-windows.zip": (
        "https://github.com/ficool2/misc_tools/releases/download/v1/tools%2B%2B_windows.zip",
        "fefa354891271176259e822727eb98f5d7dc2814b566c124463eb7fc0932a233",
    ),
    "bspsrc-windows-1.4.8.zip": (
        "https://github.com/ata4/bspsrc/releases/download/v1.4.8/bspsrc-windows.zip",
        "6297f7fa567adbaf72738b0a707ff45916edc920c66543098408e4b9d41ec4a9",
    ),
    "hammer_addons_v2.6.0.zip": (
        "https://github.com/TeamSpen210/HammerAddons/releases/download/v2.6.0/hammer_addons_v2.6.0.zip",
        "66c9128623850450a13bc2dc73c7e8271797e01991542e0a9916d27db9ca1a9b",
    ),
}

KZ_FGD = (
    "https://raw.githubusercontent.com/KZGlobalTeam/gokz/3.6.3/kz_mapping_api.fgd",
    "6274676b3093fc8a0194727c65fdd1bd438fb69d7c4d8d1dd4bea7c535d62e28",
)


def install_kz_fgd(project, editor):
    cached = project.confined(".local/downloads/kz_mapping_api-3.6.3.fgd")
    if not cached.exists():
        with urllib.request.urlopen(KZ_FGD[0], timeout=30) as response:
            atomic_write(cached, response.read(), exclusive=True)
    raw = cached.read_bytes()
    if hashlib.sha256(raw).hexdigest() != KZ_FGD[1]:
        raise ValueError(
            "GOKZ FGD checksum mismatch; verify the pinned upstream source"
        )
    path = editor / "hammerplusplus/kz_mapping_api.fgd"
    atomic_write(path, raw, exclusive=True)
    return path


def merge_kz_fgd(base, kz_fgd, output):
    """Inject the pinned addon fields into complete CS:GO definitions without
    re-exporting/removing HammerAddons editor helpers or assuming stock base names.
    """
    raw = base.read_bytes()
    text, encoding = decode(raw)
    addon = kz_fgd.read_text("utf-8")
    trigger = re.search(r"(\tclimb_teleport_type[\s\S]*?)(?=\t// Inputs)", addon)
    world = re.search(r"(\tclimb_mapping_api_version[^\r\n]+)", addon)
    if not trigger or not world:
        raise ValueError("Pinned GOKZ FGD field layout changed; review before merging")
    fragments = {"trigger_multiple": trigger.group(1), "worldspawn": world.group(1)}
    # Quoted descriptions/comments can contain brackets: tokenize before matching.
    token = re.compile(r'//[^\r\n]*|"(?:\\.|[^"\\])*"|[\[\]=]|[^\s\[\]="\x00]+')
    tokens = [m for m in token.finditer(text) if not m.group().startswith("//")]
    changes = []
    found = set()
    for index, t in enumerate(tokens[:-1]):
        if t.group() != "=" or tokens[index + 1].group().rstrip(":") not in fragments:
            continue
        name = tokens[index + 1].group().rstrip(":")
        start = index + 2
        while start < len(tokens) and tokens[start].group() != "[":
            start += 1
        depth = 0
        for end in range(start, len(tokens)):
            if tokens[end].group() == "[":
                depth += 1
            elif tokens[end].group() == "]":
                depth -= 1
                if depth == 0:
                    if "climb_" in text[tokens[start].end() : tokens[end].start()]:
                        raise ValueError(
                            f"{name} already contains KZ fields; select the unmodified base FGD"
                        )
                    newline = "\r\n" if "\r\n" in text else "\n"
                    changes.append(
                        (
                            tokens[end].start(),
                            tokens[end].start(),
                            newline
                            + fragments[name]
                            .replace("\r\n", "\n")
                            .replace("\n", newline)
                            + newline,
                        )
                    )
                    found.add(name)
                    break
    if found != set(fragments):
        raise ValueError("Base FGD must define trigger_multiple and worldspawn")
    atomic_write(output, vmf.replace(text, changes).encode(encoding), exclusive=True)
    return output


def archive(project, name, folder, prefixes=None):
    url, expected = ARCHIVES[name]
    cached = project.confined(".local/downloads/" + name)
    if not cached.exists():
        with urllib.request.urlopen(url, timeout=120) as response:
            atomic_write(cached, response.read(), exclusive=True)
    if hashlib.sha256(cached.read_bytes()).hexdigest() != expected:
        raise ValueError(
            f"{name} checksum mismatch; review upstream release changes before updating the pinned hash"
        )
    target = project.confined(folder)
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(cached) as zipped:
        for member in zipped.infolist():
            path = (target / member.filename).resolve()
            if not path.is_relative_to(target):
                raise ValueError("Archive path escapes installation")
        zipped.extractall(
            target,
            members=[
                m
                for m in zipped.infolist()
                if prefixes is None or any(m.filename.startswith(p) for p in prefixes)
            ],
        )
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        default=".",
        help="Workspace root for isolated downloads, installation and configuration (default: current directory)",
    )
    parser.add_argument(
        "--runtime",
        required=True,
        help="Owned legacy CS:GO installation containing bin DLLs",
    )
    parser.add_argument(
        "--content", help="Legacy csgo content directory, defaults to RUNTIME/csgo"
    )
    parser.add_argument(
        "--install-dir",
        default=".local/csgo-editor",
        help="New installation directory relative to the workspace (default: .local/csgo-editor)",
    )
    parser.add_argument(
        "--output-config",
        default="mapwright.local.json",
        help="New configuration path relative to the workspace (default: mapwright.local.json)",
    )
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("The native CS:GO editor installation requires Windows")
    project = Project(args.workspace)
    config_path = project.confined(args.output_config)
    if config_path.exists():
        parser.error(
            "Output configuration already exists; select a new --output-config"
        )
    runtime = Path(args.runtime).resolve(strict=True)
    content = (
        Path(args.content).resolve(strict=True) if args.content else runtime / "csgo"
    )
    required = [
        "tier0.dll",
        "vstdlib.dll",
        "filesystem_stdio.dll",
        "materialsystem.dll",
        "shaderapidx9.dll",
    ]
    if (
        not all((runtime / "bin" / name).is_file() for name in required)
        or not (content / "gameinfo.txt").is_file()
    ):
        parser.error(
            "Runtime must contain compatible CS:GO engine DLLs; content must contain gameinfo.txt"
        )
    install = project.confined(args.install_dir)
    editor = install / "bin"
    if editor.exists():
        parser.error(
            "Installation directory already exists; select a fresh --install-dir"
        )
    hammer = archive(
        project, "hammerplusplus_csgo_build8864.zip", ".local/hammerplusplus-csgo"
    )
    tools = (
        archive(project, "toolsplusplus-windows.zip", ".local/toolsplusplus")
        / "tools++_windows"
    )
    bspsrc = archive(project, "bspsrc-windows-1.4.8.zip", ".local/bspsrc-1.4.8")
    editor.mkdir(parents=True)
    for item in (runtime / "bin").iterdir():
        if item.is_file() and item.suffix.casefold() in {
            ".dll",
            ".cfg",
            ".ini",
            ".txt",
        }:
            shutil.copy2(item, editor / item.name)
    shutil.copytree(
        hammer / "hammerplusplus_csgo_build8864/bin", editor, dirs_exist_ok=True
    )
    # The srctools engine database intentionally excludes editor model/icon helpers.
    # Use its maintainer's complete published FGD and editor assets instead.
    addons = archive(
        project,
        "hammer_addons_v2.6.0.zip",
        ".local/hammer-addons",
        ("csgo.fgd", "hammer/"),
    )
    fgd = editor / "hammerplusplus/csgo_agent.fgd"
    # Normalize undefined CP1252 bytes in descriptions from the upstream archive.
    definitions = (
        (addons / "csgo.fgd")
        .read_bytes()
        .decode("cp1252", errors="replace")
        .encode("cp1252", errors="replace")
    )
    atomic_write(fgd, definitions, exclusive=True)
    kz_fgd = install_kz_fgd(project, editor)
    merged_fgd = merge_kz_fgd(fgd, kz_fgd, editor / "hammerplusplus/csgo_kz.fgd")
    game = install / "csgo"
    game.mkdir()
    assets = project.confined("assets")
    assets.mkdir(exist_ok=True)
    mounts = "".join(
        "\tGame " + vmf.quote(str(path)) + "\n"
        for path in (
            game,
            assets,
            addons / "hammer",
            content,
            content.parent / "platform",
        )
    )
    gameinfo = vmf.block(
        "GameInfo",
        {
            "game": "Counter-Strike: Global Offensive",
            "title": "CSGO Agent Mapping",
            "type": "multiplayer_only",
        },
        vmf.block(
            "FileSystem",
            {"SteamAppId": "730"},
            vmf.block("SearchPaths", {}, mounts),
        ),
    )
    atomic_write(game / "gameinfo.txt", gameinfo.encode(), exclusive=True)
    settings = {
        "GameData0": str(merged_fgd),
        "TextureFormat": "5",
        "MapFormat": "4",
        "DefaultTextureScale": "0.25",
        "DefaultLightmapScale": "16",
        "DefaultSolidEntity": "func_detail",
        "DefaultPointEntity": "info_player_terrorist",
        "BSP": str(tools / "vbsp++.exe"),
        "Vis": str(tools / "vvis++.exe"),
        "Light": str(tools / "vrad++.exe"),
        "GameExe": str(runtime / "csgo.exe"),
        "GameExeDir": str(runtime),
        "MapDir": str(project.root / "maps"),
        "BSPDir": str(install / "compiled-maps"),
        "PrefabDir": str(editor / "Prefabs"),
    }
    config = vmf.block(
        "Configs",
        {"SDKVersion": "5"},
        vmf.block(
            "Games",
            {},
            vmf.block(
                '"Counter-Strike: Global Offensive"',
                {"GameDir": str(game)},
                vmf.block("Hammer", settings),
            ),
        ),
    )
    atomic_write(
        editor / "hammerplusplus/hammerplusplus_gameconfig.txt", config.encode()
    )
    settings_path = editor / "hammerplusplus/hammerplusplus_settings.ini"
    if settings_path.exists():
        # Keep the frozen CS:GO build and avoid the documented Windows file-dialog freeze.
        text = (
            settings_path.read_text()
            .replace("StartupCheckForUpdates=1", "StartupCheckForUpdates=0")
            .replace("FileDialogHack=1", "FileDialogHack=0")
            .replace("DiscordRPC=1", "DiscordRPC=0")
        )
        atomic_write(settings_path, text.encode())
    else:
        atomic_write(
            settings_path,
            b"[General]\nStartupCheckForUpdates=0\nFileDialogHack=0\nDiscordRPC=0\n",
        )
    result = {
        "game_dir": str(game),
        "hammer": str(editor / "hammerplusplus.exe"),
        "vbsp": str(tools / "vbsp++.exe"),
        "vvis": str(tools / "vvis++.exe"),
        "vrad": str(tools / "vrad++.exe"),
        "fgd": [str(fgd), str(kz_fgd)],
        "bspsrc_java": str(bspsrc / "bin/java.exe"),
    }
    atomic_write(config_path, json.dumps(result, indent=2).encode(), exclusive=True)
    atomic_write(
        install / "installation.json",
        json.dumps(
            {
                "runtime": str(runtime),
                "content": str(content),
                "archives": ARCHIVES,
                "kz_fgd": KZ_FGD,
                "fgd": "HammerAddons v2.6.0 complete CS:GO FGD and editor assets; undefined CP1252 description bytes normalized",
            },
            indent=2,
        ).encode(),
        exclusive=True,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "configuration": str(config_path),
                "installation": str(install),
                "verification": "Run scripts/verify_backend.py and inspect_editor/capture_editor. Installation does not prove rendering.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
