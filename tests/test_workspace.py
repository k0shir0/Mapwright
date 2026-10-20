import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cli.hammerplusplus import workspace, vmf
from cli.hammerplusplus.api import execute
from cli.hammerplusplus.project import Project, digest

RUNS = Path(__file__).resolve().parents[1] / ".local/test-runs"
RUNS.mkdir(parents=True, exist_ok=True)


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=RUNS)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = Project(self.root)

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def test_log_spans_success_failure_and_redacts_source(self):
        created = execute(self.project, {}, "create_map", {"path": "a.vmf"})
        with self.assertRaises(vmf.MapError):
            execute(
                self.project,
                {},
                "edit_map",
                {
                    "path": "a.vmf",
                    "expected_revision": "0" * 64,
                    "operations": [{"op": "delete", "id": 1}],
                },
            )
        text = self.project.source("a.vmf")["source"] + "\n// unique source secret\n"
        execute(
            self.project,
            {},
            "map_replace_source",
            {"path": "a.vmf", "expected_revision": created["revision"], "source": text},
        )
        records = workspace.operations(self.project)["events"]
        self.assertTrue(any(r["status"] == "failed" for r in records))
        self.assertTrue(
            all(
                "timestamp" in r and "session_id" in r and "call_id" in r
                for r in records
            )
        )
        self.assertNotIn("unique source secret", json.dumps(records))

    def test_folder_checkpoint_restore_refuses_conflicts_and_has_reverse(self):
        self.write("maps/a.vmf", b"first")
        self.write("assets/a.bin", b"\x00\xff")
        cp = workspace.checkpoint(self.project, ["maps", "assets"], "before")
        self.write("maps/a.vmf", b"changed")
        self.write("maps/new.vmf", b"new")
        (self.root / "assets/a.bin").unlink()
        state = workspace.checkpoint_status(self.project, cp["token"])
        with self.assertRaises(vmf.MapError):
            workspace.restore_checkpoint(self.project, cp["token"], {})
        preview = workspace.restore_checkpoint(
            self.project, cp["token"], state["current_revisions"], True
        )
        self.assertTrue(preview["dry_run"])
        self.assertEqual((self.root / "maps/a.vmf").read_bytes(), b"changed")
        restored = workspace.restore_checkpoint(
            self.project, cp["token"], state["current_revisions"]
        )
        self.assertEqual((self.root / "maps/a.vmf").read_bytes(), b"first")
        self.assertEqual((self.root / "assets/a.bin").read_bytes(), b"\x00\xff")
        self.assertFalse((self.root / "maps/new.vmf").exists())
        reverse = workspace.checkpoint_status(
            self.project, restored["reverse_checkpoint"]
        )
        workspace.restore_checkpoint(
            self.project, reverse["token"], reverse["current_revisions"]
        )
        self.assertEqual((self.root / "maps/a.vmf").read_bytes(), b"changed")
        self.assertTrue((self.root / "maps/new.vmf").exists())
        self.assertFalse((self.root / "assets/a.bin").exists())

    def test_interrupted_restore_resumes_but_refuses_external_edits(self):
        self.write("maps/a", b"a")
        self.write("maps/b", b"b")
        cp = workspace.checkpoint(self.project, ["maps"])
        self.write("maps/a", b"A")
        self.write("maps/b", b"B")
        state = workspace.checkpoint_status(self.project, cp["token"])
        real = workspace.restore_saved_file

        def fail(project, path, *args, **kwargs):
            if path == "maps/b":
                raise OSError("interrupted")
            return real(project, path, *args, **kwargs)

        with (
            patch.object(workspace, "restore_saved_file", side_effect=fail),
            self.assertRaises(OSError),
        ):
            workspace.restore_checkpoint(
                self.project, cp["token"], state["current_revisions"]
            )
        pending = next((self.root / ".hammer-agent/recovery").glob("*.json"))
        self.assertEqual((self.root / "maps/a").read_bytes(), b"a")
        self.write("maps/b", b"external")
        with self.assertRaisesRegex(vmf.MapError, "External"):
            workspace.resume_recovery(self.project, pending.stem)
        self.write("maps/b", b"B")
        result = workspace.resume_recovery(self.project, pending.stem)
        self.assertEqual(result["status"], "complete")
        self.assertEqual((self.root / "maps/b").read_bytes(), b"b")

    def test_checkpoint_checksums_protected_paths_and_artifact_reads(self):
        self.write("a", b"before")
        cp = workspace.checkpoint(self.project, ["a"])
        self.write("a", b"after")
        blob = self.root / f'.hammer-agent/checkpoints/blobs/{cp["files"]["a"]}'
        blob.write_bytes(b"corrupt")
        with self.assertRaisesRegex(vmf.MapError, "checksum"):
            workspace.restore_checkpoint(
                self.project,
                cp["token"],
                workspace.checkpoint_status(self.project, cp["token"])[
                    "current_revisions"
                ],
            )
        self.assertEqual((self.root / "a").read_bytes(), b"after")
        for name in ("../outside", ".git/config", ".hammer-agent/checkpoints"):
            with self.assertRaises(vmf.MapError):
                workspace.checkpoint(self.project, [name])
        rows = workspace.artifacts(self.project)["artifacts"]
        self.assertTrue(any(cp["token"] in r["path"] for r in rows))
        result = workspace.read_artifact(
            self.project, f'.hammer-agent/checkpoints/{cp["token"]}.json'
        )
        self.assertEqual(json.loads(result["content"])["label"], "")
        with self.assertRaises(vmf.MapError):
            workspace.read_artifact(self.project, "a")

    def test_history_is_read_only_even_with_write_lock_and_stale_recovery(self):
        created = self.project.create("a.vmf")
        self.project.apply(
            "a.vmf",
            created["revision"],
            [{"op": "add_entity", "classname": "light", "origin": [0, 0, 0]}],
        )
        journal = self.project.journal_path(self.root / "a.vmf")
        original = journal.read_bytes()
        with self.project.locked():
            self.assertEqual(self.project.history("a.vmf")["position"], 1)
            self.assertFalse(workspace.lock_status(self.project)["recoverable"])
        self.assertEqual(journal.read_bytes(), original)
        lock = self.root / ".hammer-agent/write.lock"
        lock.write_text("2147483647")
        with patch.object(
            workspace,
            "lock_status",
            return_value={
                "recoverable": True,
                "revision": digest(lock.read_bytes()),
                "owner": {"pid": 2147483647},
            },
        ):
            self.assertTrue(
                workspace.recover_lock(self.project, digest(lock.read_bytes()))[
                    "recovered"
                ]
            )
        self.assertFalse(lock.exists())


if __name__ == "__main__":
    unittest.main()
