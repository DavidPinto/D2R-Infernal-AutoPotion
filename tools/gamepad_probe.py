"""Real-controller input recorder: learn the actual feed-merc binding.

Run while playing (read-only - only WATCHES your physical controller):

    python tools\\gamepad_probe.py

It polls all XInput slots and prints/logs every CHANGE in buttons, triggers
or thumbsticks.  Perform the feed-to-merc gesture manually with your real
controller (however you do it in D2R), then Ctrl+C.  The captured sequence -
which button/trigger combination you actually held - tells us exactly what
the synthetic pad must send.
"""
from __future__ import annotations

import ctypes
import os
import sys
import time

LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "config", "gamepad_scan.log")

XINPUT_GAMEPAD = 0x0001   # XINPUT_STATE.gamepad offset in the struct


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_uint),
                ("wButtons", ctypes.c_ushort),
                ("bLeftTrigger", ctypes.c_ubyte),
                ("bRightTrigger", ctypes.c_ubyte),
                ("sThumbLX", ctypes.c_short),
                ("sThumbLY", ctypes.c_short),
                ("sThumbRX", ctypes.c_short),
                ("sThumbRY", ctypes.c_short)]

BUTTONS = [
    (0x0001, "DPAD_UP"), (0x0002, "DPAD_DOWN"), (0x0004, "DPAD_LEFT"),
    (0x0008, "DPAD_RIGHT"), (0x0010, "START"), (0x0020, "BACK"),
    (0x0040, "L3"), (0x0080, "R3"), (0x0100, "LB"), (0x0200, "RB"),
    (0x1000, "A"), (0x2000, "B"), (0x4000, "X"), (0x8000, "Y"),
]


def describe(st: XINPUT_STATE) -> str:
    names = [n for bit, n in BUTTONS if st.wButtons & bit]
    return (f"buttons={'+'.join(names) or '-'} LT={st.bLeftTrigger} "
            f"RT={st.bRightTrigger} LX={st.sThumbLX} LY={st.sThumbLY}")


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    xinput = None
    for dll in ("XInput1_4", "XInput1_3", "XInput9_1_0"):
        try:
            xinput = ctypes.WinDLL(dll)
            break
        except OSError:
            continue
    if xinput is None:
        print("No XInput DLL found.")
        return 1

    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    log = open(LOG_PATH, "w", encoding="utf-8")
    print("Recording controller changes (~10 ms poll). Do the feed-merc "
          "gesture on your REAL controller, then Ctrl+C.")
    print(f"Log: {LOG_PATH}\n")

    last = {}
    t0 = time.monotonic()
    try:
        while time.monotonic() - t0 < 600:
            for slot in range(4):
                st = XINPUT_STATE()
                if xinput.XInputGetState(slot, ctypes.byref(st)) != 0:
                    continue
                key = describe(st)
                if last.get(slot) != key:
                    ts = time.monotonic() - t0
                    msg = f"t={ts:7.2f} slot{slot}: {key}"
                    print(msg)
                    log.write(msg + "\n")
                    last[slot] = key
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    print("done")
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
