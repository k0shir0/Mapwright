"""Owned Windows editor sessions on inactive desktops, with event-driven IPC.

The broker lives across CLI calls and owns the editor's kill-on-close job. It
never switches the input desktop. Requests/results are workspace artifacts;
Windows events wake the broker and the waiting client without idle polling.
"""

from __future__ import annotations

import json
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

from .backend import BackendError, require_game, require_tool
from .project import Project, atomic_write, decode, digest


def _win32():
    if os.name != "nt":
        raise BackendError("Native editor sessions require Windows")
    try:
        import win32api, win32con, win32event, win32gui, win32job
        import win32process, win32service
    except ImportError as exc:
        raise BackendError(
            'Install the desktop extra: pip install -e ".[desktop]"'
        ) from exc
    return (
        win32api,
        win32con,
        win32event,
        win32gui,
        win32job,
        win32process,
        win32service,
    )


def _write(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=True).encode())


def _idle_cpu(job, enabled):
    """Bound the owned editor while waiting; commands run at normal speed."""
    logical_cpus = os.cpu_count() or 1
    rate = max(1, round(500 / logical_cpus))  # Approximately 5% of one CPU.
    value = (wintypes.DWORD * 2)(5 if enabled else 0, rate if enabled else 10000)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    if not kernel.SetInformationJobObject(int(job), 15, value, ctypes.sizeof(value)):
        raise BackendError(
            f"Cannot apply owned editor idle CPU policy: {ctypes.WinError(ctypes.get_last_error())}"
        )
    if enabled:
        actual = (wintypes.DWORD * 2)()
        kernel.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        kernel.QueryInformationJobObject.restype = wintypes.BOOL
        if not kernel.QueryInformationJobObject(
            int(job), 15, actual, ctypes.sizeof(actual), None
        ) or tuple(actual) != tuple(value):
            raise BackendError("Owned editor idle CPU policy readback failed")
    return {
        "job_cpu_rate": rate,
        "logical_cpus": logical_cpus,
        "idle_percent_of_one_cpu": rate * logical_cpus / 100,
        "command_policy": "Normal speed during bounded requests; hard cap while waiting",
    }


def _directory(project, session_id):
    if not isinstance(session_id, str) or not re.fullmatch(r"[0-9a-f]{32}", session_id):
        raise BackendError("Invalid native session ID")
    return project.confined(f".hammer-agent/native-sessions/{session_id}")


