"""Capture only a selected Hammer++ window, using native Windows APIs."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import struct
import zlib

from .backend import BackendError, require_tool
from .project import Project, atomic_write
from .vmf import MapError


def set_dpi_awareness():
    """Keep window rectangles, mouse input and capture in physical pixels."""
    user = ctypes.WinDLL("user32", use_last_error=True)
    if hasattr(user, "SetThreadDpiAwarenessContext"):
        user.SetThreadDpiAwarenessContext.argtypes = [wintypes.HANDLE]
        user.SetThreadDpiAwarenessContext.restype = wintypes.HANDLE
        user.SetThreadDpiAwarenessContext(wintypes.HANDLE(-4))


def capture_editor(
    project: Project, config: dict, pid: int, output: str, method: str = "auto"
) -> dict:
    from .native_session import request

    if method not in ("auto", "window", "viewport"):
        raise BackendError(
            "Owned sessions capture native viewports or their own windows; screen capture would capture the user's desktop"
        )
    return request(
        project, config, pid, "capture", {"output": output, "method": method}
    )


def _capture_editor(
    project: Project, config: dict, pid: int, output: str, method: str = "window"
) -> dict:
    from . import desktop

    if pid != desktop._owned_pid or method != "window":
        raise BackendError("Window capture requires the owned private desktop broker")
    if os.name != "nt":
        raise BackendError("Editor window capture requires Windows")
    set_dpi_awareness()
    if isinstance(pid, bool) or pid <= 0:
        raise MapError("pid must be a positive process ID")
    path = project.confined(output)
    if path.suffix.lower() != ".png" or path.exists():
        raise MapError("Capture output must be a new PNG inside the workspace")
    exe = require_tool(project, config, "hammer")
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    process = kernel.OpenProcess(0x1000, False, pid)
    if not process:
        raise BackendError("Cannot open the selected editor process")
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if (
            not kernel.QueryFullProcessImageNameW(
                process, 0, buffer, ctypes.byref(size)
            )
            or Path(buffer.value).resolve() != exe
        ):
            raise BackendError("Selected PID is not the configured Hammer++ executable")
    finally:
        kernel.CloseHandle(process)
    windows = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

    @callback_type
    def callback(hwnd, _):
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        rect = wintypes.RECT()
        if (
            owner.value == pid
            and user.IsWindowVisible(hwnd)
            and user.GetWindowRect(hwnd, ctypes.byref(rect))
        ):
            windows.append(
                ((rect.right - rect.left) * (rect.bottom - rect.top), hwnd, rect)
            )
        return True

    for handle in desktop.owned_windows(pid):
        callback(handle, 0)
    if not windows:
        raise BackendError("No visible window belongs to this Hammer++ process")
    _, hwnd, rect = max(windows, key=lambda row: row[0])
    user.IsIconic.argtypes = [wintypes.HWND]
    if user.IsIconic(hwnd):
        raise BackendError("Editor is minimized; restore it before capturing viewports")
    if method != "window":
        raise BackendError("method must be window")
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if not (1 <= width <= 8192 and 1 <= height <= 8192 and width * height <= 8388608):
        raise BackendError(
            "Owned window exceeds the eight megapixel capture limit; restore a smaller private window or use viewport capture"
        )
    user.GetDC.argtypes = [wintypes.HWND]
    user.GetDC.restype = wintypes.HDC
    user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    gdi.SelectObject.restype = wintypes.HANDLE
    gdi.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi.DeleteDC.argtypes = [wintypes.HDC]
    gdi.GetDIBits.argtypes = [
        wintypes.HDC,
        wintypes.HBITMAP,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.UINT,
    ]
    dc = user.GetDC(hwnd)
    memory = gdi.CreateCompatibleDC(dc)
    bitmap = gdi.CreateCompatibleBitmap(dc, width, height)
    if not dc or not memory or not bitmap:
        if bitmap:
            gdi.DeleteObject(bitmap)
        if memory:
            gdi.DeleteDC(memory)
        if dc:
            user.ReleaseDC(hwnd, dc)
        raise BackendError("Cannot allocate a window capture bitmap")
    previous = gdi.SelectObject(memory, bitmap)
    try:
        if not user.PrintWindow(hwnd, memory, 2):
            raise BackendError("Hammer++ window capture failed")
        gdi.SelectObject(memory, previous)
        header = struct.pack(
            "<IiiHHIIiiII", 40, width, -height, 1, 32, 0, width * height * 4, 0, 0, 0, 0
        )
        info = ctypes.create_string_buffer(header + b"\0" * 12)
        pixels = ctypes.create_string_buffer(width * height * 4)
        if gdi.GetDIBits(memory, bitmap, 0, height, pixels, info, 0) != height:
            raise BackendError("Could not read the captured window pixels")
        raw = pixels.raw
        rgb = bytearray(width * height * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = raw[2::4], raw[1::4], raw[0::4]
        if len(set(rgb[:: max(1, len(rgb) // 4096)])) < 2:
            raise BackendError(
                "Window capture appears blank; inspect the owned editor controls and readiness"
            )
        rows = b"".join(
            b"\0" + rgb[y * width * 3 : (y + 1) * width * 3] for y in range(height)
        )

        def chunk(kind, data):
            return (
                struct.pack(">I", len(data))
                + kind
                + data
                + struct.pack(">I", zlib.crc32(kind + data))
            )

        png = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows))
            + chunk(b"IEND", b"")
        )
        atomic_write(path, png, exclusive=True)
    finally:
        gdi.SelectObject(memory, previous)
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(memory)
        user.ReleaseDC(hwnd, dc)
    return {
        "path": str(path),
        "pid": pid,
        "width": width,
        "height": height,
        "method": "PrintWindow",
        "limitations": "PrintWindow can omit GPU viewport pixels; native UI capture does not establish viewport rendering.",
        "verification": "Inspect this image to confirm editor state; a screenshot alone does not prove compilation or playability.",
    }
