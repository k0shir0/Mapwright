"""Native editor access for operations that need Hammer++ itself."""

from __future__ import annotations

import os
from pathlib import Path

from .backend import BackendError, require_tool

_owned_pid = None  # Set only by the broker after assigning its editor to the job.


def inspect_editor(project, config, pid: int, limit: int = 200):
    from .native_session import request

    return request(project, config, pid, "inspect", {"limit": limit})


def editor_action(project, config, pid: int, action: str, **arguments):
    from .native_session import action as dispatch

    return dispatch(project, config, pid, {"action": action, **arguments})


def _assert_owned(project, config, pid):
    if pid != _owned_pid:
        raise BackendError("Native GUI access requires an owned hidden editor broker")
    if os.name != "nt":
        raise BackendError("Native Hammer++ interaction requires Windows")
    from .windows import set_dpi_awareness

    set_dpi_awareness()
    try:
        import win32api, win32con, win32process
    except ImportError as exc:
        raise BackendError(
            'Install the desktop extra: pip install -e ".[desktop]"'
        ) from exc
    exe = require_tool(project, config, "hammer")
    process = win32api.OpenProcess(
        win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ, False, pid
    )
    try:
        actual = Path(win32process.GetModuleFileNameEx(process, 0)).resolve()
    finally:
        win32api.CloseHandle(process)
    if actual != exe:
        raise BackendError("PID does not belong to the configured Hammer++ executable")


def owned_windows(pid):
    import ctypes
    from ctypes import wintypes
    import win32api, win32gui, win32process, win32service

    handles = []
    user = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumDesktopWindows.argtypes = [wintypes.HANDLE, callback_type, wintypes.LPARAM]
    user.EnumDesktopWindows.restype = wintypes.BOOL

    @callback_type
    def visit(hwnd, _):
        if win32process.GetWindowThreadProcessId(hwnd)[1] == pid:
            handles.append(hwnd)
        return True

    desktop = win32service.GetThreadDesktop(win32api.GetCurrentThreadId())
    ctypes.set_last_error(0)
    if not user.EnumDesktopWindows(int(desktop), visit, 0) and ctypes.get_last_error():
        raise BackendError("Could not enumerate the owned editor desktop")
    return handles


def send_control(handle, message, wparam=0, lparam=0, timeout=2000):
    """Bounded standard-control message, without focus or input synthesis."""
    import ctypes
    from ctypes import wintypes

    user = ctypes.WinDLL("user32", use_last_error=True)
    user.SendMessageTimeoutW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    user.SendMessageTimeoutW.restype = wintypes.LPARAM
    buffer = ctypes.create_unicode_buffer(lparam) if isinstance(lparam, str) else None
    if buffer is not None:
        lparam = ctypes.cast(buffer, ctypes.c_void_p).value
    result = ctypes.c_size_t()
    if not user.SendMessageTimeoutW(
        handle, message, wparam, lparam, 2, timeout, ctypes.byref(result)
    ):
        raise BackendError(
            "Native control message timed out; dispatch outcome is unknown, inspect the owned dialog",
            {"outcome": "unknown"},
        )
    return result.value