def _identity(pid):
    api, _, _, _, _, process, _ = _win32()
    handle = api.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    try:
        # The module list is not initialized immediately after CreateProcess.
        # QueryFullProcessImageName also works before the target loader finishes.
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        query = kernel.QueryFullProcessImageNameW
        query.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        query.restype = wintypes.BOOL
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if not query(int(handle), 0, buffer, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        return {
            "pid": pid,
            "created": process.GetProcessTimes(handle)["CreationTime"].isoformat(),
            "executable": str(Path(buffer.value).resolve()),
        }
    finally:
        handle.Close()


def _verify_identity(identity):
    try:
        if _identity(identity["pid"]) != identity:
            raise BackendError(
                "Native session process identity changed; PID may have been reused"
            )
    except BackendError:
        raise
    except Exception as exc:
        raise BackendError(
            "Native session is no longer running; open a new editor session"
        ) from exc


def find_session(project, config, pid):
    """Resolve only recorded owned processes, never attach to an arbitrary PID."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise BackendError("pid must be a positive process ID")
    root = project.confined(".hammer-agent/native-sessions")
    for path in sorted(root.glob("*/session.json")) if root.exists() else []:
        state = json.loads(path.read_text("utf-8"))
        if state.get("editor", {}).get("pid") != pid or state.get("status") == "closed":
            continue
        if Path(
            state.get("configured_editor", state["editor"]["executable"])
        ) != require_tool(project, config, "hammer"):
            raise BackendError("Native session uses a different configured editor")
        _verify_identity(state["broker"])
        _verify_identity(state["editor"])
        return path.parent, state
    raise BackendError(
        "PID is not an owned hidden editor session; use editor-open first"
    )


def request(project, config, pid, command, arguments=None, timeout=30):
    """Send one bounded command to a broker on the editor's own desktop."""
    _, con, event, _, _, _, _ = _win32()
    if isinstance(timeout, bool) or not 1 <= timeout <= 120:
        raise BackendError("Native request timeout must be between 1 and 120 seconds")
    directory, state = find_session(project, config, pid)
    request_id = uuid.uuid4().hex
    name = f"Local\\Mapwright_{state['session_id']}_{request_id}"
    done = event.CreateEvent(None, False, False, name)
    wake = None
    try:
        wake = event.OpenEvent(con.EVENT_MODIFY_STATE, False, state["event"])
        _write(
            directory / f"request-{request_id}.json",
            {
                "command": command,
                "arguments": arguments or {},
                "secret": state["secret"],
                "deadline": time.time() + timeout,
                "completion": name,
            },
        )
        event.SetEvent(wake)
        if event.WaitForSingleObject(done, int(timeout * 1000)) != con.WAIT_OBJECT_0:
            raise BackendError(
                "Native editor request timed out; inspect the session before retrying",
                {
                    "session_id": state["session_id"],
                    "request_id": request_id,
                    "outcome": "unknown",
                    "artifacts": str(directory),
                },
            )
        result = json.loads(
            (directory / f"response-{request_id}.json").read_text("utf-8")
        )
        if not result["ok"]:
            raise BackendError(result["error"], result.get("details"))
        return result["data"]
    finally:
        done.Close()
        if wake is not None:
            wake.Close()


def open_editor(project, config, name, timeout=30):
    from . import timeline

    _win32()
    if isinstance(timeout, bool) or not 1 <= timeout <= 120:
        raise BackendError(
            "Native editor startup timeout must be between 1 and 120 seconds"
        )
    source, data, _, _ = project.read(name)
    configured_editor = require_tool(project, config, "hammer")
    require_game(project, config)
    session_id = uuid.uuid4().hex
    directory = _directory(project, session_id)
    directory.mkdir(parents=True)
    staged = directory / "document" / source.name
    timeline.track_file(project, staged)
    atomic_write(staged, data, exclusive=True)
    # Keep the native bin layout short and separate from session artifacts.
    runtime, runtime_info = _prepare_runtime(
        project.confined(".local/mw/" + session_id[:12]), configured_editor
    )
    _write(
        directory / "launch.json",
        {
            "config": {**config, "hammer": str(runtime)},
            "configured_editor": str(configured_editor),
            "runtime": runtime_info,
            "source": str(source.relative_to(project.root)),
            "source_revision": digest(data),
            "staged": str(staged.relative_to(project.root)),
            "client_session": project.session_id,
            "owner": (
                _identity(project.native_owner_pid)
                if getattr(project, "native_owner_pid", None)
                else None
            ),
        },
    )
    return _start_broker(project, directory, session_id, timeout)


def _prepare_runtime(directory, executable):
    """Share immutable binaries/assets, copy settings that Hammer can rewrite."""
    runtime = directory / "bin"
    info = {"fps_limit": 5, "hardlinked_files": 0, "copied_bytes": 0}
    immutable = {".dll", ".exe", ".vpk", ".mdl", ".vvd", ".vtx", ".vtf", ".vmt", ".res"}
    sources = []
    for folder, dirs, files in os.walk(executable.parent, followlinks=False):
        dirs[:] = [
            d
            for d in dirs
            if d.casefold()
            not in {
                ".git",
                ".venv",
                ".hammer-agent",
                ".local",
                "node_modules",
                "autosave",
            }
            and not (Path(folder) / d).is_symlink()
            and not directory.resolve().is_relative_to((Path(folder) / d).resolve())
        ]
        sources.extend(Path(folder) / name for name in files)
        if len(sources) > 10000:
            raise BackendError("Private editor runtime exceeds 10000 files")
    for source in sources:
        if source.is_symlink():
            raise BackendError("Private editor runtime cannot include symlink files")
        if not source.is_file() or source.suffix.lower() in {".mdmp", ".dmp", ".log"}:
            continue
        target = runtime / source.relative_to(executable.parent)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix.lower() in immutable:
            try:
                os.link(source, target)
                info["hardlinked_files"] += 1
                continue
            except OSError:
                pass  # Cross-volume installations need ordinary private copies.
        shutil.copy2(source, target)
        info["copied_bytes"] += source.stat().st_size
    settings = runtime / "hammerplusplus" / "hammerplusplus_settings.ini"
    if settings.is_file():
        text, encoding = decode(settings.read_bytes())
    else:
        text, encoding = "[General]\n", "utf-8"
    # These are private settings; never start updater/RPC prompts in an agent's
    # owned session or let a legacy file dialog wait for user intervention.
    for key, value in {
        "FPSLimit": 5,
        "DiscordRPC": 0,
        "StartupCheckForUpdates": 0,
        "FileDialogHack": 0,
    }.items():
        text, count = re.subn(
            r"(?im)^" + key + r"\s*=[^\r\n]*", f"{key}={value}", text, count=1
        )
        if not count:
            section = re.search(r"(?im)^\[General\][^\r\n]*", text)
            if section:
                text = (
                    text[: section.end()] + f"\n{key}={value}" + text[section.end() :]
                )
            else:
                text += f"\n[General]\n{key}={value}\n"
    atomic_write(settings, text.encode(encoding))
    return runtime / executable.name, info


def _start_broker(project, directory, session_id, timeout):
    api, con, event, _, _, _, _ = _win32()
    ready_name = f"Local\\Mapwright_{session_id}_{uuid.uuid4().hex}_ready"
    ready = event.CreateEvent(None, False, False, ready_name)
    launch = json.loads((directory / "launch.json").read_text("utf-8"))
    launch.update({"ready_event": ready_name, "timeout": timeout})
    _write(directory / "launch.json", launch)
    broker = None
    try:
        with (directory / "broker.log").open("wb") as log:
            broker = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "cli_anything.hammerplusplus.native_session",
                    "--broker",
                    str(project.root),
                    session_id,
                ],
                cwd=project.root,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                creationflags=con.CREATE_NO_WINDOW,
            )
        launcher = api.OpenProcess(con.SYNCHRONIZE, False, broker.pid)
        try:
            signaled = event.WaitForMultipleObjects(
                [ready, launcher], False, (timeout + 10) * 1000
            )
        finally:
            launcher.Close()
        if signaled != con.WAIT_OBJECT_0:
            raise BackendError(
                "Native editor broker exited or startup timed out",
                {
                    "artifacts": str(directory),
                    "broker_log_tail": (directory / "broker.log").read_text(
                        "utf-8", errors="replace"
                    )[-4000:],
                },
            )
        result = json.loads((directory / "session.json").read_text("utf-8"))
        if "error" in result:
            raise BackendError(result["error"], {"artifacts": str(directory)})
        return _public(result)
    except BaseException as failure:
        # The broker's job handle closes when its process exits, taking only its
        # owned editor tree with it. Preserve staging/logs for diagnosis.
        if broker is not None and broker.poll() is None:
            try:
                state = json.loads((directory / "session.json").read_text("utf-8"))
                if not state.get("cleanup_complete"):
                    _terminate_broker(state)
            except Exception as cleanup_error:
                if broker.poll() is None:
                    try:
                        broker.terminate()
                    except OSError:
                        if broker.poll() is None and isinstance(failure, BackendError):
                            failure.details["cleanup_error"] = str(cleanup_error)
            try:
                broker.wait(timeout=5)
            except subprocess.TimeoutExpired as cleanup_error:
                if isinstance(failure, BackendError):
                    failure.details["cleanup_error"] = str(cleanup_error)
        raise
    finally:
        ready.Close()


