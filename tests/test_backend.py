from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cli.hammerplusplus import backend
from cli.hammerplusplus.project import Project

RUNS = Path(__file__).resolve().parents[1] / ".local/test-runs"
RUNS.mkdir(parents=True, exist_ok=True)


def synthetic_bsp():
    header = bytearray(b"VBSP" + struct.pack("<i", 21) + bytes(1028))
    for index, offset in zip((0, 1, 5), (1036, 1037, 1038)):
        struct.pack_into("<iii4s", header, 8 + index * 16, offset, 1, 0, b"\0" * 4)
    return bytes(header) + b"abc"


class BackendTests(unittest.TestCase):
    """Mocked compiler boundary checks, not real compiler verification."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=RUNS)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = Project(self.root)
        self.revision = self.project.create("map.vmf", "csgo-room")["revision"]
        game = self.root / "csgo"
        game.mkdir()
        (game / "gameinfo.txt").write_text("gameinfo {}")
        self.config = {"game_dir": str(game)}
        # These compiler-boundary fixtures deliberately contain no real BSP data.
        self.packing = patch(
            "cli.hammerplusplus.delivery.pack_assets", return_value={"complete": True}
        )
        self.packing.start()
        self.addCleanup(self.packing.stop)
        for tool in ("vbsp", "vvis", "vrad"):
            path = self.root / (tool + ".exe")
            path.write_bytes(b"not a real executable")
            self.config[tool] = str(path)

    def test_mapwright_config_prefers_new_name_and_reads_legacy_name(self):
        legacy = self.root / "hammer-agent.local.json"
        legacy.write_text('{"game_dir":"legacy"}')
        self.assertEqual(backend.load_config(self.project), {"game_dir": "legacy"})

        current = self.root / "mapwright.local.json"
        current.write_text('{"game_dir":"mapwright"}')
        self.assertEqual(backend.load_config(self.project), {"game_dir": "mapwright"})

    def test_doctor_diagnoses_missing_and_unsupported_renderer_profiles(self):
        from cli.hammerplusplus import render_capture

        missing = backend.doctor(self.project, self.config)
        self.assertFalse(missing["viewport_profile_ready"])
        self.config["hammer"] = str(self.root / "hammer.exe")
        Path(self.config["hammer"]).write_bytes(b"fixture")
        for name in render_capture.PROFILE:
            (self.root / name).write_bytes(b"unknown renderer")
        report = backend.doctor(self.project, self.config)
        self.assertFalse(report["viewport_profile_ready"])
        self.assertTrue(
            all(
                row["sha256"] and not row["supported"]
                for row in report["viewport_profile"].values()
            )
        )

    def test_zero_exit_without_fresh_bsp_fails(self):
        class Process:
            def __init__(self, *args, **kwargs):
                pass

            def wait(self, **kwargs):
                return 0

        with (
            patch.object(backend.subprocess, "Popen", Process),
            self.assertRaisesRegex(backend.BackendError, "did not produce"),
        ):
            backend.compile_map(
                self.project, self.config, "map.vmf", self.revision, mode="bsp"
            )

    def test_leak_stops_later_stages_even_with_zero_exit(self):
        calls = []

        class Process:
            def __init__(self, args, **kwargs):
                calls.append(args)
                kwargs["stdout"].write(b"**** leaked ****\n")
                Path(args[-1]).with_suffix(".bsp").write_bytes(synthetic_bsp())

            def wait(self, **kwargs):
                return 0

        with (
            patch.object(backend.subprocess, "Popen", Process),
            self.assertRaisesRegex(backend.BackendError, "leak"),
        ):
            backend.compile_map(self.project, self.config, "map.vmf", self.revision)
        self.assertEqual(len(calls), 1)

    def test_large_logs_still_detect_late_errors_and_report_actual_tail(self):
        for marker in (b"ERROR: late failure", b"**** leaked ****"):
            with self.subTest(marker=marker):

                class Process:
                    def __init__(self, args, **kwargs):
                        kwargs["stdout"].write(
                            b"x" * (1024 * 1024) + b"\n" + marker + b"\n"
                        )
                        Path(args[-1]).with_suffix(".bsp").write_bytes(synthetic_bsp())

                    def wait(self, **kwargs):
                        return 0

                with patch.object(backend.subprocess, "Popen", Process):
                    with self.assertRaises(backend.BackendError) as failure:
                        backend.compile_map(
                            self.project, self.config, "map.vmf", self.revision
                        )
                self.assertIn(marker.decode(), failure.exception.details["output_tail"])
                self.assertTrue(failure.exception.details["stages"][0]["log_truncated"])

    def test_stage_arguments_and_receipt_use_fresh_build(self):
        calls = []

        class Process:
            def __init__(self, args, **kwargs):
                calls.append(args)
                if Path(args[0]).stem == "vbsp":
                    Path(args[-1]).with_suffix(".bsp").write_bytes(synthetic_bsp())

            def wait(self, **kwargs):
                return 0

        with patch.object(backend.subprocess, "Popen", Process):
            result = backend.compile_map(
                self.project, self.config, "map.vmf", self.revision
            )
        self.assertEqual(len(calls), 3)
        self.assertIn("-fast", calls[1])
        self.assertIn("-hdr", calls[2])
        self.assertEqual(result["bsp"]["version"], 21)
        nav = Path(result["nav"]["path"])
        self.assertEqual(nav, Path(result["bsp"]["path"]).with_suffix(".nav"))
        self.assertEqual(nav.read_bytes(), b"")
        self.assertTrue(result["nav"]["empty"])
        self.assertEqual(result["nav"]["bytes"], 0)
        self.assertTrue((Path(result["build_dir"]) / "receipt.json").is_file())
        self.assertNotEqual(Path(result["build_dir"]), self.root)

    def test_compile_preserves_existing_nav(self):
        for produced_by_compiler in (False, True):
            with self.subTest(produced_by_compiler=produced_by_compiler):
                (self.root / "map.nav").write_bytes(b"source navigation")

                class Process:
                    def __init__(self, args, **kwargs):
                        staged = Path(args[-1])
                        staged.with_suffix(".bsp").write_bytes(synthetic_bsp())
                        if produced_by_compiler:
                            staged.with_suffix(".nav").write_bytes(
                                b"compiler navigation"
                            )

                    def wait(self, **kwargs):
                        return 0

                with patch.object(backend.subprocess, "Popen", Process):
                    result = backend.compile_map(
                        self.project, self.config, "map.vmf", self.revision, mode="bsp"
                    )
                expected = (
                    b"compiler navigation"
                    if produced_by_compiler
                    else b"source navigation"
                )
                self.assertEqual(Path(result["nav"]["path"]).read_bytes(), expected)
                self.assertEqual(result["nav"]["bytes"], len(expected))
                self.assertFalse(result["nav"]["empty"])
                self.assertEqual(
                    (self.root / "map.nav").read_bytes(), b"source navigation"
                )

    def test_timeout_kills_and_reaps_compiler(self):
        events = []

        class Process:
            def __init__(self, *args, **kwargs):
                pass

            def wait(self, timeout=None):
                if timeout is not None:
                    raise subprocess.TimeoutExpired("fake", timeout)
                events.append("reaped")
                return -1

            def kill(self):
                events.append("killed")

        with (
            patch.object(backend.subprocess, "Popen", Process),
            self.assertRaisesRegex(backend.BackendError, "timeout"),
        ):
            backend.compile_map(
                self.project, self.config, "map.vmf", self.revision, timeout=1
            )
        self.assertEqual(events, ["killed", "reaped"])


if __name__ == "__main__":
    unittest.main()
