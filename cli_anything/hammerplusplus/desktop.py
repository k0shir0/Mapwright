"""Native editor access for operations that need Hammer++ itself."""

from __future__ import annotations

import os
from pathlib import Path
import warnings

from .backend import BackendError, require_tool


def application(project, config, pid):
    if os.name != "nt":
        raise BackendError("Native Hammer++ interaction requires Windows")
    from .windows import set_dpi_awareness

    set_dpi_awareness()
    try:
        from pywinauto import Application
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
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message="32-bit application should be automated"
        )
        return Application(backend="win32").connect(process=pid, timeout=5)


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


def inspect_editor(project, config, pid: int, limit: int = 200):
    application(project, config, pid)
    import win32gui, win32process

    handles = []
    windows = []
    win32gui.EnumWindows(
        lambda h, _: (
            handles.append(h)
            if win32process.GetWindowThreadProcessId(h)[1] == pid
            and win32gui.IsWindowVisible(h)
            else None
        ),
        None,
    )
    for handle in handles:
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


def editor_action(
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
    app = application(project, config, pid)
    import win32gui, win32process

    if hwnd is not None:
        if (
            not win32gui.IsWindow(hwnd)
            or win32process.GetWindowThreadProcessId(hwnd)[1] != pid
        ):
            raise BackendError(
                "Window/control handle does not belong to the configured editor PID"
            )
        target = app.window(handle=hwnd).wrapper_object()
    else:
        candidates = [w for w in app.windows() if w.is_visible()]
        if not candidates:
            raise BackendError("Editor has no visible window")
        target = max(
            candidates, key=lambda w: w.rectangle().width() * w.rectangle().height()
        )
    try:
        if not target.is_enabled() and action not in ("restore", "maximize", "focus"):
            raise BackendError(
                "Editor target is disabled, usually by a modal dialog; inspect and act on that dialog first"
            )
        if action == "menu":
            items = menu_items(win32gui.GetMenu(target.handle))
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
            if items or not item["enabled"] or not 0 < item["id"] < 65536:
                raise BackendError("Select an enabled menu command")
            win32gui.PostMessage(target.handle, 0x111, item["id"], 0)
        elif action == "keys":
            target.type_keys(keys, set_foreground=True)
        elif action == "text":
            target.set_edit_text(text)
        elif action == "select":
            target.select(text)
        elif action == "invoke":
            target.click_input()
        elif action in ("click", "double_click", "drag", "scroll"):
            rect = target.client_rect()
            points = [(x, y)] + ([(end_x, end_y)] if action == "drag" else [])
            if any(
                not 0 <= a < rect.width() or not 0 <= b < rect.height()
                for a, b in points
            ):
                raise BackendError(
                    "Mouse coordinates must stay inside the selected editor control"
                )
            if action == "scroll":
                target.wheel_mouse_input(coords=(x, y), wheel_dist=steps)
            elif action == "drag":
                target.drag_mouse_input(button=button, src=(x, y), dst=(end_x, end_y))
            else:
                target.click_input(
                    button=button, coords=(x, y), double=action == "double_click"
                )
        elif action == "focus":
            target.set_focus()
        elif action == "restore":
            target.restore()
        elif action == "maximize":
            target.maximize()
        elif action == "close":
            target.close()
        else:
            raise BackendError("Unknown editor action")
    except Exception as exc:
        if isinstance(exc, BackendError):
            raise
        raise BackendError(f"Editor action failed: {exc}") from exc
    return {
        "pid": pid,
        "hwnd": target.handle,
        "action": action,
        "status": "dispatched",
        "verification": "Inspect editor state and a viewport capture to verify the requested outcome. Native GUI saves are not protected by the VMF transaction lock.",
    }