def _public(state):
    return {
        "session_id": state["session_id"],
        "pid": state["editor"]["pid"],
        "status": state["status"],
        "map": state["source"],
        "staged_map": state["staged"],
        "readiness": state.get("readiness", {}),
        "desktop": state["desktop"],
        "runtime": state.get("runtime", {}),
        "idle_cpu_policy": state.get("idle_cpu_policy", {}),
        "verification": "Owned private desktop. Map title readiness does not prove viewport rendering or gameplay.",
        "limitations": "Editor works on a staged copy; use save_editor to apply it with a revision check. Relative map instance paths may require workspace-specific resolution.",
    }


def _terminate_broker(state):
    api, con, event, _, _, native_process, _ = _win32()
    process = api.OpenProcess(
        con.PROCESS_QUERY_INFORMATION
        | con.PROCESS_VM_READ
        | con.PROCESS_TERMINATE
        | con.SYNCHRONIZE,
        False,
        state["broker"]["pid"],
    )
    try:
        if event.WaitForSingleObject(process, 0) == con.WAIT_OBJECT_0:
            return
        actual = _identity(state["broker"]["pid"])
        if actual != state["broker"]:
            raise BackendError(
                "Broker PID identity changed; refusing to terminate another process"
            )
        api.TerminateProcess(process, 1)
        if event.WaitForSingleObject(process, 5000) != con.WAIT_OBJECT_0:
            raise BackendError("Native broker did not stop within five seconds")
    finally:
        process.Close()


