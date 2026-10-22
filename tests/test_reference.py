import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from cli.hammerplusplus import api, reference, vmf
from cli.hammerplusplus.project import Project, digest

RUNS = Path(__file__).resolve().parents[1] / ".local/test-runs"
RUNS.mkdir(parents=True, exist_ok=True)


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=RUNS)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = Project(self.root)
        self.project.create("source.vmf")
        self.project.create("destination.vmf", "csgo-room")

    def revision(self, path):
        return self.project.inspect(path)["revision"]

    def edit(self, *ops):
        return self.project.apply("source.vmf", self.revision("source.vmf"), list(ops))

    def copy(self, selection, **kwargs):
        return reference.copy_objects(
            self.project,
            "source.vmf",
            "destination.vmf",
            self.revision("source.vmf"),
            self.revision("destination.vmf"),
            selection,
            **kwargs,
        )

    def test_full_source_edit_preserves_unknown_features_and_undo(self):
        old = self.project.source("source.vmf")
        source = old["source"] + '\nunknown_future_block { "custom" "value" }\n'
        result = self.edit({"op": "replace_source", "source": source})
        self.assertEqual(self.project.source("source.vmf")["source"], source)
        history = self.project.history("source.vmf")
        self.assertNotIn(source, json.dumps(history))
        self.project.restore("source.vmf", result["revision"], "undo")
        self.assertEqual(self.revision("source.vmf"), old["revision"])
        with self.assertRaises(vmf.MapError):
            self.edit({"op": "replace_source", "source": "world {"})
        self.assertEqual(self.revision("source.vmf"), old["revision"])

    def test_file_delete_is_revision_checked_and_recoverable(self):
        old = self.revision("source.vmf")
        with self.assertRaises(vmf.MapError):
            self.project.delete_file("source.vmf", "0" * 64)
        result = self.project.delete_file("source.vmf", old)
        self.assertFalse((self.root / "source.vmf").exists())
        restored = self.project.restore_file(result["token"])
        self.assertEqual(restored["revision"], old)
        with self.assertRaises(FileExistsError):
            self.project.restore_file(result["token"])
        self.assertEqual(self.project.files()["total"], 2)
        with self.assertRaises(vmf.MapError):
            self.project.restore_file("../bad")

    def test_reference_vmf_import_is_exclusive_and_tracks_provenance(self):
        original = self.root / "source.vmf"
        result = reference.import_map(
            self.project, {}, str(original), "references/imported.vmf"
        )
        self.assertEqual(
            result["provenance"]["source_revision"], digest(original.read_bytes())
        )
        self.assertTrue(result["validation"]["valid"])
        with self.assertRaises(vmf.MapError):
            reference.import_map(
                self.project, {}, str(original), "references/imported.vmf"
            )

    def test_spatial_material_search_and_copy_geometry(self):
        result = self.edit(
            {
                "op": "add_box",
                "min": [0, 0, 0],
                "max": [32, 32, 32],
                "material": "tile/test",
            }
        )
        brush = result["results"][0]["ids"][0]
        self.edit({"op": "add_box", "min": [100, 100, 0], "max": [132, 132, 32]})
        found = reference.search(
            self.project, "source.vmf", "tile/test", [0, 0, 0], [40, 40, 40]
        )
        self.assertEqual(found["total"], 1)
        before = self.revision("destination.vmf")
        copied = self.copy([{"id": brush, "kind": "solid"}], delta=[64, 0, 0])
        new_id = copied["copied"][0]["destination_id"]
        obj = self.project.object("destination.vmf", new_id, "solid")
        self.assertIn("(96 32 32)", obj["source"])
        self.assertIn("tile/test", obj["source"])
        self.assertEqual(self.project.inspect("destination.vmf")["counts"]["solid"], 7)
        self.project.restore("destination.vmf", copied["revision"], "undo")
        self.assertEqual(self.revision("destination.vmf"), before)

    def test_copy_link_closure_remaps_names_and_duplicate_outputs(self):
        first = self.edit(
            {
                "op": "add_entity",
                "classname": "trigger_once",
                "origin": [0, 0, 0],
                "properties": {"targetname": "start"},
            }
        )["results"][0]["ids"][0]
        second = self.edit(
            {
                "op": "add_entity",
                "classname": "logic_relay",
                "origin": [0, 0, 32],
                "properties": {"targetname": "finish"},
            }
        )["results"][0]["ids"][0]
        for _ in range(2):
            self.edit(
                {
                    "op": "add_output",
                    "id": first,
                    "event": "OnStartTouch",
                    "target": "finish",
                    "input": "Trigger",
                }
            )
        self.edit(
            {
                "op": "add_output",
                "id": second,
                "event": "OnUser1",
                "target": "start",
                "input": "Trigger",
            }
        )
        result = self.copy(
            [{"id": first, "kind": "entity"}], prefix="copied_", delta=[16, 0, 0]
        )
        self.assertEqual(len(result["copied"]), 2)
        self.assertEqual(result["external_references"], [])
        source = self.project.object(
            "destination.vmf", result["copied"][0]["destination_id"], "entity"
        )["source"]
        self.assertEqual(source.count("copied_finish"), 2)
        self.assertIn("copied_start", source)
        self.assertIn("16 0 0", source)
        self.assertTrue(self.project.validate("destination.vmf")["valid"])
        with self.assertRaisesRegex(vmf.MapError, "collides"):
            self.copy([{"id": first, "kind": "entity"}], prefix="copied_")

    def test_linked_parent_replaces_explicitly_selected_child(self):
        parent = self.edit(
            {
                "op": "add_entity",
                "classname": "func_detail",
                "origin": [0, 0, 0],
                "properties": {"targetname": "owner"},
            }
        )["results"][0]["ids"][0]
        child = self.edit(
            {
                "op": "add_box",
                "min": [0, 0, 0],
                "max": [16, 16, 16],
                "parent_id": parent,
                "parent_kind": "entity",
            }
        )["results"][0]["ids"][0]
        relay = self.edit(
            {
                "op": "add_entity",
                "classname": "logic_relay",
                "origin": [0, 0, 0],
                "properties": {"target": "owner"},
            }
        )["results"][0]["ids"][0]
        result = self.copy(
            [{"id": child, "kind": "solid"}, {"id": relay, "kind": "entity"}],
            prefix="linked_",
        )
        self.assertEqual(
            [row["source_id"] for row in result["copied"]], [relay, parent]
        )
        self.assertEqual(self.project.inspect("destination.vmf")["counts"]["solid"], 7)

    def test_external_references_reported_when_links_excluded(self):
        ent = self.edit(
            {
                "op": "add_entity",
                "classname": "trigger_teleport",
                "origin": [0, 0, 0],
                "properties": {"target": "outside"},
            }
        )["results"][0]["ids"][0]
        result = self.copy([{"id": ent, "kind": "entity"}], include_links=False)
        self.assertEqual(result["external_references"], ["outside"])

    def test_output_entity_parameters_are_followed_and_remapped(self):
        first = self.edit(
            {
                "op": "add_entity",
                "classname": "logic_relay",
                "origin": [0, 0, 0],
                "properties": {"targetname": "a"},
            }
        )["results"][0]["ids"][0]
        self.edit(
            {
                "op": "add_entity",
                "classname": "info_target",
                "origin": [0, 0, 0],
                "properties": {"targetname": "b"},
            }
        )
        self.edit(
            {
                "op": "add_entity",
                "classname": "info_target",
                "origin": [0, 0, 0],
                "properties": {"targetname": "c"},
            }
        )
        self.edit(
            {
                "op": "add_output",
                "id": first,
                "event": "OnTrigger",
                "target": "b",
                "input": "SetParent",
                "parameter": "c",
            }
        )
        result = self.copy([{"id": first, "kind": "entity"}], prefix="copied_")
        self.assertEqual(len(result["copied"]), 3)
        self.assertEqual(result["external_references"], [])
        source = self.project.object(
            "destination.vmf", result["copied"][0]["destination_id"], "entity"
        )["source"]
        self.assertIn("copied_b,SetParent,copied_c", source)

    def test_gokz_copy_preserves_protocol_names_and_remaps_destination(self):
        self.edit(
            {
                "op": "set_properties",
                "id": 1,
                "kind": "world",
                "properties": {"climb_mapping_api_version": "1"},
            }
        )
        trigger = self.edit(
            {
                "op": "add_entity",
                "classname": "trigger_multiple",
                "origin": [0, 0, 0],
                "properties": {
                    "targetname": "climb_teleport",
                    "climb_teleport_destination": "landing",
                },
            }
        )["results"][0]["ids"][0]
        self.edit(
            {
                "op": "add_entity",
                "classname": "info_teleport_destination",
                "origin": [0, 0, 8],
                "properties": {"targetname": "landing"},
            }
        )
        result = self.copy([{"id": trigger, "kind": "entity"}], prefix="copied_")
        self.assertEqual(len(result["copied"]), 2)
        source = self.project.object(
            "destination.vmf", result["copied"][0]["destination_id"], "entity"
        )["source"]
        self.assertIn('"targetname" "climb_teleport"', source)
        self.assertIn('"climb_teleport_destination" "copied_landing"', source)
        self.assertEqual(
            self.project.object("destination.vmf", 1, "world")["properties"][
                "climb_mapping_api_version"
            ],
            "1",
        )

    def test_fgd_typed_output_parameters_remap_before_target_rename(self):
        first = self.edit(
            {
                "op": "add_entity",
                "classname": "logic_relay",
                "origin": [0, 0, 0],
                "properties": {"targetname": "a"},
            }
        )["results"][0]["ids"][0]
        self.edit(
            {
                "op": "add_entity",
                "classname": "logic_relay",
                "origin": [0, 0, 0],
                "properties": {"targetname": "b"},
            }
        )
        self.edit(
            {
                "op": "add_entity",
                "classname": "info_target",
                "origin": [0, 0, 0],
                "properties": {"targetname": "c"},
            }
        )
        self.edit(
            {
                "op": "add_output",
                "id": first,
                "event": "OnTrigger",
                "target": "b",
                "input": "SetCustomParent",
                "parameter": "c",
            }
        )
        fgd = self.root / "custom.fgd"
        fgd.write_text(
            "@PointClass = logic_relay\n[\ninput SetCustomParent(target_destination)\n]\n"
        )
        result = self.copy(
            [{"id": first, "kind": "entity"}],
            prefix="copied_",
            config={"fgd": str(fgd)},
        )
        self.assertEqual(len(result["copied"]), 3)
        source = self.project.object(
            "destination.vmf", result["copied"][0]["destination_id"], "entity"
        )["source"]
        self.assertIn("copied_b,SetCustomParent,copied_c", source)

    def test_unknown_sides_property_is_preserved(self):
        ent = self.edit(
            {
                "op": "add_entity",
                "classname": "comp_prop_rope",
                "origin": [0, 0, 0],
                "properties": {"sides": "8"},
            }
        )["results"][0]["ids"][0]
        result = self.copy([{"id": ent, "kind": "entity"}])
        self.assertEqual(
            self.project.object(
                "destination.vmf", result["copied"][0]["destination_id"], "entity"
            )["properties"]["sides"],
            "8",
        )

    def test_face_reference_fields_remap_all_pinned_csgo_entities(self):
        brush = self.edit({"op": "add_box", "min": [0, 0, 0], "max": [16, 16, 16]})[
            "results"
        ][0]["ids"][0]
        face = self.project.object("source.vmf", brush, "solid")["side_ids"][0]
        selection = [{"id": brush, "kind": "solid"}]
        for classname in (
            "info_overlay",
            "env_cubemap",
            "info_no_dynamic_shadow",
            "info_overlay_transition",
        ):
            properties = {"sides": str(face)}
            if classname == "info_overlay_transition":
                properties["sides2"] = str(face)
            ent = self.edit(
                {
                    "op": "add_entity",
                    "classname": classname,
                    "origin": [0, 0, 0],
                    "properties": properties,
                }
            )["results"][0]["ids"][0]
            selection.append({"id": ent, "kind": "entity"})
        result = self.copy(selection)
        newface = self.project.object(
            "destination.vmf", result["copied"][0]["destination_id"], "solid"
        )["side_ids"][0]
        self.assertNotEqual(face, newface)
        for row in result["copied"][1:]:
            properties = self.project.object(
                "destination.vmf", row["destination_id"], "entity"
            )["properties"]
            self.assertEqual(properties["sides"], str(newface))
            if "sides2" in properties:
                self.assertEqual(properties["sides2"], str(newface))

    def test_native_failure_uses_structured_backend_error(self):
        from cli.hammerplusplus import desktop, backend

        with patch.object(
            desktop, "inspect_editor", side_effect=RuntimeError("stale handle")
        ):
            with self.assertRaisesRegex(backend.BackendError, "stale handle"):
                api.execute(self.project, {}, "inspect_editor", {"pid": 123})

    def test_copy_dry_run_stale_source_and_typed_ids(self):
        result = self.edit({"op": "add_box", "min": [0, 0, 0], "max": [16, 16, 16]})
        brush = result["results"][0]["ids"][0]
        before = self.revision("destination.vmf")
        self.copy([{"id": brush, "kind": "solid"}], dry_run=True)
        self.assertEqual(self.revision("destination.vmf"), before)
        with self.assertRaisesRegex(vmf.MapError, "Revision conflict"):
            reference.copy_objects(
                self.project,
                "source.vmf",
                "destination.vmf",
                "0" * 64,
                before,
                [{"id": brush, "kind": "solid"}],
            )
        with self.assertRaises(vmf.MapError):
            self.copy([{"id": brush, "kind": "entity"}])

    def test_displacement_translation_moves_start_not_normals(self):
        source = 'solid { "id" "1" side { "id" "1" "plane" "(0 0 0) (32 0 0) (32 32 0)" dispinfo { "startposition" "[0 0 0]" normals { "row0" "0 0 1" } } } }'
        moved = reference.translated(source, [10, 20, 30])
        self.assertIn("[10 20 30]", moved)
        self.assertIn('"row0" "0 0 1"', moved)

    def fake_bsp(self, members):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as pack:
            for name, content in members.items():
                pack.writestr(name, content)
        header = bytearray(b"VBSP" + struct.pack("<i", 21) + bytes(1028))
        struct.pack_into("<ii", header, 8 + 40 * 16, 1036, len(data.getvalue()))
        path = self.root / "input.bsp"
        path.write_bytes(header + data.getvalue())
        java = self.root / "java.exe"
        java.write_bytes(b"fake")
        return path, {"bspsrc_java": str(java)}

    def decompile(self, command, **kwargs):
        Path(command[command.index("-o") + 1]).write_text(vmf.new_map())

        class Completed:
            returncode = 0

        return Completed()

    def test_embedded_assets_mount_in_workspace_and_dry_run_is_clean(self):
        path, config = self.fake_bsp(
            {"materials/custom/test.vmt": b"test", "bad.exe": b"bad"}
        )
        with patch.object(reference.subprocess, "run", self.decompile):
            imported = reference.import_map(
                self.project, config, str(path), "reference.vmf"
            )
        self.assertIn("Skipped executable", imported["provenance"]["warnings"][0])
        source = self.project.source("source.vmf")["source"]
        source += '\nentity { "id" "2" "classname" "info_target" "origin" "0 0 0" }'
        self.project.apply(
            "reference.vmf",
            imported["revision"],
            [{"op": "replace_source", "source": source}],
        )
        game = self.root / "game"
        game.mkdir()
        info = game / "gameinfo.txt"
        info.write_text('GameInfo { FileSystem { SearchPaths { Game "base" } } }')
        config["game_dir"] = str(game)
        args = dict(
            project=self.project,
            config=config,
            source="reference.vmf",
            destination="destination.vmf",
            source_revision=self.revision("reference.vmf"),
            expected_revision=self.revision("destination.vmf"),
            selection=[{"id": 2, "kind": "entity"}],
        )
        reference.copy_objects(**args, dry_run=True)
        self.assertNotIn(imported["provenance"]["assets_dir"], info.read_text())
        result = reference.copy_objects(**args)
        self.assertTrue(result["asset_mount"]["mounted"])
        self.assertIn(imported["provenance"]["assets_dir"], info.read_text())

    def test_embedded_asset_traversal_fails_without_publishing(self):
        path, config = self.fake_bsp({"../escape.vmt": b"bad"})
        with (
            patch.object(reference.subprocess, "run", self.decompile),
            self.assertRaisesRegex(vmf.MapError, "Unsafe path"),
        ):
            reference.import_map(self.project, config, str(path), "reference.vmf")
        self.assertFalse((self.root / "reference.vmf").exists())
        self.assertFalse((self.root / ".hammer-agent/imports/escape.vmt").exists())

    def test_asset_allowlist_excludes_unrelated_conflicts_and_mounts_only_selected_files(
        self,
    ):
        path, config = self.fake_bsp(
            {"materials/custom/test.vmt": b"selected", "maps/old.nav": b"unused nav"}
        )
        with patch.object(reference.subprocess, "run", self.decompile):
            imported = reference.import_map(
                self.project, config, str(path), "reference.vmf"
            )
        source = (
            self.project.source("reference.vmf")["source"]
            + '\nentity { "id" "2" "classname" "info_target" "origin" "0 0 0" }'
        )
        changed = self.project.apply(
            "reference.vmf",
            imported["revision"],
            [{"op": "replace_source", "source": source}],
        )
        game = self.root / "game"
        (game / "maps").mkdir(parents=True)
        (game / "maps/old.nav").write_bytes(b"different existing nav")
        info = game / "gameinfo.txt"
        info.write_text(
            'GameInfo { FileSystem { SearchPaths { Game "' + game.as_posix() + '" } } }'
        )
        args = dict(
            project=self.project,
            source="reference.vmf",
            destination="destination.vmf",
            source_revision=changed["revision"],
            expected_revision=self.revision("destination.vmf"),
            selection=[{"id": 2, "kind": "entity"}],
            config={**config, "game_dir": str(game)},
            asset_paths=["materials/custom/test.vmt"],
        )
        preview = reference.copy_objects(**args, dry_run=True)
        mount = Path(preview["asset_mount"]["directory"])
        self.assertFalse(mount.exists())
        reference.copy_objects(**args)
        self.assertEqual(
            (mount / "materials/custom/test.vmt").read_bytes(), b"selected"
        )
        self.assertFalse((mount / "maps/old.nav").exists())
        self.assertEqual(
            (game / "maps/old.nav").read_bytes(), b"different existing nav"
        )

    def test_conflicting_embedded_asset_is_rejected_before_map_or_mount_changes(self):
        path, config = self.fake_bsp({"materials/custom/test.vmt": b"incoming"})
        with patch.object(reference.subprocess, "run", self.decompile):
            imported = reference.import_map(
                self.project, config, str(path), "reference.vmf"
            )
        source = (
            self.project.source("reference.vmf")["source"]
            + '\nentity { "id" "2" "classname" "info_target" "origin" "0 0 0" }'
        )
        changed = self.project.apply(
            "reference.vmf",
            imported["revision"],
            [{"op": "replace_source", "source": source}],
        )
        game = self.root / "game"
        (game / "materials/custom").mkdir(parents=True)
        (game / "materials/custom/test.vmt").write_bytes(b"existing")
        info = game / "gameinfo.txt"
        info.write_text(
            'GameInfo { FileSystem { SearchPaths { Game "'
            + str(game).replace("\\", "/")
            + '" } } }'
        )
        config["game_dir"] = str(game)
        before = info.read_bytes()
        revision = self.revision("destination.vmf")
        with self.assertRaisesRegex(
            vmf.MapError, "Embedded asset conflict: materials/custom/test.vmt"
        ):
            reference.copy_objects(
                self.project,
                "reference.vmf",
                "destination.vmf",
                changed["revision"],
                revision,
                [{"id": 2, "kind": "entity"}],
                config=config,
            )
        self.assertEqual(info.read_bytes(), before)
        self.assertEqual(self.revision("destination.vmf"), revision)

        # Unrelated embedded files must not block an explicitly geometry-only copy.
        result = reference.copy_objects(
            self.project,
            "reference.vmf",
            "destination.vmf",
            changed["revision"],
            revision,
            [{"id": 2, "kind": "entity"}],
            config=config,
            asset_paths=[],
        )
        self.assertFalse(result["asset_mount"]["required"])
        self.assertEqual(info.read_bytes(), before)

    def test_api_publishes_all_reference_tools_with_schema_validation(self):
        for name in (
            "import_reference_map",
            "search_reference_map",
            "copy_reference_objects",
            "read_map_source",
            "delete_map_file",
            "restore_map_file",
            "inspect_editor",
            "editor_action",
        ):
            self.assertIn(name, api.TOOLS)
        with self.assertRaises(vmf.MapError):
            api.execute(
                self.project,
                {},
                "search_reference_map",
                {"path": "source.vmf", "minimum": [0, 0]},
            )


if __name__ == "__main__":
    unittest.main()
