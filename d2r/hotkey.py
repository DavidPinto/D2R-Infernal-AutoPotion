"""Global arm/disarm hotkey via the native Win32 RegisterHotKey API.

A hidden message-only window owns the hotkey and a background thread runs the
message loop, so the toggle keeps working while the game window has focus (the
tool's own window does not need keyboard focus).  Opt-in only: an unparseable or
already-registered hotkey logs an error and the app keeps running without it.
Pure ctypes - no third-party packages.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import threading
from typing import Callable, Optional

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312
WM_DESTROY = 0x0002

WNDPROC = ctypes.WINFUNCTYPE(wt.LPARAM, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Explicit prototypes: without them ctypes defaults parameters to c_int, which
# silently truncates 64-bit handles/lparams (classic LPARAM overflow bug).
user32.DefWindowProcW.restype = wt.LPARAM
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [
    wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID,
]
user32.RegisterClassW.restype = wt.ATOM
user32.RegisterClassW.argtypes = [ctypes.c_void_p]
user32.RegisterHotKey.restype = wt.BOOL
user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
user32.UnregisterHotKey.restype = wt.BOOL
user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
user32.PostMessageW.restype = wt.BOOL
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DestroyWindow.restype = wt.BOOL
user32.DestroyWindow.argtypes = [wt.HWND]
user32.GetMessageW.restype = ctypes.c_int
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.TranslateMessage.restype = wt.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.restype = wt.LPARAM
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
user32.PostQuitMessage.restype = None
user32.PostQuitMessage.argtypes = [ctypes.c_int]
kernel32.GetModuleHandleW.restype = wt.HINSTANCE
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]

_MOD_BY_NAME = {"CTRL": MOD_CONTROL, "ALT": MOD_ALT, "SHIFT": MOD_SHIFT, "WIN": MOD_WIN}


def parse_hotkey(spec: str) -> Optional[tuple[int, int]]:
    """Parse 'Ctrl+Alt+F12' into (modifiers, virtual-key).  None if invalid.

    The trailing token is the key (resolved like a belt binding: 'F12',
    '1', 'NUMPAD0', ...); everything before it must be modifier names."""
    if not spec:
        return None
    from .keys import resolve_key
    parts = [p.strip() for p in str(spec).split("+") if p.strip()]
    if len(parts) < 2:
        return None
    vk = resolve_key(parts[-1])
    if vk is None:
        return None
    mods = 0
    for name in parts[:-1]:
        mod = _MOD_BY_NAME.get(name.upper())
        if mod is None:
            return None
        mods |= mod
    return mods, vk


class HotkeyListener:
    """Registers a system-wide hotkey and fires ``callback`` on each press.

    ``callback`` runs on the listener thread (blocking it briefly is fine; the
    UI should marshal with ``widget.after(0, ...)`` if it touches Tkinter).
    ``start()`` returns True once the hotkey is registered and listening."""

    def __init__(self, mods: int, vk: int, callback: Callable[[], None]):
        self.mods = mods
        self.vk = vk
        self.callback = callback
        self._wndproc = WNDPROC(self._wnd_proc)
        self._hwnd: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._result: Optional[bool] = None

    def start(self) -> bool:
        """Register the hotkey and start the message loop.  Idempotent."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return bool(self._result)
            self._ready.clear()
            self._result = None
            self._thread = threading.Thread(target=self._loop, daemon=True,
                                            name="hotkey-listener")
            self._thread.start()
        self._ready.wait(timeout=3.0)
        return bool(self._result)

    def stop(self) -> None:
        """Unregister the hotkey and end the message loop (best-effort)."""
        with self._lock:
            hwnd = self._hwnd
            self._hwnd = None
        if hwnd:
            try:
                user32.PostMessageW(hwnd, WM_DESTROY, 0, 0)
            except Exception:
                pass

    # ---------------------------------------------------------------- internals
    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_HOTKEY:
            try:
                self.callback()
            except Exception:
                pass
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _loop(self) -> None:
        try:
            atom = user32.RegisterClassW(ctypes.byref(self._make_wndclass()))
            if not atom:
                self._result = False
                self._ready.set()
                return
            hwnd = user32.CreateWindowExW(
                0, "D2RAutoPotionHotkey", "d2r-autopotion-hotkey", 0,
                0, 0, 0, 0, None, None, kernel32.GetModuleHandleW(None), None)
            if not hwnd:
                self._result = False
                self._ready.set()
                return
            with self._lock:
                self._hwnd = int(hwnd)
            ok = bool(user32.RegisterHotKey(hwnd, 1, self.mods, self.vk))
            self._result = ok
            self._ready.set()
            if not ok:
                user32.DestroyWindow(hwnd)
                return
            msg = wt.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            user32.UnregisterHotKey(hwnd, 1)
            user32.DestroyWindow(hwnd)
        except Exception:
            self._result = False
            self._ready.set()
        finally:
            with self._lock:
                self._hwnd = None

    def _make_wndclass(self):
        class _WNDCLASS(ctypes.Structure):
            _fields_ = [
                ("style", wt.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
                ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR),
            ]
        wc = _WNDCLASS()
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = kernel32.GetModuleHandleW(None)
        wc.lpszClassName = "D2RAutoPotionHotkey"
        return wc
