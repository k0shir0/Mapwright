import tempfile
from pathlib import Path
import unittest

from cli.hammerplusplus import kz, vmf
from cli.hammerplusplus.api import execute
from cli.hammerplusplus.project import Project

RUNS = Path(__file__).resolve().parents[1] / ".local/test-runs"
RUNS.mkdir(parents=True, exist_ok=True)


class KZTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=RUNS)
        self.addCleanup(self.temp.cleanup)
        self.project = Project(self.temp.name)
        self.project.create("kz_test.vmf", "kz-room")

    def edit(self, **op):
        return self.project.apply(
            "kz_test.vmf", self.project.inspect("kz_test.vmf")["revision"], [op]
        )["results"][0]["ids"][0]

    def entity(self, name, cls="trigger_multiple", origin=None, **props):
        return self.edit(
            op="add_entity",
            classname=cls,
            origin=origin or [0, 0, 0],
            properties={"targetname": name, "spawnflags": "1", **props},
        )

    def volume(self, entity, low, high, **props):
        return self.edit(
            op="add_box",
            min=low,
            max=high,
            parent_id=entity,
            parent_kind="entity",
            material="tools/toolstrigger",
            **props,
        )

    def rules(self, check="audit", **kwargs):
        return {
            x["rule"]
            for x in kz.run(self.project, "kz_test.vmf", check, **kwargs)["findings"]
        }

    def test_starter_has_valid_contract_and_no_runtime_claim(self):
        result = execute(self.project, {}, "kz_audit", {"path": "kz_test.vmf"})
        self.assertTrue(result["valid"], result)
        self.assertEqual(
            result["revision"], self.project.inspect("kz_test.vmf")["revision"]
        )
        self.assertIn("not the BSP", result["limitations"])
        plan = execute(self.project, {}, "kz_test_plan", {"path": "kz_test.vmf"})
        self.assertIn("do not reproduce GOKZ", plan["cvar_scope"])

    def test_contract_typos_bonus_pairs_buttons_and_version(self):
        self.edit(
            op="set_properties",
            id=1,
            kind="world",
            properties={"climb_mapping_api_version": "V1"},
        )
        button = self.entity(
            "climb_bonus1_startbutton", "func_button", spawnflags="1025"
        )
        self.volume(button, [0, 0, 0], [32, 32, 16])
        self.entity("climb_startbuton", "func_button")
        rules = self.rules()
        self.assertTrue(
            {
                "mapping.version",
                "button.flags",
                "timer.pair",
                "course.start",
                "name.unknown",
            }
            <= rules,
            rules,
        )

    def test_antibhop_thickness_time_and_floor_clearance(self):
        anti = self.entity("climb_anti_bhop", climb_anti_bhop_time="bad")
        self.volume(anti, [-100, -100, 0], [100, 100, 15])
        self.entity("test_dest", "info_teleport_destination", [0, 0, 2], angles="0 0 0")
        self.assertTrue(
            {"antibhop.thickness", "antibhop.triggerhop", "value.climb_anti_bhop_time"}
            <= self.rules("antibhop")
        )
        self.edit(
            op="set_properties",
            id=anti,
            kind="entity",
            properties={"climb_anti_bhop_time": "0"},
        )
        self.assertNotIn("value.climb_anti_bhop_time", self.rules("antibhop"))

    def test_bhop_and_teleport_values(self):
        trigger = self.entity(
            "climb_teleport",
            climb_teleport_type="2",
            climb_teleport_delay="0.079",
            climb_teleport_destination="!player",
            climb_teleport_reorient_player="1",
            climb_teleport_relative="1",
        )
        self.volume(trigger, [0, 0, 0], [32, 32, 32])
        self.assertIn("bhop.delay", self.rules("bhop"))
        self.assertTrue(
            {"teleport.destination", "teleport.reorient_relative"}
            <= self.rules("teleports")
        )
        self.edit(
            op="set_properties",
            id=trigger,
            kind="entity",
            properties={"climb_teleport_delay": "0.08"},
        )
        self.assertNotIn("bhop.delay", self.rules("bhop"))

    def test_edge_measure_top_faces_offsets_and_route(self):
        a = self.edit(op="add_box", min=[-300, 0, 0], max=[-268, 64, 32])
        b = self.edit(op="add_box", min=[-28, 0, 0], max=[4, 64, 32])
        args = {"start": {"id": a}, "end": {"id": b}}
        result = kz.run(self.project, "kz_test.vmf", "measure", **args)
        self.assertEqual(result["gap"], 240)
        self.assertTrue(result["jumpstat_block_geometry"])
        self.assertEqual(result["delta_z"], 0)
        side = self.project.object("kz_test.vmf", a, "solid")["side_ids"][0]
        args["start"] = {"id": side, "kind": "side"}
        self.assertEqual(
            kz.run(self.project, "kz_test.vmf", "measure", **args)["gap"], 240
        )
        result = kz.run(
            self.project, "kz_test.vmf", "bhop", route=[{"id": a}, {"id": b}]
        )
        self.assertIn("bhop.mbh_distance", {f["rule"] for f in result["findings"]})
        self.edit(op="translate", id=b, kind="solid", delta=[0, 1, 1])
        self.assertFalse(
            kz.run(self.project, "kz_test.vmf", "measure", **args)[
                "jumpstat_block_geometry"
            ]
        )

    def test_plane_points_are_not_treated_as_vertices(self):
        solid = self.edit(op="add_box", min=[0, 0, 0], max=[32, 64, 16])
        root = vmf.parse(self.project.source("kz_test.vmf")["source"])
        obj = vmf.find_id(root, solid, "solid")
        self.assertEqual(kz.box(obj)["max"], [32, 64, 16])
        # A plane can use points arbitrarily far along the same infinite plane.
        top = obj.blocks("side")[0]
        self.edit(
            op="set_properties",
            id=int(top.get("id")),
            kind="side",
            properties={"plane": "(0 10000 16) (10000 0 16) (0 0 16)"},
        )
        root = vmf.parse(self.project.source("kz_test.vmf")["source"])
        self.assertEqual(kz.box(vmf.find_id(root, solid, "solid"))["max"], [32, 64, 16])

    def test_water_face_materials_ladder_owner_and_headroom(self):
        water = self.edit(
            op="add_box",
            min=[-100, -100, 0],
            max=[100, 100, 16],
            face_materials={"top": "dev/dev_water2"},
        )
        self.assertNotIn("water.top", self.rules("water"))
        self.assertNotIn("water.nodraw", self.rules("water"))
        self.assertIn("water.lod", self.rules("water"))
        ladder = self.entity("ladder", "func_ladder")
        self.edit(
            op="add_box",
            min=[200, 0, 0],
            max=[204, 32, 64],
            parent_id=ladder,
            parent_kind="entity",
            face_materials={"west": "TOOLS/TOOLSINVISIBLELADDER"},
        )
        self.assertIn("ladder.owner", self.rules("ladders"))
        self.edit(op="add_box", min=[-32, -32, 100], max=[32, 32, 116])
        self.assertIn("head.clearance", self.rules("headhitter"))
        self.assertTrue(self.project.validate("kz_test.vmf")["valid"])

    def test_unsupported_and_hidden_geometry_is_explicit(self):
        solid = self.edit(op="add_box", min=[0, 0, 0], max=[32, 32, 32])
        side = self.project.object("kz_test.vmf", solid, "solid")["side_ids"][0]
        self.edit(
            op="set_properties",
            id=side,
            kind="side",
            properties={"plane": "(0 32 32) (32 0 16) (0 0 32)"},
        )
        result = kz.run(self.project, "kz_test.vmf")
        self.assertFalse(result["complete"])
        self.assertIn(str(solid), {r["id"] for r in result["unsupported_geometry"]})
        with self.assertRaises(vmf.MapError):
            kz.run(
                self.project,
                "kz_test.vmf",
                "measure",
                start={"id": solid},
                end={"id": solid},
            )


if __name__ == "__main__":
    unittest.main()
