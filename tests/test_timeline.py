"""Saved-file action history, genuine process crashes and guarded restoration."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cli_anything.hammerplusplus import api, timeline, workspace
from cli_anything.hammerplusplus.backend import BackendError
from cli_anything.hammerplusplus.project import Project
from cli_anything.hammerplusplus.vmf import MapError

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / ".local/test-runs"
RUNS.mkdir(parents=True, exist_ok=True)


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=RUNS)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = Project(self.root)

    def call(self, tool, **arguments):
        return api.execute(self.project, {}, tool, arguments)

    def head(self):
        return timeline.Timeline(self.project).head()

    def checkout(self, action, **arguments):
        return self.call(
            "checkout_action", target=action, expected_head=self.head(), **arguments
        )

    def edit(self, path, **properties):
        current = self.call("inspect_map", path=path)
        return self.call(
            "map_set_properties",
            path=path,
            expected_revision=current["revision"],
            id=1,
            kind="world",
            properties=properties,
        )

    def child(self, code):
        result = subprocess.run(
            [sys.executable, "-c", code, str(self.root)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 97, result.stdout + result.stderr)

    def test_creation_edit_checkout_redo_and_branch_preserve_exact_bytes(self):
        created = self.call("create_map", path="a.vmf")
        original = (self.root / "a.vmf").read_bytes()
        edited = self.edit("a.vmf", message="first branch")
        future = (self.root / "a.vmf").read_bytes()
        self.checkout(created["timeline"]["action_id"])
        self.assertEqual((self.root / "a.vmf").read_bytes(), original)
        # Existing undo cursors are restored with their document.
        self.assertEqual(self.call("map_history", path="a.vmf")["position"], 0)
        other = self.edit("a.vmf", message="second branch")
        other_bytes = (self.root / "a.vmf").read_bytes()
        self.checkout(edited["timeline"]["action_id"])
        self.assertEqual((self.root / "a.vmf").read_bytes(), future)
        self.checkout(other["timeline"]["action_id"])
        self.assertEqual((self.root / "a.vmf").read_bytes(), other_bytes)
        self.checkout(timeline.ROOT)
        self.assertFalse((self.root / "a.vmf").exists())
        self.checkout(edited["timeline"]["action_id"])
        self.assertEqual((self.root / "a.vmf").read_bytes(), future)
        self.assertEqual(self.call("map_history", path="a.vmf")["position"], 1)

    def test_deletion_restore_and_readonly_actions_have_addressable_states(self):
        created = self.call("create_map", path="a.vmf")
        read = self.call("read_map_source", path="a.vmf")
        head = self.head()
        deleted = self.call(
            "delete_map_file", path="a.vmf", expected_revision=created["revision"]
        )
        self.assertFalse((self.root / "a.vmf").exists())
        self.call("restore_map_file", token=deleted["token"])
        self.checkout(deleted["timeline"]["action_id"])
        self.assertFalse((self.root / "a.vmf").exists())
        self.checkout(read["timeline"]["action_id"])
        self.assertEqual(
            self.call("read_map_source", path="a.vmf")["source"], read["source"]
        )
        self.assertEqual(head, created["timeline"]["head"])

    def test_arguments_retain_values_and_exact_source_artifacts(self):
        self.call("create_map", path="a.vmf")
        edited = self.edit("a.vmf", message="exact user-specified property")
        ledger = timeline.Timeline(self.project)
        receipt = ledger.inspect(edited["timeline"]["action_id"])
        self.assertEqual(
            receipt["arguments"]["values"]["properties"],
            {"message": "exact user-specified property"},
        )
        source = self.call("read_map_source", path="a.vmf")
        arguments = {
            "path": "a.vmf",
            "expected_revision": source["revision"],
            "source": source["source"] + "\n// retained replacement\n",
        }
        replaced = self.call("map_replace_source", **arguments)
        receipt = ledger.inspect(replaced["timeline"]["action_id"])
        self.assertNotIn("values", receipt["arguments"])
        artifact = self.project.confined(receipt["arguments"]["arguments_artifact"])
        self.assertEqual(json.loads(artifact.read_text("ascii")), arguments)
        self.assertEqual(
            artifact.stat().st_size, receipt["arguments"]["arguments_bytes"]
        )
        self.assertNotIn("retained replacement", json.dumps(receipt))
        # Identical retried arguments reuse the immutable artifact, then reach
        # normal stale-revision validation with a separately logged action ID.
        with self.assertRaisesRegex(BackendError, "Revision conflict") as stale:
            self.call("map_replace_source", **arguments)
        retry = ledger.inspect(stale.exception.details["action_id"])
        self.assertEqual(retry["status"], "failed")
        self.assertEqual(
            retry["arguments"]["arguments_artifact"],
            receipt["arguments"]["arguments_artifact"],
        )

    def test_rejected_failed_and_metadata_requests_are_permanent_and_paginated(self):
        for tool, args in (
            ("not_a_tool", {}),
            ("inspect_map", {"path": "a.vmf", "limit": False}),
            ("inspect_map", {"path": "../outside.vmf"}),
        ):
            with self.assertRaises(BackendError):
                api.execute(self.project, {}, tool, args)
        self.call("operation_log")
        self.call("list_artifacts")
        ledger = timeline.Timeline(self.project)
        first = ledger.history(limit=2)
        second = ledger.history(after=first["next_after"], limit=100)
        actions = first["actions"] + second["actions"]
        self.assertEqual(
            [r["tool"] for r in actions],
            [
                "not_a_tool",
                "inspect_map",
                "inspect_map",
                "operation_log",
                "list_artifacts",
            ],
        )
        self.assertTrue(all(r["status"] == "failed" for r in actions[:3]))
        events = list((self.root / ".hammer-agent/timeline/events").glob("*.json"))
        self.assertGreater(len(events), len(actions))
        self.assertTrue(all(json.loads(p.read_text())["action_id"] for p in events))
        # A fresh Project reads the same permanent ledger, independent of session ID.
        reopened = timeline.Timeline(Project(self.root))
        self.assertEqual(len(reopened.history()["actions"]), 5)

    def test_external_bytes_are_preserved_before_guarded_checkout_refuses(self):
        created = self.call("create_map", path="a.vmf")
        self.edit("a.vmf", message="managed")
        original_head = self.head()
        external = (self.root / "a.vmf").read_bytes() + b"\r\n// external bytes\r\n"
        (self.root / "a.vmf").write_bytes(external)
        with self.assertRaisesRegex(
            BackendError, "External changes preserved"
        ) as failure:
            self.checkout(created["timeline"]["action_id"])
        saved = failure.exception.details["preserved_action"]
        self.assertNotEqual(self.head(), original_head)
        self.assertEqual(self.head(), saved)
        self.assertEqual((self.root / "a.vmf").read_bytes(), external)
        self.checkout(created["timeline"]["action_id"])
        self.checkout(saved)
        self.assertEqual((self.root / "a.vmf").read_bytes(), external)

    def test_stale_head_and_dry_run_leave_saved_bytes_unchanged(self):
        created = self.call("create_map", path="a.vmf")
        edited = self.edit("a.vmf", message="current")
        before = (self.root / "a.vmf").read_bytes()
        with self.assertRaisesRegex(BackendError, "HEAD conflict"):
            self.call(
                "checkout_action",
                target=timeline.ROOT,
                expected_head=created["timeline"]["head"],
            )
        preview = self.checkout(created["timeline"]["action_id"], dry_run=True)
        self.assertTrue(preview["changes"])
        self.assertEqual((self.root / "a.vmf").read_bytes(), before)
        self.assertEqual(self.head(), edited["timeline"]["head"])

    def test_failed_multifile_action_retains_all_observed_effects(self):
        game = self.root / "game"
        game.mkdir()
        info = game / "gameinfo.txt"
        info.write_bytes(b"original game config")
        created = self.call("create_map", path="destination.vmf")
        config = {"game_dir": str(game)}

        def partial(*args, **kwargs):
            info.write_bytes(b"mounted import before destination failed")
            raise BackendError(
                "destination publication failed", {"fixture": "file side effect only"}
            )

        with patch(
            "cli_anything.hammerplusplus.reference.copy_objects", side_effect=partial
        ):
            with self.assertRaisesRegex(BackendError, "publication failed") as failure:
                api.execute(
                    self.project,
                    config,
                    "copy_reference_objects",
                    {
                        "source": "reference.vmf",
                        "destination": "destination.vmf",
                        "source_revision": "0" * 64,
                        "expected_revision": created["revision"],
                        "selection": [{"id": 2, "kind": "solid"}],
                    },
                )
        partial_id = failure.exception.details["action_id"]
        self.assertEqual(self.head(), partial_id)
        self.checkout(created["timeline"]["action_id"])
        self.assertEqual(info.read_bytes(), b"original game config")
        self.checkout(partial_id)
        self.assertEqual(info.read_bytes(), b"mounted import before destination failed")

    def test_process_crash_reconciles_and_clears_only_confirmed_dead_lock(self):
        created = self.call("create_map", path="a.vmf")
        before = (self.root / "a.vmf").read_bytes()
        self.child("""
