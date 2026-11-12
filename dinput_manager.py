"""
RinkStick DirectInput / WinMM Controller Manager
Provides non-XInput controller support (PS4, PS5, Switch Pro, generic HID gamepads)
using Windows built-in winmm.dll + joyGetPosEx. No external dependencies required.

Axis / button layout is auto-detected by controller type, with an optional override.
"""

import ctypes
from ctypes import wintypes
from typing import NamedTuple, Optional

# ---------------------------------------------------------------------------
# WinMM constants
# ---------------------------------------------------------------------------
JOYERR_NOERROR    = 0
JOY_RETURNNONE    = 0x00000000
JOY_RETURNX       = 0x00000001
JOY_RETURNY       = 0x00000002
JOY_RETURNZ       = 0x00000004
JOY_RETURNR       = 0x00000008
JOY_RETURNU       = 0x00000010
JOY_RETURNV       = 0x00000020
JOY_RETURNPOV     = 0x00000040
JOY_RETURNBUTTONS = 0x00000080
JOY_RETURNRAWDATA = 0x00000100
JOY_RETURNPOVCTS  = 0x00000200
JOY_RETURNCENTERED = 0x00000400
JOY_USEDEADZONE   = 0x00000800
JOY_RETURNALL     = (JOY_RETURNX | JOY_RETURNY | JOY_RETURNZ |
                     JOY_RETURNR | JOY_RETURNU | JOY_RETURNV |
                     JOY_RETURNPOV | JOY_RETURNBUTTONS)

JOYCAPS_HASZ = 0x0001
JOYCAPS_HASR = 0x0002
JOYCAPS_HASU = 0x0004
JOYCAPS_HASV = 0x0008
JOYCAPS_HASPOV     = 0x0010
JOYCAPS_POV4DIR    = 0x0020
JOYCAPS_POVCTS     = 0x0040

JOY_POVCENTERED = 0xFFFF          # 16-bit sentinel
JOY_POVCENTERED_FULL = 0xFFFFFFFF  # 32-bit sentinel (joyGetPosEx)
JOY_POVFORWARD  = 0
JOY_POVRIGHT    = 9000
JOY_POVBACKWARD = 18000
JOY_POVLEFT     = 27000

# ---------------------------------------------------------------------------
# WinMM structures
# ---------------------------------------------------------------------------
class JOYCAPSW(ctypes.Structure):
    """Device capabilities returned by joyGetDevCapsW."""
    _fields_ = [
        ("wMid",        wintypes.WORD),
        ("wPid",        wintypes.WORD),
        ("szPname",     ctypes.c_wchar * 32),
        ("wXmin",       wintypes.UINT),
        ("wXmax",       wintypes.UINT),
        ("wYmin",       wintypes.UINT),
        ("wYmax",       wintypes.UINT),
        ("wZmin",       wintypes.UINT),
        ("wZmax",       wintypes.UINT),
        ("wNumButtons", wintypes.UINT),
        ("wPeriodMin",  wintypes.UINT),
        ("wPeriodMax",  wintypes.UINT),
        ("wRmin",       wintypes.UINT),
        ("wRmax",       wintypes.UINT),
        ("wUmin",       wintypes.UINT),
        ("wUmax",       wintypes.UINT),
        ("wVmin",       wintypes.UINT),
        ("wVmax",       wintypes.UINT),
        ("wCaps",       wintypes.UINT),
        ("wMaxAxes",    wintypes.UINT),
        ("wNumAxes",    wintypes.UINT),
        ("wMaxButtons", wintypes.UINT),
        ("szRegKey",    ctypes.c_wchar * 32),
        ("szOEMVxD",    ctypes.c_wchar * 260),
    ]

class JOYINFOEX(ctypes.Structure):
    """Full joystick state returned by joyGetPosEx."""
    _fields_ = [
        ("dwSize",      wintypes.DWORD),
        ("dwFlags",     wintypes.DWORD),
        ("dwXpos",      wintypes.DWORD),
        ("dwYpos",      wintypes.DWORD),
        ("dwZpos",      wintypes.DWORD),
        ("dwRpos",      wintypes.DWORD),
        ("dwUpos",      wintypes.DWORD),
        ("dwVpos",      wintypes.DWORD),
        ("dwButtons",   wintypes.DWORD),
        ("dwButtonNumber", wintypes.DWORD),
        ("dwPOV",       wintypes.DWORD),
        ("dwReserved1", wintypes.DWORD),
        ("dwReserved2", wintypes.DWORD),
    ]

