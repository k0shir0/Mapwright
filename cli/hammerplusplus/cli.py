"""JSON CLI, usable from any directory after installation."""

import argparse
import json
from pathlib import Path
import shlex
import sys

from .api import TOOLS, OPERATIONS, KZ_TOOLS, execute
from .backend import BackendError, load_config
from .project import Project
from .vmf import MapError

ARGUMENT_HELP = {
    "path": "VMF path relative to the configured workspace",
    "expected_revision": "Current SHA-256 revision from inspect; stale writes are refused",
    "operations": "Atomic edit operations as a JSON array or @file (process-CWD-relative)",
    "query": "Case-insensitive text to match; empty matches all entries",
    "offset": "Zero-based offset for the next page",
    "limit": "Maximum entries or source characters to return in this page",
    "token": "Recovery/checkpoint token returned by the corresponding operation",
    "pid": "Owned Hammer process ID returned by editor-open",
    "template": "Initial map contents; kz-room includes GOKZ timer zones and spawns",
    "id": "VMF object ID; supply kind when IDs are reused across namespaces",
    "kind": "Object namespace or catalog category to inspect",
    "dry_run": "Preview the result without changing authoring files",
    "mode": "bsp runs VBSP only; fast/full also run VVIS and HDR VRAD",
    "timeout": "Total operation deadline in seconds",
    "output": "New output path inside the workspace; existing files are preserved",
    "method": "auto tries native GPU readback; viewport requires it; window captures UI chrome",
    "classname": "Exact entity class to describe, including inherited FGD fields",
    "target": "Configured native executable to inspect with REA",
    "after": "Return actions after this stable sequence cursor (zero starts history)",
    "action_id": "Permanent action ID returned in a result's timeline field",
    "expected_head": "Current timeline HEAD from timeline-status; prevents stale checkout",
    "category": "Artifact category to list; empty includes all categories",
    "paths": "Workspace files or folders to include in the recoverable checkpoint",
    "label": "Description retained with the checkpoint",
    "minimum": "Minimum X Y Z coordinates of the spatial search bounds",
    "maximum": "Maximum X Y Z coordinates of the spatial search bounds",
    "start": "Starting solid or side selector as JSON or @file",
    "end": "Landing solid or side selector as JSON or @file",
    "landing": "Landing solid or top-face selector as JSON or @file",
    "minimum_mbh": "Server-specific minimum multibhop distance in Source units",
    "min": "Exterior minimum X Y Z coordinates (room bounds are interior)",
    "max": "Exterior maximum X Y Z coordinates (room bounds are interior)",
    "material": "Material name without materials/ prefix or .vmt extension",
    "face_materials": "JSON object of per-face material overrides or @file",
    "parent_id": "World/entity ID which will own the new brush",
    "parent_kind": "Namespace of parent-id; world or entity",
    "thickness": "Positive room wall thickness in Source units",
    "origin": "Entity origin X Y Z in Source units",
    "properties": "JSON keyvalues or @file; null deletes a key in set-properties",
    "event": "Output event name, such as OnStartTouch",
    "input": "Input invoked on the output target entity",
    "parameter": "Optional output input parameter",
    "delay": "Nonnegative output delay in seconds",
    "times": "Number of firings; -1 means unlimited",
    "delta": "Translation X Y Z in Source units with texture lock",
    "source": "Native VMF source text or @file for replace-source; external file for import-reference",
    "tool": "Shared MCP tool name to call; schema describes its JSON arguments",
}


class Parser(argparse.ArgumentParser):
    def add_argument(self, *args, **kwargs):
        if "help" not in kwargs:
            dest = kwargs.get("dest", args[0].lstrip("-").replace("-", "_"))
            key = {"expect": "expected_revision", "ops": "operations"}.get(dest, dest)
            field = getattr(self, "tool_schema", {}).get("properties", {}).get(key, {})
            kwargs["help"] = field.get("description") or ARGUMENT_HELP.get(key)
            if not kwargs["help"]:
                kwargs["help"] = key.replace("_", " ").capitalize()
            if "default" in kwargs and kwargs["default"] not in (
                None,
                argparse.SUPPRESS,
            ):
                kwargs["help"] += " (default: %(default)s)"
        return super().add_argument(*args, **kwargs)

    def error(self, message):
        raise MapError(message)


