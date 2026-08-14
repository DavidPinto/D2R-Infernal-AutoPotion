"""Keyboard simulation using the native Win32 SendInput API.

This replaces AutoHotkey / keybd_event entirely: it talks straight to the OS
input stack, needs no helper process, and supports Shift-modifier combos (which
D2R uses to feed potions to the mercenary).  No third-party dependencies.
"""

from __future__ import annotations

import ctypes
import time
import winsound

from .config import AppConfig

# Virtual key codes for the keys we expose (belt slots, function keys, ...).
VK = {
    "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34, "5": 0x35,
    "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
    "A": 0x41, "B": 0x42, "C": 0x43, "D": 0x44, "E": 0x45, "F": 0x46,
    "G": 0x47, "H": 0x48, "I": 0x49, "J": 0x4A, "K": 0x4B, "L": 0x4C,
    "M": 0x4D, "N": 0x4E, "O": 0x4F, "P": 0x50, "Q": 0x51, "R": 0x52,
    "S": 0x53, "T": 0x54, "U": 0x55, "V": 0x56, "W": 0x57, "X": 0x58,
    "Y": 0x59, "Z": 0x5A,
}
VK.update({f"F{i}": 0x70 + i - 1 for i in range(1, 25)})
VK.update({
    "SPACE": 0x20, "ENTER": 0x0D, "TAB": 0x09, "ESC": 0x1B,
    "BACKSPACE": 0x08, "INSERT": 0x2D, "DELETE": 0x2E,
    "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21, "PAGEDOWN": 0x22,
    "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28,
    "SHIFT": 0x10, "CTRL": 0x11, "ALT": 0x12, "LWIN": 0x5B, "RWIN": 0x5C,
    # Numpad (D2R lets you bind belt slots here too).
    "NUMPAD0": 0x60, "NUMPAD1": 0x61, "NUMPAD2": 0x62, "NUMPAD3": 0x63,
    "NUMPAD4": 0x64, "NUMPAD5": 0x65, "NUMPAD6": 0x66, "NUMPAD7": 0x67,
    "NUMPAD8": 0x68, "NUMPAD9": 0x69,
    "NUMPAD_MULT": 0x6A, "NUMPAD_ADD": 0x6B, "NUMPAD_SUB": 0x6D,
    "NUMPAD_DEC": 0x6E, "NUMPAD_DIV": 0x6F,
})

# Reverse map for friendly display of captured keys.
VK_NAME = {v: k for k, v in VK.items()}

# Modifiers the tool can hold together with a belt hotkey (feed-to-merc).
MODIFIER_KEYS = {"SHIFT": VK["SHIFT"], "CTRL": VK["CTRL"], "ALT": VK["ALT"]}

# Built-in fallback key per drink action, used only while the belt content is
# unreadable (the watcher normally reads each slot and presses that column's
# key, so there are no user-configurable per-potion bindings since 1.8.0).
FALLBACK_KEYS = {
    "heal": "Q", "mana": "W", "rejuv": "E",
    "merc_heal": "Q", "merc_rejuv": "E",
}

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

# ULONG_PTR: 8 bytes on 64-bit, 4 bytes on 32-bit.  Using c_ulong here makes the
# INPUT structure the WRONG SIZE (20 bytes instead of 40), which makes SendInput
# return 0 and silently swallow every keystroke.
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long), ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong), ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort),
    ]


class INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]
    _anonymous_ = ("_input",)
    _fields_ = [("type", ctypes.c_ulong), ("_input", _I)]


user32 = ctypes.WinDLL("user32", use_last_error=True)
SendInput = user32.SendInput
SendInput.restype = ctypes.c_uint
SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]


def resolve_key(name: str) -> int | None:
    """Resolve a stored binding to a Windows virtual-key code.

    Accepts a named key ("1", "Q", "F1", "NUMPAD1", ...) or a raw hex code
    ("0x61").  Returns None if it cannot be resolved.  Plain digits like "1"
    are keyboard keys (0x31), NOT raw virtual-key codes."""
    if name is None:
        return None
    s = str(name).strip()
    if not s:
        return None
    if s.lower().startswith("0x"):
        try:
            return int(s, 16)
        except ValueError:
            return None
    return VK.get(s.upper())


