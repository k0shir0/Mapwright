"""Official SDK subprocess E2E, with native contracts explicitly fixture-labelled.

The portable lane runs installed Mapwright outside the checkout. The separate
fixture lane proves transport contracts, never Hammer rendering/native behavior.
Set MAPWRIGHT_NATIVE_E2E_CONFIG to opt into the real installed native toolchain.
"""

from datetime import timedelta
import base64
import json
import os
import signal
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from urllib.parse import quote

import anyio
import jsonschema
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError

from cli_anything.hammerplusplus import timeline

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / ".local/test-runs"
RUNS.mkdir(parents=True, exist_ok=True)
NATIVE_TOOLS = {
    "compile_map",
    "open_editor",
    "inspect_editor",
    "editor_action",
    "capture_editor",
    "save_editor",
    "close_editor",
    "rea_probe",
}
KZ_CHECKS = {
    "kz_audit",
    "kz_check_antibhop",
    "kz_check_bhop",
    "kz_check_headhitter",
    "kz_check_ladders",
    "kz_check_water",
    "kz_check_teleports",
    "kz_spawn_check",
    "kz_test_plan",
}
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6"
    "WQAAAABJRU5ErkJggg=="
)


NATIVE_FIXTURE_SERVER = r"""
import sys
from pathlib import Path
from cli_anything.hammerplusplus import backend,desktop,windows,timeline
from cli_anything.hammerplusplus.project import Project
from cli_anything.hammerplusplus.mcp_server import serve
import base64

def result(tool, **data):
    return {"native_contract_fixture":tool,**data}

def compile_map(project,config,name,expected_revision,**kwargs):
    assert project.inspect(name)["revision"] == expected_revision
    return result("compile_map",source_revision=expected_revision)

def open_editor(project,config,name,**kwargs):
    project.read(name)
    return result("open_editor",pid=77777,status="fixture")

def inspect_editor(project,config,pid,**kwargs):
    return result("inspect_editor",pid=pid,windows=[{"hwnd":123,"title":"Native contract fixture"}])

def editor_action(project,config,pid,action,**kwargs):
    return result("editor_action",pid=pid,action=action,status="dispatched",document_reversible=False)

def capture_editor(project,config,pid,output,**kwargs):
    path=project.confined(output)
    path.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6WQAAAABJRU5ErkJggg=="))
    return result("capture_editor",pid=pid,path=str(path),width=1,height=1)

def save_editor(project,config,pid,expected_revision):
    timeline.track_file(project,"fixture.vmf")
    source=project.source("fixture.vmf")["source"]+"\n// fixture saved document\n"
    saved=project.apply("fixture.vmf",expected_revision,[{"op":"replace_source","source":source}])
    return result("save_editor",**saved)

def close_editor(project,config,pid):
    return result("close_editor",pid=pid,status="fixture-closed")

backend.compile_map=compile_map
backend.open_editor=open_editor
backend.save_editor=save_editor
backend.close_editor=close_editor
backend.rea_probe=lambda project,config,**kwargs:result("rea_probe",target=kwargs["target"])
desktop.inspect_editor=inspect_editor
desktop.editor_action=editor_action
windows.capture_editor=capture_editor
serve(Project(sys.argv[1]),{})
"""


class MCPEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=RUNS)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    async def tools(self, client):
        initialized = await client.initialize()
        self.assertEqual(initialized.serverInfo.name, "mapwright")
        self.assertTrue(initialized.capabilities.tools)
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        for tool in tools.values():
            jsonschema.Draft202012Validator.check_schema(tool.inputSchema)
            jsonschema.Draft202012Validator.check_schema(tool.outputSchema)
        return tools

    async def invoke(self, client, tools, name, arguments=None, error=False):
        result = await client.call_tool(name, arguments or {})
        text = json.loads(result.content[0].text)
        self.assertEqual(result.structuredContent, text, name)
        self.assertEqual(bool(result.isError), error, f"{name}: {text}")
        self.assertEqual(text["ok"], not error, name)
        if name in tools:
            jsonschema.validate(text, tools[name].outputSchema)
        if error:
            self.assertTrue(text["error"], name)
            self.assertNotIn("ExceptionGroup", text["error"])
            self.assertIn("action_id", text["details"])
        else:
            self.assertIn("timeline", text["data"], name)
        return result, text.get("data", text)

    def parameters(self, fixture=False):
        if fixture:
            script = self.root / "native_fixture_server.py"
            script.write_text(NATIVE_FIXTURE_SERVER, encoding="utf-8")
            args = [str(script), str(self.root)]
        else:
            args = [
                "-m",
                "cli_anything.hammerplusplus",
                "--workspace",
                str(self.root),
                "mcp",
            ]
        return StdioServerParameters(
            command=sys.executable,
            args=args,
            cwd=self.root,
            env={"PYTHONPATH": ""},
        )

    def test_every_portable_tool_over_installed_stdio_and_real_missing_native_errors(
        self,
    ):
        # Real srctools parses these controlled FGD/loose-asset fixtures.
        game = self.root / "game"
        (game / "materials/test").mkdir(parents=True)
        (game / "gameinfo.txt").write_text(
            'GameInfo { FileSystem { SearchPaths { Game "|gameinfo_path|." } } }',
            encoding="utf-8",
        )
        (game / "materials/test/e2e.vmt").write_text(
            "UnlitGeneric {}", encoding="utf-8"
        )
        fgd = self.root / "test.fgd"
        fgd.write_text(
            '@PointClass = logic_relay [\n targetname(string) : "Name"\n input Trigger(void)\n output OnTrigger(void)\n]\n',
            encoding="utf-8",
        )
        (self.root / "mapwright.local.json").write_text(
            json.dumps({"game_dir": str(game), "fgd": str(fgd)})
        )

        async def scenario():
            server_pid = None
            covered = set()
            with anyio.fail_after(120):
                async with stdio_client(self.parameters()) as (read, write):
                    async with ClientSession(
                        read, write, read_timeout_seconds=timedelta(seconds=30)
                    ) as client:
                        tools = await self.tools(client)

                        async def call(name, **args):
                            _, data = await self.invoke(client, tools, name, args)
                            covered.add(name)
                            return data

                        doctor = await call("doctor")
                        self.assertFalse(doctor["compile_ready"])
                        self.assertTrue(doctor["fgd_ready"])
                        created = await call(
                            "create_map", path="kz.vmf", template="kz-room"
                        )
                        self.assertGreater(created["counts"]["solid"], 6)
                        action = await call(
                            "inspect_action", action_id=created["timeline"]["action_id"]
                        )
                        server_pid = action["pid"]
                        initial = (self.root / "kz.vmf").read_bytes()

                        async def mutate(tool, **args):
                            current = await call("inspect_map", path="kz.vmf")
                            return await call(
                                tool,
                                path="kz.vmf",
                                expected_revision=current["revision"],
                                **args,
                            )

                        first = await mutate(
                            "map_add_box", min=[0, 0, 0], max=[32, 32, 32]
                        )
                        second = await mutate(
                            "map_add_box", min=[128, 0, 0], max=[160, 32, 32]
                        )
                        start, end = (
                            first["results"][0]["ids"][0],
                            second["results"][0]["ids"][0],
                        )
                        await mutate(
                            "map_add_room", min=[-128, -128, 512], max=[128, 128, 640]
                        )
                        entity = await mutate(
                            "map_add_entity", classname="logic_relay", origin=[0, 0, 64]
                        )
                        entity_id = entity["results"][0]["ids"][0]
                        await mutate(
                            "map_set_properties",
                            id=entity_id,
                            kind="entity",
                            properties={"targetname": "e2e_relay"},
                        )
                        await mutate(
                            "map_add_output",
                            id=entity_id,
                            event="OnTrigger",
                            target="e2e_relay",
                            input="Trigger",
                        )
                        obj = await call(
                            "inspect_object", path="kz.vmf", id=entity_id, kind="entity"
                        )
                        self.assertIn("OnTrigger", obj["source"])
                        await mutate(
                            "map_translate",
                            id=entity_id,
                            kind="entity",
                            delta=[16, 0, 0],
                        )
                        translated = await call(
                            "inspect_object", path="kz.vmf", id=entity_id, kind="entity"
                        )
                        self.assertIn('"16 0 64"', translated["source"])
                        await mutate("map_delete", id=entity_id, kind="entity")
                        source = await call("read_map_source", path="kz.vmf")
                        replacement = (
                            source["source"]
                            + '\nfuture_extension { "untouched" "retained" }\n'
                        )
                        await mutate("map_replace_source", source=replacement)
                        self.assertEqual(
                            (await call("read_map_source", path="kz.vmf"))["source"],
                            replacement,
                        )
                        before_batch = (self.root / "kz.vmf").read_bytes()
                        batch = await mutate(
                            "edit_map",
                            operations=[
                                {
                                    "op": "add_entity",
                                    "classname": "logic_relay",
                                    "origin": [0, 0, 96],
                                    "properties": {"targetname": "reference_marker"},
                                }
                            ],
                        )
                        after_batch = (self.root / "kz.vmf").read_bytes()
                        undone = await call(
                            "undo_map",
                            path="kz.vmf",
                            expected_revision=batch["revision"],
                        )
                        self.assertEqual(
                            (self.root / "kz.vmf").read_bytes(), before_batch
                        )
                        await call(
                            "redo_map",
                            path="kz.vmf",
                            expected_revision=undone["revision"],
                        )
                        self.assertEqual(
                            (self.root / "kz.vmf").read_bytes(), after_batch
                        )
                        self.assertGreater(
                            (await call("map_history", path="kz.vmf"))["position"], 0
                        )
                        self.assertTrue(
                            (await call("validate_map", path="kz.vmf"))["valid"]
                        )
                        page = await call(
                            "read_map_source", path="kz.vmf", offset=12, limit=17
                        )
                        self.assertEqual(
                            page["source"], after_batch.decode("utf-8")[12:29]
                        )

                        for name in sorted(KZ_CHECKS):
                            data = await call(name, path="kz.vmf")
                            self.assertIn("revision", data)
                        measured = await call(
                            "kz_measure_jumps",
                            path="kz.vmf",
                            start={"id": start},
                            end={"id": end},
                        )
                        self.assertEqual(measured["gap"], 96)
                        self.assertIn(
                            "reference_marker", (self.root / "kz.vmf").read_text()
                        )

                        imported = await call(
                            "import_reference_map",
                            source=str(self.root / "kz.vmf"),
                            output="reference.vmf",
                        )
                        found = await call(
                            "search_reference_map",
                            path="reference.vmf",
                            query="reference_marker",
                            kind="entity",
                        )
                        self.assertEqual(found["total"], 1)
                        current = await call("inspect_map", path="kz.vmf")
                        await call(
                            "copy_reference_objects",
                            source="reference.vmf",
                            destination="kz.vmf",
                            source_revision=imported["revision"],
                            expected_revision=current["revision"],
                            selection=[
                                {"id": found["objects"][0]["id"], "kind": "entity"}
                            ],
                            prefix="copied_",
                            delta=[64, 0, 0],
                        )
                        self.assertIn(
                            "copied_reference_marker",
                            (self.root / "kz.vmf").read_text(),
                        )
                        reference_bytes = (self.root / "reference.vmf").read_bytes()
                        deleted = await call(
                            "delete_map_file",
                            path="reference.vmf",
                            expected_revision=imported["revision"],
                        )
                        self.assertFalse((self.root / "reference.vmf").exists())
                        await call("restore_map_file", token=deleted["token"])
                        self.assertEqual(
                            (self.root / "reference.vmf").read_bytes(), reference_bytes
                        )
                        self.assertEqual(
                            (await call("list_map_files", query="reference"))["total"],
                            1,
                        )

                        checkpoint = await call(
                            "create_checkpoint", paths=["kz.vmf"], label="stdio e2e"
                        )
                        checkpoint_bytes = (self.root / "kz.vmf").read_bytes()
                        await mutate(
                            "map_set_properties",
                            id=1,
                            kind="world",
                            properties={"message": "after checkpoint"},
                        )
                        state = await call(
                            "inspect_checkpoint", token=checkpoint["token"]
                        )
                        await call(
                            "restore_checkpoint",
                            token=checkpoint["token"],
                            expected_revisions=state["current_revisions"],
                        )
                        self.assertEqual(
                            (self.root / "kz.vmf").read_bytes(), checkpoint_bytes
                        )
                        recovery = await call(
                            "restore_checkpoint",
                            token=checkpoint["token"],
                            expected_revisions=(
                                await call(
                                    "inspect_checkpoint", token=checkpoint["token"]
                                )
                            )["current_revisions"],
                        )
                        self.assertEqual(
                            (
                                await call(
                                    "resume_recovery", token=recovery["recovery_token"]
                                )
                            )["status"],
                            "complete",
                        )
                        artifacts = await call("list_artifacts", category="checkpoints")
                        self.assertGreater(artifacts["total"], 0)
                        artifact_path = (
                            f".hammer-agent/checkpoints/{checkpoint['token']}.json"
                        )
                        artifact = await call("read_artifact", path=artifact_path)
                        self.assertEqual(
                            json.loads(artifact["content"])["label"], "stdio e2e"
                        )

                        self.assertFalse((await call("lock_status"))["locked"])
                        lock = self.root / ".hammer-agent/write.lock"
                        lock.write_text('{"pid":2147483647}', encoding="utf-8")
                        stale_lock = await call("lock_status")
                        self.assertTrue(stale_lock["recoverable"])
                        self.assertTrue(
                            (
                                await call(
                                    "recover_lock",
                                    expected_revision=stale_lock["revision"],
                                )
                            )["recovered"]
                        )
                        self.assertFalse(lock.exists())

                        catalog = await call("entity_catalog", classname="logic_relay")
                        self.assertIn(
                            "OnTrigger", {r["name"] for r in catalog["outputs"]}
                        )
                        assets = await call(
                            "asset_catalog", kind="material", query="test/e2e"
                        )
                        self.assertEqual(assets["assets"][0]["name"], "test/e2e")
                        for name, args in (
                            ("not_advertised", {}),
                            ("inspect_map", {"path": "../outside.vmf"}),
                            ("inspect_map", {"path": "kz.vmf", "limit": False}),
                            (
                                "map_set_properties",
                                {
                                    "path": "kz.vmf",
                                    "expected_revision": "0" * 64,
                                    "id": 1,
                                    "properties": {"message": "stale"},
                                },
                            ),
                        ):
                            await self.invoke(client, tools, name, args, error=True)

                        # These use untouched real handlers with missing prerequisites.
                        revision = (await call("inspect_map", path="kz.vmf"))[
                            "revision"
                        ]
                        native_args = {
                            "compile_map": {
                                "path": "kz.vmf",
                                "expected_revision": revision,
                            },
                            "open_editor": {"path": "kz.vmf"},
                            "inspect_editor": {"pid": server_pid},
                            "editor_action": {"pid": server_pid, "action": "restore"},
                            "capture_editor": {
                                "pid": server_pid,
                                "output": "missing-editor.png",
                            },
                            "save_editor": {
                                "pid": server_pid,
                                "expected_revision": revision,
                            },
                            "close_editor": {"pid": server_pid},
                            "rea_probe": {"target": "hammer"},
                        }
                        for name, args in native_args.items():
                            _, failure = await self.invoke(
                                client, tools, name, args, error=True
                            )
                            self.assertRegex(
                                failure["error"],
                                r"(?i)Windows|desktop|owned|editor-open|Hammer|game_dir|REA|configure|session|missing",
                            )

                        resources = await client.list_resources()
                        self.assertEqual(len(resources.resources), 3)
                        for resource in resources.resources:
                            self.assertTrue(
                                (await client.read_resource(resource.uri)).contents
                            )
                        templates = await client.list_resource_templates()
                        self.assertEqual(len(templates.resourceTemplates), 1)
                        artifact_resource = await client.read_resource(
                            "hammer://artifact/" + quote(artifact_path, safe="")
                        )
                        self.assertEqual(
                            json.loads(artifact_resource.contents[0].text)["content"],
                            artifact["content"],
                        )
                        with self.assertRaises(McpError):
                            await client.read_resource("hammer://unknown/resource")
                        prompts = await client.list_prompts()
                        self.assertEqual(
                            [p.name for p in prompts.prompts], ["kz_mapping_workflow"]
                        )
                        prompt = await client.get_prompt(
                            "kz_mapping_workflow",
                            {"path": "kz.vmf", "task": "inspect edge gap"},
                        )
                        self.assertIn(
                            "inspect edge gap", prompt.messages[0].content.text
                        )
                        with self.assertRaises(McpError):
                            await client.get_prompt("kz_mapping_workflow", {})

                        logs = await call("operation_log", limit=1000)
                        self.assertTrue(
                            any(e["status"] == "failed" for e in logs["events"])
                        )
                        history = await call("action_history", limit=1000)
                        self.assertTrue(
                            any(
                                a["tool"] == "not_advertised"
                                for a in history["actions"]
                            )
                        )
                        status = await call("timeline_status")
                        head = status["timeline"]["head"]
                        final_bytes = (self.root / "kz.vmf").read_bytes()
                        await call(
                            "checkout_action",
                            target=created["timeline"]["action_id"],
                            expected_head=head,
                        )
                        self.assertEqual((self.root / "kz.vmf").read_bytes(), initial)
                        current_head = (await call("timeline_status"))["timeline"][
                            "head"
                        ]
                        await call(
                            "checkout_action", target=head, expected_head=current_head
                        )
                        self.assertEqual(
                            (self.root / "kz.vmf").read_bytes(), final_bytes
                        )
                        self.assertEqual(
                            set(tools),
                            covered | NATIVE_TOOLS,
                            "Every advertised tool needs an explicit successful portable or named native fixture scenario",
                        )
            self.assertIsNotNone(server_pid)
            self.assertFalse(
                timeline.alive(server_pid), "SDK stdio context must reap its server"
            )

        anyio.run(scenario)

    def test_native_transport_contracts_with_explicit_child_process_fixtures(self):
        async def scenario():
            with anyio.fail_after(60):
                async with stdio_client(self.parameters(fixture=True)) as (read, write):
                    async with ClientSession(
                        read, write, read_timeout_seconds=timedelta(seconds=15)
                    ) as client:
                        tools = await self.tools(client)
                        _, created = await self.invoke(
                            client, tools, "create_map", {"path": "fixture.vmf"}
                        )
                        arguments = {
                            "compile_map": {
                                "path": "fixture.vmf",
                                "expected_revision": created["revision"],
                            },
                            "open_editor": {"path": "fixture.vmf"},
                            "inspect_editor": {"pid": 77777},
                            "editor_action": {"pid": 77777, "action": "restore"},
                            "capture_editor": {"pid": 77777, "output": "fixture.png"},
                            "save_editor": {
                                "pid": 77777,
                                "expected_revision": created["revision"],
                            },
                            "close_editor": {"pid": 77777},
                            "rea_probe": {"target": "hammer"},
                        }
                        self.assertEqual(set(arguments), NATIVE_TOOLS)
                        for name, args in arguments.items():
                            result, data = await self.invoke(client, tools, name, args)
                            self.assertEqual(data["native_contract_fixture"], name)
                            if name == "capture_editor":
                                self.assertEqual(result.content[1].type, "image")
                                self.assertEqual(
                                    base64.b64decode(result.content[1].data), PNG
                                )
                            if name == "save_editor":
                                self.assertIn(
                                    "fixture saved document",
                                    (self.root / "fixture.vmf").read_text(),
                                )

        anyio.run(scenario)


