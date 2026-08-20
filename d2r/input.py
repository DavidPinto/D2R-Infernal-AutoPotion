"""Mouse + window helpers for the belt refill clicker.

Pure ctypes, no third-party packages.  The clicker never moves the cursor or
clicks unless the game window is the foreground window, so the injected click
always lands on the game (never on the tool's own UI or another app).  The
Win32 INPUT structs are reused from :mod:`d2r.keys`.
"""

from __future__ import annotations

import ctypes
import time

from .keys import INPUT, SendInput, user32

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


user32.SetCursorPos.restype = ctypes.c_bool
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.GetCursorPos.restype = ctypes.c_bool
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.ClientToScreen.restype = ctypes.c_bool
user32.ClientToScreen.argtypes = [ctypes.c_void_p, ctypes.POINTER(POINT)]
user32.GetClientRect.restype = ctypes.c_bool
user32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(RECT)]
user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]


def cursor_pos() -> tuple[int, int]:
    """Current cursor position on screen, or (0, 0) on failure."""
    pt = POINT()
    if user32.GetCursorPos(ctypes.byref(pt)):
        return int(pt.x), int(pt.y)
    return 0, 0


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """Client rectangle of ``hwnd`` in *screen* coords, or None when unusable."""
    if not hwnd:
        return None
    origin = POINT()
    rect = RECT()
    if (not user32.GetClientRect(hwnd, ctypes.byref(rect))
            or not user32.ClientToScreen(hwnd, ctypes.byref(origin))):
        return None
    return (origin.x, origin.y, origin.x + rect.right, origin.y + rect.bottom)


def window_client_rect(hwnd: int) -> tuple[int, int] | None:
    """Client area size (w, h) of ``hwnd``, or None when unreadable."""
    rect = window_rect(hwnd)
    if not rect:
        return None
    return rect[2] - rect[0], rect[3] - rect[1]


def game_foreground(pid: int) -> bool:
    """True when the window currently on top belongs to process ``pid``."""
    if not pid:
        return False
    fg = user32.GetForegroundWindow()
    if not fg:
        return False
    fg_pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(fg, ctypes.byref(fg_pid))
    return fg_pid.value == pid


def _click() -> bool:
    """Inject a left-button down+up at the current cursor position."""
    for flags in (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP):
        inp = INPUT()
        inp.type = 0  # INPUT_MOUSE
        inp.mi.dwFlags = flags
        if SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) == 0:
            return False
        time.sleep(0.02)
    return True


def click_at(screen_x: int, screen_y: int) -> bool:
    """Move the cursor to ``(screen_x, screen_y)`` and left-click once."""
    if not user32.SetCursorPos(int(screen_x), int(screen_y)):
        return False
    time.sleep(0.03)
    return _click()
