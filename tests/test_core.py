import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from cli_anything.hammerplusplus import api, backend, catalog, vmf
from cli_anything.hammerplusplus.project import Project, atomic_write, digest

TEST_ROOT = Path(__file__).resolve().parents[1] / ".local/test-runs"
TEST_ROOT.mkdir(parents=True, exist_ok=True)


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEST_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = Project(self.root)
        self.project.create("map.vmf")

    def revision(self):
        return self.project.inspect("map.vmf")["revision"]

    def edit(self, *operations):
        return self.project.apply("map.vmf", self.revision(), list(operations))

    def test_room_and_independent_geometry_oracle(self):
        from srctools import Keyvalues, Vec
        from srctools.vmf import VMF

        self.project.create("room.vmf", "csgo-room")
        source = (self.root / "room.vmf").read_text()
        parsed = VMF.parse(Keyvalues.parse(source))
        self.assertEqual(len(parsed.brushes), 6)
        self.assertEqual(len(parsed.entities), 3)
        low, high = parsed.brushes[0].get_bbox()
        self.assertEqual(low, Vec(-528, -528, -16))
        self.assertEqual(high, Vec(528, 528, 0))
        for brush in parsed.brushes:
            low, high = brush.get_bbox()
            centre = (low + high) / 2
            for side in brush.sides:
                self.assertGreater(side.normal().dot(centre - side.planes[0]), 0)
        self.assertTrue(self.project.validate("room.vmf")["valid"])

    def test_targeted_edits_preserve_unknown_comments_and_encoding(self):
        path = self.root / "map.vmf"
        original = (
            path.read_bytes()
            + b'// caf\xe9\r\nhammerplusplus_custom\r\n{ "future" "unchanged" }\r\n'
        )
        path.write_bytes(original)
        self.edit(
            {"op": "set_properties", "id": 1, "properties": {"skyname": "sky_day01_01"}}
        )
        after = path.read_bytes()
        self.assertEqual(after, original.replace(b"sky_dust", b"sky_day01_01"))

    def test_batch_is_atomic_on_late_failure(self):
        before = (self.root / "map.vmf").read_bytes()
        with self.assertRaises(vmf.MapError):
            self.edit(
                {"op": "add_entity", "classname": "logic_relay", "origin": [0, 0, 0]},
                {"op": "delete", "id": 9999},
            )
        self.assertEqual((self.root / "map.vmf").read_bytes(), before)
        self.assertEqual(self.project.history("map.vmf")["position"], 0)

    def test_stale_revision_and_dry_run(self):
        revision = self.revision()
        result = self.project.apply(
            "map.vmf",
            revision,
            [{"op": "add_box", "min": [0, 0, 0], "max": [16, 16, 16]}],
            True,
        )
        self.assertNotEqual(revision, result["revision"])
        self.assertEqual(revision, self.revision())
        self.assertEqual(self.project.history("map.vmf")["position"], 0)
        self.edit({"op": "add_entity", "classname": "light", "origin": [0, 0, 64]})
        with self.assertRaisesRegex(vmf.MapError, "Revision conflict"):
            self.project.apply("map.vmf", revision, [{"op": "delete", "id": 2}])

    def test_unique_ids_duplicate_outputs_and_brush_entity(self):
        entity = self.edit(
            {"op": "add_entity", "classname": "func_detail", "origin": [0, 0, 0]}
        )["results"][0]["ids"][0]
        brush = self.edit(
            {
                "op": "add_box",
                "min": [0, 0, 0],
                "max": [64, 64, 64],
                "parent_id": entity,
            }
        )["results"][0]["ids"][0]
        for _ in range(2):
            self.edit(
                {
                    "op": "add_output",
                    "id": entity,
                    "event": "OnUser1",
                    "target": "relay",
                    "input": "Trigger",
                }
            )
        self.assertEqual(len(self.project.object("map.vmf", entity)["outputs"]), 2)
        self.assertEqual(len(self.project.object("map.vmf", brush)["side_ids"]), 6)
        self.assertTrue(self.project.validate("map.vmf")["valid"])

    def test_translation_moves_planes_origin_and_texture_lock(self):
        brush = self.edit({"op": "add_box", "min": [0, 0, 0], "max": [32, 32, 32]})[
            "results"
        ][0]["ids"][0]
        self.edit({"op": "translate", "id": brush, "delta": [16, 32, 64]})
        result = self.project.object("map.vmf", brush)
        self.assertIn("(16 32 96)", result["source"])
        self.assertIn("[1 0 0 -64] 0.25", result["source"])
        ent = self.edit(
            {"op": "add_entity", "classname": "light", "origin": [0, 0, 16]}
        )["results"][0]["ids"][0]
        self.edit({"op": "translate", "id": ent, "delta": [16, 0, 0]})
        self.assertEqual(
            self.project.object("map.vmf", ent)["properties"]["origin"], "16 0 16"
        )

    def test_undo_redo_and_new_branch(self):
        original = self.revision()
        first = self.edit(
            {"op": "add_entity", "classname": "light", "origin": [0, 0, 64]}
        )["revision"]
        self.project.restore("map.vmf", first, "undo")
        self.assertEqual(self.revision(), original)
        self.project.restore("map.vmf", original, "redo")
        self.assertEqual(self.revision(), first)
        self.project.restore("map.vmf", first, "undo")
        self.edit({"op": "add_entity", "classname": "logic_relay", "origin": [0, 0, 0]})
        with self.assertRaisesRegex(vmf.MapError, "Nothing to redo"):
            self.project.restore("map.vmf", self.revision(), "redo")

    def test_external_edit_cannot_be_overwritten_by_undo(self):
        self.edit({"op": "add_entity", "classname": "light", "origin": [0, 0, 0]})
        path = self.root / "map.vmf"
        path.write_bytes(path.read_bytes() + b"// human edit\n")
        before = path.read_bytes()
        with self.assertRaisesRegex(vmf.MapError, "External map changes"):
            self.project.restore("map.vmf", self.revision(), "undo")
        self.assertEqual(path.read_bytes(), before)

    def test_pending_journal_recovers_after_map_published(self):
        before = self.revision()
        self.edit({"op": "add_entity", "classname": "light", "origin": [0, 0, 0]})
        journal = self.project.journal_path(self.root / "map.vmf")
        state = json.loads(journal.read_text())
        atomic_write(
            journal,
            json.dumps(
                {
                    "entries": [],
                    "position": 0,
                    "pending": {
                        "before": before,
                        "after": self.revision(),
                        "state": state,
                    },
                }
            ).encode(),
        )
        self.assertEqual(self.project.history("map.vmf")["position"], 1)
        self.assertNotIn("pending", json.loads(journal.read_text()))

    def test_pending_journal_recovers_before_map_published(self):
        before = self.revision()
        self.edit({"op": "add_entity", "classname": "light", "origin": [0, 0, 0]})
        after = self.revision()
        journal = self.project.journal_path(self.root / "map.vmf")
        state = json.loads(journal.read_text())
        (self.root / "map.vmf").write_bytes(self.project.snapshot(before))
        atomic_write(
            journal,
            json.dumps(
                {
                    "entries": [],
                    "position": 0,
                    "pending": {"before": before, "after": after, "state": state},
                }
            ).encode(),
        )
        self.assertEqual(self.project.history("map.vmf")["position"], 0)

    def test_failed_map_publication_retains_original(self):
        before = self.revision()
        real = atomic_write

        def fail_map(path, data):
            if path == self.root / "map.vmf":
                raise OSError("simulated publication failure")
            return real(path, data)

        with patch(
            "cli_anything.hammerplusplus.project.atomic_write", side_effect=fail_map
        ):
            with self.assertRaises(OSError):
                self.edit(
                    {"op": "add_entity", "classname": "light", "origin": [0, 0, 0]}
                )
        self.assertEqual(self.revision(), before)
        self.assertEqual(self.project.history("map.vmf")["position"], 0)

    def test_paths_locks_and_overwrite(self):
        for path in ("../outside.vmf", "map.txt", ".hammer-agent/map.vmf"):
            with self.subTest(path=path), self.assertRaises(vmf.MapError):
                self.project.create(path)
        with self.assertRaises(vmf.MapError):
            self.project.create("map.vmf")
        with self.project.locked(), self.assertRaisesRegex(vmf.MapError, "locked"):
            self.edit({"op": "delete", "id": 2})

    def test_symlink_escape(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as external:
            try:
                (self.root / "link").symlink_to(external, target_is_directory=True)
            except OSError:
                self.skipTest("Host does not permit symlink creation")
            with self.assertRaisesRegex(vmf.MapError, "inside"):
                self.project.create("link/escape.vmf")

    def test_schema_validation_at_shared_boundary(self):
        for args in (
            {"path": "map.vmf", "offset": True},
            {"path": "map.vmf", "extra": "invalid"},
            {"path": ["map.vmf"]},
            {},
        ):
            with self.subTest(args=args), self.assertRaises(vmf.MapError):
                api.execute(self.project, {}, "inspect_map", args)
        with self.assertRaises(vmf.MapError):
            api.execute(
                self.project,
                {},
                "edit_map",
                {
                    "path": "map.vmf",
                    "expected_revision": self.revision(),
                    "operations": [{"op": "unknown"}],
                },
            )

    def test_catalog_fgd_inheritance_and_vpk(self):
        from srctools.vpk import VPK

        fgd = self.root / "test.fgd"
        fgd.write_text(
            '@BaseClass = Base\n[\n targetname(string) : "Name" : ""\n]\n@PointClass base(Base) = logic_relay : "Relay"\n[\n input Trigger(void) : "Run"\n output OnTrigger(void) : "Fired"\n]\n'
        )
        result = catalog.entities(
            self.project, {"fgd": str(fgd)}, classname="logic_relay"
        )
        self.assertIn("targetname", [key["name"] for key in result["keyvalues"]])
        self.assertEqual(result["inputs"][0]["name"], "Trigger")
        game = self.root / "game"
        game.mkdir()
        (game / "gameinfo.txt").write_text("test")
        with VPK(game / "pak01_dir.vpk", mode="w") as vpk:
            vpk.add_file("materials/dev/test.vmt", b"UnlitGeneric {}")
            vpk.add_file("models/test.mdl", b"test")
        result = catalog.assets(self.project, {"game_dir": str(game)}, query="test")
        self.assertEqual(result["assets"][0]["name"], "dev/test")

    def test_missing_backend_fails_without_fake_artifacts(self):
        with self.assertRaises(backend.BackendError):
            backend.compile_map(self.project, {}, "map.vmf", self.revision())
        self.assertFalse((self.root / ".hammer-agent/builds").exists())
        self.assertFalse(backend.doctor(self.project, {})["compile_ready"])


class FormatTests(unittest.TestCase):
    def test_parser_rejects_malformed_input(self):
        for text in (
            "world {",
            "world }",
            '"unterminated',
            'world { "key" }',
            'world { key "unterminated }',
        ):
            with self.subTest(text=text), self.assertRaises(vmf.MapError):
                vmf.parse(text)

    def test_invalid_geometry_and_mutation(self):
        for op in (
            {"op": "add_box", "min": [1, 1, 1], "max": [0, 0, 0]},
            {"op": "add_box", "min": [float("nan"), 0, 0], "max": [16, 16, 16]},
            {"op": "add_room", "min": [0, 0, 0], "max": [16, 16, 16], "thickness": 0},
            {"op": "set_properties", "id": 1, "properties": {"id": "99"}},
            {"op": "delete", "id": 1},
            {"op": "add_entity", "classname": "worldspawn", "origin": [0, 0, 0]},
        ):
            with self.subTest(op=op), self.assertRaises(vmf.MapError):
                vmf.mutate(vmf.new_map(), op)

    def test_validator_detects_duplicate_ids_and_bad_planes(self):
        source, _ = vmf.mutate(
            vmf.new_map(), {"op": "add_box", "min": [0, 0, 0], "max": [16, 16, 16]}
        )
        source = source.replace('"id" "3"', '"id" "1"', 1)
        self.assertFalse(vmf.validate(source)["valid"])
        plane = (
            vmf.parse(source)
            .blocks("world")[0]
            .blocks("solid")[0]
            .blocks("side")[0]
            .get("plane")
        )
        source = source.replace(plane, "(0 0 0) (0 0 0) (0 0 0)", 1)
        self.assertTrue(
            any("degenerate" in error for error in vmf.validate(source)["errors"])
        )

    def test_bsp_header_rejects_empty_and_wrong_version(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as folder:
            path = Path(folder) / "map.bsp"
            for data in (
                b"",
                b"VBSP" + struct.pack("<i", 20) + bytes(1028),
                b"VBSP" + struct.pack("<i", 21) + bytes(1028),
            ):
                path.write_bytes(data)
                with self.assertRaises(backend.BackendError):
                    backend.bsp_info(path)


if __name__ == "__main__":
    unittest.main()
