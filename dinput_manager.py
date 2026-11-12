"""
RinkStick DirectInput / WinMM Controller Manager
Provides non-XInput controller support (PS4, PS5, Switch Pro, generic HID gamepads)
using Windows built-in winmm.dll + joyGetPosEx. No external dependencies required.

Axis / button layout is auto-detected by controller type, with dynamic axis discovery.
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

JOY_POVCENTERED = 0xFFFF
JOY_POVCENTERED_FULL = 0xFFFFFFFF

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

SWITCH_BUTTON_MAP = {
    0: "A",      # South button (B on Switch) → A
    1: "B",      # East button  (A on Switch) → B
    2: "X",      # West button  (Y on Switch) → X
    3: "Y",      # North button (X on Switch) → Y
    4: "LB",     # L
    5: "RB",     # R
    8: "BACK",   # Minus
    9: "START",  # Plus
    10: "L3",
    11: "R3",
}

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
        min_val = 0
        max_val = 65535

    span = max_val - min_val
    if span <= 0:
        return 0

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
        min_val = 0
        max_val = 65535
    span = max_val - min_val
    if span <= 0:
        return 0
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
    if angle <= 4500 or angle >= 31500:
        flags |= XINPUT_MASK["DPAD_UP"]
    if 4500 <= angle <= 13500:
        flags |= XINPUT_MASK["DPAD_RIGHT"]
    if 13500 <= angle <= 22500:
        flags |= XINPUT_MASK["DPAD_DOWN"]
    if 22500 <= angle <= 31500:
        flags |= XINPUT_MASK["DPAD_LEFT"]
    return flags

def _get_axis_val(info: JOYINFOEX, caps: JOYCAPSW, axis_key: Optional[str]) -> tuple:
    """Return (raw_value, min_val, max_val). Safe against uninitialized caps."""
    if not axis_key:
        return 32767, 0, 65535

    attr_pos = "dw" + axis_key.upper() + "pos"
    attr_min = "w" + axis_key.upper() + "min"
    attr_max = "w" + axis_key.upper() + "max"

    val = getattr(info, attr_pos, 32767)
    min_v = getattr(caps, attr_min, 0)
    max_v = getattr(caps, attr_max, 65535)

    if max_v <= min_v:
        min_v = 0
        max_v = 65535

    return val, min_v, max_v

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
        # Dynamic axis detection cache per device index: dev_idx -> (rs_x_key, rs_y_key)
        self._rs_axis_map: dict = {}

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

    def _resolve_rs_axes(self, dev_idx: int, info: JOYINFOEX, default_x: str, default_y: str) -> tuple:
        """
        Dynamically binds Right Stick X and Y to whichever physical axes sit near
        neutral center (15,000 to 50,000) on initial detection.
        Caches the result so it stays locked even when stick is pushed to 0.
        """
        if dev_idx in self._rs_axis_map:
            return self._rs_axis_map[dev_idx]

        candidates = ["z", "u", "r", "v"]
        live = []
        for c in candidates:
            val = getattr(info, "dw" + c.upper() + "pos", 0)
            # A real physical stick at rest sits near center (~32,767)
            if 15000 <= val <= 50000:
                live.append(c)

        rx_key = default_x
        ry_key = default_y

        if len(live) >= 2:
            rx_key = live[0]
            ry_key = live[1]
        elif len(live) == 1:
            rx_key = live[0]
            ry_key = "r" if rx_key != "r" else "v"

        self._rs_axis_map[dev_idx] = (rx_key, ry_key)
        print(f"[RinkStick/DInput] Device {dev_idx} bound Right Stick: X={rx_key.upper()}, Y={ry_key.upper()}")
        return rx_key, ry_key

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
            self._rs_axis_map.pop(dev_idx, None)
            return None

        info = JOYINFOEX()
        info.dwSize  = ctypes.sizeof(JOYINFOEX)
        info.dwFlags = JOY_RETURNALL
        ret = self._winmm.joyGetPosEx(dev_idx, ctypes.byref(info))
        if ret != JOYERR_NOERROR:
            self._rs_axis_map.pop(dev_idx, None)
            return None

        ctype = controller_type if controller_type in BUTTON_MAPS else "auto"
        button_map = BUTTON_MAPS.get(ctype, GENERIC_BUTTON_MAP)

        # -- Left Stick (standard across all controllers) -----------------
        raw_lx, lx_min, lx_max = _get_axis_val(info, caps, "x")
        raw_ly, ly_min, ly_max = _get_axis_val(info, caps, "y")
        lx = _norm_axis(raw_lx, lx_min, lx_max)
        ly = _norm_axis(raw_ly, ly_min, ly_max, invert=True)

        # -- Right Stick (dynamically bound to active physical axes) -------
        default_x = "u" if ctype == "switch" else "z"
        default_y = "r"
        rx_key, ry_key = self._resolve_rs_axes(dev_idx, info, default_x, default_y)

        raw_rx, rx_min, rx_max = _get_axis_val(info, caps, rx_key)
        raw_ry, ry_min, ry_max = _get_axis_val(info, caps, ry_key)
        rx = _norm_axis(raw_rx, rx_min, rx_max)
        ry = _norm_axis(raw_ry, ry_min, ry_max, invert=True)

        # -- Triggers -----------------------------------------------------
        raw_btns = info.dwButtons
        lt = rt = 0

        # PS4/PS5 analog triggers via U/V axes if present
        if ctype in ("ps4", "ps5"):
            raw_lt, t_min, t_max = _get_axis_val(info, caps, "u")
            raw_rt, tr_min, tr_max = _get_axis_val(info, caps, "v")
            if raw_lt > 1000:
                lt = _norm_trigger(raw_lt, t_min, t_max)
            if raw_rt > 1000:
                rt = _norm_trigger(raw_rt, tr_min, tr_max)

        # Digital triggers (Switch ZL=btn 6, ZR=btn 7; PS4 fallback L2=btn 6, R2=btn 7)
        if raw_btns & (1 << 6):
            lt = 255
        if raw_btns & (1 << 7):
            rt = 255

        # -- Buttons ------------------------------------------------------
        out_btns = 0
        for bit_idx, xinput_name in button_map.items():
            if raw_btns & (1 << bit_idx):
                out_btns |= XINPUT_MASK.get(xinput_name, 0)

        # -- D-pad (POV hat) ----------------------------------------------
        out_btns |= _pov_to_dpad(info.dwPOV)

        return PadState(lx=lx, ly=ly, rx=rx, ry=ry, lt=lt, rt=rt, buttons=out_btns)

    def device_name(self, dev_idx: int) -> str:
        """Return human-readable device name, or empty string on failure."""
        caps = self._get_caps(dev_idx)
        if caps:
            return caps.szPname.strip()
        return ""
