"""
RinkStick Controller I/O Engine
Captures physical controller inputs, applies sensitivity curves and button remapping,
and streams them into NHL Legacy via in-process memory hook.
Physical controller stays input0 so RinkSide registers the signed-in account.
"""

import ctypes
import os
import threading
import time
from ctypes import wintypes
from typing import Optional, Any, Dict, Tuple

from config import AppConfig, BUTTON_NAMES
from sensitivity import apply_stick_transformation
from game_hook import GameInputBridge
from dinput_manager import DirectInputPad

try:
    import vgamepad as vg
    HAS_VGAMEPAD = True
except Exception as e:
    HAS_VGAMEPAD = False
    vg = None

# Opt-in only. Creating a virtual pad as input0 breaks RinkSide account attach.
USE_VIGEM = os.environ.get("RINKSTICK_USE_VIGEM", "").strip() in ("1", "true", "yes")

# XInput Structures
class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ('wButtons', wintypes.WORD),
        ('bLeftTrigger', ctypes.c_ubyte),
        ('bRightTrigger', ctypes.c_ubyte),
        ('sThumbLX', ctypes.c_short),
        ('sThumbLY', ctypes.c_short),
        ('sThumbRX', ctypes.c_short),
        ('sThumbRY', ctypes.c_short),
    ]

class XINPUT_STATE(ctypes.Structure):
    _fields_ = [
        ('dwPacketNumber', wintypes.DWORD),
        ('Gamepad', XINPUT_GAMEPAD)
    ]

