"""Install Mapwright locally and register persistent MCP and portable agent skills.

Run without --yes to inspect the resolved plan. No client configuration is
written until the entire plan has been validated. Agent setup is independent
of the optional REA/CLI-Anything development tools.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import uuid

CHECKOUT = Path(__file__).resolve().parents[1]
CLIENTS = ("codex", "claude", "opencode", "antigravity", "pi", "hermes")
GUIDES = ("kz-mapping.md", "reference-maps.md", "recovery.md")


def sha(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def read(path):
    return path.read_bytes() if path.exists() else None


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate configuration key: {key}")
        result[key] = value
    return result


def jsonc_clean(text):
    """Replace comments and trailing commas with spaces, preserving offsets."""
    chars = list(text)
    index = 0
    while index < len(text):
        if text[index] == '"':
            index += 1
            while index < len(text):
                if text[index] == "\\":
                    index += 2
                elif text[index] == '"':
                    index += 1
                    break
                else:
                    index += 1
        elif text.startswith("//", index):
            end = text.find("\n", index)
            end = len(text) if end < 0 else end
            chars[index:end] = " " * (end - index)
            index = end
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                raise ValueError("Unclosed JSONC comment")
            end += 2
            chars[index:end] = [c if c in "\r\n" else " " for c in text[index:end]]
            index = end
        else:
            index += 1
    cleaned = "".join(chars)
    # Strings have already been identified by the decoder in the second pass.
    index = 0
    decoder = json.JSONDecoder()
    while index < len(cleaned):
        if cleaned[index] == '"':
            _, index = decoder.raw_decode(cleaned, index)
        else:
            if cleaned[index] == "," and re.match(r"\s*[}\]]", cleaned[index + 1 :]):
                chars[index] = " "
            index += 1
    return "".join(chars)


def json_members(cleaned, start):
    decoder = json.JSONDecoder(object_pairs_hook=unique_object)
    if cleaned[start] != "{":
        raise ValueError("Configuration section must be an object")
    index = start + 1
    fields = {}
    while True:
        while cleaned[index].isspace() or cleaned[index] == ",":
            index += 1
        if cleaned[index] == "}":
            return fields, index
        key, index = decoder.raw_decode(cleaned, index)
        while cleaned[index].isspace() or cleaned[index] == ":":
            index += 1
        value_start = index
        _, index = decoder.raw_decode(cleaned, index)
        fields[key] = (value_start, index)


def merge_json(text, keys, values):
    text = text or "{}\n"
    cleaned = jsonc_clean(text)
    data = json.loads(cleaned, object_pairs_hook=unique_object)
    if not isinstance(data, dict):
        raise ValueError("Configuration root must be an object")

    def update(start, remaining, additions):
        fields, close = json_members(cleaned, start)
        if remaining:
            key = remaining[0]
            if key in fields:
                return update(fields[key][0], remaining[1:], additions)
            value = additions
            for child in reversed(remaining[1:]):
                value = {child: value}
            additions = {key: value}
        edits = []
        missing = {}
        for key, value in additions.items():
            if key in fields:
                first, last = fields[key]
                old = json.loads(cleaned[first:last], object_pairs_hook=unique_object)
                if old != value:
                    edits.append((first, last, json.dumps(value, ensure_ascii=False)))
            else:
                missing[key] = value
        if missing:
            # Insert after the final value, before any trailing comments/comma.
            pos = max((last for _, last in fields.values()), default=start + 1)
            body = ", ".join(
                json.dumps(k) + ": " + json.dumps(v, ensure_ascii=False)
                for k, v in missing.items()
            )
            edits.append((pos, pos, ("," if fields else "") + "\n  " + body))
        result = text
        for first, last, replacement in sorted(edits, reverse=True):
            result = result[:first] + replacement + result[last:]
        json.loads(jsonc_clean(result), object_pairs_hook=unique_object)
        return result

    return update(len(cleaned) - len(cleaned.lstrip()), keys, values)


def merge_toml(text, name, values):
    data = tomllib.loads(text)
    section = data.get("mcp_servers", {})
    if not isinstance(section, dict):
        raise ValueError("mcp_servers must be a TOML table")
    old = section.get(name, {})
    if not isinstance(old, dict):
        raise ValueError("Existing Mapwright registration must be a TOML table")
    if all(old.get(k) == v for k, v in values.items()):
        return text
    header = re.compile(r"(?m)^\[mcp_servers\." + re.escape(name) + r"\]\s*(?:#.*)?$")
    match = header.search(text)
    if match is None:
        if (
            name in section
            or "mcp_servers" in data
            and not re.search(r"(?m)^\[mcp_servers(?:\.|\])", text)
        ):
            raise ValueError(
                "Use a standard [mcp_servers.NAME] table; inline/quoted table edits are refused"
            )
        result = text.rstrip() + f"\n\n[mcp_servers.{name}]\n"
        result += "".join(
            f"{k} = {json.dumps(v, ensure_ascii=False)}\n" for k, v in values.items()
        )
    else:
        end_match = re.search(r"(?m)^\[", text[match.end() :])
        end = match.end() + end_match.start() if end_match else len(text)
        body = text[match.end() : end]
        for key, value in values.items():
            if old.get(key) == value:
                continue
            field = re.compile(r"(?m)^" + re.escape(key) + r"\s*=.*$")
            if key in old:
                found = field.search(body)
                if found is None or "\n" in json.dumps(old[key]):
                    raise ValueError(f"Cannot safely replace TOML field {key}")
                # Replacing a multiline value would leave invalid trailing data;
                # final full parsing rejects the result before any write.
                body = field.sub(
                    lambda _: f"{key} = {json.dumps(value, ensure_ascii=False)}",
                    body,
                    count=1,
                )
            else:
                body = (
                    body.rstrip()
                    + f"\n{key} = {json.dumps(value, ensure_ascii=False)}\n"
                )
        result = text[: match.end()] + body + text[end:]
    parsed = tomllib.loads(result)
    if any(parsed["mcp_servers"][name].get(k) != v for k, v in values.items()):
        raise ValueError("TOML registration validation failed")
    return result


def merge_yaml(text, name, values):
    try:
        import yaml
    except ImportError as exc:
        raise ValueError(
            "Hermes setup needs setup-only PyYAML; bootstrap installs it when Hermes is selected"
        ) from exc
    # Aliases can make one edit affect unrelated settings. Refuse that ambiguous
    # representation instead of flattening the user's YAML.
    try:
        if any(
            isinstance(t, (yaml.AliasToken, yaml.AnchorToken)) for t in yaml.scan(text)
        ):
            raise ValueError(
                "Hermes configuration contains YAML aliases/anchors; no changes made"
            )
        root = yaml.compose(text or "{}")
        yaml.safe_load(text or "{}")
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid Hermes YAML: {exc}") from exc
    edits = []
    insertions = {}

    def members(node):
        if not isinstance(node, yaml.MappingNode):
            raise ValueError("Hermes configuration sections must be mappings")
        if any(
            not isinstance(key, yaml.ScalarNode) or key.tag != "tag:yaml.org,2002:str"
            for key, _ in node.value
        ):
            raise ValueError("Hermes configuration mapping keys must be strings")
        pairs = [(key.value, val) for key, val in node.value]
        unique_object(pairs)
        return dict(pairs)

    def add(node, key, value):
        rendered = json.dumps(key) + ": " + json.dumps(value, ensure_ascii=False)
        if node.flow_style:
            pos = node.end_mark.index - 1
            previous = insertions.get(pos, 0)
            edits.append(
                (pos, pos, (", " if node.value or previous else "") + rendered)
            )
            insertions[pos] = previous + 1
        else:
            pos = node.end_mark.index
            indent = node.start_mark.column
            prefix = "" if not pos or text[pos - 1] == "\n" else "\n"
            edits.append((pos, pos, prefix + " " * indent + rendered + "\n"))

    top = members(root)
    if "mcp_servers" not in top:
        add(root, "mcp_servers", {name: values})
    else:
        servers = top["mcp_servers"]
        entries = members(servers)
        if name not in entries:
            add(servers, name, values)
        else:
            current = members(entries[name])
            if any(key in current for key in ("url", "serverUrl", "httpUrl")):
                raise ValueError(
                    f"Existing server {name} uses another transport; choose a distinct --name"
                )
            for key, value in values.items():
                if key in current:
                    node = current[key]
                    old = yaml.safe_load(
                        text[node.start_mark.index : node.end_mark.index]
                    )
                    if old != value:
                        edits.append(
                            (
                                node.start_mark.index,
                                node.end_mark.index,
                                json.dumps(value, ensure_ascii=False),
                            )
                        )
                else:
                    add(entries[name], key, value)
    result = text or "{}"
    # Multiple insertions at one point must retain all fields.
    combined = {}
    for first, last, replacement in edits:
        combined[(first, last)] = combined.get((first, last), "") + replacement
    for (first, last), replacement in sorted(combined.items(), reverse=True):
        result = result[:first] + replacement + result[last:]
    loaded = yaml.safe_load(result)
    if any(loaded["mcp_servers"][name].get(k) != v for k, v in values.items()):
        raise ValueError("YAML registration validation failed")
    return result


@dataclass
class Change:
    path: Path
    before: bytes | None
    after: bytes


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".mapwright-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply_changes(changes, workspace):
    changes = [c for c in changes if c.before != c.after]
    if not changes:
        return None
    for change in changes:
        if read(change.path) != change.before:
            raise ValueError(f"Configuration changed during planning: {change.path}")
    folder = workspace / ".local/agent-setup" / uuid.uuid4().hex
    folder.mkdir(parents=True)
    manifest = {"version": 1, "status": "applying", "files": []}
    for index, change in enumerate(changes):
        backup = f"before/{index}"
        if change.before is not None:
            atomic(folder / backup, change.before)
        manifest["files"].append(
            {
                "path": str(change.path),
                "before": sha(change.before),
                "after": sha(change.after),
                "backup": backup,
            }
        )
    receipt = folder / "manifest.json"
    atomic(receipt, json.dumps(manifest, indent=2).encode())
    applied = []
    try:
        for change in changes:
            if read(change.path) != change.before:
                raise ValueError(
                    f"Configuration changed during installation: {change.path}"
                )
            atomic(change.path, change.after)
            applied.append(change)
        manifest["status"] = "applied"
    except BaseException:
        manifest["status"] = "rolled-back"
        for change in reversed(applied):
            if read(change.path) != change.after:
                manifest["status"] = "rollback-conflict"
                continue
            if change.before is None:
                change.path.unlink()
            else:
                atomic(change.path, change.before)
        raise
    finally:
        atomic(receipt, json.dumps(manifest, indent=2).encode())
    return receipt


def rollback(receipt, apply=False):
    manifest = json.loads(receipt.read_text("utf-8"))
    if manifest.get("version") != 1 or manifest.get("status") != "applied":
        raise ValueError("Receipt must describe an applied setup transaction")
    changes = []
    for entry in manifest["files"]:
        path = Path(entry["path"])
        current = read(path)
        if sha(current) != entry["after"]:
            raise ValueError(f"Refusing rollback over later changes: {path}")
        before = None
        if entry["before"] is not None:
            backup = (receipt.parent / entry["backup"]).resolve()
            if not backup.is_relative_to(receipt.parent.resolve()):
                raise ValueError("Backup path escapes receipt directory")
            before = backup.read_bytes()
            if sha(before) != entry["before"]:
                raise ValueError("Backup digest mismatch")
        changes.append((path, before))
    if apply:
        for path, before in reversed(changes):
            if before is None:
                path.unlink()
            else:
                atomic(path, before)
        manifest["status"] = "rolled-back"
        atomic(receipt, json.dumps(manifest, indent=2).encode())
    return {
        "status": "rolled-back" if apply else "planned",
        "files": [str(p) for p, _ in changes],
    }


def locations(client, scope, workspace, home, environ):
    user = scope == "user"
    if client == "codex":
        base = (
            Path(environ.get("CODEX_HOME", home / ".codex"))
            if user
            else workspace / ".codex"
        )
        return base / "config.toml", (home if user else workspace) / ".agents/skills"
    if client == "claude":
        return (home / ".claude.json" if user else workspace / ".mcp.json"), (
            home if user else workspace
        ) / ".claude/skills"
    if client == "opencode":
        base = (
            Path(
                environ.get(
                    "OPENCODE_CONFIG_DIR",
                    Path(environ.get("XDG_CONFIG_HOME", home / ".config")) / "opencode",
                )
            )
            if user
            else workspace
        )
        names = [base / "opencode.jsonc", base / "opencode.json"]
        return next((p for p in names if p.exists()), names[1]), (
            base / "skills" if user else workspace / ".opencode/skills"
        )
    if client == "antigravity":
        return (
            home / ".gemini/config/mcp_config.json"
            if user
            else workspace / ".agents/mcp_config.json"
        ), (home / ".gemini/config/skills" if user else workspace / ".agents/skills")
    if client == "pi":
        base = (
            Path(environ.get("PI_CODING_AGENT_DIR", home / ".pi/agent"))
            if user
            else workspace / ".pi"
        )
        return base / "mcp.json", base / "skills"
    if not user:
        raise ValueError(
            "Hermes MCP is profile-scoped; select --scope user for the active HERMES_HOME"
        )
    base = Path(
        environ.get(
            "HERMES_HOME",
            (
                Path(environ["LOCALAPPDATA"]) / "hermes"
                if os.name == "nt" and environ.get("LOCALAPPDATA")
                else home / ".hermes"
            ),
        )
    )
    return base / "config.yaml", base / "skills"


def registration(client, command, workspace):
    args = ["--workspace", str(workspace), "mcp"]
    if client == "opencode":
        return {
            "type": "local",
            "command": [str(command), *args],
            "enabled": True,
            "timeout": 3700000,
        }
    values = {"command": str(command), "args": args}
    if client == "codex":
        values.update(startup_timeout_sec=30, tool_timeout_sec=3700)
    elif client in ("pi", "hermes"):
        values["timeout"] = 3700
    return values


def plan_registration(client, config, name, values):
    before = read(config)
    text = before.decode("utf-8-sig") if before is not None else ""
    if client == "codex":
        section = tomllib.loads(text).get("mcp_servers", {})
        existing = section.get(name, {}) if isinstance(section, dict) else {}
    elif client == "hermes":
        existing = {}  # YAML structure is validated by merge_yaml below.
    else:
        parsed = json.loads(jsonc_clean(text or "{}"), object_pairs_hook=unique_object)
        section = (
            parsed.get("mcp" if client == "opencode" else "mcpServers", {})
            if isinstance(parsed, dict)
            else {}
        )
        existing = section.get(name, {}) if isinstance(section, dict) else {}
    if isinstance(existing, dict) and (
        any(k in existing for k in ("url", "serverUrl", "httpUrl"))
        or existing.get("type") in ("http", "sse", "remote", "streamable-http")
    ):
        raise ValueError(
            f"Existing server {name} uses another transport; choose a distinct --name"
        )
    if client == "codex":
        updated = merge_toml(text, name, values)
    elif client == "hermes":
        updated = merge_yaml(text, name, values)
    else:
        updated = merge_json(
            text, ["mcp" if client == "opencode" else "mcpServers", name], values
        )
    if before is not None and before.startswith(b"\xef\xbb\xbf"):
        updated = "\ufeff" + updated
    return Change(config, before, updated.encode())


def skill_changes(root, checkout, command, workspace):
    changes = []
    metadata = {
        "checkout": str(checkout),
        "workspace": str(workspace),
        "command": str(command),
        "setup_script": str(checkout / "scripts/setup_agent.py"),
    }
    for name in ("mapwright", "mapwright-setup"):
        dest = root / name
        marker = dest / "installation.json"
        if (
            dest.exists()
            and not marker.is_file()
            and any(path.is_file() or path.is_symlink() for path in dest.rglob("*"))
        ):
            raise ValueError(
                f"Refusing to replace an unmanaged skill directory: {dest}"
            )
        if marker.exists() and json.loads(marker.read_text("utf-8")).get(
            "checkout"
        ) != str(checkout):
            raise ValueError(f"Skill belongs to another checkout: {dest}")
        text = (checkout / "skills" / name / "SKILL.md").read_text("utf-8")
        text = text.replace("../../docs/", "references/")
        text = text.replace(
            "../../scripts/setup_agent.py",
            str(checkout / "scripts/setup_agent.py").replace("\\", "/"),
        )
        files = {
            dest / "SKILL.md": text.encode(),
            marker: (json.dumps(metadata, indent=2) + "\n").encode(),
        }
        if name == "mapwright":
            files.update(
                {
                    dest
                    / "references"
                    / guide: (checkout / "docs" / guide).read_bytes()
                    for guide in GUIDES
                }
            )
        for path, data in files.items():
            changes.append(Change(path, read(path), data))
    return changes


def detect_clients(workspace, home, environ):
    found = []
    executables = {"antigravity": ("agy", "antigravity")}
    for client in CLIENTS:
        profile_scope = "user" if client == "hermes" else "project"
        config, _ = locations(client, profile_scope, workspace, home, environ)
        user_config, _ = locations(client, "user", workspace, home, environ)
        if (
            config.exists()
            or user_config.exists()
            or any(shutil.which(exe) for exe in executables.get(client, (client,)))
        ):
            found.append(client)
    return found


def is_native_runtime(path):
    required = (
        "tier0.dll",
        "vstdlib.dll",
        "filesystem_stdio.dll",
        "materialsystem.dll",
        "shaderapidx9.dll",
    )
    return (path / "csgo/gameinfo.txt").is_file() and all(
        (path / "bin" / name).is_file() for name in required
    )


def runtime_candidates(checkout, environ):
    candidates = [
        checkout / ".local" / name
        for name in ("csgo-sdk", "csgo-editor-complete", "csgo-editor")
    ]
    steam = Path(environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam"
    libraries = [steam]
    file = steam / "steamapps/libraryfolders.vdf"
    if file.is_file():
        libraries += [
            Path(v.replace("\\\\", "\\"))
            for v in re.findall(
                r'"path"\s*"([^"\r\n]+)"', file.read_text("utf-8", errors="replace")
            )
        ]
    candidates += [
        p / "steamapps/common/Counter-Strike Global Offensive" for p in libraries
    ]
    return [p.resolve() for p in candidates if is_native_runtime(p)]


def native_plan(checkout, workspace, mode, runtime, environ):
    target = workspace / "mapwright.local.json"
    if mode == "off":
        return [], {"status": "skipped"}
    for candidate in (
        target,
        workspace / "hammer-agent.local.json",
        checkout / "mapwright.local.json",
    ):
        if candidate.is_file():
            config = json.loads(
                candidate.read_text("utf-8-sig"), object_pairs_hook=unique_object
            )
            if not isinstance(config, dict):
                raise ValueError(f"Invalid native configuration: {candidate}")
            if set(config) - {
                "game_dir",
                "hammer",
                "vbsp",
                "vvis",
                "vrad",
                "fgd",
                "rea",
                "bspsrc_java",
            }:
                raise ValueError(f"Unknown native configuration fields: {candidate}")
            for key, value in config.items():
                paths = value if key == "fgd" and isinstance(value, list) else [value]
                if not paths or any(not isinstance(v, str) or not v for v in paths):
                    raise ValueError(f"Invalid native path field {key}: {candidate}")
            if mode == "required":
                game = (
                    candidate.parent / Path(config.get("game_dir", "")).expanduser()
                ).resolve()
                tools_exist = all(
                    key in config
                    and (candidate.parent / Path(config[key]).expanduser()).is_file()
                    for key in ("hammer", "vbsp", "vvis", "vrad")
                )
                if not (game / "gameinfo.txt").is_file() or not tools_exist:
                    raise ValueError(
                        f"Existing native configuration has missing game/tools: {candidate}"
                    )
            if candidate.parent == workspace:
                return [], {"status": "configured", "configuration": str(candidate)}
            normalized = {
                k: (
                    [
                        str((candidate.parent / Path(v).expanduser()).resolve())
                        for v in value
                    ]
                    if isinstance(value, list)
                    else str((candidate.parent / Path(value).expanduser()).resolve())
                )
                for k, value in config.items()
            }
            return [
                Change(target, None, (json.dumps(normalized, indent=2) + "\n").encode())
            ], {"status": "reuse", "configuration": str(target)}
    if runtime and not is_native_runtime(runtime.expanduser().resolve()):
        raise ValueError(
            "Selected runtime is missing legacy CS:GO engine DLLs or csgo/gameinfo.txt"
        )
    candidates = (
        [runtime.expanduser().resolve()]
        if runtime
        else runtime_candidates(checkout, environ)
    )
    if candidates and os.name == "nt":
        return [], {
            "status": "install",
            "runtime": str(candidates[0]),
            "configuration": str(target),
        }
    if mode == "required":
        raise ValueError(
            "No owned legacy CS:GO runtime detected; supply --runtime or restore an entitled legacy installation"
        )
    return [], {
        "status": "offline",
        "reason": "No owned Windows legacy CS:GO runtime detected; VMF/MCP remain available",
    }


def bootstrap(checkout, apply=False, hermes=False):
    python = (
        checkout / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    command = (
        checkout
        / ".venv"
        / ("Scripts/mapwright.exe" if os.name == "nt" else "bin/mapwright")
    )
    if apply:
        if not python.is_file():
            subprocess.run(
                [sys.executable, "-m", "venv", str(checkout / ".venv")], check=True
            )
        probe = subprocess.run(
            [
                str(python),
                "-c",
                "import pathlib; import mcp, srctools, jsonschema; import cli_anything.hammerplusplus as package; assert pathlib.Path(package.__file__).resolve().parent == pathlib.Path("
                + repr(str(checkout / "cli_anything/hammerplusplus"))
                + "); "
                + ("import pywinauto, PIL; " if os.name == "nt" else "")
                + ("import yaml" if hermes else ""),
            ],
            capture_output=True,
        )
        stamp = checkout / ".local/agent-setup/runtime.json"
        fingerprint = sha((checkout / "pyproject.toml").read_bytes())
        installed = json.loads(stamp.read_text()) if stamp.exists() else {}
        if (
            probe.returncode
            or not command.is_file()
            or installed
            and installed.get("pyproject_sha256") != fingerprint
        ):
            packages = [str(checkout) + "[mcp,source,desktop]"]
            if hermes:
                packages += ["PyYAML==6.0.3"]
            subprocess.run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "-e",
                    *packages,
                ],
                check=True,
                stdout=sys.stderr,
            )
        atomic(stamp, json.dumps({"pyproject_sha256": fingerprint}).encode())
    return python, command


def verify_server(python, command, workspace):
    """Exercise the exact registered stdio command, with no model/API account."""
    code = """import asyncio, json, sys
