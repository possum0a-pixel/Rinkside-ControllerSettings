"""
RinkStick Sensitivity & Response Curve Engine
Provides mathematical models for anti-deadzones, early saturation, sensitivity multipliers,
and custom hockey skill-stick response curves.
"""

import math
from typing import Tuple
from config import StickSettings

def apply_stick_transformation(
    raw_x: int,
    raw_y: int,
    settings: StickSettings,
    physical_deadzone: float = 0.05
) -> Tuple[int, int, float, float]:
    """
    Transforms raw analog stick coordinates [-32768, 32767] using sensitivity settings.
    
    Returns:
        (out_x_int, out_y_int, norm_out_x, norm_out_y)
    """
    # 1. Normalize to float [-1.0, 1.0]
    nx = raw_x / 32767.0
    ny = raw_y / 32767.0
    
    # Clamp to unit circle / square bounds
    nx = max(-1.0, min(1.0, nx))
    ny = max(-1.0, min(1.0, ny))
    
    # 2. Convert to polar coordinates (magnitude r and angle theta)
    r = math.hypot(nx, ny)
    if r < 1e-5:
        return 0, 0, 0.0, 0.0
    
    theta = math.atan2(ny, nx)
    
    # 3. Check physical deadzone
    if r <= physical_deadzone:
        return 0, 0, 0.0, 0.0
        
    # 4. Normalize magnitude between physical deadzone and outer deadzone
    effective_outer = max(physical_deadzone + 0.05, min(1.0, settings.outer_deadzone))
    
    # Relative position between physical deadzone and outer saturation
    rel_r = (r - physical_deadzone) / (effective_outer - physical_deadzone)
    rel_r = max(0.0, min(1.0, rel_r))
    
    # 5. Apply Anti-Deadzone (boost starting floor)
    # This immediately gets past NHL Legacy's internal deadzone for instantaneous response
    anti_dz = max(0.0, min(0.40, settings.anti_deadzone))
    r_with_anti = anti_dz + (1.0 - anti_dz) * rel_r
    
    # 6. Apply Sensitivity Multiplier
    r_sens = r_with_anti * settings.sensitivity
    r_sens = min(1.0, r_sens)
    
    # 7. Apply Response Curve
    curve = settings.curve_type.lower()
    if curve == "snappy":
        # Power curve with exponent < 1.0 for rapid initial stick action
        exp = max(0.3, min(1.0, settings.curve_exponent))
        r_final = math.pow(r_sens, exp)
    elif curve == "exponential":
        # Precision near center, fast near rim
        exp = max(1.0, min(3.0, settings.curve_exponent if settings.curve_exponent > 1.0 else 1.8))
        r_final = math.pow(r_sens, exp)
    elif curve == "s_curve":
        # Smooth center, explosive mid-throw, smooth saturation
        # Sigmoid function centered at 0.5
        k = 6.0
        sig = 1.0 / (1.0 + math.exp(-k * (r_sens - 0.5)))
        sig_0 = 1.0 / (1.0 + math.exp(-k * (-0.5)))
        sig_1 = 1.0 / (1.0 + math.exp(-k * (0.5)))
        r_final = (sig - sig_0) / (sig_1 - sig_0)
    else: # "linear"
        r_final = r_sens

    r_final = max(0.0, min(1.0, r_final))
    
    # 8. Convert back to Cartesian coordinates
    out_nx = r_final * math.cos(theta)
    out_ny = r_final * math.sin(theta)
    
    out_nx = max(-1.0, min(1.0, out_nx))
    out_ny = max(-1.0, min(1.0, out_ny))
    
    out_x_int = int(round(out_nx * 32767.0))
    out_y_int = int(round(out_ny * 32767.0))
    
    out_x_int = max(-32767, min(32767, out_x_int))
    out_y_int = max(-32767, min(32767, out_y_int))
    
    return out_x_int, out_y_int, out_nx, out_ny
