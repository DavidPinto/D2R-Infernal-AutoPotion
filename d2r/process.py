"""Windows process discovery and memory reading via the Win32 API (ctypes).

Zero third-party dependencies - only the standard library plus kernel32/psapi/
user32.  This is what lets the tool avoid AutoHotkey entirely: we open the game
process and read its memory directly, then send key presses through the native
SendInput API (see d2r/keys.py).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from dataclasses import dataclass, field

# Executable names the game may run under.  "Infernal Edition" is a D2R client
# build, so the process is still D2R.exe.  D2RMM.exe is the *mod manager* / loader
# and is NOT the game itself, so D2R.exe is listed first and preferred.
GAME_PROCESS_NAMES = ["D2R.exe", "Diablo II Resurrected.exe", "D2RMM.exe"]
# Strict preference order (lower number = tried first).
GAME_PROCESS_PRIORITY = {n.lower(): i for i, n in enumerate(GAME_PROCESS_NAMES)}

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_ALL_ACCESS = 0x1F0FFF

MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100

TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

# ctypes prototypes ----------------------------------------------------------
class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", wt.LONG),
        ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_char * 260),
    ]


class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("th32ModuleID", wt.DWORD),
        ("th32ProcessID", wt.DWORD), ("GlblcntUsage", wt.DWORD),
        ("ProccntUsage", wt.DWORD), ("modBaseAddr", wt.LPVOID),
        ("modBaseSize", wt.DWORD), ("hModule", wt.HMODULE),
        ("szModule", ctypes.c_char * 256), ("szExePath", ctypes.c_char * 260),
    ]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", wt.LPVOID), ("AllocationBase", wt.LPVOID),
        ("AllocationProtect", wt.DWORD), ("PartitionId", wt.WORD),
        ("RegionSize", ctypes.c_size_t), ("State", wt.DWORD),
        ("Protect", wt.DWORD), ("Type", wt.DWORD),
    ]


def _protect_readable(protect: int) -> bool:
    if protect & (PAGE_NOACCESS | PAGE_GUARD):
        return False
    base = protect & 0xFF
    return base in (0x02, 0x04, 0x08, 0x20, 0x40, 0x80)


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wt.DWORD), ("HighPart", wt.LONG)]


kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
advapi32.OpenProcessToken.restype = wt.BOOL
advapi32.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
advapi32.LookupPrivilegeValueW.restype = wt.BOOL
advapi32.LookupPrivilegeValueW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, ctypes.POINTER(LUID)]
advapi32.AdjustTokenPrivileges.restype = wt.BOOL
advapi32.AdjustTokenPrivileges.argtypes = [
    wt.HANDLE, wt.BOOL, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, ctypes.c_void_p,
]

SE_PRIVILEGE_ENABLED = 0x00000002
TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_QUERY = 0x0008


def _enable_debug_privilege() -> None:
    """Enable SeDebugPrivilege so we can open/scan protected-ish processes."""
    try:
        token = wt.HANDLE()
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(),
                                         TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(token)):
            return
        luid = LUID()
        if not advapi32.LookupPrivilegeValueW(None, "SeDebugPrivilege", ctypes.byref(luid)):
            return

        class _TOKEN_PRIVILEGES(ctypes.Structure):
            _fields_ = [("PrivilegeCount", wt.DWORD),
                        ("Luid", LUID),
                        ("Attributes", wt.DWORD)]
        tp = _TOKEN_PRIVILEGES(1, luid, SE_PRIVILEGE_ENABLED)
        advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(tp),
                                       ctypes.sizeof(tp), None, None)
    except Exception:
        pass


kernel32.GetCurrentProcess.restype = wt.HANDLE
kernel32.ReadProcessMemory.argtypes = [
    wt.HANDLE, wt.LPCVOID, wt.LPVOID, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.VirtualQueryEx.argtypes = [
    wt.HANDLE, wt.LPCVOID, ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t,
]
kernel32.VirtualQueryEx.restype = ctypes.c_size_t


def _process_snapshot() -> list[PROCESSENTRY32]:
    """Enumerate running processes via Toolhelp32."""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        return []
    out: list[PROCESSENTRY32] = []
    try:
        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if not kernel32.Process32First(snap, ctypes.byref(pe)):
            return []
        while True:
            out.append(pe)
            pe = PROCESSENTRY32()
            pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
            if not kernel32.Process32Next(snap, ctypes.byref(pe)):
                break
    finally:
        kernel32.CloseHandle(snap)
    return out


def _is_game_name(name: str) -> bool:
    low = name.lower()
    return any(low == n.lower() for n in GAME_PROCESS_NAMES)


def find_d2r_processes() -> list[int]:
    """Return pids of game-ish processes, ordered by preference (D2R.exe first)."""
    found: dict[int, int] = {}
    for pe in _process_snapshot():
        name = pe.szExeFile.decode("utf-8", "ignore").rstrip("\x00")
        if _is_game_name(name):
            prio = GAME_PROCESS_PRIORITY.get(name.lower(), 99)
            found.setdefault(pe.th32ProcessID, prio)
    return [pid for pid, _ in sorted(found.items(), key=lambda kv: kv[1])]


def get_process_name(pid: int) -> str:
    """Executable file name for a pid ('' if the process is gone)."""
    for pe in _process_snapshot():
        if pe.th32ProcessID == pid:
            return pe.szExeFile.decode("utf-8", "ignore").rstrip("\x00")
    return ""


def get_process_modules(pid: int) -> list[tuple[int, int, str]]:
    """All loaded modules of a process as ``(base, size, name)`` tuples."""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, pid)
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, pid)
    if snap == INVALID_HANDLE_VALUE:
        return []
    modules: list[tuple[int, int, str]] = []
    try:
        me = MODULEENTRY32()
        me.dwSize = ctypes.sizeof(MODULEENTRY32)
        if not kernel32.Module32First(snap, ctypes.byref(me)):
            return []
        while True:
            modules.append((
                int(me.modBaseAddr), int(me.modBaseSize),
                me.szModule.decode("utf-8", "ignore"),
            ))
            me = MODULEENTRY32()
            me.dwSize = ctypes.sizeof(MODULEENTRY32)
            if not kernel32.Module32Next(snap, ctypes.byref(me)):
                break
    finally:
        kernel32.CloseHandle(snap)
    return modules


@dataclass
class Process:
    """Handle to a D2R game process opened with read access."""
    pid: int
    handle: int
    module_base: int
    module_size: int
    module_name: str = ""
    module_bytes_read: int = 0
    all_modules: list = field(default_factory=list)

    def __del__(self):
        try:
            kernel32.CloseHandle(self.handle)
        except Exception:
            pass

    @classmethod
    def attach(cls, pid: int | None = None) -> "Process":
        """Open a game process for reading and return a Process handle.

        Without ``pid`` the best running game is chosen (D2R.exe preferred over
        loaders).  Tries a read-only open first, then retries with full access
        after enabling SeDebugPrivilege so games running as Administrator can
        be attached."""
        if pid is None:
            pids = find_d2r_processes()
            if not pids:
                raise ProcessNotFound("D2R is not running.")
        else:
            pids = [pid]

        last_err = ""
        for cand in pids:
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, cand)
            if not handle:
                _enable_debug_privilege()
                handle = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, cand)
            if not handle:
                last_err = f"Could not open process (pid {cand})."
                continue
            modules = get_process_modules(cand)
            exe = get_process_name(cand).lower()
            # Only accept a module that is genuinely the game image: its basename
            # must end with one of the known game names.  A system DLL such as
            # CRYPT32.dll can never satisfy this, so it can't be mistaken for the
            # game even if a process happens to share a name fragment.
            game_mods = [
                m for m in modules
                if any(m[2].lower().endswith(n.lower()) for n in GAME_PROCESS_NAMES)
            ]
            if not game_mods:
                kernel32.CloseHandle(handle)
                last_err = "No game module in that process."
                continue
            # Prefer the executable module (basename == process exe basename);
            # otherwise prefer D2R.exe over a loader, then by priority.
            def _score(m):
                nm = m[2].lower()
                if exe and nm == exe:
                    return 0
                return GAME_PROCESS_PRIORITY.get(nm, 99)
            game_mods.sort(key=_score)
            base, size, name = game_mods[0]
            obj = cls(pid=cand, handle=handle, module_base=base, module_size=size)
            obj.module_name = name
            obj.module_bytes_read = 0
            obj.all_modules = modules
            return obj

        raise ProcessNotFound(last_err or "Could not locate the D2R.exe module.")

    # ---------------------------------------------------------------- reads
    def read_bytes(self, address: int, size: int) -> bytes:
        """Read 'size' bytes at 'address'; returns b"" on failure/partial read."""
        if size <= 0 or not address:
            return b""
        buf = ctypes.create_string_buffer(size)
        nread = ctypes.c_size_t(0)
        ok = kernel32.ReadProcessMemory(
            self.handle, ctypes.c_void_p(address), buf, size,
            ctypes.byref(nread))
        if not ok or nread.value != size:
            return b""
        return buf.raw

    def read_u8(self, address: int) -> int:
        """Read one unsigned byte (0 if unreadable)."""
        b = self.read_bytes(address, 1)
        return b[0] if len(b) == 1 else 0

    def read_u16(self, address: int) -> int:
        """Read a little-endian unsigned 16-bit value (0 if unreadable)."""
        b = self.read_bytes(address, 2)
        return int.from_bytes(b, "little") if len(b) == 2 else 0

    def read_u32(self, address: int) -> int:
        """Read a little-endian unsigned 32-bit value (0 if unreadable)."""
        b = self.read_bytes(address, 4)
        return int.from_bytes(b, "little") if len(b) == 4 else 0

    def read_u64(self, address: int) -> int:
        """Read a little-endian unsigned 64-bit value (0 if unreadable)."""
        b = self.read_bytes(address, 8)
        return int.from_bytes(b, "little") if len(b) == 8 else 0

    def read_ptr(self, address: int) -> int:
        """Read a native pointer (u64 on 64-bit)."""
        return self.read_u64(address)

    def read_string(self, address: int, size: int = 0) -> str:
        """Read a NUL-terminated string; with a fixed size, capped at that."""
        if size > 0:
            raw = self.read_bytes(address, size)
            return raw.split(b"\x00", 1)[0].decode("utf-8", "ignore")
        chunk = 1
        raw = b""
        while chunk <= 64:
            part = self.read_bytes(address + len(raw), chunk)
            if not part:
                break
            raw += part
            if b"\x00" in part:
                break
            chunk = min(chunk * 2, 64)
        return raw.split(b"\x00", 1)[0].decode("utf-8", "ignore")

    def read_wide_string(self, address: int, size: int = 0) -> str:
        """Read a NUL-terminated UTF-16LE string; with a fixed size, capped at
        that (in bytes).  Unit names (hirelings, monsters) are wide strings, so
        ``read_string`` (UTF-8) returns garbage for them."""
        if size > 0:
            raw = self.read_bytes(address, size)
            if len(raw) < 2:
                return ""
            return raw.split(b"\x00\x00", 1)[0].decode("utf-16le", "ignore")
        chunk = 64
        raw = b""
        while chunk <= 2048:
            part = self.read_bytes(address + len(raw), chunk)
            if not part:
                break
            raw += part
            if b"\x00\x00" in part:
                break
            chunk = min(chunk * 2, 2048)
        if len(raw) < 2:
            return ""
        return raw.split(b"\x00\x00", 1)[0].decode("utf-16le", "ignore")

    # --------------------------------------------------- module + patterns
    def _module_extent(self, base: int, size: int = 0) -> int:
        """Compute the real end address of a module image by walking regions
        whose AllocationBase equals the module base (handles modBaseSize == 0)."""
        start = base
        end = start + (size or 0)
        addr = start
        while True:
            mbi = MEMORY_BASIC_INFORMATION()
            if kernel32.VirtualQueryEx(
                    self.handle, ctypes.c_void_p(addr), ctypes.byref(mbi),
                    ctypes.sizeof(mbi)) == 0:
                break
            if int(mbi.AllocationBase or 0) != start:
                break
            candidate = int(mbi.BaseAddress or 0) + mbi.RegionSize
            if candidate > end:
                end = candidate
            if candidate <= addr:
                break
            addr = candidate
        return end

    def read_module(self, base: int | None = None, size: int | None = None) -> bytes:
        """Read a whole module image for pattern / structural scanning.

        Defaults to the attached (main) module.  Pass an explicit base/size to
        scan a different module (e.g. the real game module loaded by a loader).

        Regions are walked from the module base (so a zero/incorrect
        modBaseSize doesn't break us) and each committed, readable region is
        read in a single ReadProcessMemory call.  Gaps stay zero-filled.
        """
        if base is None:
            base = self.module_base
        if size is None:
            size = self.module_size
        if not base:
            return b""
        start = base
        end = self._module_extent(base, size)
        size = end - start
        if size <= 0:
            size = size or 0
        if size <= 0:
            return b""

        image = bytearray(size)
        total = 0
        addr = start
        while addr < end:
            mbi = MEMORY_BASIC_INFORMATION()
            if kernel32.VirtualQueryEx(
                    self.handle, ctypes.c_void_p(addr), ctypes.byref(mbi),
                    ctypes.sizeof(mbi)) == 0:
                addr += 0x1000
                continue
            rstart = max(addr, int(mbi.BaseAddress or 0))
            rend = min(end, int(mbi.BaseAddress or 0) + mbi.RegionSize)
            if (mbi.State == MEM_COMMIT and _protect_readable(mbi.Protect)
                    and rend > rstart):
                buf = ctypes.create_string_buffer(rend - rstart)
                nread = ctypes.c_size_t(0)
                ok = kernel32.ReadProcessMemory(
                    self.handle, ctypes.c_void_p(rstart), buf, rend - rstart,
                    ctypes.byref(nread))
                if ok and nread.value > 0:
                    off = rstart - start
                    if 0 <= off < len(image):
                        image[off:off + nread.value] = buf.raw[:nread.value]
                        total += nread.value
            nxt = int(mbi.BaseAddress or 0) + mbi.RegionSize
            if nxt <= addr:
                nxt = addr + 0x1000
            addr = nxt

        if base is None:
            self.module_bytes_read = total
            self.module_size = size
        return bytes(image) if total else b""

    def find_pattern(self, pattern: bytes, mask: bytes) -> int:
        """First absolute address matching the pattern in the main module (0 if none)."""
        memory = self.read_module()
        if not memory:
            return 0
        hits = find_pattern_in_all(memory, self.module_base, pattern, mask, limit=1)
        return hits[0] if hits else 0

    def module_ranges(self) -> list[tuple[int, int]]:
        """(base, size) ranges of every loaded module (used to reject pointers
        that land inside a module image — a classic false-positive shape)."""
        return [(int(b), int(s)) for b, s, _ in get_process_modules(self.pid) if b]


# --- window helpers (used to focus the game before sending keys) -------------

_EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)


def find_window_for_pid(pid: int) -> int | None:
    """First visible top-level window belonging to 'pid' (or None)."""
    result: list[int] = []

    @_EnumWindowsProc
    def _cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        wpid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid:
            result.append(hwnd)
            return False
        return True

    user32.EnumWindows(_cb, 0)
    return result[0] if result else None


def bring_window_to_front(hwnd: int) -> None:
    """Raise the game window AND give it real keyboard focus.

    A plain SetForegroundWindow() called from a background process is normally
    blocked by Windows' foreground-lock timeout, so the window is merely raised to
    the top of the Z-order but never receives keyboard input -- which is exactly
    why SendInput key presses would be swallowed.  Attaching our thread's input to
    the game's thread lets SetForegroundWindow/SetFocus succeed."""
    if not hwnd:
        return
    try:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE (in case minimised)
    except Exception:
        pass
    if user32.GetForegroundWindow() == hwnd:
        try:
            user32.SetFocus(hwnd)
        except Exception:
            pass
        return
    our_thread = kernel32.GetCurrentThreadId()
    fg = user32.GetForegroundWindow()
    fg_thread = wt.DWORD(0)
    if fg:
        user32.GetWindowThreadProcessId(fg, ctypes.byref(fg_thread))
    target_thread = wt.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(target_thread))
    attached = False
    if target_thread.value and target_thread.value != our_thread:
        try:
            user32.AttachThreadInput(our_thread, target_thread.value, True)
            attached = True
        except Exception:
            attached = False
    try:
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)
    except Exception:
        pass
    finally:
        if attached:
            try:
                user32.AttachThreadInput(our_thread, target_thread.value, False)
            except Exception:
                pass


class ProcessNotFound(Exception):
    pass


def find_pattern_in_all(memory: bytes, base: int, pattern: bytes, mask: bytes,
                        limit: int = 0) -> list[int]:
    """Return all absolute addresses where ``pattern`` matches ``memory``.

    Mask bytes of '?' are wildcards.  ``limit`` > 0 stops early.
    """
    n = len(pattern)
    if n == 0 or len(mask) != n or len(memory) < n:
        return []
    fixed_first = pattern[0] if mask[0] != ord("?") else None
    results: list[int] = []
    i = 0
    limit_n = len(memory) - n
    while i <= limit_n:
        if fixed_first is not None:
            i = memory.find(fixed_first, i)
            if i == -1 or i > limit_n:
                break
        matched = True
        for j in range(1, n):
            if mask[j] != ord("?") and memory[i + j] != pattern[j]:
                matched = False
                break
        if matched:
            results.append(base + i)
            if limit and len(results) >= limit:
                break
        i += 1
    return results