COMMANDS = {
    "files": "list_map_files",
    "source": "read_map_source",
    "delete-file": "delete_map_file",
    "restore-file": "restore_map_file",
    "import-reference": "import_reference_map",
    "find": "search_reference_map",
    "editor-state": "inspect_editor",
    "editor-action": "editor_action",
    "copy-reference-objects": "copy_reference_objects",
    "new": "create_map",
    "inspect": "inspect_map",
    "object": "inspect_object",
    "validate": "validate_map",
    "edit": "edit_map",
    "history": "map_history",
    "undo": "undo_map",
    "redo": "redo_map",
    "compile": "compile_map",
    "package": "package_map",
    "editor-open": "open_editor",
    "editor-save": "save_editor",
    "editor-close": "close_editor",
    "editor-capture": "capture_editor",
    "entities": "entity_catalog",
    "assets": "asset_catalog",
    "rea-probe": "rea_probe",
    "logs": "operation_log",
    "artifacts": "list_artifacts",
    "artifact": "read_artifact",
    "checkpoint": "create_checkpoint",
    "checkpoint-state": "inspect_checkpoint",
    "checkpoint-restore": "restore_checkpoint",
    "resume-recovery": "resume_recovery",
    "lock-status": "lock_status",
    "recover-lock": "recover_lock",
    "timeline-status": "timeline_status",
    "action-history": "action_history",
    "action": "inspect_action",
    "checkout-action": "checkout_action",
}
COMMANDS.update({name.replace("_", "-"): name for name in KZ_TOOLS})
COMMANDS["kz-measure"] = "kz_measure_jumps"
COMMANDS.update(
    {
        op["properties"]["op"]["const"].replace("_", "-"): "map_"
        + op["properties"]["op"]["const"]
        for op in OPERATIONS["oneOf"]
    }
)


