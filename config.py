"""
RinkStick Configuration Module
Handles user preferences, sensitivity curves, deadzones, button remapping, and profile persistence.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Dict, Any

BUTTON_NAMES = [
    "A", "B", "X", "Y",
    "LB", "RB", "LT", "RT",
    "L3", "R3", "BACK", "START",
    "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT"
]

REMAP_PRESETS = {
    "Default (1:1)": {b: b for b in BUTTON_NAMES},
    "Flipped Bumpers & Triggers (LB/LT & RB/RT)": {
        **{b: b for b in BUTTON_NAMES},
        "LB": "LT", "LT": "LB",
        "RB": "RT", "RT": "RB",
    },
    "Swap Stick Clicks (L3 <-> R3)": {
        **{b: b for b in BUTTON_NAMES},
        "L3": "R3", "R3": "L3",
    },
    "Invert Face Buttons (A<->B, X<->Y)": {
        **{b: b for b in BUTTON_NAMES},
        "A": "B", "B": "A",
        "X": "Y", "Y": "X",
    },
}

@dataclass
class StickSettings:
    sensitivity: float = 1.45       # Sensitivity multiplier (1.0 = normal, 1.5 = 50% faster)
    anti_deadzone: float = 0.12     # Eliminates inner deadzone slop (0.0 to 0.35)
    outer_deadzone: float = 0.88    # Reaches 100% deflection earlier (0.70 to 1.0)
    curve_type: str = "snappy"      # linear, snappy, exponential, s_curve
    curve_exponent: float = 0.68    # Exponent for power curves (< 1.0 = aggressive near center)

@dataclass
class AppConfig:
    left_stick: StickSettings = field(default_factory=lambda: StickSettings(
        sensitivity=1.25,
        anti_deadzone=0.10,
        outer_deadzone=0.92,
        curve_type="linear",
        curve_exponent=1.0
    ))
    right_stick: StickSettings = field(default_factory=lambda: StickSettings(
        sensitivity=1.55,
        anti_deadzone=0.15,
        outer_deadzone=0.85,
        curve_type="snappy",
        curve_exponent=0.65
    ))
    button_mappings: Dict[str, str] = field(default_factory=lambda: {b: b for b in BUTTON_NAMES})
    overlay_enabled: bool = True
    active_profile: str = "Competitive Deker"
    controller_type: str = "auto"  # "auto", "xinput", "ps4", "ps5", "switch", "generic"
    mute_player2: bool = False
    rumble_intensity: int = 100  # 0 to 100% (haptic feedback strength)

PRESETS = {
    "Competitive Deker": {
        "left_stick": {"sensitivity": 1.25, "anti_deadzone": 0.10, "outer_deadzone": 0.90, "curve_type": "linear", "curve_exponent": 1.0},
        "right_stick": {"sensitivity": 1.65, "anti_deadzone": 0.18, "outer_deadzone": 0.82, "curve_type": "snappy", "curve_exponent": 0.60},
    },
    "Sniper Snap (Quick Release)": {
        "left_stick": {"sensitivity": 1.20, "anti_deadzone": 0.08, "outer_deadzone": 0.92, "curve_type": "linear", "curve_exponent": 1.0},
        "right_stick": {"sensitivity": 1.85, "anti_deadzone": 0.22, "outer_deadzone": 0.78, "curve_type": "snappy", "curve_exponent": 0.55},
    },
    "High Agility Skating": {
        "left_stick": {"sensitivity": 1.60, "anti_deadzone": 0.15, "outer_deadzone": 0.85, "curve_type": "s_curve", "curve_exponent": 0.75},
        "right_stick": {"sensitivity": 1.40, "anti_deadzone": 0.12, "outer_deadzone": 0.88, "curve_type": "linear", "curve_exponent": 1.0},
    },
    "Vanilla / Default (1:1 Raw)": {
        "left_stick": {"sensitivity": 1.0, "anti_deadzone": 0.0, "outer_deadzone": 1.0, "curve_type": "linear", "curve_exponent": 1.0},
        "right_stick": {"sensitivity": 1.0, "anti_deadzone": 0.0, "outer_deadzone": 1.0, "curve_type": "linear", "curve_exponent": 1.0},
    }
}

CONFIG_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rinkstick_config.json")

def load_config() -> AppConfig:
    """Loads configuration from file or returns default."""
    if not os.path.exists(CONFIG_FILE_PATH):
        cfg = AppConfig()
        save_config(cfg)
        return cfg
    try:
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        cfg = AppConfig()
        if "left_stick" in data:
            cfg.left_stick = StickSettings(**data["left_stick"])
        if "right_stick" in data:
            cfg.right_stick = StickSettings(**data["right_stick"])
        if "button_mappings" in data:
            # Merge with defaults to ensure all buttons are present
            base = {b: b for b in BUTTON_NAMES}
            base.update(data["button_mappings"])
            cfg.button_mappings = base
        cfg.overlay_enabled = data.get("overlay_enabled", True)
        cfg.active_profile = data.get("active_profile", "Competitive Deker")
        cfg.controller_type = data.get("controller_type", "auto")
        cfg.mute_player2 = data.get("mute_player2", False)
        cfg.rumble_intensity = int(data.get("rumble_intensity", 100))
        return cfg
    except Exception as e:
        print(f"[RinkStick] Error loading config: {e}. Using defaults.")
        return AppConfig()

def save_config(config: AppConfig):
    """Saves configuration to JSON file."""
    try:
        data = {
            "left_stick": asdict(config.left_stick),
            "right_stick": asdict(config.right_stick),
            "button_mappings": config.button_mappings,
            "overlay_enabled": config.overlay_enabled,
            "active_profile": config.active_profile,
            "controller_type": config.controller_type,
            "mute_player2": config.mute_player2,
            "rumble_intensity": config.rumble_intensity,
        }
        with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"[RinkStick] Error saving config: {e}")
