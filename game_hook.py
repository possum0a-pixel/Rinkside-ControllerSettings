"""
RinkStick In-Memory Hook Engine for NHL Legacy (rexruntime.dll).

Definitive dynamic single-point hook on InputSystem::GetState.

In rexruntime.dll (the Xbox 360 runtime for NHL Legacy), all controller drivers
(SDL, XInput, DirectInput) report to InputSystem::GetState. The drivers' inputs
are accumulated together (buttons bitwise-OR'd, triggers maxed, sticks blended).

At the end of InputSystem::GetState, it performs the FINAL write of the aggregated
X_INPUT_STATE structure to the caller's output buffer (rcx) before returning:
    movl %ebp, (%rcx)        ; dwPacketNumber
    movl 0x2c(%rsp), %edx    ; accumulated wButtons
    movw %dx, 0x4(%rcx)      ; write wButtons
    movb %r13b, 0x6(%rcx)    ; write bLeftTrigger
    movb %bl, 0x7(%rcx)      ; write bRightTrigger
    vmovq %xmm7, 0x8(%rcx)   ; write sticks (lx, ly, rx, ry)
    jmp <epilogue>           ; jump to epilogue

By placing an inline hook at this exact 24-byte write site:
  1. We intercept the FINAL output for Player 1 (user_index == 0 in edi).
  2. We write our boosted analog sticks directly into [rcx+0x08..0x0E].
  3. We write our remapped buttons directly into [rcx+0x04].
  4. We write our remapped triggers directly into [rcx+0x06..0x07].
  5. No earlier driver or OR-accumulation can bypass or un-remap our inputs.
  6. Non-Player 1 slots (user_index != 0) pass through unmodified.
  7. Physical controller stays on input0 so the RinkSide account attaches.

Auto-adaptation:
  Offsets are dynamically discovered via PE export parsing and signature scanning
  so future RinkSide updates never cause crashes due to hardcoded addresses.
"""

from __future__ import annotations

import ctypes
import os
import struct
import time
from ctypes import wintypes
from typing import Optional, Tuple

# ── Win32 Constants ──────────────────────────────────────────────────────────
PROCESS_ALL_ACCESS       = 0x1F0FFF
PROCESS_VM_OPERATION     = 0x0008
PROCESS_VM_READ          = 0x0010
PROCESS_VM_WRITE         = 0x0020
MEM_COMMIT               = 0x1000
MEM_RESERVE              = 0x2000
MEM_RELEASE              = 0x8000
PAGE_EXECUTE_READWRITE   = 0x40
PAGE_READWRITE           = 0x04
TH32CS_SNAPPROCESS       = 0x00000002
TH32CS_SNAPMODULE        = 0x00000008
TH32CS_SNAPMODULE32      = 0x00000010
INVALID_HANDLE_VALUE     = ctypes.c_void_p(-1).value
STILL_ACTIVE             = 259
DONT_RESOLVE_DLL_REFERENCES = 0x00000001

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

kernel32.VirtualAllocEx.restype = ctypes.c_uint64
kernel32.VirtualAllocEx.argtypes = [
    wintypes.HANDLE, ctypes.c_uint64, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD
]

kernel32.VirtualFreeEx.restype = wintypes.BOOL
kernel32.VirtualFreeEx.argtypes = [
    wintypes.HANDLE, ctypes.c_uint64, ctypes.c_size_t, wintypes.DWORD
]

kernel32.VirtualProtectEx.restype = wintypes.BOOL
kernel32.VirtualProtectEx.argtypes = [
    wintypes.HANDLE, ctypes.c_uint64, ctypes.c_size_t, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)
]

kernel32.ReadProcessMemory.restype = wintypes.BOOL
kernel32.ReadProcessMemory.argtypes = [
    wintypes.HANDLE, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)
]

kernel32.WriteProcessMemory.restype = wintypes.BOOL
kernel32.WriteProcessMemory.argtypes = [
    wintypes.HANDLE, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)
]

kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]

kernel32.GetExitCodeProcess.restype = wintypes.BOOL
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]

kernel32.LoadLibraryExW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32]
kernel32.LoadLibraryExW.restype = ctypes.c_void_p

