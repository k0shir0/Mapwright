"""Regressions from the kz_edp delivery investigation, without native/game claims."""

import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from cli.hammerplusplus import api, backend, kz, vmf
from cli.hammerplusplus.project import Project, digest

RUNS = Path(__file__).resolve().parents[1] / ".local/test-runs"
RUNS.mkdir(parents=True, exist_ok=True)


def material_bsp(path, material="custom/floor", sky="customsky"):
    """Minimal real BSP container for the dependency reader, not a playable map."""
    lumps = {
        0: ('{\n"classname" "worldspawn"\n"skyname" "' + sky + '"\n}\n\0').encode(),
        1: bytes(20),
        5: bytes(32),
        35: bytes(4),
        43: material.encode() + b"\0",
        44: bytes(4),
    }
    header = bytearray(b"VBSP" + struct.pack("<i", 21) + bytes(1028))
    body = bytearray()
    for index, data in sorted(lumps.items()):
        struct.pack_into(
            "<iii4s", header, 8 + index * 16, 1036 + len(body), len(data), 0, bytes(4)
        )
        body.extend(data)
    path.write_bytes(header + body)


class ResearchRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=RUNS)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = Project(self.root)
        self.project.create("map.vmf", "kz-room")

    def test_physical_timer_profile_rejects_zones_and_missing_use_flag(self):
        args = {"path": "map.vmf", "timer_profile": "buttons"}
        result = api.execute(self.project, {}, "kz_audit", args)
        self.assertIn("timer.buttons_required", {f["rule"] for f in result["findings"]})
        revision = self.project.inspect("map.vmf")["revision"]
        for name in ("climb_startbutton", "climb_endbutton"):
            result = self.project.apply(
                "map.vmf",
                revision,
                [
                    {
                        "op": "add_entity",
                        "classname": "func_button",
                        "origin": [0, 0, 0],
                        "properties": {"targetname": name, "spawnflags": "33"},
                    }
                ],
            )
            revision = result["revision"]
        result = api.execute(self.project, {}, "kz_audit", args)
        self.assertIn("button.use", {f["rule"] for f in result["findings"]})

    def test_spawn_over_void_and_capacity_are_reported(self):
        source = self.project.source("map.vmf")["source"]
        root = vmf.parse(source)
        # Keep the original clear spawns, remove every potential floor provider.
        source = vmf.replace(
            source,
            [(s.start, s.end, "") for s in root.blocks("world")[0].blocks("solid")],
        )
        self.project.apply(
            "map.vmf",
            digest((self.root / "map.vmf").read_bytes()),
            [{"op": "replace_source", "source": source}],
        )
        result = api.execute(
            self.project,
            {},
            "kz_spawn_check",
            {"path": "map.vmf", "minimum_ct_spawns": 5},
        )
        rules = {f["rule"] for f in result["findings"]}
        self.assertIn("spawn.support", rules)
        self.assertIn("spawn.capacity", rules)
        self.assertFalse(result["route_verified"])

    def test_route_larger_than_old_limit_retains_every_segment(self):
        root = vmf.parse(self.project.source("map.vmf")["source"])
        solid = int(root.blocks("world")[0].blocks("solid")[0].get("id"))
        result = api.execute(
            self.project,
            {},
            "kz_check_bhop",
            {"path": "map.vmf", "route": [{"id": solid, "kind": "solid"}] * 103},
        )
        self.assertEqual(len(result["route_measurements"]), 102)

    def test_independent_translations_match_sequential_and_parse_once(self):
        source = (
            self.project.source("map.vmf")["source"] + '\nunknown { "future" "kept" }\n'
        )
        root = vmf.parse(source)
        ops = [
            {
                "op": "translate",
                "kind": "solid",
                "id": int(s.get("id")),
                "delta": [1, 2, 3],
            }
            for s in root.blocks("world")[0].blocks("solid")
        ]
        expected = source
        results = []
        for op in ops:
            expected, result = vmf.mutate(expected, op)
            results.append(result)
        with patch.object(vmf, "parse", wraps=vmf.parse) as parsing:
            actual, actual_results = vmf.mutate_many(source, ops)
        self.assertEqual((actual, actual_results), (expected, results))
        self.assertEqual(parsing.call_count, 1)
        # Repeated/overlapping selectors must retain sequential semantics.
        twice, _ = vmf.mutate_many(source, [ops[0], ops[0]])
        expected, _ = vmf.mutate(source, ops[0])
        expected, _ = vmf.mutate(expected, ops[0])
        self.assertEqual(twice, expected)

    def assets(self):
        game = self.root / "game"
        (game / "materials/custom").mkdir(parents=True)
        (game / "materials/skybox").mkdir()
        (game / "gameinfo.txt").write_text(
            'GameInfo { FileSystem { SearchPaths { Game "|gameinfo_path|." } } }'
        )
        (game / "materials/custom/floor.vmt").write_text(
            'LightmappedGeneric { "$basetexture" "custom/floor" "$detail" "custom/detail" }'
        )
        (game / "materials/custom/floor.vtf").write_bytes(b"texture fixture")
        (game / "materials/custom/detail.vtf").write_bytes(b"detail fixture")
        for suffix in ("bk", "dn", "ft", "lf", "rt", "up"):
            (game / f"materials/skybox/customsky{suffix}.vmt").write_text(
                'UnlitGeneric { "$basetexture" "custom/floor" }'
            )
        return game

    def test_compiler_packs_transitive_material_sky_and_nav_then_packages_verified_pair(
        self,
    ):
        game = self.assets()
        tool = self.root / "vbsp.exe"
        tool.touch()

        class Process:
            def __init__(self, args, **kwargs):
                material_bsp(Path(args[-1]).with_suffix(".bsp"))

            def wait(self, **kwargs):
                return 0

        with patch.object(backend.subprocess, "Popen", Process):
            result = backend.compile_map(
                self.project,
                {"game_dir": str(game), "vbsp": str(tool)},
                "map.vmf",
                self.project.inspect("map.vmf")["revision"],
                mode="bsp",
            )
        self.assertTrue(result["assets"]["complete"], result)
        self.assertFalse(result["verification"]["gameplay_verified"])
        raw = Path(result["bsp"]["path"]).read_bytes()
        offset, size = struct.unpack_from("<ii", raw, 8 + 40 * 16)
        with zipfile.ZipFile(io.BytesIO(raw[offset : offset + size])) as pak:
            self.assertEqual(pak.read("materials/custom/detail.vtf"), b"detail fixture")
            self.assertIn("materials/skybox/customskyup.vmt", pak.namelist())
        package = api.execute(
            self.project,
            {},
            "package_map",
            {"build_dir": result["build_dir"], "output": "demo.zip"},
        )
        with zipfile.ZipFile(self.root / "demo.zip") as archive:
            self.assertEqual(archive.read("maps/map.nav"), b"")
            self.assertEqual(
                digest(archive.read("maps/map.bsp")), result["bsp"]["revision"]
            )
        self.assertTrue(package["verified"])
        with self.assertRaisesRegex(ValueError, "new|exists"):
            api.execute(
                self.project,
                {},
                "package_map",
                {"build_dir": result["build_dir"], "output": "demo.zip"},
            )
        Path(result["nav"]["path"]).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "changed|hash|revision"):
            api.execute(
                self.project,
                {},
                "package_map",
                {"build_dir": result["build_dir"], "output": "stale.zip"},
            )

    def test_missing_texture_fails_before_modifying_bsp(self):
        from cli.hammerplusplus.delivery import pack_assets

        game = self.assets()
        bsp = self.root / "map.bsp"
        material_bsp(bsp)
        before = bsp.read_bytes()
        (game / "materials/custom/detail.vtf").unlink()
        with self.assertRaises(backend.BackendError) as failure:
            pack_assets(bsp, game)
        self.assertIn(
            "materials/custom/detail.vtf", failure.exception.details["unresolved"]
        )
        self.assertEqual(bsp.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