def close_editor(project, config, pid):
    from . import timeline

    directory, state = find_session(project, config, pid)
    saved = checkpoint(project, config, pid)
    timeline.track_file(project, state["staged"])
    try:
        result = request(project, config, pid, "close", timeout=10)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            final = json.loads((directory / "session.json").read_text("utf-8"))
            if final.get("status") == "closed":
                result["cleanup_complete"] = final.get("cleanup_complete", False)
                result["job_active_processes"] = final.get("job_active_processes")
                break
            time.sleep(0.05)
        else:
            raise BackendError(
                "Native broker did not finish cleanup within five seconds"
            )
    except BackendError:
        _terminate_broker(state)
        result = {"pid": pid, "status": "terminated", "session_id": state["session_id"]}
    result["staged_map"] = state["staged"]
    result["checkpoint"] = saved
    result["recovery"] = (
        "Saved staging is retained; unsaved GUI state is discarded when closing the owned editor tree."
    )
    return result


def checkpoint(project, config, pid):
    """Persist the owned document, returning uncertainty for modal/failed saves."""
    try:
        return request(project, config, pid, "checkpoint", timeout=15)
    except BackendError as exc:
        return {"checkpointed": False, "document_reversible": False, "error": str(exc)}


def action(project, config, pid, arguments):
    from . import timeline

    before = checkpoint(project, config, pid)
    _, state = find_session(project, config, pid)
    timeline.track_file(project, state["staged"])
    result = request(project, config, pid, "action", arguments)
    after = checkpoint(project, config, pid)
    return {
        **result,
        "checkpointed": before.get("checkpointed", False)
        and after.get("checkpointed", False),
        "document_reversible": before.get("checkpointed", False)
        and after.get("checkpointed", False),
        "before_checkpoint": before,
        "after_checkpoint": after,
    }


def quiesce(project, config, paths):
    from . import timeline

    selected = {project.confined(p) for p in paths}
    specs = []
    root = project.confined(".hammer-agent/native-sessions")
    for metadata in sorted(root.glob("*/session.json")) if root.exists() else []:
        state = json.loads(metadata.read_text("utf-8"))
        if (
            state.get("status") == "closed"
            or project.confined(state["staged"]) not in selected
        ):
            continue
        find_session(project, config, state["editor"]["pid"])
        checkpoint(project, config, state["editor"]["pid"])
        timeline.track_file(project, state["staged"])
        close_editor(project, config, state["editor"]["pid"])
        specs.append({"session_id": state["session_id"]})
    return specs


def reload(project, config, specs):
    sessions = []
    for spec in specs:
        directory = _directory(project, spec["session_id"])
        launch = json.loads((directory / "launch.json").read_text("utf-8"))
        if not project.confined(launch["staged"]).exists():
            sessions.append(
                {
                    "session_id": spec["session_id"],
                    "status": "closed",
                    "reason": "Staged document absent at the restored action",
                }
            )
            continue
        sessions.append(_start_broker(project, directory, spec["session_id"], 30))
    return sessions


def close_sessions(project, config):
    """MCP shutdown closes only brokers created by this Project instance."""
    closed = []
    root = project.confined(".hammer-agent/native-sessions")
    for metadata in sorted(root.glob("*/session.json")) if root.exists() else []:
        state = json.loads(metadata.read_text("utf-8"))
        if (
            state.get("client_session") == project.session_id
            and state.get("status") != "closed"
        ):
            closed.append(close_editor(project, config, state["editor"]["pid"]))
    return closed


def save_editor(project, config, pid, expected_revision):
    from . import timeline

    _, state = find_session(project, config, pid)
    # Check before dispatch and again in the ordinary atomic map transaction.
    if digest(project.read(state["source"])[1]) != expected_revision:
        raise BackendError(
            "Revision conflict; inspect the source map before saving editor work"
        )
    timeline.track_file(project, state["staged"])
    result = request(project, config, pid, "save")
    staged = project.confined(state["staged"])
    if staged.stat().st_size > 64 * 1024 * 1024:
        raise BackendError("Staged VMF exceeds the 64 MiB editing limit")
    data = staged.read_bytes()
    if digest(data) != result["staged_revision"]:
        raise BackendError(
            "Staged map changed during readback; inspect before retrying"
        )
    timeline.track_file(project, state["source"])
    transaction = project.apply(
        state["source"],
        expected_revision,
        [{"op": "replace_source", "source": decode(data)[0]}],
    )
    return {
        **transaction,
        "session_id": state["session_id"],
        "pid": pid,
        "staged_map": state["staged"],
    }