XINPUT_BUTTON_MASKS: Dict[str, int] = {
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

V_BUTTON_MAP = {
    0x0001: getattr(vg.XUSB_BUTTON, 'XUSB_GAMEPAD_DPAD_UP', 0x0001) if HAS_VGAMEPAD else 0x0001,
    0x0002: getattr(vg.XUSB_BUTTON, 'XUSB_GAMEPAD_DPAD_DOWN', 0x0002) if HAS_VGAMEPAD else 0x0002,
    0x0004: getattr(vg.XUSB_BUTTON, 'XUSB_GAMEPAD_DPAD_LEFT', 0x0004) if HAS_VGAMEPAD else 0x0004,
    0x0008: getattr(vg.XUSB_BUTTON, 'XUSB_GAMEPAD_DPAD_RIGHT', 0x0008) if HAS_VGAMEPAD else 0x0008,
    0x0010: getattr(vg.XUSB_BUTTON, 'XUSB_GAMEPAD_START', 0x0010) if HAS_VGAMEPAD else 0x0010,
    0x0020: getattr(vg.XUSB_BUTTON, 'XUSB_GAMEPAD_BACK', 0x0020) if HAS_VGAMEPAD else 0x0020,
    0x0040: getattr(vg.XUSB_BUTTON, 'XUSB_GAMEPAD_LEFT_THUMB', 0x0040) if HAS_VGAMEPAD else 0x0040,
    0x0080: getattr(vg.XUSB_BUTTON, 'XUSB_GAMEPAD_RIGHT_THUMB', 0x0080) if HAS_VGAMEPAD else 0x0080,
    0x0100: getattr(vg.XUSB_BUTTON, 'XUSB_GAMEPAD_LEFT_SHOULDER', 0x0100) if HAS_VGAMEPAD else 0x0100,
    0x0200: getattr(vg.XUSB_BUTTON, 'XUSB_GAMEPAD_RIGHT_SHOULDER', 0x0200) if HAS_VGAMEPAD else 0x0200,
    0x1000: getattr(vg.XUSB_BUTTON, 'XUSB_GAMEPAD_A', 0x1000) if HAS_VGAMEPAD else 0x1000,
    0x2000: getattr(vg.XUSB_BUTTON, 'XUSB_GAMEPAD_B', 0x2000) if HAS_VGAMEPAD else 0x2000,
    0x4000: getattr(vg.XUSB_BUTTON, 'XUSB_GAMEPAD_X', 0x4000) if HAS_VGAMEPAD else 0x4000,
    0x8000: getattr(vg.XUSB_BUTTON, 'XUSB_GAMEPAD_Y', 0x8000) if HAS_VGAMEPAD else 0x8000,
}

def apply_button_remapping(
    raw_buttons: int,
    raw_lt: int,
    raw_rt: int,
    mappings: Dict[str, str]
) -> Tuple[int, int, int]:
    """
    Translates raw physical button/trigger states to remapped output states.
    Supports digital buttons, analog triggers, and cross-mapping (e.g. Bumper <-> Trigger).
    """
    out_buttons = 0
    out_lt = 0
    out_rt = 0

    for phys_input, target_output in mappings.items():
        if target_output in ("NONE", "DISABLED"):
            continue

        is_pressed = False
        val = 0

        if phys_input == "LT":
            if raw_lt > 30:
                is_pressed = True
                val = raw_lt
        elif phys_input == "RT":
            if raw_rt > 30:
                is_pressed = True
                val = raw_rt
        else:
            mask = XINPUT_BUTTON_MASKS.get(phys_input, 0)
            if raw_buttons & mask:
                is_pressed = True
                val = 255

        if not is_pressed:
            continue

        if target_output == "LT":
            out_lt = max(out_lt, val)
        elif target_output == "RT":
            out_rt = max(out_rt, val)
        elif target_output in XINPUT_BUTTON_MASKS:
            out_buttons |= XINPUT_BUTTON_MASKS[target_output]

    return out_buttons, out_lt, out_rt


class ControllerIO:
    def __init__(self, config: AppConfig):
        self.config = config
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # Connection status
        self.connected = False
        self.controller_index = 0
        self.controller_backend: str = ""   # "xinput" | "dinput" | ""
        self.vpad_active = False
        self.vpad: Optional[Any] = None
        self.hook = GameInputBridge()
        self.hook_active = False
        
        # Raw physical controller state
        self.raw_lx: int = 0
        self.raw_ly: int = 0
        self.raw_rx: int = 0
        self.raw_ry: int = 0
        self.raw_buttons: int = 0
        self.raw_lt: int = 0
        self.raw_rt: int = 0
        
        # Boosted/Transformed state
        self.out_lx: int = 0
        self.out_ly: int = 0
        self.out_rx: int = 0
        self.out_ry: int = 0
        self.out_buttons: int = 0
        self.out_lt: int = 0
        self.out_rt: int = 0
        
        # Normalized values [-1.0, 1.0] for GUI visualizers
        self.norm_raw_lx: float = 0.0
        self.norm_raw_ly: float = 0.0
        self.norm_raw_rx: float = 0.0
        self.norm_raw_ry: float = 0.0
        
        self.norm_out_lx: float = 0.0
        self.norm_out_ly: float = 0.0
        self.norm_out_rx: float = 0.0
        self.norm_out_ry: float = 0.0
        
        if USE_VIGEM:
            print("[RinkStick] RINKSTICK_USE_VIGEM=1: virtual pad enabled.")
            self._init_virtual_gamepad()
        else:
            print("[RinkStick] Virtual pad disabled. Physical controller stays input0 "
                  "so RinkSide registers the signed-in account.")

        # Initialize COM and XInput DLL
        ctypes.windll.ole32.CoInitialize(None)
        self.xinput = None
        for dll_name in ['xinput1_4.dll', 'xinput1_3.dll']:
            try:
                self.xinput = ctypes.WinDLL(dll_name)
                self.xinput.XInputGetState.argtypes = [wintypes.DWORD, ctypes.POINTER(XINPUT_STATE)]
                self.xinput.XInputGetState.restype = wintypes.DWORD
                break
            except Exception:
                continue

        # DirectInput fallback for non-XInput controllers
        self.dinput = DirectInputPad()
        self._dinput_idx: Optional[int] = None

    def _init_virtual_gamepad(self):
        """Creates the virtual Xbox 360 controller via ViGEmBus (opt-in only)."""
        if not HAS_VGAMEPAD:
            self.vpad_active = False
            return
        try:
            self.vpad = vg.VX360Gamepad()
            self.vpad_active = True
            print("[RinkStick] Virtual Xbox 360 Gamepad created via ViGEmBus.")
        except Exception as e:
            self.vpad_active = False
            self.vpad = None
            print(f"[RinkStick] Virtual gamepad creation failed: {e}")

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self.vpad:
            try:
                self.vpad.reset()
                self.vpad.update()
                del self.vpad
            except Exception:
                pass
            self.vpad = None
            self.vpad_active = False
        try:
            self.hook.detach()
        except Exception:
            pass
        self.hook_active = False

    def _loop(self):
        """High-frequency polling & transformation loop (150Hz = 6.6ms interval)."""
        # COM must be initialized on this specific background thread for xinput1_4.dll
        try:
            ctypes.windll.ole32.CoInitialize(None)
        except Exception:
            pass

        xstate = XINPUT_STATE()
        # DirectInput scan counter — only rescan every ~150 frames (~1 second)
        _dinput_scan_countdown = 0
        
        while self._running:
            t0 = time.perf_counter()

            # 1. Game hook attach / lifecycle (independent of physical controller polling)
            try:
                now = time.perf_counter()
                self.hook.try_attach(now)
                self.hook_active = self.hook.hooked
            except Exception:
                self.hook_active = False

            # 2. Poll physical controller
            found_controller = False
            raw_lx = raw_ly = raw_rx = raw_ry = buttons = lt = rt = 0

            # -- XInput path (Xbox / XInput-compatible pads) --
            try:
                if self.xinput and self.config.controller_type in ("auto", "xinput"):
                    occupied = []
                    for idx in range(4):
                        res = self.xinput.XInputGetState(idx, ctypes.byref(xstate))
                        if res == 0:
                            occupied.append(idx)
                    if occupied:
                        pick = occupied[-1] if len(occupied) > 1 else occupied[0]
                        if self.xinput.XInputGetState(pick, ctypes.byref(xstate)) == 0:
                            self.controller_index = pick
                            self.controller_backend = "xinput"
                            found_controller = True
                            gp = xstate.Gamepad
                            raw_lx = gp.sThumbLX
                            raw_ly = gp.sThumbLY
                            raw_rx = gp.sThumbRX
                            raw_ry = gp.sThumbRY
                            buttons = gp.wButtons
                            lt = gp.bLeftTrigger
                            rt = gp.bRightTrigger
            except Exception:
                pass

            # -- DirectInput fallback (PS4/PS5/Switch/generic) --
            # Activated when: XInput found nothing, OR user forced a non-xinput type
            if not found_controller and self.config.controller_type != "xinput":
                try:
                    _dinput_scan_countdown -= 1
                    # Rescan for device periodically, or if we lost one
                    if _dinput_scan_countdown <= 0 or self._dinput_idx is None:
                        self._dinput_idx = self.dinput.scan(self.config.controller_type)
                        _dinput_scan_countdown = 150  # rescan every ~1 s

                    if self._dinput_idx is not None:
                        state = self.dinput.poll(self._dinput_idx, self.config.controller_type)
                        if state is not None:
                            raw_lx   = state.lx
                            raw_ly   = state.ly
                            raw_rx   = state.rx
                            raw_ry   = state.ry
                            buttons  = state.buttons
                            lt       = state.lt
                            rt       = state.rt
                            # Use index 10+ to distinguish from XInput slots 0-3
                            self.controller_index = 10 + self._dinput_idx
                            self.controller_backend = "dinput"
                            found_controller = True
                        else:
                            # Device vanished — force rescan next tick
                            self._dinput_idx = None
                            _dinput_scan_countdown = 0
                except Exception:
                    pass

            self.connected = found_controller

            # Store raw states
            self.raw_lx = raw_lx
            self.raw_ly = raw_ly
            self.raw_rx = raw_rx
            self.raw_ry = raw_ry
            self.raw_buttons = buttons
            self.raw_lt = lt
            self.raw_rt = rt
            
            self.norm_raw_lx = raw_lx / 32767.0
            self.norm_raw_ly = raw_ly / 32767.0
            self.norm_raw_rx = raw_rx / 32767.0
            self.norm_raw_ry = raw_ry / 32767.0

            # 3. Apply sensitivity transformations & button remappings
            try:
                with self._lock:
                    out_lx, out_ly, n_lx, n_ly = apply_stick_transformation(raw_lx, raw_ly, self.config.left_stick)
                    out_rx, out_ry, n_rx, n_ry = apply_stick_transformation(raw_rx, raw_ry, self.config.right_stick)
                    out_buttons, out_lt, out_rt = apply_button_remapping(buttons, lt, rt, self.config.button_mappings)
            except Exception:
                out_lx, out_ly, n_lx, n_ly = raw_lx, raw_ly, self.norm_raw_lx, self.norm_raw_ly
                out_rx, out_ry, n_rx, n_ry = raw_rx, raw_ry, self.norm_raw_rx, self.norm_raw_ry
                out_buttons, out_lt, out_rt = buttons, lt, rt

            self.out_lx = out_lx
            self.out_ly = out_ly
            self.out_rx = out_rx
            self.out_ry = out_ry
            self.out_buttons = out_buttons
            self.out_lt = out_lt
            self.out_rt = out_rt
            
            self.norm_out_lx = n_lx
            self.norm_out_ly = n_ly
            self.norm_out_rx = n_rx
            self.norm_out_ry = n_ry

            # 4. Stream to in-game hook
            try:
                self.hook.push_pad_state(out_lx, out_ly, out_rx, out_ry, out_buttons, out_lt, out_rt)
            except Exception:
                pass

            # 5. Optional ViGEm path (disabled by default)
            if self.vpad and self.vpad_active:
                try:
                    self.vpad.left_joystick_float(x_value_float=n_lx, y_value_float=n_ly)
                    self.vpad.right_joystick_float(x_value_float=n_rx, y_value_float=n_ry)
                    self.vpad.left_trigger_float(value_float=out_lt / 255.0)
                    self.vpad.right_trigger_float(value_float=out_rt / 255.0)
                    for bit_mask, v_btn in V_BUTTON_MAP.items():
                        if out_buttons & bit_mask:
                            self.vpad.press_button(button=v_btn)
                        else:
                            self.vpad.release_button(button=v_btn)
                    self.vpad.update()
                except Exception:
                    pass

            # Sleep to maintain ~150Hz
            elapsed = time.perf_counter() - t0
            sleep_time = 0.0065 - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        try:
            ctypes.windll.ole32.CoUninitialize()
        except Exception:
            pass