import os,sys
from cli_anything.hammerplusplus import timeline
from cli_anything.hammerplusplus.project import Project,atomic_write
p=Project(sys.argv[1])
def crash():
    timeline.track_file(p,'a.vmf')
    path=p.map_path('a.vmf')
    atomic_write(path,path.read_bytes()+b'\\n// interrupted native-independent action\\n')
    os._exit(97)
timeline.run(p,{},'crash_fixture',{},crash,mutating=True)
""")
        self.assertTrue((self.root / ".hammer-agent/write.lock").exists())
        self.call("timeline_status")
        self.assertFalse((self.root / ".hammer-agent/write.lock").exists())
        actions = timeline.Timeline(self.project).history()["actions"]
        interrupted = next(a for a in actions if a["tool"] == "crash_fixture")
        self.assertEqual(interrupted["status"], "interrupted")
        partial = (self.root / "a.vmf").read_bytes()
        self.assertNotEqual(partial, before)
        self.checkout(created["timeline"]["action_id"])
        self.assertEqual((self.root / "a.vmf").read_bytes(), before)
        self.checkout(interrupted["id"])
        self.assertEqual((self.root / "a.vmf").read_bytes(), partial)

    def test_crashed_checkout_resumes_a_mixed_before_after_file_set(self):
        self.call("create_map", path="a.vmf")
        baseline = self.call("create_map", path="b.vmf")
        original = {
            name: (self.root / name).read_bytes() for name in ("a.vmf", "b.vmf")
        }
        self.edit("a.vmf", message="changed a")
        self.edit("b.vmf", message="changed b")
        target, head = baseline["timeline"]["action_id"], self.head()
        self.child(f"""