def vk_name(code: int) -> str:
    """Human-readable label for a virtual-key code (for the UI)."""
    if code in VK_NAME:
        return VK_NAME[code]
    return f"0x{code:X}"


def _send(vk: int, keyup: bool) -> bool:
    """Inject one keystroke event.  Returns False (and logs the OS error) if the
    injection was rejected — e.g. when the tool runs unprivileged against an
    elevated game process (UIPI)."""
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = vk
    inp.ki.dwFlags = KEYEVENTF_KEYUP if keyup else 0
    sent = SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    if sent == 0:
        err = ctypes.get_last_error()
        print(f"[keys] SendInput failed (keyup={keyup}, vk=0x{vk:X}, last_error={err})")
    return sent != 0


def resolve_modifier(name: str) -> int | None:
    """Resolve a modifier name ("SHIFT" / "CTRL" / "ALT") to its VK code."""
    if name is None:
        return None
    return MODIFIER_KEYS.get(str(name).strip().upper())


def press_key(vk: int, modifier: str | None = None) -> bool:
    """Press (and release) a virtual key, optionally while holding a modifier.

    The tiny sleep between down/up gives the game a chance to sample the key;
    the modifier is released AFTER the main key so the game sees the full
    combo (e.g. Shift+Q for feeding the merc a potion)."""
    mod_vk = resolve_modifier(modifier)
    ok = True
    if mod_vk is not None:
        ok = _send(mod_vk, keyup=False) and ok
    ok = _send(vk, keyup=False) and ok
    time.sleep(0.02)
    ok = _send(vk, keyup=True) and ok
    if mod_vk is not None:
        ok = _send(mod_vk, keyup=True) and ok
    return ok


class KeySender:
    """Potion key presser. Optionally focuses the game and plays a chime."""

    def __init__(self, config: AppConfig, pid: int | None = None):
        self.config = config
        self.pid = pid
        self._vks: dict[str, int | None] = {}

    def resolve(self, name: str) -> int | None:
        """Resolve a binding name to a VK, caching the result per name."""
        if name not in self._vks:
            self._vks[name] = resolve_key(name)
        return self._vks[name]

    def _ensure_game_focused(self) -> None:
        """Focus the game window so SendInput lands in the game, not the tool.

        SendInput goes to the *focused* window; from a background process the
        game won't receive the key otherwise.  No-op unless auto_focus_game is
        enabled."""
        if not self.config.behavior.get("auto_focus_game", True) or not self.pid:
            return
        try:
            from .process import bring_window_to_front, find_window_for_pid
            hwnd = find_window_for_pid(self.pid)
            if hwnd:
                bring_window_to_front(hwnd)
                time.sleep(0.05)
        except Exception:
            pass

    def press(self, action: str, key: str | None = None) -> bool:
        """Press the key for an action ('heal', 'mana', 'merc_heal', ...).

        ``key`` is the belt column to press (the watcher always passes the
        column that holds the potion); when omitted, the built-in fallback key
        for the action is used (belt unreadable).  Merc actions add the
        configured feed-to-merc modifier (default Shift).  Returns False if the
        binding is unresolved or the injection was rejected by the OS."""
        modifier = self.config.merc_modifier() if action.startswith("merc_") else None
        key_name = key if key else FALLBACK_KEYS.get(action, "")
        vk = self.resolve(key_name)
        if vk is None:
            return False
        self._ensure_game_focused()
        ok = press_key(vk, modifier=modifier)
        if ok and self.config.behavior.get("sound", True):
            self.chime()
        return ok

    @staticmethod
    def chime() -> None:
        """Play a short confirmation beep.  Best-effort; never raises."""
        try:
            winsound.Beep(880, 50)
            winsound.Beep(1320, 50)
        except Exception:
            pass
