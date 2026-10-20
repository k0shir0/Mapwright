"""Mocked boundary tests; native rendering is verified separately on Windows."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from cli.hammerplusplus import backend, desktop, native_session, windows
from cli.hammerplusplus.project import Project, digest

RUNS = Path(__file__).resolve().parents[1] / ".local/test-runs"
RUNS.mkdir(parents=True, exist_ok=True)


class NativeSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=RUNS)
        self.addCleanup(self.temp.cleanup)
        self.project = Project(self.temp.name)
        self.project.create("map.vmf", "csgo-room")

    def state(self):
        return {
            "source": "map.vmf",
            "staged": ".hammer-agent/native-sessions/" + "a" * 32 + "/document/map.vmf",
            "session_id": "a" * 32,
        }

    def test_readiness_requires_exact_document_title_and_enabled_main(self):
        main = {
            "class": "HammmerPlusPlus",
            "title": "Hammer++",
            "visible": True,
            "enabled": True,
        }
        self.assertFalse(native_session.readiness([main], "map.vmf")["ready"])
        main["title"] = (
            f"Hammer++ - [{Path(self.temp.name) / 'another-map.vmf'} - Textured Shaded]"
        )
        self.assertFalse(native_session.readiness([main], "map.vmf")["ready"])
        main["title"] = (
            f"Hammer++ - [{Path(self.temp.name) / 'map.vmf'} - Textured Shaded]"
        )
        self.assertTrue(native_session.readiness([main], "map.vmf")["ready"])
        main["enabled"] = False
        self.assertEqual(
            native_session.readiness([main], "map.vmf")["status"], "blocked"
        )

    def test_reused_process_id_is_rejected(self):
        original = {"pid": 123, "created": "first", "executable": "hammer.exe"}
        with patch.object(
            native_session, "_identity", return_value={**original, "created": "second"}
        ):
            with self.assertRaisesRegex(backend.BackendError, "identity changed"):
                native_session._verify_identity(original)

    def test_unknown_pid_never_attaches_to_desktop(self):
        with self.assertRaisesRegex(backend.BackendError, "not an owned hidden"):
            native_session.find_session(self.project, {}, 123)

    def test_session_directory_cannot_escape_workspace(self):
        for value in ("../other", "a" * 31, "A" * 32):
            with self.assertRaises(backend.BackendError):
                native_session._directory(self.project, value)

    def test_background_text_uses_only_owned_standard_control_message(self):
        gui, process = MagicMock(), MagicMock()
        gui.IsWindow.return_value = True
        gui.IsWindowEnabled.return_value = True
        gui.GetClassName.return_value = "Edit"
        process.GetWindowThreadProcessId.return_value = (8, 123)
        with (
            patch.dict("sys.modules", {"win32gui": gui, "win32process": process}),
            patch.object(desktop, "_assert_owned"),
            patch.object(desktop, "send_control") as message,
        ):
            desktop._editor_action(self.project, {}, 123, "text", hwnd=99, text="owned")
        message.assert_called_once_with(99, 0xC, 0, "owned")
        self.assertFalse(gui.SetForegroundWindow.called)
        self.assertFalse(gui.SetWindowPos.called)

    def test_runtime_copies_mutable_settings_without_changing_original(self):
        source = Path(self.temp.name) / "editor"
        (source / "hammerplusplus").mkdir(parents=True)
        executable = source / "hammerplusplus.exe"
        executable.write_bytes(b"immutable executable")
        original = source / "hammerplusplus/hammerplusplus_settings.ini"
        original_bytes = b"[General]\r\nFPSLimit=144\r\nStartupCheckForUpdates=1\r\nDiscordRPC=1\r\nFileDialogHack=1\r\n"
        original.write_bytes(original_bytes)
        runtime, info = native_session._prepare_runtime(
            Path(self.temp.name) / "session", executable
        )
        self.assertEqual(runtime.read_bytes(), executable.read_bytes())
        self.assertEqual(original.read_bytes(), original_bytes)
        private = (
            runtime.parent / "hammerplusplus/hammerplusplus_settings.ini"
        ).read_bytes()
        for key in (b"StartupCheckForUpdates", b"DiscordRPC", b"FileDialogHack"):
            self.assertIn(key + b"=0", private)
        self.assertIn(
            b"FPSLimit=5",
            (
                runtime.parent / "hammerplusplus/hammerplusplus_settings.ini"
            ).read_bytes(),
        )
        self.assertEqual(info["fps_limit"], 5)

    def test_foreign_window_and_global_input_do_not_dispatch(self):
        gui, process = MagicMock(), MagicMock()
        gui.IsWindow.return_value = True
        gui.IsWindowEnabled.return_value = True
        process.GetWindowThreadProcessId.return_value = (8, 999)
        with (
            patch.dict("sys.modules", {"win32gui": gui, "win32process": process}),
            patch.object(desktop, "_assert_owned"),
            patch.object(desktop, "send_control") as message,
        ):
            with self.assertRaisesRegex(backend.BackendError, "does not belong"):
                desktop._editor_action(
                    self.project, {}, 123, "text", hwnd=99, text="wrong"
                )
            process.GetWindowThreadProcessId.return_value = (8, 123)
            for action in ("keys", "click", "drag", "focus"):
                with self.assertRaisesRegex(
                    backend.BackendError, "global keyboard/mouse"
                ):
                    desktop._editor_action(self.project, {}, 123, action, hwnd=99)
        message.assert_not_called()

    def test_screen_capture_never_enters_native_dispatch(self):
        with patch.object(native_session, "request") as dispatch:
            with self.assertRaisesRegex(backend.BackendError, "user's desktop"):
                windows.capture_editor(
                    self.project, {}, 123, "capture.png", method="screen"
                )
        dispatch.assert_not_called()

    def test_staged_save_commits_with_normal_revision_history(self):
        state = self.state()
        staged = self.project.confined(state["staged"])
        staged.parent.mkdir(parents=True)
        before = self.project.read("map.vmf")[1]
        after = (
            before.replace(b"worldspawn", b"worldspawn", 1)
            + b"\n// native saved change\n"
        )
        staged.write_bytes(after)
        with (
            patch.object(
                native_session, "find_session", return_value=(staged.parent, state)
            ),
            patch.object(
                native_session,
                "request",
                return_value={"staged_revision": digest(after)},
            ),
        ):
            result = native_session.save_editor(self.project, {}, 123, digest(before))
        self.assertEqual(self.project.read("map.vmf")[1], after)
        self.project.restore("map.vmf", result["revision"], "undo")
        self.assertEqual(self.project.read("map.vmf")[1], before)

    def test_staged_save_conflict_never_sends_editor_save(self):
        state = self.state()
        with (
            patch.object(
                native_session,
                "find_session",
                return_value=(Path(self.temp.name), state),
            ),
            patch.object(native_session, "request") as dispatch,
        ):
            with self.assertRaisesRegex(backend.BackendError, "Revision conflict"):
                native_session.save_editor(self.project, {}, 123, "0" * 64)
        dispatch.assert_not_called()

    def test_modal_checkpoint_does_not_claim_document_rollback(self):
        with patch.object(
            native_session, "request", side_effect=backend.BackendError("modal dialog")
        ):
            result = native_session.checkpoint(self.project, {}, 123)
        self.assertFalse(result["checkpointed"])
        self.assertFalse(result["document_reversible"])


class ReaEntrypointTests(unittest.TestCase):
    def test_installed_package_wrapper_and_json_flag(self):
        with tempfile.TemporaryDirectory() as root:
            project = Project(root)
            configured = Path(root) / "rea" / "dist" / "cli.js"
            configured.parent.mkdir(parents=True)
            configured.write_text("export {}", encoding="utf-8")
            wrapper = configured.parent.parent / "scripts" / "rea.mjs"
            wrapper.parent.mkdir()
            wrapper.write_text("", encoding="utf-8")
            hammer = Path(root) / "hammer.exe"
            hammer.write_bytes(b"fixture")
            config = {"rea": str(configured), "hammer": str(hammer)}
            success = subprocess.CompletedProcess(
                [], 0, json.dumps({"evidence_id": "fixture"}), ""
            )
            with (
                patch.object(backend.shutil, "which", return_value="node"),
                patch.object(backend.subprocess, "run", return_value=success) as run,
            ):
                self.assertEqual(
                    backend.rea_probe(project, config, "hammer")["evidence_id"],
                    "fixture",
                )
            self.assertEqual(
                run.call_args.args[0],
                [
                    "node",
                    str(wrapper.resolve()),
                    "inspect-pe-resources",
                    str(hammer.resolve()),
                    "--format",
                    "json",
                ],
            )
            self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)
            with (
                patch.object(backend.shutil, "which", return_value="node"),
                patch.object(
                    backend.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess([], 0, "", ""),
                ),
            ):
                with self.assertRaisesRegex(backend.BackendError, "no valid JSON"):
                    backend.rea_probe(project, config, "hammer")


if __name__ == "__main__":
    unittest.main()