def _titles(pid):
    """Only the broker calls this; its thread is already on the private desktop."""
    _, _, _, gui, _, process, _ = _win32()
    from .desktop import owned_windows

    rows = []

    def visit(hwnd, _):
        if process.GetWindowThreadProcessId(hwnd)[1] == pid:
            rows.append(
                {
                    "hwnd": hwnd,
                    "title": gui.GetWindowText(hwnd),
                    "class": gui.GetClassName(hwnd),
                    "visible": bool(gui.IsWindowVisible(hwnd)),
                    "enabled": bool(gui.IsWindowEnabled(hwnd)),
                }
            )
        return True

    for handle in owned_windows(pid):
        visit(handle, None)
    for row in list(rows):
        gui.EnumChildWindows(row["hwnd"], visit, None)
    return rows


def readiness(rows, basename):
    """Pure state classification, tested without touching a real desktop."""
    pattern = re.compile(
        r"(?<![\w.-])" + re.escape(basename) + r"(?![\w.-])", re.IGNORECASE
    )
    matching = [r for r in rows if pattern.search(r["title"]) and r["visible"]]
    main = [r for r in rows if r["class"] == "HammmerPlusPlus" and r["visible"]]
    blocked = bool(main and not main[0]["enabled"])
    return {
        "map_title_matches": [r["title"] for r in matching],
        "ready": bool(matching and main and not blocked),
        "dialogs": [
            r for r in rows if r["class"] == "#32770" and r["visible"] and r["enabled"]
        ],
        "status": "blocked" if blocked else "ready" if matching and main else "loading",
    }


def _decline_recovery(pid, rows):
    _, _, _, gui, _, _, _ = _win32()
    for row in rows:
        if row["class"] != "#32770" or not row["visible"] or row["title"] != "Hammer++":
            continue
        children = []
        gui.EnumChildWindows(row["hwnd"], lambda h, _: children.append(h), None)
        if not any(
            "Hammer++ did not shut down correctly the last time it was used."
            in gui.GetWindowText(h)
            for h in children
        ):
            continue
        no = next(
            (
                h
                for h in children
                if gui.GetClassName(h) == "Button" and gui.GetDlgCtrlID(h) == 7
            ),
            None,
        )
        if no:
            gui.PostMessage(no, 0xF5, 0, 0)
            return True
    return False


def _save_staged(project, config, state, deadline):
    from . import desktop as native

    pid = state["editor"]["pid"]
    staged = project.confined(state["staged"])
    current = readiness(_titles(pid), staged.name)
    if not current["ready"]:
        raise BackendError(
            "Requested staged map is not ready or a modal dialog blocks saving",
            {"readiness": current},
        )
    if any("*" in title for title in current["map_title_matches"]):
        native._editor_action(project, config, pid, action="menu", menu="File->Save")
    previous = None
    while time.time() < deadline:
        current = readiness(_titles(pid), staged.name)
        saved = staged.read_bytes()
        if (
            current["ready"]
            and not any("*" in t for t in current["map_title_matches"])
            and saved == previous
        ):
            return {
                "staged_revision": digest(saved),
                "staged_map": state["staged"],
                "checkpointed": True,
                "document_reversible": True,
            }
        previous = saved
        time.sleep(0.25)
    raise BackendError(
        "Editor save was not confirmed; staging retained without changing the source map"
    )


def _stop_editor(editor, job, pid):
    _, con, event, gui, jobapi, _, _ = _win32()
    for row in _titles(pid):
        if row["class"] == "HammmerPlusPlus" and row["visible"]:
            gui.PostMessage(row["hwnd"], 0x10, 0, 0)
    graceful = event.WaitForSingleObject(editor, 3000) == con.WAIT_OBJECT_0
    jobapi.TerminateJobObject(job, 0)
    if event.WaitForSingleObject(editor, 5000) != con.WAIT_OBJECT_0:
        raise BackendError("Owned editor did not stop within five seconds")
    return graceful