kernel32.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
kernel32.GetProcAddress.restype = ctypes.c_void_p

kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]
kernel32.FreeLibrary.restype = wintypes.BOOL


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize",              wintypes.DWORD),
        ("cntUsage",            wintypes.DWORD),
        ("th32ProcessID",       wintypes.DWORD),
        ("th32DefaultHeapID",   ctypes.c_size_t),
        ("th32ModuleID",        wintypes.DWORD),
        ("cntThreads",          wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase",      wintypes.LONG),
        ("dwFlags",             wintypes.DWORD),
        ("szExeFile",           ctypes.c_wchar * 260),
    ]

class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize",        wintypes.DWORD),
        ("th32ModuleID",  wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage",  wintypes.DWORD),
        ("ProccntUsage",  wintypes.DWORD),
        ("modBaseAddr",   ctypes.c_uint64),
        ("modBaseSize",   wintypes.DWORD),
        ("hModule",       wintypes.HMODULE),
        ("szModule",      ctypes.c_wchar * 256),
        ("szExePath",     ctypes.c_wchar * 260),
    ]

# ── Shared control block layout (20 bytes) ───────────────────────────────────
# +0x00 DWORD magic         0x4B4E4952 ("RINK")
# +0x04 DWORD active        1 = enabled, 0 = bypass
# +0x08 SHORT lx            Transformed Left Stick X (-32767..32767)
# +0x0A SHORT ly            Transformed Left Stick Y
# +0x0C SHORT rx            Transformed Right Stick X
# +0x0E SHORT ry            Transformed Right Stick Y
# +0x10 WORD  wButtons      Remapped digital buttons bitmask
# +0x12 BYTE  bLeftTrigger  Remapped Left Trigger (0..255)
# +0x13 BYTE  bRightTrigger Remapped Right Trigger (0..255)
SHARED_BLOCK_FMT  = "<IIhhhhHBB"
SHARED_BLOCK_SIZE = struct.calcsize(SHARED_BLOCK_FMT)   # 20 bytes
MAGIC             = 0x4B4E4952

HOOK_SITE_SIZE = 24

# Unique instruction signature at the write site inside InputSystem::GetState:
# mov [rcx], ebp; mov edx, [rsp+0x2c]; mov [rcx+4], dx; mov [rcx+6], r13b; mov [rcx+7], bl
WRITE_SITE_SIG = bytes([
    0x89, 0x29,                         # mov [rcx], ebp
    0x8B, 0x54, 0x24, 0x2C,             # mov edx, [rsp+0x2c]
    0x66, 0x89, 0x51, 0x04,             # mov [rcx+0x04], dx
    0x44, 0x88, 0x69, 0x06,             # mov [rcx+0x06], r13b
    0x88, 0x59, 0x07                    # mov [rcx+0x07], bl
])

# Fallback offsets for current RinkSide build (Nov 10+ 2026 update)
DEFAULT_WRITE_RVA = 0x368e80
DEFAULT_RESUME_RVA = 0x368e9d

_OFFSETS_CACHE: dict[str, Tuple[int, int]] = {}


def resolve_rex_offsets(dll_path: str) -> Optional[Tuple[int, int]]:
    """
    Dynamically discovers the write site and resume site RVAs from rexruntime.dll.
    Ensures compatibility across game and runtime updates.
    """
    if not dll_path or not os.path.exists(dll_path):
        return DEFAULT_WRITE_RVA, DEFAULT_RESUME_RVA
    if dll_path in _OFFSETS_CACHE:
        return _OFFSETS_CACHE[dll_path]
    try:
        h = kernel32.LoadLibraryExW(dll_path, None, DONT_RESOLVE_DLL_REFERENCES)
        if not h:
            return DEFAULT_WRITE_RVA, DEFAULT_RESUME_RVA
        try:
            sym = b"?GetState@InputSystem@input@rex@@QEAAIIPEAUX_INPUT_STATE@23@@Z"
            fn = kernel32.GetProcAddress(h, sym)
            if not fn:
                return DEFAULT_WRITE_RVA, DEFAULT_RESUME_RVA
            func_rva = fn - h
            buf = (ctypes.c_ubyte * 0x300).from_address(fn)
            func_bytes = bytes(buf)
            pos = func_bytes.find(WRITE_SITE_SIG)
            if pos != -1:
                write_rva = func_rva + pos
                resume_rva = write_rva + 29
                _OFFSETS_CACHE[dll_path] = (write_rva, resume_rva)
                return write_rva, resume_rva
        finally:
            kernel32.FreeLibrary(h)
    except Exception:
        pass
    return DEFAULT_WRITE_RVA, DEFAULT_RESUME_RVA


