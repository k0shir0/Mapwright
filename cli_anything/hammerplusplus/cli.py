"""JSON CLI, usable from any directory after installation."""

import argparse
import json
from pathlib import Path
import shlex
import sys

from .api import TOOLS, execute
from .backend import BackendError, load_config
from .project import Project
from .vmf import MapError


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise MapError(message)


def parser():
    root = Parser(
        prog="hammer-agent",
        description="Local JSON CLI and MCP for legacy CS:GO Hammer++ mapping.",
    )
    root.add_argument(
        "--workspace",
        default=".",
        help="Root for all map reads, edits and output artifacts",
    )
    root.add_argument(
        "--config",
        default="hammer-agent.local.json",
        help="Configuration file inside the workspace",
    )
    root.add_argument(
        "--json",
        action="store_true",
        help="Compact JSON output (JSON is always the output format)",
    )
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help=TOOLS["doctor"]["description"])
    new = commands.add_parser("new", help="Create a VMF without overwrite")
    new.add_argument("path")
    new.add_argument("--template", choices=["empty", "csgo-room"], default="empty")
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
    capture = commands.add_parser("editor-capture")
    capture.add_argument("pid", type=int)
    capture.add_argument("output")
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
    try:
        args = vars(parser().parse_args(argv))
        compact = args.pop("json")
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
            print("Hammer++ agent CLI. Type help or exit.", file=sys.stderr)
            while True:
                try:
                    line = input("hammer> ")
                except EOFError:
                    break
                if line.strip() in ("exit", "quit"):
                    break
                if line.strip() == "help":
                    parser().print_help(file=sys.stderr)
                elif line.strip():
                    try:
                        main(
                            [
                                "--workspace",
                                str(project.root),
                                "--config",
                                config_name,
                                *shlex.split(line),
                            ]
                        )
                    except SystemExit:
                        pass
            return 0
        else:
            action = {
                "new": "create_map",
                "inspect": "inspect_map",
                "object": "inspect_object",
                "validate": "validate_map",
                "edit": "edit_map",
                "history": "map_history",
                "undo": "undo_map",
                "redo": "redo_map",
                "compile": "compile_map",
                "editor-open": "open_editor",
                "editor-capture": "capture_editor",
                "entities": "entity_catalog",
                "assets": "asset_catalog",
                "rea-probe": "rea_probe",
            }.get(command, command)
            if command == "call":
                action = args["tool"]
                args = read_json(args["arguments"])
            if "expect" in args:
                args["expected_revision"] = args.pop("expect")
            if "ops" in args:
                args["operations"] = read_json(args.pop("ops"))
            data = execute(project, config, action, args)
            result = {"ok": True, "data": data}
            if action == "validate_map" and not data["valid"]:
                result["ok"] = False
    except (ValueError, OSError, TypeError, KeyError, TimeoutError) as exc:
        result = {"ok": False, "error": str(exc)}
        if isinstance(exc, BackendError):
            result["details"] = exc.details
    print(
        json.dumps(
            result, indent=None if compact else 2, ensure_ascii=False, allow_nan=False
        )
    )
    return 0 if result["ok"] else 1


def entrypoint():
    sys.exit(main())


if __name__ == "__main__":
    entrypoint()
