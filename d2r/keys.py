"""Keyboard and gamepad simulation using native Win32 APIs.

Keyboard input goes through SendInput (no AutoHotkey / keybd_event); gamepad
input through Microsoft's synthetic gamepad API (xboxgipsynthetic.dll — ships
with Windows 10 22H2+ cumulative updates, no driver install).  Supports
Shift-modifier combos (which D2R uses to feed potions to the mercenary).  No
third-party dependencies.
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

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

# XInput constants (defined at module level for use in XINPUT_BUTTON_MAP)
XINPUT_GAMEPAD_DPAD_UP = 0x0001
XINPUT_GAMEPAD_DPAD_DOWN = 0x0002
XINPUT_GAMEPAD_DPAD_LEFT = 0x0004
XINPUT_GAMEPAD_DPAD_RIGHT = 0x0008
XINPUT_GAMEPAD_A = 0x1000
XINPUT_GAMEPAD_B = 0x2000
XINPUT_GAMEPAD_X = 0x4000
XINPUT_GAMEPAD_Y = 0x8000

# XInput button mapping for D-pad (belt keys)
XINPUT_BUTTON_MAP = {
    "DPAD_UP": XINPUT_GAMEPAD_DPAD_UP,
    "DPAD_DOWN": XINPUT_GAMEPAD_DPAD_DOWN,
    "DPAD_LEFT": XINPUT_GAMEPAD_DPAD_LEFT,
    "DPAD_RIGHT": XINPUT_GAMEPAD_DPAD_RIGHT,
    "A": XINPUT_GAMEPAD_A,
    "B": XINPUT_GAMEPAD_B,
    "X": XINPUT_GAMEPAD_X,
    "Y": XINPUT_GAMEPAD_Y,
}

# Reverse map for friendly display of XInput buttons.
XINPUT_BUTTON_NAME = {v: k for k, v in XINPUT_BUTTON_MAP.items()}

# Built-in fallback key per drink action, used only while the belt content is
# unreadable (the watcher normally reads each slot and presses that column's
# key, so there are no user-configurable per-potion bindings since 1.8.0).
FALLBACK_KEYS = {
    "heal": "Q", "mana": "W", "rejuv": "E",
    "merc_heal": "Q", "merc_rejuv": "E",
}

# Modifiers the tool can hold together with a belt hotkey (feed-to-merc).
MODIFIER_KEYS = {"SHIFT": VK["SHIFT"], "CTRL": VK["CTRL"], "ALT": VK["ALT"]}

# XInput structures
class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", ctypes.c_ushort),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [
        ("dwPacketNumber", ctypes.c_ulong),
        ("Gamepad", XINPUT_GAMEPAD),
    ]


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

# XInput
xinput = ctypes.WinDLL("xinput1_4", use_last_error=True)
XInputGetState = xinput.XInputGetState
XInputGetState.restype = ctypes.c_uint
XInputGetState.argtypes = [ctypes.c_uint, ctypes.POINTER(XINPUT_STATE)]


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


def keysym_to_key_name(code: int) -> str:
    """Return the key name for a given virtual-key code (for display)."""
    if code in VK_NAME:
        return VK_NAME[code]
    return f"0x{code:X}"


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


# --- Xbox Synthetic Gamepad --------------------------------------------------
# Microsoft's built-in virtual gamepad API (xboxgipsynthetic.dll, ships with
# Windows 10 22H2+ cumulative updates — no driver install).  Requirements,
# probe-verified: the process must be ELEVATED (E_ACCESSDENIED otherwise), the
# calling thread needs STA COM (0x800401F0 otherwise), and the xboxgipsvc
# service auto-starts when elevated.  Input report = 14-byte GIP payload with
# report type 0 (any other type returns E_INVALIDARG): byte[0] holds the left
# face buttons (Y X B A View Menu KeepAlive), byte[1] the D-pad + right buttons
# (RSB LSB RB LB Dpad-R L D U), bytes [2:14] the triggers/sticks in LE.

_SYNTH_DLL = "xboxgipsynthetic.dll"
_SYNTH_REPORT_TYPE_GAMEPAD = 0
_SYNTH_CONTROLLER_XBOX = 0  # standard Xbox One-style controller

# GIP button bits, grouped by payload byte.
_GIP_BUTTONS_MSB = {  # payload[1]
    "DPAD_UP": 0x01, "DPAD_DOWN": 0x02, "DPAD_LEFT": 0x04, "DPAD_RIGHT": 0x08,
}
_GIP_BUTTONS_LSB = {  # payload[0]
    "Y": 0x80, "X": 0x40, "B": 0x20, "A": 0x10,
}


def _gip_payload(buttons_lsb: int = 0, buttons_msb: int = 0,
                 left_trigger: int = 0) -> bytes:
    """14-byte GIP gamepad input report (all values little-endian).

    Probe-verified on this build: [0..1] = buttons, [3] = left trigger
    0-255 (byte[2] does not register as a trigger)."""
    payload = bytearray(14)
    payload[0] = buttons_lsb & 0xFF
    payload[1] = buttons_msb & 0xFF
    payload[3] = left_trigger & 0xFF
    return bytes(payload)


class XboxSyntheticGamepad:
    """Virtual Xbox controller via the OS synthetic gamepad API (no drivers)."""

    def __init__(self):
        self._dll: ctypes.WinDLL | None = None
        self._handle: ctypes.c_void_p | None = None

    @staticmethod
    def available() -> bool:
        """True when xboxgipsynthetic.dll exists on this Windows."""
        try:
            ctypes.WinDLL(_SYNTH_DLL)
            return True
        except OSError:
            return False

    def connect(self) -> bool:
        """Create + connect the controller.  Returns False (logged) on failure."""
        if self._handle is not None:
            return True
        try:
            if self._dll is None:
                self._dll = ctypes.WinDLL(_SYNTH_DLL)
            # STA COM is required by the API on this thread.
            ole32 = ctypes.WinDLL("ole32")
            ole32.CoInitializeEx(None, 0x00000002)  # COINIT_APARTMENTTHREADED
            create = self._dll.SyntheticController_CreateController
            create.restype = ctypes.c_ulong
            create.argtypes = [ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p)]
            connect = self._dll.SyntheticController_Connect
            connect.restype = ctypes.c_ulong
            connect.argtypes = [ctypes.c_void_p]
            handle = ctypes.c_void_p()
            rc = create(_SYNTH_CONTROLLER_XBOX, ctypes.byref(handle))
            if rc != 0 or not handle.value:
                print(f"[keys] SyntheticController_CreateController rc=0x{rc:08X} "
                      f"(run the app as administrator)")
                return False
            rc = connect(handle)
            if rc != 0:
                print(f"[keys] SyntheticController_Connect rc=0x{rc:08X}")
                return False
            self._handle = handle
            print("[keys] Synthetic gamepad connected")
            return True
        except OSError as exc:
            print(f"[keys] Synthetic gamepad unavailable: {exc}")
            return False

    def send(self, payload: bytes) -> bool:
        """Send one GIP input report; False when not connected or rejected."""
        if self._handle is None:
            return False
        send = self._dll.SyntheticController_SendReport
        send.restype = ctypes.c_ulong
        send.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                         ctypes.c_void_p, ctypes.c_uint]
        buf = ctypes.create_string_buffer(payload, len(payload))
        rc = send(self._handle, _SYNTH_REPORT_TYPE_GAMEPAD, buf, len(payload))
        return rc == 0

    def press(self, buttons_lsb: int = 0, buttons_msb: int = 0,
              left_trigger: int = 0) -> bool:
        """Press (hold ~50ms) then release, as one tap.

        ``left_trigger`` (0-255) is held for the whole tap — the D2R controller
        feed-to-merc binding is LT + potion direction."""
        if not self.send(_gip_payload(buttons_lsb, buttons_msb, left_trigger)):
            return False
        time.sleep(0.05)
        return self.send(_gip_payload())

    def disconnect(self) -> None:
        """Disconnect + remove the controller (best-effort)."""
        if self._handle is None:
            return
        try:
            d = self._dll.SyntheticController_Disconnect
            d.restype = ctypes.c_ulong
            d.argtypes = [ctypes.c_void_p]
            d(self._handle)
            r = self._dll.SyntheticController_RemoveController
            r.restype = ctypes.c_ulong
            r.argtypes = [ctypes.c_void_p]
            r(self._handle)
        except Exception:
            pass
        self._handle = None


# Legacy module-level entry point; KeySender uses its own instance.  The
# controller_id is ignored — the synthetic controller takes the first free
# XInput slot (the app cannot choose the slot).
_synth_default = XboxSyntheticGamepad()


def press_gamepad_button(button: int, controller_id: int = 0) -> bool:
    """Press (and release) a gamepad button through the synthetic gamepad API."""
    name = XINPUT_BUTTON_NAME.get(button, "")
    if name in _GIP_BUTTONS_LSB:
        low, high = _GIP_BUTTONS_LSB[name], 0
    elif name in _GIP_BUTTONS_MSB:
        low, high = 0, _GIP_BUTTONS_MSB[name]
    else:
        print(f"[keys] Unknown gamepad button: 0x{button:X}")
        return False
    if not _synth_default.connect():
        return False
    return _synth_default.press(low, high)


class KeySender:
    """Potion key presser. Supports keyboard and gamepad input. Optionally focuses the game and plays a chime."""

    def __init__(self, config: AppConfig, pid: int | None = None):
        self.config = config
        self.pid = pid
        self._vks: dict[str, int | None] = {}
        self._gamepad = XboxSyntheticGamepad()

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
        # Read the flag live: toggling gamepad mode in the UI must apply to the
        # running watcher (KeySender lives for the whole connection session).
        if self.config.use_gamepad:
            return self._press_gamepad(action, key)
        
        modifier = self.config.merc_modifier() if action.startswith("merc_") else None
        key_name = key if key else self._fallback_key(action)
        vk = self.resolve(key_name)
        if vk is None:
            return False
        self._ensure_game_focused()
        ok = press_key(vk, modifier=modifier)
        if ok and self.config.behavior.get("sound", True):
            self.chime()
        return ok

    def _press_gamepad(self, action: str, key: str | None = None) -> bool:
        """Tap the gamepad D-pad direction for an action.

        Column letters map to D-pad directions per the game defaults
        (Q=Left, W=Up, E=Down, R=Right).  Merc actions hold LT while tapping —
        the D2R controller feed-to-merc binding (LT + potion direction); without
        it the PLAYER would drink the potion instead."""
        key_name = key if key else self._fallback_key(action)
        dpad_map = {"Q": "DPAD_LEFT", "W": "DPAD_UP", "E": "DPAD_DOWN", "R": "DPAD_RIGHT"}
        dpad = dpad_map.get(key_name, "")
        if not dpad:
            print(f"[keys] No D-pad mapping for column '{key_name}'")
            return False
        lt = 0xFF if action.startswith("merc_") else 0
        if not self._gamepad.connect():
            print("[keys] Gamepad unavailable — restart the app as administrator "
                  "(needs Windows 10 22H2+ with xboxgipsynthetic.dll)")
            return False
        self._ensure_game_focused()
        ok = self._gamepad.press(0, _GIP_BUTTONS_MSB[dpad], left_trigger=lt)
        if ok and self.config.behavior.get("sound", True):
            self.chime()
        return ok

    def _fallback_key(self, action: str) -> str:
        """Column letter for an action's fallback binding, honouring rebinds.

        The built-in fallbacks (heal Q / mana W / rejuv E) are column letters;
        if the user rebinds a belt column in the game the app must press the
        rebound key even while the belt content is unreadable."""
        letter = FALLBACK_KEYS.get(action, "")
        return self.config.belt_key(letter) if letter else ""

    @staticmethod
    def chime() -> None:
        """Play a short confirmation beep.  Best-effort; never raises."""
        try:
            winsound.Beep(880, 50)
            winsound.Beep(1320, 50)
        except Exception:
            pass
