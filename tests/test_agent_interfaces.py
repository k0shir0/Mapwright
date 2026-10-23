"""Exercise focused discovery, repairable errors and portable skill execution."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from cli.hammerplusplus.api import TOOLS, execute
from cli.hammerplusplus.project import Project
from cli.hammerplusplus.results import bounded, serialized, MAX_RESULT_BYTES
from scripts import setup_agent

ROOT = Path(__file__).resolve().parents[1]


class AgentInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = Project(self.root)

    def cli(self, *args):
        process = subprocess.run(
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
        return process, json.loads(process.stdout)

    def test_selective_schema_and_compact_encoding_preserve_contract(self):
        full_process, full = self.cli("schema")
        process, selected = self.cli("schema", "--tool", "inspect")
        self.assertEqual(selected["data"], {"inspect_map": full["data"]["inspect_map"]})
        self.assertEqual(
            process.stdout.strip(), json.dumps(selected, separators=(",", ":"))
        )
        self.assertLess(len(process.stdout), len(full_process.stdout) // 20)
        _, index = self.cli("schema", "--group", "kz", "--index")
        self.assertTrue(index["data"])
        self.assertTrue(all(name.startswith("kz_") for name in index["data"]))
        self.assertNotIn("inputSchema", next(iter(index["data"].values())))
        process, error = self.cli("schema", "--tool", "absent")
        self.assertEqual(process.returncode, 1)
        self.assertEqual(error["details"]["code"], "UNKNOWN_TOOL")

    def test_parameter_meanings_are_available_to_mcp(self):
        fields = TOOLS["map_add_box"]["inputSchema"]["properties"]
        self.assertIn("Source units", fields["min"]["description"])
        self.assertIn(".vmt", fields["material"]["description"])
        self.assertIn(
            "Finalized action",
            TOOLS["checkout_action"]["inputSchema"]["properties"]["target"][
                "description"
            ],
        )
        self.assertIn(
            "character",
            TOOLS["read_map_source"]["inputSchema"]["properties"]["offset"][
                "description"
            ],
        )
        self.assertIn(
            "byte",
            TOOLS["read_artifact"]["inputSchema"]["properties"]["offset"][
                "description"
            ],
        )

    def test_discovery_works_before_workspace_setup(self):
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "cli.hammerplusplus",
                "--workspace",
                str(self.root / "missing"),
                "--json",
                "schema",
                "--tool",
                "inspect_map",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIn("inspect_map", json.loads(process.stdout)["data"])

    def test_batch_error_identifies_missing_field_without_mutating_map(self):
        created = self.project.create("map.vmf")
        request = {
            "path": "map.vmf",
            "expected_revision": created["revision"],
            "operations": [{"op": "add_box", "min": [0, 0, 0]}],
        }
        process, error = self.cli("call", "edit_map", json.dumps(request))
        self.assertEqual(process.returncode, 1)
        self.assertEqual(error["details"]["field"], "operations[0].max")
        self.assertEqual(error["details"]["code"], "INVALID_ARGUMENT")
        self.assertIn("action_id", error["details"])
        self.assertEqual(
            self.project.inspect("map.vmf")["revision"], created["revision"]
        )
        _, unknown = self.cli("call", "absent", "{}")
        self.assertEqual(unknown["details"]["code"], "UNKNOWN_TOOL")
        self.assertLess(len(unknown["error"]), 100)

    def test_selected_evidence_pages_keep_findings_and_original_bytes(self):
        original = {
            "valid": False,
            "complete": False,
            "findings": [{"id": i, "message": "detail " * 15} for i in range(400)],
            "source": "source " * 10000,
        }
        summary = bounded(self.project, original)
        self.assertLessEqual(len(serialized(summary)), MAX_RESULT_BYTES)
        self.assertFalse(summary["source_complete"])
        next_call = summary["response"]["next_call"]
        self.assertEqual(next_call["tool"], "read_artifact")
        path = summary["response"]["artifact"]["path"]
        rows, offset = [], 0
        while offset is not None:
            page = execute(
                self.project,
                {},
                "read_artifact",
                {"path": path, "field": "findings", "offset": offset, "limit": 17},
            )
            self.assertNotIn("source", page)
            rows.extend(page["value"])
            offset = page["next_offset"]
        self.assertEqual(rows, original["findings"])
        self.assertEqual(json.loads((self.root / path).read_bytes()), original)
        (self.root / path).write_text("{}")
        with self.assertRaisesRegex(ValueError, "checksum"):
            execute(
                self.project, {}, "read_artifact", {"path": path, "field": "findings"}
            )

    def test_bundled_skills_resolve_outside_checkout_and_detect_relocation(self):
        skills = self.root / "profile/skills"
        command = self.root / "venv/bin/mapwright"
        command.parent.mkdir(parents=True)
        command.write_text("fixture")
        setup_agent.apply_changes(
            setup_agent.skill_changes(skills, ROOT, command, self.root), self.root
        )
        mapping = skills / "mapwright"
        setup = skills / "mapwright-setup"
        self.assertFalse((setup / "references/kz-mapping.md").exists())
        self.assertFalse((mapping / "references/agent-connections.md").exists())
        resolver = mapping / "scripts/resolve_installation.py"
        process = subprocess.run(
            [sys.executable, str(resolver)],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertTrue(json.loads(process.stdout)["ok"], process.stdout)
        command.unlink()
        process = subprocess.run(
            [sys.executable, str(resolver)],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(process.returncode, 1)
        self.assertEqual(
            json.loads(process.stdout)["details"]["code"], "STALE_INSTALLATION"
        )

    def test_obsolete_managed_guide_removal_can_be_rolled_back(self):
        skills = self.root / "skills"
        setup_agent.apply_changes(
            setup_agent.skill_changes(skills, ROOT, Path(sys.executable), self.root),
            self.root,
        )
        old = skills / "mapwright-setup/references/reference-maps.md"
        old.write_bytes((ROOT / "docs/reference-maps.md").read_bytes())
        changes = setup_agent.skill_changes(
            skills, ROOT, Path(sys.executable), self.root
        )
        receipt = setup_agent.apply_changes(changes, self.root)
        self.assertFalse(old.exists())
        setup_agent.rollback(receipt, True)
        self.assertEqual(
            old.read_bytes(), (ROOT / "docs/reference-maps.md").read_bytes()
        )

    def test_failed_verification_keeps_partial_receipt(self):
        from cli.hammerplusplus.errors import AgentError
        from scripts._support import verify

        report = {"steps": ["create_map"]}
        output = self.root / "verification.json"

        async def failing():
            raise AgentError(
                "compiler unavailable",
                {"code": "PREREQUISITE_MISSING", "action_id": "retained"},
            )

        with self.assertRaises(AgentError) as raised:
            verify(failing, report, output)
        self.assertEqual(raised.exception.details["receipt"], str(output))
        recorded = json.loads(output.read_text())
        self.assertEqual(recorded["steps"], ["create_map"])
        self.assertEqual(recorded["failure"]["details"]["action_id"], "retained")

    def test_script_argument_failures_are_json_and_retain_diagnostics(self):
        for name in (
            "setup_agent",
            "setup_local",
            "verify_backend",
            "verify_kz",
            "verify_reference",
            "verify_native_session",
            "benchmark_portable",
        ):
            with self.subTest(script=name):
                process = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "scripts" / (name + ".py")),
                        "--unknown-option",
                    ],
                    cwd=self.root,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(process.returncode, 1, process.stderr)
                result = json.loads(process.stdout)
                self.assertFalse(result["ok"])
                self.assertEqual(result["details"]["code"], "INVALID_ARGUMENT")
                self.assertNotIn("Traceback", process.stderr)
                self.assertTrue(Path(result["details"]["diagnostic"]).is_file())

    @unittest.skipIf(os.name == "nt", "Exercises the non-Windows prerequisite failure")
    def test_native_prerequisite_failure_is_json(self):
        process = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/verify_native_session.py"),
                "--run",
                "--workspace",
                str(self.root),
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(process.returncode, 1)
        result = json.loads(process.stdout)
        self.assertIn("Windows", result["error"])
        self.assertNotIn("Traceback", process.stderr)
        self.assertTrue(Path(result["details"]["diagnostic"]).is_file())


if __name__ == "__main__":
    unittest.main()