from datetime import timedelta
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
async def check():
    params = StdioServerParameters(command=sys.argv[1], args=["--workspace", sys.argv[2], "mcp"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as session:
            initialized = await session.initialize()
            tools = await session.list_tools()
            resources = await session.list_resources()
            prompts = await session.list_prompts()
            doctor = await session.call_tool("doctor", {})
            if doctor.isError:
                raise RuntimeError(str(doctor.structuredContent))
            print(json.dumps({"server": initialized.serverInfo.name, "tool_count": len(tools.tools), "resources": [str(r.uri) for r in resources.resources], "prompts": [p.name for p in prompts.prompts], "doctor": doctor.structuredContent}))
asyncio.run(check())
"""
    result = subprocess.run(
        [str(python), "-c", code, str(command), str(workspace)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode:
        raise ValueError("MCP smoke test failed: " + result.stderr[-4000:])
    return json.loads(result.stdout)


def parser():
    result = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    result.add_argument(
        "--client",
        action="append",
        choices=(*CLIENTS, "auto"),
        help="Client to configure; repeat for multiple clients (default: detect installed clients)",
    )
    result.add_argument(
        "--scope",
        choices=("project", "user"),
        default="project",
        help="Registration/skill scope; Hermes requires user/profile scope (default: project)",
    )
    result.add_argument(
        "--workspace",
        type=Path,
        default=CHECKOUT,
        help="Absolute map workspace and project config root (default: this checkout)",
    )
    result.add_argument(
        "--name", default="mapwright", help="MCP server name (default: mapwright)"
    )
    result.add_argument(
        "--home",
        type=Path,
        help="Explicit client home, useful for isolated profiles/tests; ignores environment profile overrides",
    )
    result.add_argument(
        "--native",
        choices=("auto", "off", "required"),
        default="auto",
        help="Reuse/detect native tools, skip them, or require an owned runtime (default: auto)",
    )
    result.add_argument(
        "--runtime",
        type=Path,
        help="Owned legacy CS:GO runtime when automatic discovery is insufficient",
    )
    result.add_argument(
        "--yes",
        action="store_true",
        help="Apply the resolved setup or rollback without an interactive prompt",
    )
    result.add_argument(
        "--rollback",
        type=Path,
        help="Restore files from an installer receipt; refuses subsequent edits, requires --yes to apply",
    )
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    result = None
    try:
        if args.rollback:
            result = rollback(args.rollback.resolve(), args.yes)
        else:
            if not re.fullmatch(r"[a-zA-Z0-9_-]+", args.name):
                raise ValueError(
                    "Server name must contain only letters, digits, underscores and hyphens"
                )
            workspace = args.workspace.resolve()
            home = (args.home or Path.home()).resolve()
            environ = {} if args.home else os.environ
            clients = list(dict.fromkeys(args.client or ["auto"]))
            skipped = []
            if "auto" in clients:
                detected = detect_clients(workspace, home, environ)
                if (
                    args.scope == "project"
                    and "hermes" in detected
                    and "hermes" not in clients
                ):
                    detected.remove("hermes")
                    skipped.append("Hermes: profile-scoped MCP requires --scope user")
                clients = list(
                    dict.fromkeys([c for c in clients if c != "auto"] + detected)
                )
            if not clients:
                raise ValueError(
                    "No client detected; select --client codex|claude|opencode|antigravity|pi|hermes"
                )
            # Resolve scope and reject malformed config before installing packages.
            targets = [
                (client, *locations(client, args.scope, workspace, home, environ))
                for client in clients
            ]
            python, command = bootstrap(CHECKOUT)
            native_changes, native = native_plan(
                CHECKOUT, workspace, args.native, args.runtime, environ
            )
            if (
                args.yes
                and "hermes" in clients
                and importlib.util.find_spec("yaml") is None
            ):
                python, command = bootstrap(CHECKOUT, True, True)
                os.execv(
                    str(python),
                    [
                        str(python),
                        str(Path(__file__)),
                        *(argv if argv is not None else sys.argv[1:]),
                    ],
                )
            changes = list(native_changes)
            skill_roots = set()
            deferred_yaml = []
            for client, config, skills in targets:
                if client == "hermes" and importlib.util.find_spec("yaml") is None:
                    deferred_yaml.append(str(config))
                else:
                    changes.append(
                        plan_registration(
                            client,
                            config,
                            args.name,
                            registration(client, command, workspace),
                        )
                    )
                if skills not in skill_roots:
                    changes += skill_changes(skills, CHECKOUT, command, workspace)
                    skill_roots.add(skills)
                if client == "antigravity" and args.scope == "user":
                    cli_skills = home / ".gemini/antigravity-cli/skills"
                    changes += skill_changes(cli_skills, CHECKOUT, command, workspace)
            result = {
                "status": "planned-with-prerequisites" if deferred_yaml else "planned",
                "clients": clients,
                "skipped_clients": skipped,
                "scope": args.scope,
                "workspace": str(workspace),
                "command": str(command),
                "native": native,
                "files": [str(c.path) for c in changes if c.before != c.after]
                + deferred_yaml,
                "prerequisites": (
                    [
                        "Hermes YAML validation requires setup-only PyYAML; --yes bootstraps it before configuration writes"
                    ]
                    if deferred_yaml
                    else []
                ),
                "registrations": [
                    {
                        "client": client,
                        "configuration": str(config),
                        "name": args.name,
                        "server": registration(client, command, workspace),
                    }
                    for client, config, _ in targets
                ],
                "runtime_install": "repo .venv, editable [mcp,source,desktop]; no Node or REA required",
                "reload": "Reload MCP/skills or start a new client session; existing conversations may retain their old tool catalog",
            }
            if args.yes:
                python, command = bootstrap(CHECKOUT, True, "hermes" in clients)
                receipt = apply_changes(changes, workspace)
                result.update(
                    status="applied", receipt=str(receipt) if receipt else None
                )
                if native["status"] == "install":
                    subprocess.run(
                        [
                            str(python),
                            str(CHECKOUT / "scripts/setup_local.py"),
                            "--workspace",
                            str(workspace),
                            "--runtime",
                            native["runtime"],
                        ],
                        check=True,
                        stdout=sys.stderr,
                    )
                    result["native"]["status"] = "installed"
                result["verification"] = verify_server(python, command, workspace)
        print(json.dumps({"ok": True, "data": result}, indent=2))
        return 0
    except (
        ValueError,
        OSError,
        subprocess.SubprocessError,
        tomllib.TOMLDecodeError,
    ) as exc:
        failure = {"ok": False, "error": str(exc)}
        if result is not None:
            failure["details"] = result
        print(json.dumps(failure))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