def parser():
    root = Parser(
        prog="mapwright",
        description="Mapwright KZ-first CLI and MCP for legacy CS:GO mapping in Hammer++.",
    )
    root.add_argument(
        "--workspace",
        default=".",
        help="Root for all map reads, edits and output artifacts",
    )
    root.add_argument(
        "--config",
        default="mapwright.local.json",
        help="Configuration file inside the workspace",
    )
    root.add_argument(
        "--json",
        action="store_true",
        help="Compact JSON output (JSON is always the output format)",
    )
    subparsers = root.add_subparsers(dest="command", required=True)

    class Commands:
        def add_parser(self, name, **kwargs):
            tool = TOOLS.get(COMMANDS.get(name, name), {})
            description = tool.get("description", kwargs.get("help", ""))
            command_parser = subparsers.add_parser(
                name, **{**kwargs, "help": description, "description": description}
            )
            command_parser.tool_schema = tool.get("inputSchema", {})
            if tool:
                command_parser.add_argument(
                    "--response-mode",
                    choices=["bounded", "full"],
                    default=argparse.SUPPRESS,
                    help="Bound large results with evidence links, or return the full result",
                )
            return command_parser

    commands = Commands()
    commands.add_parser("doctor", help=TOOLS["doctor"]["description"])
    files = commands.add_parser("files")
    files.add_argument("--query", default="")
    files.add_argument("--limit", type=int, default=100)
    source = commands.add_parser("source")
    source.add_argument("path")
    source.add_argument("--offset", type=int, default=0)
    source.add_argument("--limit", type=int, default=8000)
    source.add_argument("--expect", default=argparse.SUPPRESS)
    delete = commands.add_parser("delete-file")
    delete.add_argument("path")
    delete.add_argument("--expect", required=True)
    restore = commands.add_parser("restore-file")
    restore.add_argument("token")
    imp = commands.add_parser("import-reference")
    imp.add_argument("source")
    imp.add_argument("output")
    imp.add_argument("--timeout", type=int, default=180)
    find = commands.add_parser("find")
    find.add_argument("path")
    find.add_argument("--query", default="")
    find.add_argument("--kind", choices=["solid", "entity", ""], default="")
    find.add_argument("--offset", type=int, default=0)
    find.add_argument("--limit", type=int, default=100)
    find.add_argument("--minimum", nargs=3, type=float, default=argparse.SUPPRESS)
    find.add_argument("--maximum", nargs=3, type=float, default=argparse.SUPPRESS)
    state = commands.add_parser("editor-state")
    state.add_argument("pid", type=int)
    state.add_argument("--limit", type=int, default=200)
    new = commands.add_parser("new", help="Create a VMF without overwrite")
    new.add_argument("path")
    new.add_argument(
        "--template", choices=["empty", "csgo-room", "kz-room"], default="empty"
    )
    inspect = commands.add_parser(
        "inspect", help="Inspect a map and obtain its current revision"
    )
    inspect.add_argument("path")
    inspect.add_argument("--offset", type=int, default=0)
    inspect.add_argument("--limit", type=int, default=100)
    obj = commands.add_parser("object", help="Inspect an object and its VMF source")
    obj.add_argument("path")
    obj.add_argument("id", type=int)
    obj.add_argument(
        "--kind",
        choices=["world", "entity", "solid", "side", "group"],
        default=argparse.SUPPRESS,
    )
    for command in ("validate", "history", "editor-open"):
        sub = commands.add_parser(command)
        sub.add_argument("path")
        if command == "editor-open":
            sub.add_argument("--timeout", type=int, default=30)
        if command == "history":
            sub.add_argument("--offset", type=int, default=0)
            sub.add_argument("--limit", type=int, default=100)
            sub.add_argument("--expected-history-revision", default=argparse.SUPPRESS)
    for command in ("editor-save", "editor-close"):
        sub = commands.add_parser(command)
        sub.add_argument("pid", type=int)
        if command == "editor-save":
            sub.add_argument("--expect", required=True)
    for command in ("edit", "undo", "redo", "compile"):
        sub = commands.add_parser(command)
        sub.add_argument("path")
        sub.add_argument(
            "--expect", required=True, help="Current map SHA-256 from inspect"
        )
        if command == "edit":
            sub.add_argument(
                "--ops",
                required=True,
                help="JSON operations array or @path-to-json-file",
            )
            sub.add_argument("--dry-run", action="store_true")
        if command == "compile":
            sub.add_argument("--mode", choices=["bsp", "fast", "full"], default="fast")
            sub.add_argument("--timeout", type=int, default=120)
            sub.add_argument(
                "--pack-assets", action=argparse.BooleanOptionalAction, default=True
            )
    package = commands.add_parser("package")
    package.add_argument("build_dir")
    package.add_argument("output")
    capture = commands.add_parser("editor-capture")
    capture.add_argument("pid", type=int)
    capture.add_argument("output")
    capture.add_argument(
        "--method", choices=["auto", "viewport", "window"], default="auto"
    )
    for command in ("entities", "assets"):
        sub = commands.add_parser(command)
        sub.add_argument("--query", default="")
        sub.add_argument("--limit", type=int, default=100)
        if command == "entities":
            sub.add_argument("--classname", default="")
        else:
            sub.add_argument(
                "--kind", choices=["material", "model"], default="material"
            )
    rea = commands.add_parser("rea-probe")
    rea.add_argument("target", choices=["hammer", "vbsp", "vvis", "vrad"])
    for command in ("editor-action", "copy-reference-objects"):
        sub = commands.add_parser(command)
        sub.add_argument(
            "request", help="Tool arguments as JSON or @file (relative to process cwd)"
        )
    for command in ("logs", "artifacts"):
        sub = commands.add_parser(command)
        sub.add_argument("--offset", type=int, default=0)
        sub.add_argument("--limit", type=int, default=100)
        if command == "artifacts":
            sub.add_argument("--category", default="")
    sub = commands.add_parser("artifact")
    sub.add_argument("path")
    sub.add_argument("--offset", type=int, default=0)
    sub.add_argument("--limit", type=int, default=8000)
    sub = commands.add_parser("checkpoint")
    sub.add_argument("paths", nargs="+")
    sub.add_argument("--label", default="")
    for command in ("checkpoint-state", "resume-recovery"):
        sub = commands.add_parser(command)
        sub.add_argument("token")
    sub = commands.add_parser("checkpoint-restore")
    sub.add_argument("token")
    sub.add_argument(
        "--expected-revisions",
        required=True,
        help="JSON object or @file from checkpoint-state current_revisions",
    )
    sub.add_argument("--dry-run", action="store_true")
    commands.add_parser("lock-status")
    sub = commands.add_parser("recover-lock")
    sub.add_argument("--expect", required=True)
    commands.add_parser("timeline-status")
    sub = commands.add_parser("action-history")
    sub.add_argument("--after", type=int, default=0)
    sub.add_argument("--limit", type=int, default=100)
    sub = commands.add_parser("action")
    sub.add_argument("action_id")
    sub.add_argument("--offset", type=int, default=0)
    sub.add_argument("--limit", type=int, default=100)
    sub = commands.add_parser("checkout-action")
    sub.add_argument(
        "target", help="Action ID whose saved after-state will be restored"
    )
    sub.add_argument("--expected-head", required=True)
    sub.add_argument("--dry-run", action="store_true")
    for command, action in COMMANDS.items():
        if action not in KZ_TOOLS:
            continue
        sub = commands.add_parser(command)
        sub.add_argument("path")
        check = KZ_TOOLS[action][0]
        if check == "audit":
            sub.add_argument(
                "--timer-profile", choices=["either", "buttons"], default="either"
            )
        if check in ("audit", "spawns"):
            sub.add_argument("--minimum-t-spawns", type=int, default=1)
            sub.add_argument("--minimum-ct-spawns", type=int, default=1)
        if check in ("measure", "headhitter"):
            sub.add_argument(
                "--start",
                type=read_json,
                required=check == "measure",
                default=argparse.SUPPRESS,
                help='JSON selector e.g. {"id":47,"kind":"solid"}',
            )
            sub.add_argument(
                "--end",
                type=read_json,
                required=check == "measure",
                default=argparse.SUPPRESS,
            )
        if check == "ladders":
            sub.add_argument("--landing", type=read_json, default=argparse.SUPPRESS)
        if check == "bhop":
            sub.add_argument(
                "--route",
                type=read_json,
                default=argparse.SUPPRESS,
                help="Ordered JSON array of 2..1000 landing-solid selectors or @file",
            )
        if check in ("bhop", "measure"):
            sub.add_argument("--minimum-mbh", type=float, default=300)
    for op in OPERATIONS["oneOf"]:
        operation = op["properties"]["op"]["const"]
        sub = commands.add_parser(operation.replace("_", "-"))
        sub.add_argument("path")
        sub.add_argument("--expect", required=True)
        sub.add_argument("--dry-run", action="store_true")
        for key, field in op["properties"].items():
            if key == "op":
                continue
            kwargs = {"required": key in op["required"], "default": argparse.SUPPRESS}
            if field.get("type") == "array":
                kwargs.update(nargs=3, type=float)
            elif field.get("type") == "object":
                kwargs["type"] = read_json
            elif field.get("type") == "integer":
                kwargs["type"] = int
            elif field.get("type") == "number":
                kwargs["type"] = float
            if "enum" in field:
                kwargs["choices"] = field["enum"]
            sub.add_argument("--" + key.replace("_", "-"), **kwargs)
    commands.add_parser(
        "schema", help="Discover every tool and the complete edit operation JSON schema"
    )
    commands.add_parser("mcp", help="Run the stdio MCP server, no network listener")
    commands.add_parser("repl", help="Interactive shell using the same CLI commands")
    call = commands.add_parser(
        "call", help="Call a tool directly with a JSON arguments object"
    )
    call.add_argument("tool", choices=list(TOOLS))
    call.add_argument("arguments", help="JSON object or @path-to-json-file")
    return root