class GameHook:
    def __init__(self):
        self.hooked:             bool          = False
        self.pid:                Optional[int] = None
        self.hProcess:           Optional[int] = None
        self.rexruntime_base:    int           = 0
        self.rexruntime_path:    str           = ""
        self.allocated_page:     int           = 0
        self.shared_block_addr:  int           = 0
        self.hook_code_addr:     int           = 0
        self.target_write_va:    int           = 0
        self.target_resume_va:   int           = 0
        self.orig_site_bytes:    bytes         = b""
        self.status_message:     str           = "Waiting for nhllegacy.exe..."

    def is_process_alive(self) -> bool:
        """Checks if the hooked game process is still actively running."""
        if not self.hProcess:
            return False
        exit_code = wintypes.DWORD(0)
        if not kernel32.GetExitCodeProcess(self.hProcess, ctypes.byref(exit_code)):
            return False
        return exit_code.value == STILL_ACTIVE

    def find_nhllegacy_pid(self) -> Optional[int]:
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == INVALID_HANDLE_VALUE:
            return None
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        try:
            if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
                return None
            while True:
                if entry.szExeFile.lower() == "nhllegacy.exe":
                    return entry.th32ProcessID
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    return None
        finally:
            kernel32.CloseHandle(snapshot)

    def find_module_info(self, pid: int, module_name: str) -> Tuple[int, str]:
        """Finds the base address and executable path of a module in the target process."""
        snap = kernel32.CreateToolhelp32Snapshot(
            TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
        if snap == INVALID_HANDLE_VALUE:
            return 0, ""
        entry = MODULEENTRY32W()
        entry.dwSize = ctypes.sizeof(MODULEENTRY32W)
        try:
            if not kernel32.Module32FirstW(snap, ctypes.byref(entry)):
                return 0, ""
            while True:
                if entry.szModule.lower() == module_name.lower():
                    return entry.modBaseAddr, entry.szExePath
                if not kernel32.Module32NextW(snap, ctypes.byref(entry)):
                    return 0, ""
        finally:
            kernel32.CloseHandle(snap)

    def _build_hook_assembly(self, shared_addr: int, resume_addr: int) -> bytes:
        """
        Constructs the x64 assembly executed when InputSystem::GetState writes output.

        Register state at entry (from InputSystem::GetState):
          rcx = destination X_INPUT_STATE* (caller buffer)
          edi = user_index (0 = Player 1)
          ebp = dwPacketNumber
          [rsp+0x2c] = accumulated original wButtons
          r13b = accumulated original bLeftTrigger
          bl   = accumulated original bRightTrigger
          xmm7 = accumulated original sticks
        """
        b = bytearray()

        # 1. Always write dwPacketNumber
        b += bytes([0x89, 0x29])                        # mov [rcx], ebp

        # 2. Check if user_index == 0 (Player 1)
        b += bytes([0x85, 0xFF])                        # test edi, edi
        off_jnz_p1 = len(b)
        b += bytes([0x75, 0x00])                        # jne write_orig

        # 3. Load shared block address and verify magic + active
        b += bytes([0x49, 0xBA])
        b += struct.pack("<Q", shared_addr)             # mov r10, <shared_addr>
        b += bytes([0x41, 0x81, 0x3A, 0x52, 0x49, 0x4E, 0x4B]) # cmp [r10], 'RINK'
        off_jnz_magic = len(b)
        b += bytes([0x75, 0x00])                        # jne write_orig
        b += bytes([0x41, 0x83, 0x7A, 0x04, 0x00])      # cmp dword ptr [r10+4], 0
        off_jz_active = len(b)
        b += bytes([0x74, 0x00])                        # je write_orig

        # 4. Write transformed analog sticks (Big-Endian for Xbox 360 runtime)
        # sThumbLX: [r10+0x08] -> [rcx+0x08]
        b += bytes([
            0x66, 0x41, 0x8B, 0x52, 0x08,               # mov dx, [r10+0x08]
            0x86, 0xF2,                                 # xchg dh, dl
            0x66, 0x89, 0x51, 0x08,                     # mov [rcx+0x08], dx
        ])
        # sThumbLY: [r10+0x0A] -> [rcx+0x0A]
        b += bytes([
            0x66, 0x41, 0x8B, 0x52, 0x0A,               # mov dx, [r10+0x0A]
            0x86, 0xF2,                                 # xchg dh, dl
            0x66, 0x89, 0x51, 0x0A,                     # mov [rcx+0x0A], dx
        ])
        # sThumbRX: [r10+0x0C] -> [rcx+0x0C]
        b += bytes([
            0x66, 0x41, 0x8B, 0x52, 0x0C,               # mov dx, [r10+0x0C]
            0x86, 0xF2,                                 # xchg dh, dl
            0x66, 0x89, 0x51, 0x0C,                     # mov [rcx+0x0C], dx
        ])
        # sThumbRY: [r10+0x0E] -> [rcx+0x0E]
        b += bytes([
            0x66, 0x41, 0x8B, 0x52, 0x0E,               # mov dx, [r10+0x0E]
            0x86, 0xF2,                                 # xchg dh, dl
            0x66, 0x89, 0x51, 0x0E,                     # mov [rcx+0x0E], dx
        ])

        # 5. Write remapped buttons (Big-Endian for Xbox 360 runtime)
        # wButtons: [r10+0x10] -> [rcx+0x04]
        b += bytes([
            0x66, 0x41, 0x8B, 0x52, 0x10,               # mov dx, [r10+0x10]
            0x86, 0xF2,                                 # xchg dh, dl
            0x66, 0x89, 0x51, 0x04,                     # mov [rcx+0x04], dx
        ])

        # 6. Write remapped triggers (1 byte each)
        # bLeftTrigger: [r10+0x12] -> [rcx+0x06]
        b += bytes([
            0x41, 0x8A, 0x52, 0x12,                     # mov dl, [r10+0x12]
            0x88, 0x51, 0x06,                           # mov [rcx+0x06], dl
        ])
        # bRightTrigger: [r10+0x13] -> [rcx+0x07]
        b += bytes([
            0x41, 0x8A, 0x52, 0x13,                     # mov dl, [r10+0x13]
            0x88, 0x51, 0x07,                           # mov [rcx+0x07], dl
        ])

        # Jump to exit
        off_jmp_exit = len(b)
        b += bytes([0xEB, 0x00])

        # write_orig: write accumulated inputs verbatim (Player 2+ or hook disabled)
        pos_write_orig = len(b)
        b += bytes([
            0x8B, 0x54, 0x24, 0x2C,                     # mov edx, [rsp+0x2c]
            0x66, 0x89, 0x51, 0x04,                     # mov [rcx+0x04], dx
            0x44, 0x88, 0x69, 0x06,                     # mov [rcx+0x06], r13b
            0x88, 0x59, 0x07,                           # mov [rcx+0x07], bl
            0xC5, 0xF9, 0xD6, 0x79, 0x08,               # vmovq [rcx+0x08], xmm7
        ])

        # exit_hook: resume original function epilogue
        pos_exit = len(b)
        b += bytes([0x31, 0xC0])                        # xor eax, eax (ERROR_SUCCESS)
        b += bytes([0x49, 0xBB])
        b += struct.pack("<Q", resume_addr)             # mov r11, <resume_addr>
        b += bytes([0x41, 0xFF, 0xE3])                  # jmp r11

        # Fix up relative jumps
        b[off_jnz_p1 + 1] = pos_write_orig - (off_jnz_p1 + 2)
        b[off_jnz_magic + 1] = pos_write_orig - (off_jnz_magic + 2)
        b[off_jz_active + 1] = pos_write_orig - (off_jz_active + 2)
        b[off_jmp_exit + 1] = pos_exit - (off_jmp_exit + 2)

        return bytes(b)

    def attach(self) -> bool:
        """Finds nhllegacy.exe, allocates an RWX page, and safely patches InputSystem::GetState."""
        pid = self.find_nhllegacy_pid()
        if not pid:
            if self.hooked:
                self.detach()
            self.status_message = "Waiting for nhllegacy.exe to launch..."
            return False

        if self.hooked and self.pid == pid:
            if self.is_process_alive():
                return True
            # Process died; reset state to reattach cleanly
            self.detach()

        self.pid = pid
        hProcess = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if not hProcess:
            err = ctypes.get_last_error()
            if err == 5:
                self.status_message = "Admin rights required to attach"
            else:
                self.status_message = f"OpenProcess failed (PID {pid}, Err {err})"
            return False
        self.hProcess = hProcess

        rex_base, rex_path = self.find_module_info(pid, "rexruntime.dll")
        if not rex_base:
            self.status_message = "Found nhllegacy.exe, waiting for rexruntime.dll..."
            kernel32.CloseHandle(hProcess)
            self.hProcess = None
            return False
        self.rexruntime_base = rex_base
        self.rexruntime_path = rex_path

        # ── Dynamically resolve write site RVAs ───────────────────────────────
        offsets = resolve_rex_offsets(rex_path)
        if offsets:
            write_rva, resume_rva = offsets
        else:
            write_rva, resume_rva = DEFAULT_WRITE_RVA, DEFAULT_RESUME_RVA

        self.target_write_va = rex_base + write_rva
        self.target_resume_va = rex_base + resume_rva

        # ── Read and verify current bytes at target location ──────────────────
        current_bytes = (ctypes.c_ubyte * HOOK_SITE_SIZE)()
        read_sz = ctypes.c_size_t(0)
        if not kernel32.ReadProcessMemory(hProcess, self.target_write_va,
                                          current_bytes, HOOK_SITE_SIZE,
                                          ctypes.byref(read_sz)):
            self.status_message = "Failed reading InputSystem::GetState target bytes."
            kernel32.CloseHandle(hProcess)
            self.hProcess = None
            return False

        current_bytes_data = bytes(current_bytes)
        # Safety check: ensure memory begins with the write site signature
        if not current_bytes_data.startswith(WRITE_SITE_SIG):
            self.status_message = "Signature mismatch at hook target. Aborting to prevent crash."
            print(f"[RinkStick Hook] Target bytes mismatch at 0x{self.target_write_va:X}: {current_bytes_data[:10].hex()}")
            kernel32.CloseHandle(hProcess)
            self.hProcess = None
            return False

        self.orig_site_bytes = current_bytes_data

        # ── Allocate RWX page in game process ─────────────────────────────────
        PAGE_SIZE = 4096
        page = kernel32.VirtualAllocEx(hProcess, 0, PAGE_SIZE,
                                       MEM_COMMIT | MEM_RESERVE,
                                       PAGE_EXECUTE_READWRITE)
        if not page:
            err = ctypes.get_last_error()
            self.status_message = f"VirtualAllocEx failed (Err {err})"
            kernel32.CloseHandle(hProcess)
            self.hProcess = None
            return False

        self.allocated_page    = page
        self.shared_block_addr = page          # page+0x00: shared control block
        self.hook_code_addr    = page + 0x40   # page+0x40: hook code

        written = ctypes.c_size_t(0)

        # 1. Write initial shared block (active=1)
        initial_block = struct.pack(SHARED_BLOCK_FMT, MAGIC, 1, 0, 0, 0, 0, 0, 0, 0)
        kernel32.WriteProcessMemory(hProcess, self.shared_block_addr,
                                    initial_block, len(initial_block),
                                    ctypes.byref(written))

        # 2. Build and write hook assembly
        hook_asm = self._build_hook_assembly(self.shared_block_addr, self.target_resume_va)
        kernel32.WriteProcessMemory(hProcess, self.hook_code_addr,
                                    hook_asm, len(hook_asm),
                                    ctypes.byref(written))

        # 3. Patch the 24-byte write site in InputSystem::GetState:
        #    FF 25 00000000 <8-byte hook_code_addr>  (14 bytes)
        #    followed by 10 NOPs (0x90)               (10 bytes)
        #    Total = 24 bytes (exact fit)
        patch = bytearray([0xFF, 0x25, 0x00, 0x00, 0x00, 0x00])
        patch += struct.pack("<Q", self.hook_code_addr)
        patch += bytes([0x90] * (HOOK_SITE_SIZE - len(patch)))
        assert len(patch) == HOOK_SITE_SIZE

        old_prot = wintypes.DWORD(0)
        kernel32.VirtualProtectEx(hProcess, self.target_write_va, HOOK_SITE_SIZE,
                                  PAGE_EXECUTE_READWRITE, ctypes.byref(old_prot))
        kernel32.WriteProcessMemory(hProcess, self.target_write_va,
                                    bytes(patch), HOOK_SITE_SIZE,
                                    ctypes.byref(written))
        kernel32.VirtualProtectEx(hProcess, self.target_write_va, HOOK_SITE_SIZE,
                                  old_prot, ctypes.byref(old_prot))

        self.hooked = True
        self.status_message = f"🟢 ATTACHED & ACTIVE (NHL Legacy PID: {pid})"
        print(f"[RinkStick Hook] Successfully attached to NHL Legacy (PID {pid}) at 0x{self.target_write_va:X}!")
        return True

    def update_state(self, lx: int, ly: int, rx: int, ry: int,
                     buttons: int, lt: int, rt: int) -> None:
        """Writes transformed stick + remapped button/trigger data into shared control block."""
        if not self.hooked or not self.hProcess:
            return
        block = struct.pack(
            SHARED_BLOCK_FMT,
            MAGIC, 1,
            int(lx), int(ly), int(rx), int(ry),
            int(buttons) & 0xFFFF,
            int(lt) & 0xFF, int(rt) & 0xFF
        )
        written = ctypes.c_size_t(0)
        kernel32.WriteProcessMemory(self.hProcess,
                                    self.shared_block_addr,
                                    block, len(block),
                                    ctypes.byref(written))

    def detach(self) -> None:
        """Restores original 24 bytes in InputSystem::GetState and frees allocated page."""
        if not self.hProcess:
            self.hooked = False
            return
        old_prot = wintypes.DWORD(0)
        written  = ctypes.c_size_t(0)

        # Restore original instructions
        if self.target_write_va and self.orig_site_bytes:
            kernel32.VirtualProtectEx(self.hProcess, self.target_write_va,
                                      HOOK_SITE_SIZE, PAGE_EXECUTE_READWRITE,
                                      ctypes.byref(old_prot))
            kernel32.WriteProcessMemory(self.hProcess, self.target_write_va,
                                        self.orig_site_bytes, HOOK_SITE_SIZE,
                                        ctypes.byref(written))
            kernel32.VirtualProtectEx(self.hProcess, self.target_write_va,
                                      HOOK_SITE_SIZE, old_prot,
                                      ctypes.byref(old_prot))

        if self.allocated_page:
            kernel32.VirtualFreeEx(self.hProcess, self.allocated_page, 0, MEM_RELEASE)
            self.allocated_page = 0

        kernel32.CloseHandle(self.hProcess)
        self.hProcess = None
        self.hooked   = False
        self.status_message = "Detached."


class GameInputBridge:
    """Interface used by ControllerIO."""
    def __init__(self):
        self._hook = GameHook()
        self._last_attach_try = 0.0

    @property
    def hooked(self) -> bool:
        return self._hook.hooked

    @property
    def status_message(self) -> str:
        return self._hook.status_message

    def try_attach(self, now: float, interval_s: float = 1.0) -> bool:
        if self.hooked:
            if not self._hook.is_process_alive():
                self._hook.detach()
                return False
            return True
        if (now - self._last_attach_try) < interval_s:
            return False
        self._last_attach_try = now
        try:
            return bool(self._hook.attach())
        except Exception as exc:
            self._hook.status_message = f"Attach error: {exc}"
            return False

    def push_pad_state(self, lx: int, ly: int, rx: int, ry: int,
                       buttons: int, lt: int, rt: int) -> None:
        if self.hooked:
            try:
                self._hook.update_state(lx, ly, rx, ry, buttons, lt, rt)
            except Exception:
                pass

    def detach(self) -> None:
        try:
            self._hook.detach()
        except Exception:
            pass