# ---------------------------------------------------------------------------
# XInput button masks (output format consumed by game_hook)
# ---------------------------------------------------------------------------
XINPUT_MASK = {
    "DPAD_UP":    0x0001,
    "DPAD_DOWN":  0x0002,
    "DPAD_LEFT":  0x0004,
    "DPAD_RIGHT": 0x0008,
    "START":      0x0010,
    "BACK":       0x0020,
    "L3":         0x0040,
    "R3":         0x0080,
    "LB":         0x0100,
    "RB":         0x0200,
    "A":          0x1000,
    "B":          0x2000,
    "X":          0x4000,
    "Y":          0x8000,
}

# ---------------------------------------------------------------------------
# Per-controller button index → XInput button name mappings
# ---------------------------------------------------------------------------
# PS4 / PS5 — DualShock4 / DualSense in DirectInput mode (no DS4Windows)
#   0=Square, 1=Cross, 2=Circle, 3=Triangle, 4=L1, 5=R1,
#   6=L2(digital), 7=R2(digital), 8=Share/Create, 9=Options,
#   10=L3, 11=R3, 12=PS, 13=Touchpad
PS4_BUTTON_MAP = {
    0: "X",      # Square → X (face left)
    1: "A",      # Cross  → A (face bottom)
    2: "B",      # Circle → B (face right)
    3: "Y",      # Triangle → Y (face top)
    4: "LB",     # L1
    5: "RB",     # R1
    8: "BACK",   # Share / Create
    9: "START",  # Options
    10: "L3",
    11: "R3",
}

# Switch Pro Controller in DirectInput mode
# Mapped physically to Xbox standard layout for intuitive hockey controls:
#   0: South (B on Switch)  → A (Pass / Protect Puck)
#   1: East  (A on Switch)  → B (Body Check / Slap Shot)
#   2: West  (Y on Switch)  → X (Stick Lift / Poke)
#   3: North (X on Switch)  → Y (Board Pin / Fight)
#   4: L     → LB
#   5: R     → RB
#   6: ZL    → Digital trigger (handled in poll)
#   7: ZR    → Digital trigger (handled in poll)
#   8: Minus → BACK
#   9: Plus  → START
#   10: L3
#   11: R3
SWITCH_BUTTON_MAP = {
    0: "A",      # South button → A
    1: "B",      # East button  → B
    2: "X",      # West button  → X
    3: "Y",      # North button → Y
    4: "LB",     # L
    5: "RB",     # R
    8: "BACK",   # Minus
    9: "START",  # Plus
    10: "L3",
    11: "R3",
}

# Generic / unknown — assume a common Xbox-like layout
GENERIC_BUTTON_MAP = {
    0: "A",
    1: "B",
    2: "X",
    3: "Y",
    4: "LB",
    5: "RB",
    6: "BACK",
    7: "START",
    8: "L3",
    9: "R3",
}

BUTTON_MAPS = {
    "ps4":     PS4_BUTTON_MAP,
    "ps5":     PS4_BUTTON_MAP,
    "switch":  SWITCH_BUTTON_MAP,
    "generic": GENERIC_BUTTON_MAP,
    "xinput":  {},
    "auto":    GENERIC_BUTTON_MAP,
}

# ---------------------------------------------------------------------------
# Axis assignments per controller type
# Fields: lx, ly, rx, ry, lt, rt
# Axis sources: "x"=dwXpos, "y"=dwYpos, "z"=dwZpos,
#               "r"=dwRpos, "u"=dwUpos, "v"=dwVpos
# ---------------------------------------------------------------------------
AXIS_MAP = {
    # PS4/PS5: LS=(X,Y), RS=(Z,Rpos), L2=Upos, R2=Vpos
    "ps4":     {"lx": "x", "ly": "y", "rx": "z", "ry": "r", "lt": "u", "rt": "v"},
    "ps5":     {"lx": "x", "ly": "y", "rx": "z", "ry": "r", "lt": "u", "rt": "v"},
    # Switch Pro: LS=(X,Y), RS=(Z,Rpos), ZL/ZR are digital buttons 6 & 7
    "switch":  {"lx": "x", "ly": "y", "rx": "z", "ry": "r", "lt": None, "rt": None},
    # Generic fallback: LS=(X,Y), RS=(Z,Rpos)
    "generic": {"lx": "x", "ly": "y", "rx": "z", "ry": "r", "lt": "u", "rt": "v"},
    "auto":    {"lx": "x", "ly": "y", "rx": "z", "ry": "r", "lt": "u", "rt": "v"},
}