def menu_items(handle, depth=0):
    """Read native menus without pywinauto's unbounded inaccessible-menu retries."""
    import ctypes
    from ctypes import wintypes

    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetMenuItemCount.argtypes = [wintypes.HMENU]
    user.GetMenuStringW.argtypes = [
        wintypes.HMENU,
        wintypes.UINT,
        wintypes.LPWSTR,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user.GetMenuItemID.argtypes = [wintypes.HMENU, ctypes.c_int]
    user.GetMenuState.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
    user.GetSubMenu.argtypes = [wintypes.HMENU, ctypes.c_int]
    user.GetSubMenu.restype = wintypes.HMENU
    if not handle or depth > 8:
        return []
    result = []
    for index in range(min(500, max(0, user.GetMenuItemCount(handle)))):
        label = ctypes.create_unicode_buffer(2048)
        user.GetMenuStringW(handle, index, label, len(label), 0x400)
        state = user.GetMenuState(handle, index, 0x400)
        sub = user.GetSubMenu(handle, index)
        result.append(
            {
                "label": label.value,
                "id": user.GetMenuItemID(handle, index),
                "enabled": not bool(state & 3),
                "checked": bool(state & 8),
                "items": menu_items(sub, depth + 1),
            }
        )
    return result


def control_text(handle, class_name):
    import ctypes
    from ctypes import wintypes
    import win32gui

    if class_name not in ("Edit", "ComboBox", "Static", "Button"):
        return win32gui.GetWindowText(handle)
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.SendMessageTimeoutW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    user.SendMessageTimeoutW.restype = wintypes.LPARAM
    buffer = ctypes.create_unicode_buffer(32768)
    result = ctypes.c_size_t()
    if not user.SendMessageTimeoutW(
        handle,
        0xD,
        len(buffer),
        ctypes.cast(buffer, ctypes.c_void_p).value,
        2,
        100,
        ctypes.byref(result),
    ):
        return "[control did not answer within 100 ms]"
    return buffer.value


def _inspect_editor(project, config, pid: int, limit: int = 200):
    _assert_owned(project, config, pid)
    import win32gui, win32process

    handles = owned_windows(pid)
    windows = []
    for handle in handles:
        if not win32gui.IsWindowVisible(handle):
            continue
        children = []
        win32gui.EnumChildWindows(handle, lambda h, _: children.append(h), None)
        controls = [
            {
                "hwnd": h,
                "id": win32gui.GetDlgCtrlID(h),
                "class": win32gui.GetClassName(h),
                "text": control_text(h, win32gui.GetClassName(h)),
                "visible": bool(win32gui.IsWindowVisible(h)),
                "enabled": bool(win32gui.IsWindowEnabled(h)),
                "rect": list(win32gui.GetWindowRect(h)),
            }
            for h in children[:limit]
        ]
        menu = win32gui.GetMenu(handle)
        windows.append(
            {
                "hwnd": handle,
                "title": win32gui.GetWindowText(handle),
                "class": win32gui.GetClassName(handle),
                "enabled": bool(win32gui.IsWindowEnabled(handle)),
                "controls": controls,
                "menus": menu_items(menu) if menu else [],
            }
        )
    return {
        "pid": pid,
        "windows": windows,
        "control_limit": limit,
        "instructions": "Use actual menu labels or owned window/control handles from this state. Capture and inspect the editor after actions; commands can change unsaved editor state.",
    }


def _editor_action(
    project,
    config,
    pid: int,
    action: str,
    hwnd: int | None = None,
    menu: str = "",
    text: str = "",
    keys: str = "",
    x: int = 0,
    y: int = 0,
    end_x: int = 0,
    end_y: int = 0,
    button: str = "left",
    steps: int = 1,
):
    _assert_owned(project, config, pid)
    import win32gui, win32process

    if hwnd is not None:
        if (
            not win32gui.IsWindow(hwnd)
            or win32process.GetWindowThreadProcessId(hwnd)[1] != pid
        ):
            raise BackendError(
                "Window/control handle does not belong to the configured editor PID"
            )
        target = hwnd
    else:
        candidates = [
            h
            for h in owned_windows(pid)
            if win32gui.IsWindowVisible(h) and win32gui.GetMenu(h)
        ]
        if not candidates:
            raise BackendError("Editor has no visible window")
        target = max(
            candidates,
            key=lambda h: (lambda r: (r[2] - r[0]) * (r[3] - r[1]))(
                win32gui.GetWindowRect(h)
            ),
        )
    try:
        if not win32gui.IsWindowEnabled(target) and action not in (
            "restore",
            "maximize",
        ):
            raise BackendError(
                "Editor target is disabled, usually by a modal dialog; inspect and act on that dialog first"
            )
        if action in ("keys", "click", "double_click", "drag", "scroll", "focus"):
            raise BackendError(
                "Hidden sessions use semantic menu/control messages. Inspect menu labels and control handles, or edit the VMF through terminal tools; global keyboard/mouse input is unavailable."
            )
        if action == "menu":
            items = menu_items(win32gui.GetMenu(target))
            item = None
            clean = (
                lambda label: label.split("\t")[0].replace("&", "").strip().casefold()
            )
            for label in menu.split("->"):
                matches = [
                    item for item in items if clean(item["label"]) == clean(label)
                ]
                if len(matches) != 1:
                    raise BackendError(
                        "Menu path must match actual inspected labels exactly"
                    )
                item = matches[0]
                items = item["items"]
            if (
                item is None
                or items
                or not item["enabled"]
                or not 0 < item["id"] < 65536
            ):
                raise BackendError("Select an enabled menu command")
            send_control(target, 0x111, item["id"], 0)
        elif action == "text":
            if win32gui.GetClassName(target) != "Edit":
                raise BackendError("text requires a standard Edit control")
            send_control(target, 0xC, 0, text)
        elif action == "select":
            class_name = win32gui.GetClassName(target)
            if class_name not in ("ComboBox", "ListBox"):
                raise BackendError("select requires a standard ComboBox or ListBox")
            index = send_control(
                target, 0x158 if class_name == "ComboBox" else 0x1A2, -1, text
            )
            if index == (1 << (8 * __import__("struct").calcsize("P"))) - 1:
                raise BackendError(
                    "Selection must exactly match an existing control item"
                )
            send_control(target, 0x14E if class_name == "ComboBox" else 0x186, index, 0)
            send_control(
                win32gui.GetParent(target),
                0x111,
                win32gui.GetDlgCtrlID(target) | (1 << 16),
                target,
            )
        elif action == "invoke":
            if win32gui.GetClassName(target) == "Button":
                send_control(target, 0xF5, 0, 0)
            else:
                raise BackendError("invoke requires a standard Button control")
        elif action == "restore":
            win32gui.ShowWindow(target, 4)  # SW_SHOWNOACTIVATE, private desktop only.
        elif action == "maximize":
            win32gui.ShowWindow(target, 3)
        elif action == "close":
            win32gui.PostMessage(target, 0x10, 0, 0)
        else:
            raise BackendError("Unknown editor action")
    except Exception as exc:
        if isinstance(exc, BackendError):
            raise
        raise BackendError(f"Editor action failed: {exc}") from exc
    return {
        "pid": pid,
        "hwnd": target,
        "action": action,
        "status": "dispatched",
        "verification": "Dispatched on the owned private desktop. Inspect resulting controls and a viewport capture; save_editor commits staged VMF bytes through the revision-checked transaction.",
    }