def read_json(value: str):
    return json.loads(
        Path(value[1:]).read_text("utf-8-sig") if value.startswith("@") else value
    )


def main(argv=None):
    compact = False
    check_failed = False
    command = None
    try:
        args = vars(parser().parse_args(argv))
        compact = args.pop("json")
        response_mode = args.pop("response_mode", None)
        workspace, config_name, command = (
            args.pop("workspace"),
            args.pop("config"),
            args.pop("command"),
        )
        project = Project(workspace)
        config = load_config(project, config_name)
        if command == "schema":
            result = {"ok": True, "data": TOOLS}
        elif command == "mcp":
            from .mcp_server import serve

            serve(project, config)
            return 0
        elif command == "repl":
            print("Mapwright CLI. Type help or exit.", file=sys.stderr)
            status = 0
            while True:
                try:
                    line = input("mapwright> ")
                except EOFError:
                    break
                if line.strip() in ("exit", "quit"):
                    break
                if line.strip() == "help":
                    parser().print_help(file=sys.stderr)
                elif line.strip():
                    try:
                        status = max(
                            status,
                            main(
                                [
                                    "--workspace",
                                    str(project.root),
                                    "--config",
                                    config_name,
                                    *shlex.split(line),
                                ]
                            ),
                        )
                    except SystemExit:
                        pass
            return status
        else:
            action = COMMANDS.get(command, command)
            if command == "call":
                action = args["tool"]
                args = read_json(args["arguments"])
            if command in ("editor-action", "copy-reference-objects"):
                args = read_json(args["request"])
            if command == "checkpoint-restore":
                args["expected_revisions"] = read_json(args["expected_revisions"])
            if command == "replace-source" and args["source"].startswith("@"):
                args["source"] = Path(args["source"][1:]).read_text("utf-8-sig")
            if "expect" in args:
                args["expected_revision"] = args.pop("expect")
            if "ops" in args:
                args["operations"] = read_json(args.pop("ops"))
            if response_mode is not None:
                args["response_mode"] = response_mode
            data = execute(project, config, action, args)
            result = {"ok": True, "data": data}
            check_failed = (
                action == "validate_map"
                or action in KZ_TOOLS
                and action != "kz_test_plan"
            ) and not data.get("valid", True)
    except (ValueError, OSError, TypeError, KeyError, TimeoutError) as exc:
        result = {"ok": False, "error": str(exc)}
        if isinstance(exc, BackendError):
            result["details"] = exc.details
        if command == "mcp" and isinstance(exc, PermissionError):
            result["hint"] = (
                "Check the server process's filesystem permissions. A child launched "
                "from a restricted shell inherits its access limits; use the registered "
                "MCP server in the intended client context. See docs/agent-connections.md."
            )
    print(
        json.dumps(
            result, indent=None if compact else 2, ensure_ascii=True, allow_nan=False
        ),
        file=sys.stderr if command == "mcp" else sys.stdout,
    )
    return 0 if result["ok"] and not check_failed else 1


def entrypoint():
    sys.exit(main())


if __name__ == "__main__":
    entrypoint()
