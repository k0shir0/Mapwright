import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from cli_anything.hammerplusplus.api import TOOLS

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / ".local/test-runs"
RUNS.mkdir(parents=True, exist_ok=True)


def resolve_cli():
    name = "mapwright"
    executable = shutil.which(name)
    if executable:
        return [executable]
    if os.environ.get("CLI_ANYTHING_FORCE_INSTALLED") == "1":
        raise RuntimeError("Install the CLI and add its Scripts/bin directory to PATH")
    return [sys.executable, "-m", "cli_anything.hammerplusplus"]


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=RUNS)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_cli(self, *args, success=True):
        result = subprocess.run(
            [*resolve_cli(), "--workspace", str(self.root), "--json", *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            result.returncode, 0 if success else 1, result.stderr + result.stdout
        )
        self.assertNotIn("Traceback", result.stderr)
        return json.loads(result.stdout)

    def test_every_command_and_flag_has_help_and_tool_coverage(self):
        from cli_anything.hammerplusplus.cli import COMMANDS, parser

        root = parser()
        commands = next(
            a for a in root._actions if isinstance(a, argparse._SubParsersAction)
        ).choices
        self.assertEqual(set(TOOLS), set(COMMANDS.values()) | {"doctor"})
        for name, command in [("root", root), *commands.items()]:
            with self.subTest(command=name):
                self.assertTrue(command.description)
                self.assertIn("usage:", command.format_help())
                for argument in command._actions:
                    if not isinstance(argument, argparse._SubParsersAction):
                        self.assertTrue(argument.help, (name, argument.dest))

    def test_complete_editing_workflow_and_stale_revision(self):
        created = self.run_cli("new", "room.vmf", "--template", "csgo-room")["data"]
        self.assertEqual(created["counts"]["solid"], 6)
        self.assertEqual(created["counts"]["entity"], 3)
        revision = created["revision"]
        ops = self.root / "operations.json"
        ops.write_text(
            json.dumps([{"op": "add_box", "min": [-32, -32, 0], "max": [32, 32, 64]}])
        )
        edited = self.run_cli(
            "edit", "room.vmf", "--expect", revision, "--ops", "@" + str(ops)
        )["data"]
        self.assertNotEqual(edited["revision"], revision)
        self.assertTrue(self.run_cli("validate", "room.vmf")["data"]["valid"])
        self.run_cli(
            "edit",
            "room.vmf",
            "--expect",
            revision,
            "--ops",
            "@" + str(ops),
            success=False,
        )
        self.run_cli("undo", "room.vmf", "--expect", edited["revision"])
        self.assertEqual(
            self.run_cli("inspect", "room.vmf")["data"]["revision"], revision
        )
        self.run_cli("redo", "room.vmf", "--expect", revision)
        self.assertEqual(self.run_cli("history", "room.vmf")["data"]["position"], 1)

    def test_help_schema_errors_and_missing_backend(self):
        result = subprocess.run(
            [*resolve_cli(), "--help"], capture_output=True, text=True, timeout=30
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(set(self.run_cli("schema")["data"]), set(TOOLS))
        self.run_cli("new", "map.vmf")
        self.assertEqual(
            self.run_cli("object", "map.vmf", "1")["data"]["kind"], "world"
        )
        self.assertEqual(
            self.run_cli("object", "map.vmf", "1", "--kind", "world")["data"]["kind"],
            "world",
        )
        self.run_cli("new", "map.vmf", success=False)
        self.run_cli(
            "call", "inspect_map", '{"path":"map.vmf","limit":false}', success=False
        )
        revision = self.run_cli("inspect", "map.vmf")["data"]["revision"]
        failed = self.run_cli("compile", "map.vmf", "--expect", revision, success=False)
        self.assertIn("game_dir", failed["error"])

    def test_installed_command_outside_repo(self):
        # This Python test starts outside the checkout, without relying on cwd/PYTHONPATH.
        code = (
            "import subprocess,json; r=subprocess.run("
            + repr([*resolve_cli(), "--workspace", str(self.root), "--json", "doctor"])
            + ',capture_output=True,text=True,check=True); assert json.loads(r.stdout)["ok"]'
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_actual_mcp_sdk_stdio_session(self):
        import anyio
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def scenario():
            params = StdioServerParameters(
                command=resolve_cli()[0],
                args=[*resolve_cli()[1:], "--workspace", str(self.root), "mcp"],
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    self.assertEqual(initialized.serverInfo.name, "mapwright")
                    tools = await session.list_tools()
                    self.assertEqual({tool.name for tool in tools.tools}, set(TOOLS))
                    created = await session.call_tool(
                        "create_map", {"path": "mcp.vmf", "template": "csgo-room"}
                    )
                    self.assertFalse(created.isError)
                    result = json.loads(created.content[0].text)
                    self.assertEqual(created.structuredContent, result)
                    revision = result["data"]["revision"]
                    edited = await session.call_tool(
                        "edit_map",
                        {
                            "path": "mcp.vmf",
                            "expected_revision": revision,
                            "operations": [
                                {
                                    "op": "add_entity",
                                    "classname": "logic_relay",
                                    "origin": [0, 0, 32],
                                }
                            ],
                        },
                    )
                    self.assertFalse(edited.isError)
                    stale = await session.call_tool(
                        "edit_map",
                        {
                            "path": "mcp.vmf",
                            "expected_revision": revision,
                            "operations": [{"op": "delete", "id": 1}],
                        },
                    )
                    self.assertTrue(stale.isError)
                    escaped = await session.call_tool(
                        "inspect_map", {"path": "../escape.vmf"}
                    )
                    self.assertTrue(escaped.isError)
                    malformed = await session.call_tool(
                        "inspect_map", {"path": "mcp.vmf", "limit": False}
                    )
                    self.assertTrue(malformed.isError)
                    self.assertFalse(json.loads(malformed.content[0].text)["ok"])
                    imported = await session.call_tool(
                        "import_reference_map",
                        {
                            "source": str(self.root / "mcp.vmf"),
                            "output": "reference.vmf",
                        },
                    )
                    self.assertFalse(imported.isError)
                    found = await session.call_tool(
                        "search_reference_map",
                        {"path": "reference.vmf", "query": "logic_relay"},
                    )
                    selection = found.structuredContent["data"]["objects"][0]
                    current = await session.call_tool(
                        "inspect_map", {"path": "mcp.vmf"}
                    )
                    copied = await session.call_tool(
                        "copy_reference_objects",
                        {
                            "source": "reference.vmf",
                            "destination": "mcp.vmf",
                            "source_revision": imported.structuredContent["data"][
                                "revision"
                            ],
                            "expected_revision": current.structuredContent["data"][
                                "revision"
                            ],
                            "selection": [{"id": selection["id"], "kind": "entity"}],
                        },
                    )
                    self.assertFalse(copied.isError)
                    deleted = await session.call_tool(
                        "delete_map_file",
                        {
                            "path": "reference.vmf",
                            "expected_revision": imported.structuredContent["data"][
                                "revision"
                            ],
                        },
                    )
                    self.assertFalse(deleted.isError)
                    self.assertFalse((self.root / "reference.vmf").exists())
                    restored = await session.call_tool(
                        "restore_map_file",
                        {"token": deleted.structuredContent["data"]["token"]},
                    )
                    self.assertFalse(restored.isError)
                    self.assertTrue((self.root / "reference.vmf").exists())
                    self.assertEqual(
                        restored.structuredContent["data"]["revision"],
                        imported.structuredContent["data"]["revision"],
                    )

        anyio.run(scenario)


if __name__ == "__main__":
    unittest.main()
