"""Behavior checks for the installed transports, not registry self-comparisons."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from cli.hammerplusplus import catalog, backend
from cli.hammerplusplus.project import Project
from cli.hammerplusplus.api import execute

RUNS = Path(__file__).resolve().parents[1] / ".local/test-runs"
RUNS.mkdir(parents=True, exist_ok=True)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=RUNS)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = Project(self.root)

    def cli(self, *args):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "cli.hammerplusplus",
                "--workspace",
                str(self.root),
                "--json",
                *args,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_cli_flat_operations_and_completed_invalid_checks(self):
        created = json.loads(
            self.cli("new", "kz_test.vmf", "--template", "kz-room").stdout
        )["data"]
        added = self.cli(
            "add-box",
            "kz_test.vmf",
            "--expect",
            created["revision"],
            "--min",
            "0",
            "0",
            "0",
            "--max",
            "32",
            "32",
            "32",
            "--face-materials",
            '{"top":"dev/dev_water2"}',
        )
        self.assertEqual(added.returncode, 0, added.stdout + added.stderr)
        file = self.root / "kz_test.vmf"
        file.write_text(
            file.read_text().replace(
                '"climb_mapping_api_version" "1"', '"climb_mapping_api_version" "V1"'
            )
        )
        checked = self.cli("kz-audit", "kz_test.vmf")
        result = json.loads(checked.stdout)
        self.assertEqual(checked.returncode, 1)
        self.assertTrue(result["ok"])
        self.assertFalse(result["data"]["valid"])
        file.write_text(
            file.read_text().replace(
                '"classname" "worldspawn"', '"classname" "invalid"'
            )
        )
        checked = self.cli("validate", "kz_test.vmf")
        result = json.loads(checked.stdout)
        self.assertEqual(checked.returncode, 1)
        self.assertTrue(result["ok"])
        self.assertFalse(result["data"]["valid"])

    def test_multi_fgd_retains_original_fields_and_bases(self):
        base = self.root / "base.fgd"
        addon = self.root / "kz.fgd"
        base.write_text(
            '@BaseClass = TriggerBase [\n targetname(string) : "Name"\n]\n@SolidClass base(TriggerBase) = trigger_multiple : "base" [\n wait(float) : "Wait" : 1\n output OnStartTouch(void)\n]\n'
        )
        addon.write_text(
            '@SolidClass = trigger_multiple : "KZ" [\n climb_anti_bhop_time(float) : "Time" : 0.2\n]\n'
        )
        config = {"fgd": [str(base), str(addon)]}
        (self.root / "mapwright.local.json").write_text(json.dumps(config))
        loaded = backend.load_config(self.project)
        result = catalog.entities(self.project, loaded, classname="trigger_multiple")
        self.assertTrue(
            {"targetname", "wait", "climb_anti_bhop_time"}
            <= {r["name"] for r in result["keyvalues"]}
        )
        self.assertIn("OnStartTouch", {r["name"] for r in result["outputs"]})
        self.assertTrue(backend.doctor(self.project, loaded)["fgd_ready"])

    def test_setup_merges_gokz_without_stock_bases_or_losing_editor_data(self):
        from scripts.setup_local import merge_kz_fgd

        base = self.root / "base.fgd"
        addon = self.root / "kz.fgd"
        merged = self.root / "merged.fgd"
        base.write_text(
            '// keep editor data [ untouched ]\n@SolidClass = trigger_multiple: "Trigger [description]" [\n targetname(string) : "Name"\n wait(float) : "Wait" : 1\n]\n@SolidClass = worldspawn: "World" [\n skyname(string) : "Sky"\n]\n'
        )
        addon.write_text(
            '@SolidClass base(Trigger) = trigger_multiple [\n\tclimb_teleport_type(choices) : "Type" : 0 = [ 0 : "Normal" ]\n\tclimb_anti_bhop_time(float) : "Time" : 0.2\n\t// Inputs\n]\n@SolidClass base(Targetname, worldbase) = worldspawn [\n\tclimb_mapping_api_version(integer) : "Version" : 1\n]\n'
        )
        merge_kz_fgd(base, addon, merged)
        self.assertIn("// keep editor data [ untouched ]", merged.read_text())
        result = catalog.entities(
            self.project, {"fgd": str(merged)}, classname="trigger_multiple"
        )
        self.assertTrue(
            {"targetname", "wait", "climb_anti_bhop_time"}
            <= {r["name"] for r in result["keyvalues"]}
        )
        combined = catalog.entities(
            self.project, {"fgd": [str(base), str(addon)]}, classname="worldspawn"
        )
        self.assertTrue(combined["warnings"])
        self.assertTrue(
            {"skyname", "climb_mapping_api_version"}
            <= {r["name"] for r in combined["keyvalues"]}
        )

    def test_mcp_discovery_resources_prompt_progress_and_findings(self):
        import anyio
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def scenario():
            params = StdioServerParameters(
                command=sys.executable,
                args=[
                    "-m",
                    "cli.hammerplusplus",
                    "--workspace",
                    str(self.root),
                    "mcp",
                ],
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    initialized = await client.initialize()
                    self.assertIn("KZ-first", initialized.instructions)
                    tools = {t.name: t for t in (await client.list_tools()).tools}
                    for name in (
                        "kz_audit",
                        "kz_measure_jumps",
                        "create_checkpoint",
                        "read_artifact",
                        "map_add_box",
                    ):
                        self.assertIn(name, tools)
                        self.assertIsNotNone(tools[name].outputSchema)
                    self.assertFalse(tools["create_map"].annotations.destructiveHint)
                    self.assertTrue(tools["map_history"].annotations.idempotentHint)
                    self.assertTrue(
                        tools["import_reference_map"].annotations.openWorldHint
                    )
                    self.assertNotIn(
                        "oneOf", json.dumps(tools["map_add_box"].inputSchema)
                    )
                    resources = await client.list_resources()
                    self.assertIn(
                        "hammer://guide/kz", {str(r.uri) for r in resources.resources}
                    )
                    guidance = await client.read_resource("hammer://guide/kz")
                    self.assertIn(">=16u", guidance.contents[0].text)
                    templates = await client.list_resource_templates()
                    self.assertTrue(templates.resourceTemplates)
                    prompts = await client.list_prompts()
                    self.assertIn(
                        "kz_mapping_workflow", {p.name for p in prompts.prompts}
                    )
                    prompt = await client.get_prompt(
                        "kz_mapping_workflow",
                        {"path": "kz_test.vmf", "task": "add a jump"},
                    )
                    self.assertIn("add a jump", prompt.messages[0].content.text)
                    created = await client.call_tool(
                        "create_map", {"path": "kz_test.vmf", "template": "kz-room"}
                    )
                    self.assertFalse(created.isError)
                    cp = await client.call_tool(
                        "create_checkpoint",
                        {"paths": ["kz_test.vmf"], "label": "before"},
                    )
                    token = cp.structuredContent["data"]["token"]
                    artifact = await client.read_resource(
                        f"hammer://artifact/.hammer-agent%2Fcheckpoints%2F{token}.json"
                    )
                    self.assertIn("before", artifact.contents[0].text)
                    progress = []

                    async def callback(value, total, message):
                        progress.append(value)

                    imported = await client.call_tool(
                        "import_reference_map",
                        {
                            "source": str(self.root / "kz_test.vmf"),
                            "output": "reference.vmf",
                        },
                        progress_callback=callback,
                    )
                    self.assertFalse(imported.isError)
                    self.assertTrue(progress)
                    progress.clear()
                    edit = await client.call_tool(
                        "edit_map",
                        {
                            "path": "kz_test.vmf",
                            "expected_revision": created.structuredContent["data"][
                                "revision"
                            ],
                            "operations": [
                                {
                                    "op": "set_properties",
                                    "id": 1,
                                    "kind": "world",
                                    "properties": {"message": "progress check"},
                                }
                            ],
                            "dry_run": True,
                        },
                        progress_callback=callback,
                    )
                    self.assertFalse(edit.isError)
                    self.assertTrue(progress)
                    file = self.root / "kz_test.vmf"
                    file.write_text(
                        file.read_text().replace(
                            '"classname" "worldspawn"', '"classname" "invalid"'
                        )
                    )
                    checked = await client.call_tool(
                        "validate_map", {"path": "kz_test.vmf"}
                    )
                    self.assertFalse(checked.isError)
                    self.assertTrue(checked.structuredContent["ok"])
                    self.assertFalse(checked.structuredContent["data"]["valid"])
                    bad = await client.call_tool(
                        "map_add_entity",
                        {
                            "path": "kz_test.vmf",
                            "expected_revision": created.structuredContent["data"][
                                "revision"
                            ],
                            "classname": "light",
                            "origin": [0, 0, 0],
                            "properties": {"foo": None},
                        },
                    )
                    self.assertTrue(bad.isError)

        anyio.run(scenario)

    def test_nonfinite_input_and_compile_bounds_fail_before_mutation(self):
        created = self.project.create("test.vmf")
        with self.assertRaisesRegex(ValueError, "finite"):
            execute(
                self.project,
                {},
                "map_add_entity",
                {
                    "path": "test.vmf",
                    "expected_revision": created["revision"],
                    "classname": "light",
                    "origin": [float("nan"), 0, 0],
                },
            )
        with self.assertRaisesRegex(ValueError, "16384"):
            execute(
                self.project,
                {},
                "map_add_box",
                {
                    "path": "test.vmf",
                    "expected_revision": created["revision"],
                    "min": [16380, 0, 0],
                    "max": [16390, 32, 32],
                },
            )
        self.assertEqual(
            self.project.inspect("test.vmf")["revision"], created["revision"]
        )


if __name__ == "__main__":
    unittest.main()
