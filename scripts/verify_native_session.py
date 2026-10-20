"""Opt-in real Windows hidden-session verification; never switches desktops."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import threading
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cli.hammerplusplus import backend, desktop, native_session, windows
from cli.hammerplusplus.project import Project


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        action="store_true",
        help="Run actual configured Hammer++ on a private desktop",
    )
    parser.add_argument(
        "--workspace",
        default=".",
        help="Existing workspace containing native configuration",
    )
    parser.add_argument(
        "--config",
        default="mapwright.local.json",
        help="Native tool configuration relative to the workspace",
    )
    parser.add_argument(
        "--map", help="Existing workspace VMF, otherwise create an owned room fixture"
    )
    parser.add_argument(
        "--idle-seconds",
        type=float,
        default=3,
        help="Seconds to measure live idle CPU and memory (2 through 5)",
    )
    args = parser.parse_args()
    if not args.run:
        parser.error(
            "Pass --run to start the configured native editor; no native GUI runs in unit tests"
        )
    if not 2 <= args.idle_seconds <= 5:
        parser.error("--idle-seconds must be between 2 and 5")
    api, con, event, gui, _, process, service = native_session._win32()
    project = Project(args.workspace)
    config = backend.load_config(project, args.config)
    prefix = ".local/native-session-verification/" + uuid.uuid4().hex
    folder = project.confined(prefix)
    folder.mkdir(parents=True)
    source = args.map or prefix + "/native-session-probe.vmf"
    if not args.map:
        project.create(source, "csgo-room")
    report = {
        "scope": "Actual Win32 session, native viewport readback, UI capture, guarded save, resource measurement and cleanup. Images require content inspection; this does not test gameplay."
    }

    def desktop_state():
        handle = service.OpenInputDesktop(0, False, con.DESKTOP_READOBJECTS)
        try:
            return {
                "input_desktop": service.GetUserObjectInformation(handle, 2),
                "foreground": gui.GetForegroundWindow(),
                "cursor": list(gui.GetCursorPos()),
            }
        finally:
            handle.CloseDesktop()

    stop = threading.Event()
    samples = []
    baseline = desktop_state()

    def sample_desktop():
        while not stop.wait(0.1):
            samples.append(desktop_state())

    observer = threading.Thread(target=sample_desktop, daemon=True)
    observer.start()
    opened = None
    try:
        started = time.monotonic()
        opened = backend.open_editor(project, config, source)
        report["launch_seconds"] = round(time.monotonic() - started, 3)
        report["session"] = opened
        pid = opened["pid"]
        report["inspection"] = desktop.inspect_editor(project, config, pid, 100)
        if not report["inspection"]["readiness"]["ready"]:
            raise RuntimeError(
                "Requested map is not ready; inspect owned dialogs in the report"
            )
        report["capture"] = windows.capture_editor(
            project, config, pid, prefix + "/viewport.png", method="viewport"
        )
        report["window_capture"] = windows.capture_editor(
            project, config, pid, prefix + "/window.png", method="window"
        )
        report["save"] = backend.save_editor(
            project, config, pid, project.inspect(source)["revision"]
        )
        _, state = native_session.find_session(project, config, pid)
        handles = {}
        try:
            for label, identity in (
                ("editor", state["editor"]),
                ("broker", state["broker"]),
            ):
                handles[label] = api.OpenProcess(
                    con.PROCESS_QUERY_INFORMATION | con.PROCESS_VM_READ,
                    False,
                    identity["pid"],
                )
            before = {
                label: process.GetProcessTimes(handle)
                for label, handle in handles.items()
            }
            started = time.monotonic()
            time.sleep(args.idle_seconds)
            interval = time.monotonic() - started
            report["idle_sample"] = {}
            for label, handle in handles.items():
                after = process.GetProcessTimes(handle)
                cpu_seconds = (
                    sum(
                        after[key] - before[label][key]
                        for key in ("UserTime", "KernelTime")
                    )
                    / 10_000_000
                )
                report["idle_sample"][label] = {
                    "wall_seconds": interval,
                    "cpu_seconds": cpu_seconds,
                    "cpu_percent_of_one_core": 100 * cpu_seconds / interval,
                    "memory": process.GetProcessMemoryInfo(handle),
                    "still_running": process.GetExitCodeProcess(handle)
                    == con.STILL_ACTIVE,
                }
        finally:
            for handle in handles.values():
                handle.Close()
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        if opened:
            try:
                report["close"] = backend.close_editor(project, config, opened["pid"])
            except Exception as exc:
                report["cleanup_error"] = str(exc)
        stop.set()
        observer.join(timeout=2)
        report["desktop_before"] = baseline
        report["desktop_after"] = desktop_state()
        report["desktop_samples"] = samples
        report["observed_input_desktop_unchanged"] = all(
            s["input_desktop"] == baseline["input_desktop"]
            for s in [*samples, report["desktop_after"]]
        )
        report["observed_foreground_unchanged"] = all(
            s["foreground"] == baseline["foreground"]
            for s in [*samples, report["desktop_after"]]
        )
        report["observed_cursor_unchanged"] = all(
            s["cursor"] == baseline["cursor"]
            for s in [*samples, report["desktop_after"]]
        )
        output = folder / "report.json"
        output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str(output),
                "status": (
                    "failed"
                    if "error" in report or "cleanup_error" in report
                    else "complete"
                ),
                "viewport_rendering_verified": False,
                "native_gpu_readback_verified": report.get("capture", {}).get("method")
                == "native-viewport",
            },
            indent=2,
        )
    )
    return 1 if "error" in report or "cleanup_error" in report else 0


if __name__ == "__main__":
    raise SystemExit(main())