def _broker(project, session_id):
    api, con, event, gui, jobapi, process, service = _win32()
    directory = _directory(project, session_id)
    launch = json.loads((directory / "launch.json").read_text("utf-8"))
    ready_event = event.OpenEvent(con.EVENT_MODIFY_STATE, False, launch["ready_event"])
    desktop = job = editor = wake = owner_handle = None
    original_desktop = service.GetThreadDesktop(api.GetCurrentThreadId())
    state = {
        "session_id": session_id,
        "status": "starting",
        "broker": _identity(os.getpid()),
    }
    _write(directory / "session.json", state)
    try:
        if launch.get("owner"):
            _verify_identity(launch["owner"])
            owner_handle = api.OpenProcess(
                con.SYNCHRONIZE, False, launch["owner"]["pid"]
            )
            _verify_identity(launch["owner"])
            state["owner"] = launch["owner"]
        desktop_name = "Mapwright_" + session_id
        desktop = service.CreateDesktop(desktop_name, 0, con.GENERIC_ALL, None)
        desktop.SetThreadDesktop()
        job = jobapi.CreateJobObject(None, "Local\\Mapwright_" + session_id + "_Job")
        limits = jobapi.QueryInformationJobObject(
            job, jobapi.JobObjectExtendedLimitInformation
        )
        limits["BasicLimitInformation"][
            "LimitFlags"
        ] = jobapi.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        jobapi.SetInformationJobObject(
            job, jobapi.JobObjectExtendedLimitInformation, limits
        )
        config = launch["config"]
        exe = require_tool(project, config, "hammer")
        si = process.STARTUPINFO()
        si.lpDesktop = "WinSta0\\" + desktop_name
        si.dwFlags = con.STARTF_USESHOWWINDOW | con.STARTF_FORCEOFFFEEDBACK
        si.wShowWindow = con.SW_SHOWNORMAL
        argv = [
            str(exe),
            "-game",
            str(require_game(project, config)),
            str(project.confined(launch["staged"])),
        ]
        editor, thread, pid, _ = process.CreateProcess(
            str(exe),
            subprocess.list2cmdline(argv),
            None,
            None,
            False,
            con.CREATE_SUSPENDED,
            None,
            str(exe.parent),
            si,
        )
        try:
            jobapi.AssignProcessToJobObject(job, editor)
            process.ResumeThread(thread)
        except BaseException:
            api.TerminateProcess(editor, 1)
            raise
        finally:
            thread.Close()
        state.update(
            {
                "editor": _identity(pid),
                "desktop": desktop_name,
                "secret": uuid.uuid4().hex,
                "source": launch["source"],
                "staged": launch["staged"],
                "client_session": launch["client_session"],
                "configured_editor": launch.get("configured_editor", str(exe)),
                "runtime": launch.get("runtime", {}),
                "event": f"Local\\Mapwright_{session_id}_requests",
            }
        )
        wake = event.CreateEvent(None, False, False, state["event"])
        _write(directory / "session.json", state)
        deadline = time.monotonic() + launch["timeout"]
        previous = None
        state["readiness"] = {
            "status": "loading",
            "ready": False,
            "map_title_matches": [],
            "dialogs": [],
        }
        while time.monotonic() < deadline:
            if (
                owner_handle is not None
                and event.WaitForSingleObject(owner_handle, 0) == con.WAIT_OBJECT_0
            ):
                raise BackendError("MCP host exited during editor startup")
            if event.WaitForSingleObject(editor, 0) == con.WAIT_OBJECT_0:
                raise BackendError(
                    f"Hammer++ exited before loading the staged map (code {process.GetExitCodeProcess(editor)})"
                )
            try:
                rows = _titles(pid)
            except BackendError as exc:
                state.setdefault("startup_observations", []).append(str(exc))
                time.sleep(0.25)
                continue
            if _decline_recovery(pid, rows):
                state["declined_previous_document_recovery"] = True
                time.sleep(0.25)
                continue
            current = readiness(rows, Path(launch["staged"]).name)
            state["readiness"] = current
            if current["ready"] and current == previous:
                break
            previous = current
            time.sleep(0.25)
        state["status"] = state["readiness"]["status"]
        state["idle_cpu_policy"] = _idle_cpu(job, True)
        _write(directory / "session.json", state)
        event.SetEvent(ready_event)
        from . import desktop as native

        native._owned_pid = pid
        closing = False
        while not closing:
            # No heartbeat timer or repeated window inspection while idle.
            signals = [wake, editor] + (
                [owner_handle] if owner_handle is not None else []
            )
            signal = event.WaitForMultipleObjects(signals, False, event.INFINITE)
            if signal == con.WAIT_OBJECT_0 + 1:
                break
            if signal == con.WAIT_OBJECT_0 + 2:
                state["shutdown_reason"] = "mcp_host_exited"
                _idle_cpu(job, False)
                state["graceful"] = _stop_editor(editor, job, pid)
                break
            for pending in sorted(directory.glob("request-*.json")):
                request_id = pending.stem.removeprefix("request-")
                response = directory / f"response-{request_id}.json"
                if response.exists():
                    continue
                call = json.loads(pending.read_text("utf-8"))
                completion = None
                try:
                    if (
                        call["secret"] != state["secret"]
                        or call["deadline"] < time.time()
                    ):
                        raise BackendError(
                            "Native request expired or belongs to another session"
                        )
                    _verify_identity(state["editor"])
                    _idle_cpu(job, False)
                    command, arguments = call["command"], call["arguments"]
                    if command == "inspect":
                        data = native._inspect_editor(project, config, pid, **arguments)
                        data["readiness"] = readiness(
                            _titles(pid), Path(state["staged"]).name
                        )
                    elif command == "action":
                        data = native._editor_action(project, config, pid, **arguments)
                    elif command == "capture":
                        from .windows import _capture_editor

                        data = _capture_editor(project, config, pid, **arguments)
                    elif command in ("save", "checkpoint"):
                        data = _save_staged(
                            project,
                            config,
                            state,
                            min(call["deadline"], time.time() + 10),
                        )
                    elif command == "close":
                        closing = True
                        graceful = _stop_editor(editor, job, pid)
                        data = {
                            "pid": pid,
                            "session_id": session_id,
                            "status": "closed",
                            "graceful": graceful,
                        }
                    else:
                        raise BackendError("Unknown native session command")
                    result = {"ok": True, "data": data}
                except Exception as exc:
                    result = {
                        "ok": False,
                        "error": str(exc),
                        "details": getattr(exc, "details", {}),
                    }
                finally:
                    if not closing:
                        _idle_cpu(job, True)
                _write(response, result)
                try:
                    completion = event.OpenEvent(
                        con.EVENT_MODIFY_STATE, False, call["completion"]
                    )
                    event.SetEvent(completion)
                finally:
                    if completion is not None:
                        completion.Close()
    except Exception as exc:
        state["error"] = str(exc)
    finally:
        cleanup_errors = []

        def cleanup(label, operation):
            try:
                operation()
            except Exception as exc:
                cleanup_errors.append(f"{label}: {exc}")

        if job is not None:
            cleanup("terminate owned job", lambda: jobapi.TerminateJobObject(job, 0))
        if editor is not None:
            cleanup("wait editor", lambda: event.WaitForSingleObject(editor, 5000))
            cleanup("close editor handle", editor.Close)
        if job is not None:

            def settle_job():
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    state["job_active_processes"] = jobapi.QueryInformationJobObject(
                        job, jobapi.JobObjectBasicAccountingInformation
                    )["ActiveProcesses"]
                    if not state["job_active_processes"]:
                        break
                    time.sleep(0.05)

            cleanup("settle owned process tree", settle_job)
            cleanup("close job handle", job.Close)
        if wake is not None:
            cleanup("close request event", wake.Close)
        if owner_handle is not None:
            cleanup("close host handle", owner_handle.Close)
        if desktop is not None:
            cleanup("detach private desktop", original_desktop.SetThreadDesktop)
            cleanup("close private desktop", desktop.CloseDesktop)
        state["status"] = "closed"
        state["cleanup_complete"] = not cleanup_errors and not state.get(
            "job_active_processes", 0
        )
        if cleanup_errors:
            state["cleanup_errors"] = cleanup_errors
        try:
            _write(directory / "session.json", state)
        finally:
            event.SetEvent(ready_event)
            ready_event.Close()


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "--broker":
        raise SystemExit("Native session broker is launched by editor-open")
    _broker(Project(sys.argv[2]), sys.argv[3])
