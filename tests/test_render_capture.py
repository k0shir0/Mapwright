"""Renderer profile and worker boundaries; real pixels use the native E2E lane."""

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from cli.hammerplusplus import render_capture
from cli.hammerplusplus.backend import BackendError
from cli.hammerplusplus.project import Project


class RenderCaptureTests(unittest.TestCase):
    def test_unrecognized_profile_never_arms_native_calls_and_detaches(self):
        frida = MagicMock()
        session = frida.attach.return_value
        session.create_script.return_value.exports_sync.describe.return_value = {
            "architecture": "ia32",
            "modules": [],
        }
        with patch.dict("sys.modules", {"frida": frida}):
            with self.assertRaisesRegex(BackendError, "unrecognized"):
                render_capture.read_frame(123, lambda: self.fail("must not redraw"))
        session.create_script.return_value.exports_sync.arm.assert_not_called()
        session.detach.assert_called_once()

    def test_wrong_architecture_refuses_before_file_reads(self):
        with self.assertRaisesRegex(BackendError, "x86"):
            render_capture.validate_profile({"architecture": "x64", "modules": []})

    def test_profile_checks_actual_module_bytes(self):
        with tempfile.TemporaryDirectory() as root:
            module = Path(root) / "engine.dll"
            module.write_bytes(b"observed binary bytes")
            revision = hashlib.sha256(module.read_bytes()).hexdigest()
            description = {
                "architecture": "ia32",
                "modules": [{"name": "ENGINE.DLL", "path": str(module)}],
            }
            with patch.object(render_capture, "PROFILE", {"engine.dll": revision}):
                self.assertEqual(
                    render_capture.validate_profile(description),
                    {"engine.dll": str(module)},
                )
                module.write_bytes(b"other ABI")
                with self.assertRaisesRegex(BackendError, "unrecognized"):
                    render_capture.validate_profile(description)

    def test_existing_output_refuses_before_worker_creation(self):
        with tempfile.TemporaryDirectory() as root:
            project = Project(root)
            output = Path(root) / "capture.png"
            output.write_bytes(b"user-owned existing image")
            with (
                patch("cli.hammerplusplus.desktop._assert_owned"),
                patch.object(render_capture.subprocess, "run") as run,
            ):
                with self.assertRaisesRegex(BackendError, "new PNG"):
                    render_capture.capture(project, {}, 123, "capture.png", "a" * 32)
            run.assert_not_called()
            self.assertEqual(output.read_bytes(), b"user-owned existing image")


if __name__ == "__main__":
    unittest.main()