import os,sys
from cli_anything.hammerplusplus import api,timeline
from cli_anything.hammerplusplus.project import Project
p=Project(sys.argv[1])
real=timeline.restore_file
def crash(*args,**kwargs):
    real(*args,**kwargs)
    os._exit(97)
timeline.restore_file=crash
api.execute(p,{{}},'checkout_action',{{'target':{target!r},'expected_head':{head!r}}})
""")
        self.call("timeline_status")
        for name, data in original.items():
            self.assertEqual((self.root / name).read_bytes(), data)
        states = timeline.Timeline(self.project).history()["actions"]
        self.assertTrue(any(a["status"] == "reconciled" for a in states))

    def test_missing_or_corrupt_blob_prevents_checkout_without_overwriting(self):
        created = self.call("create_map", path="a.vmf")
        self.edit("a.vmf", message="current")
        before = (self.root / "a.vmf").read_bytes()
        blob = self.root / f".hammer-agent/checkpoints/blobs/{created['revision']}"
        blob.write_bytes(b"corrupt blob")
        with self.assertRaisesRegex(BackendError, "checksum"):
            self.checkout(created["timeline"]["action_id"])
        self.assertEqual((self.root / "a.vmf").read_bytes(), before)

    def test_audit_persistence_failure_prevents_creation(self):
        with patch.object(
            timeline.Timeline, "export_events", side_effect=OSError("disk full")
        ):
            with self.assertRaises(OSError):
                self.call("create_map", path="a.vmf")
        self.assertFalse((self.root / "a.vmf").exists())

    def test_native_staging_hook_tracks_saved_bytes_and_excludes_metadata(self):
        stage = self.root / ".hammer-agent/native-sessions/session/document/a.vmf"
        stage.parent.mkdir(parents=True)
        stage.write_bytes(b"saved document before command")

        def dispatched():
            timeline.track_file(self.project, stage)
            stage.write_bytes(b"saved document after command")
            return {"status": "dispatched", "document_reversible": True}

        result = timeline.run(
            self.project, {}, "native_fixture", {}, dispatched, mutating=True
        )
        self.assertEqual(result["timeline"]["status"], "dispatched")
        self.checkout(timeline.ROOT)
        self.assertEqual(stage.read_bytes(), b"saved document before command")
        self.checkout(result["timeline"]["action_id"])
        self.assertEqual(stage.read_bytes(), b"saved document after command")
        with self.assertRaisesRegex(MapError, "metadata"):
            timeline.file_path(self.project, ".hammer-agent/timeline/actions.sqlite3")


if __name__ == "__main__":
    unittest.main()