@unittest.skipUnless(
    os.environ.get("MAPWRIGHT_NATIVE_E2E_CONFIG"), "Opt-in real native toolchain lane"
)
class RealNativeMCPEndToEndTests(MCPEndToEndTests):
    # Do not inherit portable scenarios into the opt-in class.
    test_every_portable_tool_over_installed_stdio_and_real_missing_native_errors = None
    test_native_transport_contracts_with_explicit_child_process_fixtures = None

    def setUp(self):
        super().setUp()
        config_path = Path(os.environ["MAPWRIGHT_NATIVE_E2E_CONFIG"]).resolve(
            strict=True
        )
        config = json.loads(config_path.read_text("utf-8-sig"))
        for key, value in config.items():
            config[key] = (
                [str((config_path.parent / p).resolve()) for p in value]
                if isinstance(value, list)
                else str((config_path.parent / value).resolve())
            )
        (self.root / "mapwright.local.json").write_text(
            json.dumps(config), encoding="utf-8"
        )

    def test_actual_configured_native_toolchain(self):
        evidence = {}

        async def scenario():
            pid = None
            with anyio.fail_after(300):
                async with stdio_client(self.parameters()) as (read, write):
                    async with ClientSession(
                        read, write, read_timeout_seconds=timedelta(seconds=180)
                    ) as client:
                        tools = await self.tools(client)

                        async def call(name, **args):
                            result, data = await self.invoke(client, tools, name, args)
                            self.assertNotIn("native_contract_fixture", data)
                            evidence[name] = data
                            return result, data

                        _, created = await call(
                            "create_map", path="native.vmf", template="kz-room"
                        )
                        await call(
                            "compile_map",
                            path="native.vmf",
                            expected_revision=created["revision"],
                            timeout=120,
                        )
                        await call("rea_probe", target="hammer")
                        _, opened = await call(
                            "open_editor", path="native.vmf", timeout=90
                        )
                        pid = opened["pid"]
                        try:
                            _, inspected = await call("inspect_editor", pid=pid)
                            self.assertTrue(inspected["windows"])
                            window = next(
                                w for w in inspected["windows"] if w.get("menus")
                            )
                            normalize = (
                                lambda label: label.split("\t")[0]
                                .replace("&", "")
                                .strip()
                                .casefold()
                            )
                            file_menu = next(
                                m
                                for m in window["menus"]
                                if normalize(m["label"]) == "file"
                            )
                            save = next(
                                m
                                for m in file_menu["items"]
                                if normalize(m["label"]) == "save"
                            )
                            await call(
                                "editor_action",
                                pid=pid,
                                action="menu",
                                menu=file_menu["label"] + "->" + save["label"],
                                hwnd=window["hwnd"],
                            )
                            captured, _ = await call(
                                "capture_editor", pid=pid, output="native-window.png"
                            )
                            self.assertEqual(captured.content[1].mimeType, "image/png")
                            _, saved = await call(
                                "save_editor",
                                pid=pid,
                                expected_revision=created["revision"],
                            )
                            before = (self.root / "native.vmf").read_bytes()
                            _, changed = await call(
                                "map_set_properties",
                                path="native.vmf",
                                expected_revision=saved["revision"],
                                id=1,
                                kind="world",
                                properties={"message": "real native rollback probe"},
                            )
                            self.assertNotEqual(
                                (self.root / "native.vmf").read_bytes(), before
                            )
                            await self.invoke(
                                client,
                                tools,
                                "save_editor",
                                {
                                    "pid": pid,
                                    "expected_revision": saved["revision"],
                                },
                                error=True,
                            )
                            _, restored = await call(
                                "checkout_action",
                                target=saved["timeline"]["action_id"],
                                expected_head=changed["timeline"]["head"],
                            )
                            self.assertEqual(
                                (self.root / "native.vmf").read_bytes(), before
                            )
                            reopened = restored["native_reload"]["sessions"][0]
                            pid = reopened["pid"]
                            _, checked = await call("inspect_editor", pid=pid)
                            self.assertTrue(checked["readiness"]["ready"])
                        finally:
                            if pid:
                                await call("close_editor", pid=pid)
                                pid = None

        anyio.run(scenario)
        output = ROOT / ".local/research/mcp-native-e2e"
        output.mkdir(parents=True, exist_ok=True)
        (output / "results.json").write_text(
            json.dumps(evidence, indent=2), encoding="utf-8"
        )
        if (self.root / "native-window.png").exists():
            shutil.copy2(self.root / "native-window.png", output / "native-window.png")

    def test_crashed_mcp_host_closes_its_owned_native_session(self):
        async def scenario():
            with anyio.fail_after(120):
                async with stdio_client(self.parameters()) as (read, write):
                    async with ClientSession(read, write) as client:
                        tools = await self.tools(client)
                        await self.invoke(
                            client,
                            tools,
                            "create_map",
                            {
                                "path": "crash.vmf",
                                "template": "csgo-room",
                            },
                        )
                        _, opened = await self.invoke(
                            client,
                            tools,
                            "open_editor",
                            {
                                "path": "crash.vmf",
                                "timeout": 90,
                            },
                        )
                        _, action = await self.invoke(
                            client,
                            tools,
                            "inspect_action",
                            {
                                "action_id": opened["timeline"]["action_id"],
                            },
                        )
                        # Kill only our SDK-created server, bypassing Python finally.
                        os.kill(action["pid"], signal.SIGTERM)
                        metadata = (
                            self.root
                            / ".hammer-agent/native-sessions"
                            / opened["session_id"]
                            / "session.json"
                        )
                        with anyio.fail_after(15):
                            while True:
                                state = json.loads(metadata.read_text("utf-8"))
                                if state["status"] == "closed":
                                    break
                                await anyio.sleep(0.05)
                        self.assertEqual(state["shutdown_reason"], "mcp_host_exited")
                        self.assertTrue(state["cleanup_complete"])
                        self.assertEqual(state["job_active_processes"], 0)
                        self.assertFalse(timeline.alive(opened["pid"]))
                        output = ROOT / ".local/research/mcp-native-e2e"
                        output.mkdir(parents=True, exist_ok=True)
                        (output / "crash-cleanup.json").write_text(
                            json.dumps(state, indent=2), encoding="utf-8"
                        )

        anyio.run(scenario)


if __name__ == "__main__":
    unittest.main()
