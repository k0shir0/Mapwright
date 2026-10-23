"""Install Mapwright locally and register persistent MCP and portable agent skills.

Run without --yes to inspect the resolved plan. No client configuration is
written until the entire plan has been validated. Agent setup is independent
of the optional REA development tools.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts._support import JsonArgumentParser, emit, report_failure, run

import argparse
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import uuid
from urllib.parse import quote

CHECKOUT = Path(__file__).resolve().parents[1]
CLIENTS = ("codex", "claude", "opencode", "antigravity", "pi", "hermes")
GUIDES = (
    "kz-mapping.md",
    "reference-maps.md",
    "recovery.md",
    "setup.md",
)
SKILL_GUIDES = {"mapwright": GUIDES, "mapwright-setup": ("agent-connections.md",)}


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
            if change.after is None:
                change.path.unlink()
            else:
                atomic(change.path, change.after)
            applied.append(change)
        manifest["status"] = "applied"
    except BaseException:
        # Keep recovery possible if automatic unwinding itself fails or the
        # process exits between restores. Only declare completion after all writes.
        manifest["status"] = "rolling-back"
        atomic(receipt, json.dumps(manifest, indent=2).encode())
        for change in reversed(applied):
            if read(change.path) != change.after:
                manifest["status"] = "rollback-conflict"
                continue
            if change.before is None:
                change.path.unlink()
            else:
                atomic(change.path, change.before)
        if manifest["status"] != "rollback-conflict":
            manifest["status"] = "rolled-back"
        raise
    finally:
        atomic(receipt, json.dumps(manifest, indent=2).encode())
    return receipt


def rollback(receipt, apply=False):
    manifest = json.loads(receipt.read_text("utf-8"))
    if manifest.get("version") != 1 or manifest.get("status") not in (
        "applied",
        "applying",
        "rolling-back",
        "rollback-conflict",
    ):
        raise ValueError(
            "Receipt must describe an applied or interrupted setup/rollback transaction"
        )
    resuming = manifest["status"] != "applied"
    changes = []
    for entry in manifest["files"]:
        path = Path(entry["path"])
        current = read(path)
        current_hash = sha(current)
        if current_hash != entry["after"] and not (
            resuming and current_hash == entry["before"]
        ):
            raise ValueError(f"Refusing rollback over later changes: {path}")
        before = None
        if entry["before"] is not None:
            backup = (receipt.parent / entry["backup"]).resolve()
            if not backup.is_relative_to(receipt.parent.resolve()):
                raise ValueError("Backup path escapes receipt directory")
            before = backup.read_bytes()
            if sha(before) != entry["before"]:
                raise ValueError("Backup digest mismatch")
        changes.append((path, before, entry["after"]))
    if apply:
        # Persist intent before the first file write. A restarted rollback accepts
        # only the recorded before/after bytes, and preflights the entire scope.
        manifest["status"] = "rolling-back"
        atomic(receipt, json.dumps(manifest, indent=2).encode())
        for path, before, expected in reversed(changes):
            current = read(path)
            if current == before:
                continue
            if sha(current) != expected:
                raise ValueError(f"Refusing rollback over later changes: {path}")
            if before is None:
                path.unlink()
            else:
                atomic(path, before)
        manifest["status"] = "rolled-back"
        atomic(receipt, json.dumps(manifest, indent=2).encode())
    return {
        "status": "rolled-back" if apply else "planned",
        "files": [str(p) for p, _, _ in changes],
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
        for guide in (*GUIDES, "agent-connections.md"):
            owner = (
                name
                if guide in SKILL_GUIDES[name]
                else ("mapwright" if guide in GUIDES else "mapwright-setup")
            )
            target = (
                f"references/{guide}"
                if owner == name
                else f"../{owner}/references/{guide}"
            )
            text = text.replace(f"../../docs/{guide}", target)
        text = text.replace(
            "../../scripts/setup_agent.py",
            quote((checkout / "scripts/setup_agent.py").as_posix(), safe="/:"),
        )
        files = {
            dest / "SKILL.md": text.encode(),
            marker: (json.dumps(metadata, indent=2) + "\n").encode(),
            dest
            / "scripts/resolve_installation.py": (
                checkout / "skills/mapwright/scripts/resolve_installation.py"
            ).read_bytes(),
        }
        for guide in SKILL_GUIDES[name]:
            contents = (checkout / "docs" / guide).read_text("utf-8")
            for other in (*GUIDES, "agent-connections.md"):
                if other not in SKILL_GUIDES[name]:
                    owner = "mapwright" if other in GUIDES else "mapwright-setup"
                    contents = contents.replace(
                        f"]({other}", f"](../../{owner}/references/{other}"
                    )
            contents = contents.replace(
                "../skills/mapwright-setup/SKILL.md", "../../mapwright-setup/SKILL.md"
            )
            for relative in ("../scripts/setup_local.py", "../mapwright.example.json"):
                contents = contents.replace(
                    relative, quote((checkout / relative[3:]).as_posix(), safe="/:")
                )
            files[dest / "references" / guide] = contents.encode()
        for guide in (*GUIDES, "agent-connections.md"):
            old = dest / "references" / guide
            if guide not in SKILL_GUIDES[name] and marker.exists() and old.is_file():
                previous = (checkout / "docs" / guide).read_text("utf-8")
                previous = previous.replace(
                    "../skills/mapwright-setup/SKILL.md",
                    "../../mapwright-setup/SKILL.md",
                )
                for relative in (
                    "../scripts/setup_local.py",
                    "../mapwright.example.json",
                ):
                    previous = previous.replace(
                        relative, (checkout / relative[3:]).as_posix()
                    )
                if read(old) == previous.encode():
                    changes.append(Change(old, read(old), None))
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
    return (
        (path / "csgo/gameinfo.txt").is_file()
        and (path / "csgo/pak01_dir.vpk").is_file()
        and all((path / "bin" / name).is_file() for name in required)
    )


def runtime_candidates(checkout, environ):
    candidates = [checkout / ".local/csgo-sdk"]
    # Generated editor gameinfo mounts are not recursively inherited by Source.
    # Recover their original content runtime rather than mounting the empty shim.
    for receipt in (checkout / ".local").glob("csgo-editor*/installation.json"):
        try:
            data = json.loads(receipt.read_text("utf-8"))
            original = data.get("runtime") if isinstance(data, dict) else None
            if isinstance(original, str):
                candidates.append(Path(original))
        except (ValueError, OSError):
            continue
    steam = Path(environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam"
    libraries = [steam, checkout / ".local/csgo-sdk"]
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
    if runtime:
        runtime = runtime.expanduser().resolve()
        if not is_native_runtime(runtime):
            raise ValueError(
                "Selected runtime needs legacy CS:GO bin DLLs, csgo/gameinfo.txt and csgo/pak01_dir.vpk (owned game content)"
            )
    if mode == "required" and os.name != "nt":
        raise ValueError(
            "Native Hammer++ requires Windows; use --native off for portable VMF/MCP tools"
        )
    stale = []
    for candidate in dict.fromkeys(
        (
            target,
            workspace / "hammer-agent.local.json",
            checkout / "mapwright.local.json",
            checkout / "hammer-agent.local.json",
        )
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
            game = (
                candidate.parent / Path(config.get("game_dir", "")).expanduser()
            ).resolve()
            missing = [
                key
                for key in ("hammer", "vbsp", "vvis", "vrad", "bspsrc_java")
                if key not in config
                or not (candidate.parent / Path(config[key]).expanduser()).is_file()
            ]
            if not (game / "gameinfo.txt").is_file():
                missing.append("game_dir/gameinfo.txt")
            fgds = config.get("fgd", [])
            fgds = [fgds] if isinstance(fgds, str) else fgds
            if not fgds or not all(
                (candidate.parent / Path(p).expanduser()).is_file() for p in fgds
            ):
                missing.append("fgd")
            editor = candidate.parent / Path(config.get("hammer", "")).expanduser()
            missing += [
                name
                for name in (
                    "tier0.dll",
                    "vstdlib.dll",
                    "filesystem_stdio.dll",
                    "materialsystem.dll",
                    "shaderapidx9.dll",
                )
                if not (editor.parent / name).is_file()
            ]
            if missing:
                stale.append({"configuration": str(candidate), "missing": missing})
                continue
            # An explicit runtime replaces reused tools only after the new install succeeds.
            if runtime:
                continue
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
                Change(
                    target,
                    read(target),
                    (json.dumps(normalized, indent=2) + "\n").encode(),
                )
            ], {"status": "reuse", "configuration": str(target)}
    candidates = (
        [runtime]
        if runtime
        else list(
            dict.fromkeys(
                runtime_candidates(workspace, environ)
                + runtime_candidates(checkout, environ)
            )
        )
    )
    if candidates and os.name == "nt":
        install = workspace / ".local/csgo-editor"
        if install.exists():
            install = install.with_name("csgo-editor-" + uuid.uuid4().hex[:12])
        return [], {
            "status": "install",
            "runtime": str(candidates[0]),
            "configuration": str(target),
            "install_dir": str(install.relative_to(workspace)),
            "stale_configurations": stale,
        }
    if mode == "required":
        raise ValueError(
            "No owned legacy CS:GO runtime detected; supply --runtime or restore an entitled legacy installation. "
            + (
                "Missing configured prerequisites: " + json.dumps(stale)
                if stale
                else ""
            )
        )
    return [], {
        "status": "offline",
        "reason": "No owned Windows legacy CS:GO runtime detected; VMF/MCP remain available",
        "stale_configurations": stale,
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
        cfg = checkout / ".venv/pyvenv.cfg"
        if not python.is_file():
            subprocess.run(
                [sys.executable, "-I", "-m", "venv", str(checkout / ".venv")],
                check=True,
                timeout=120,
                stdout=sys.stderr,
            )
        elif not cfg.is_file():
            raise ValueError(
                "Existing .venv is invalid; preserve it elsewhere and rerun setup to recreate it"
            )
        else:
            text = cfg.read_text("utf-8")
            isolated = re.sub(
                r"(?im)^(include-system-site-packages\s*=\s*)true\s*$",
                r"\g<1>false",
                text,
            )
            if isolated != text:
                # The active interpreter may live here; avoid replacing Windows' locked launcher.
                atomic(cfg, isolated.encode())
        probe = subprocess.run(
            [
                str(python),
                "-I",
                "-c",
                "import pathlib, sys, site; assert sys.version_info >= (3, 11); assert sys.prefix != sys.base_prefix; assert not site.ENABLE_USER_SITE; import mcp, srctools, jsonschema; import cli.hammerplusplus as package; assert pathlib.Path(package.__file__).resolve().parent == pathlib.Path("
                + repr(str(checkout / "cli/hammerplusplus"))
                + "); "
                + ("import win32api, win32job, PIL, frida; " if os.name == "nt" else "")
                + ("import yaml" if hermes else ""),
            ],
            capture_output=True,
            timeout=30,
        )
        stamp = checkout / ".local/agent-setup/runtime.json"
        fingerprint = sha((checkout / "pyproject.toml").read_bytes())
        installed = json.loads(stamp.read_text()) if stamp.exists() else {}
        if (
            probe.returncode
            or not command.is_file()
            or installed.get("pyproject_sha256") != fingerprint
        ):
            packages = [str(checkout) + "[mcp,source,desktop]"]
            if hermes:
                packages += ["PyYAML==6.0.3"]
            subprocess.run(
                [
                    str(python),
                    "-I",
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "-e",
                    *packages,
                ],
                check=True,
                stdout=sys.stderr,
                timeout=600,
            )
        subprocess.run(
            [str(python), "-I", "-m", "pip", "check"],
            check=True,
            stdout=sys.stderr,
            timeout=60,
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
    result = JsonArgumentParser(
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
    result = None
    try:
        args = parser().parse_args(argv)
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
            native_before = read(workspace / "mapwright.local.json")
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
                "reload": "Use supported client reload; otherwise continue through the installed absolute CLI command now. Persistent MCP/skills load in future client sessions",
            }
            if args.yes:
                python, command = bootstrap(CHECKOUT, True, "hermes" in clients)
                if native["status"] == "install":
                    workspace.mkdir(parents=True, exist_ok=True)
                    generated = (
                        workspace
                        / ".local/agent-setup"
                        / (uuid.uuid4().hex + "-native.json")
                    )
                    subprocess.run(
                        [
                            str(python),
                            str(CHECKOUT / "scripts/setup_local.py"),
                            "--workspace",
                            str(workspace),
                            "--runtime",
                            native["runtime"],
                            "--install-dir",
                            native["install_dir"],
                            "--output-config",
                            str(generated.relative_to(workspace)),
                        ],
                        check=True,
                        stdout=sys.stderr,
                        timeout=1800,
                    )
                    target = workspace / "mapwright.local.json"
                    changes.append(
                        Change(target, native_before, generated.read_bytes())
                    )
                    result["native"]["status"] = "installed"
                receipt = apply_changes(changes, workspace)
                result.update(
                    status="applied", receipt=str(receipt) if receipt else None
                )
                result["verification"] = verify_server(python, command, workspace)
                if args.native == "required":
                    doctor = result["verification"]["doctor"]["data"]
                    missing = [
                        key
                        for key in (
                            "editor_ready",
                            "compile_ready",
                            "fgd_ready",
                            "decompile_ready",
                            "viewport_profile_ready",
                        )
                        if not doctor.get(key)
                    ]
                    if missing:
                        raise ValueError(
                            "Native prerequisites are incomplete: " + ", ".join(missing)
                        )
        emit({"ok": True, "data": result})
        return 0
    except (
        ValueError,
        OSError,
        subprocess.SubprocessError,
        tomllib.TOMLDecodeError,
    ) as exc:
        return report_failure(exc, result)


if __name__ == "__main__":
    raise SystemExit(run(main))