# ---------------------------------------------------------------------------
# Output pad state (normalized to XInput ranges)
# ---------------------------------------------------------------------------
class PadState(NamedTuple):
    lx: int       # -32767 .. 32767
    ly: int       # -32767 .. 32767 (Y-up positive, matches XInput convention)
    rx: int
    ry: int
    lt: int       # 0 .. 255
    rt: int       # 0 .. 255
    buttons: int  # XInput wButtons bitmask

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _norm_axis(raw: int, min_val: int, max_val: int, invert: bool = False, deadzone: float = 0.08) -> int:
    """
    Map a raw WinMM axis value (0–65535 or custom range) to -32767..32767.
    Applies an internal center deadzone (default 8%) to suppress uncalibrated
    DirectInput drift, then smoothly rescales from deadzone to 100%.
    """
    if max_val <= min_val:
        return 0
    span = max_val - min_val
    centered = raw - min_val - span // 2
    frac = centered / (span / 2.0)
    
    if invert:
        frac = -frac

    # Clamp to [-1.0, 1.0]
    frac = max(-1.0, min(1.0, frac))

    # Center deadzone filter to kill neutral potentiometer noise
    if abs(frac) < deadzone:
        return 0
    
    # Smooth rescaling past deadzone
    sign = 1.0 if frac > 0.0 else -1.0
    rescaled = sign * (abs(frac) - deadzone) / (1.0 - deadzone)
    out = int(round(rescaled * 32767.0))
    return max(-32767, min(32767, out))

def _norm_trigger(raw: int, min_val: int, max_val: int, deadzone: float = 0.05) -> int:
    """Map a raw WinMM axis value to 0..255 with deadzone."""
    if max_val <= min_val:
        return 0
    span = max_val - min_val
    frac = (raw - min_val) / span
    frac = max(0.0, min(1.0, frac))
    if frac < deadzone:
        return 0
    rescaled = (frac - deadzone) / (1.0 - deadzone)
    return max(0, min(255, int(round(rescaled * 255.0))))

def _pov_to_dpad(pov: int) -> int:
    """
    Convert WinMM POV hat angle (hundredths of degrees) to XInput dpad bits.
    Sentinels: negative, 0xFFFF, 0xFFFFFFFF, or >= 36000 mean centered/released.
    """
    if pov < 0 or pov >= 36000:
        return 0
    angle = pov % 36000
    flags = 0
    # Up = 0 (also catches wrap-around 31500..36000 and 0..4500)
    if angle <= 4500 or angle >= 31500:
        flags |= XINPUT_MASK["DPAD_UP"]
    if 4500 <= angle <= 13500:
        flags |= XINPUT_MASK["DPAD_RIGHT"]
    if 13500 <= angle <= 22500:
        flags |= XINPUT_MASK["DPAD_DOWN"]
    if 22500 <= angle <= 31500:
        flags |= XINPUT_MASK["DPAD_LEFT"]
    return flags

def _get_axis(info: JOYINFOEX, caps: JOYCAPSW, axis_key: Optional[str]) -> tuple:
    """
    Return (raw_value, min_val, max_val) for the requested axis key.
    If the axis is missing or not supported by device caps, returns (32767, 0, 65535)
    so it evaluates to neutral center (0), NEVER max deflection.
    """
    if not axis_key:
        return 32767, 0, 65535
    if axis_key == "x":
        return info.dwXpos, caps.wXmin, caps.wXmax
    elif axis_key == "y":
        return info.dwYpos, caps.wYmin, caps.wYmax
    elif axis_key == "z":
        if caps.wCaps & JOYCAPS_HASZ:
            return info.dwZpos, caps.wZmin, caps.wZmax
        return 32767, 0, 65535
    elif axis_key == "r":
        if caps.wCaps & JOYCAPS_HASR:
            return info.dwRpos, caps.wRmin, caps.wRmax
        return 32767, 0, 65535
    elif axis_key == "u":
        if caps.wCaps & JOYCAPS_HASU:
            return info.dwUpos, caps.wUmin, caps.wUmax
        return 32767, 0, 65535
    elif axis_key == "v":
        if caps.wCaps & JOYCAPS_HASV:
            return info.dwVpos, caps.wVmin, caps.wVmax
        return 32767, 0, 65535
    return 32767, 0, 65535

# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------
class DirectInputPad:
    """
    Wraps winmm.dll joyGetPosEx to poll a non-XInput joystick and return
    its state normalized to XInput button/axis ranges.
    """

    def __init__(self):
        try:
            self._winmm = ctypes.WinDLL("winmm.dll")
            self._winmm.joyGetNumDevs.restype        = wintypes.UINT
            self._winmm.joyGetDevCapsW.argtypes      = [wintypes.UINT, ctypes.POINTER(JOYCAPSW), wintypes.UINT]
            self._winmm.joyGetDevCapsW.restype       = wintypes.UINT
            self._winmm.joyGetPosEx.argtypes         = [wintypes.UINT, ctypes.POINTER(JOYINFOEX)]
            self._winmm.joyGetPosEx.restype          = wintypes.UINT
            self._available = True
        except Exception as exc:
            print(f"[RinkStick/DInput] winmm.dll load failed: {exc}")
            self._winmm = None
            self._available = False

        self._caps_cache: dict = {}

    def _get_caps(self, dev_idx: int) -> Optional[JOYCAPSW]:
        if dev_idx in self._caps_cache:
            return self._caps_cache[dev_idx]
        caps = JOYCAPSW()
        ret = self._winmm.joyGetDevCapsW(dev_idx, ctypes.byref(caps), ctypes.sizeof(caps))
        if ret == JOYERR_NOERROR:
            self._caps_cache[dev_idx] = caps
            return caps
        return None

    def scan(self, prefer_type: str = "auto") -> Optional[int]:
        """
        Scan for the first connected joystick device.
        Returns the WinMM device index (0-based), or None if none found.
        """
        if not self._available:
            return None
        try:
            num = self._winmm.joyGetNumDevs()
        except Exception:
            return None

        for idx in range(num):
            info = JOYINFOEX()
            info.dwSize  = ctypes.sizeof(JOYINFOEX)
            info.dwFlags = JOY_RETURNALL
            ret = self._winmm.joyGetPosEx(idx, ctypes.byref(info))
            if ret == JOYERR_NOERROR:
                return idx
        return None

    def poll(self, dev_idx: int, controller_type: str = "auto") -> Optional[PadState]:
        """
        Poll device *dev_idx* and return a PadState normalized to XInput ranges.
        Returns None on error (device disconnected etc.).
        """
        if not self._available:
            return None

        caps = self._get_caps(dev_idx)
        if caps is None:
            self._caps_cache.pop(dev_idx, None)
            return None

        info = JOYINFOEX()
        info.dwSize  = ctypes.sizeof(JOYINFOEX)
        info.dwFlags = JOY_RETURNALL
        ret = self._winmm.joyGetPosEx(dev_idx, ctypes.byref(info))
        if ret != JOYERR_NOERROR:
            return None

        # Pick axis / button layout
        ctype = controller_type if controller_type in AXIS_MAP else "auto"
        axis_cfg    = AXIS_MAP[ctype]
        button_map  = BUTTON_MAPS.get(ctype, GENERIC_BUTTON_MAP)

        # -- Sticks -------------------------------------------------------
        # WinMM Y-axis: 0=top (up), max=bottom (down) — invert to match XInput
        raw_lx, lx_min, lx_max = _get_axis(info, caps, axis_cfg["lx"])
        raw_ly, ly_min, ly_max = _get_axis(info, caps, axis_cfg["ly"])
        raw_rx, rx_min, rx_max = _get_axis(info, caps, axis_cfg["rx"])
        raw_ry, ry_min, ry_max = _get_axis(info, caps, axis_cfg["ry"])

        lx = _norm_axis(raw_lx, lx_min, lx_max)
        ly = _norm_axis(raw_ly, ly_min, ly_max, invert=True)
        rx = _norm_axis(raw_rx, rx_min, rx_max)
        ry = _norm_axis(raw_ry, ry_min, ry_max, invert=True)

        # -- Triggers -----------------------------------------------------
        lt_key = axis_cfg.get("lt")
        rt_key = axis_cfg.get("rt")
        lt = rt = 0
        if lt_key:
            raw_lt, t_min, t_max = _get_axis(info, caps, lt_key)
            lt = _norm_trigger(raw_lt, t_min, t_max)
        if rt_key:
            raw_rt, t_min, t_max = _get_axis(info, caps, rt_key)
            rt = _norm_trigger(raw_rt, t_min, t_max)

        # -- Buttons ------------------------------------------------------
        raw_btns = info.dwButtons
        out_btns = 0
        for bit_idx, xinput_name in button_map.items():
            if raw_btns & (1 << bit_idx):
                out_btns |= XINPUT_MASK.get(xinput_name, 0)

        # Digital triggers for Switch and PS4/PS5 fallbacks
        if ctype == "switch":
            if raw_btns & (1 << 6):  # ZL
                lt = 255
            if raw_btns & (1 << 7):  # ZR
                rt = 255
        elif ctype in ("ps4", "ps5"):
            if raw_btns & (1 << 6) and lt < 30:
                lt = 255
            if raw_btns & (1 << 7) and rt < 30:
                rt = 255

        # -- D-pad (POV hat) ----------------------------------------------
        if caps.wCaps & JOYCAPS_HASPOV:
            out_btns |= _pov_to_dpad(info.dwPOV)

        return PadState(lx=lx, ly=ly, rx=rx, ry=ry, lt=lt, rt=rt, buttons=out_btns)

    def device_name(self, dev_idx: int) -> str:
        """Return human-readable device name, or empty string on failure."""
        caps = self._get_caps(dev_idx)
        if caps:
            return caps.szPname.strip()
        return ""
