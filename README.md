
### Advanced Stick Sensitivity & Button Remapping Engine for RinkSide (NHL Legacy PC)

**RinkStick Pro** is a dedicated third-party input companion designed specifically for **RinkSide's native PC port of NHL Legacy (Xbox 360)**. It gives you complete mastery over your controller's analog stick sensitivity, anti-deadzones, early saturation, response curves, and full controller button/trigger remapping without modifying game files on disk or interfering with your RinkSide account.

---



### 1. Right Stick (SkillStick / Shooting / Puckhandling) Tuning
- **Sensitivity Multiplier (1.0x – 3.0x)**: Drastically increases stick deflection speed so you reach maximum toe-drag angle, puck extension, and quick-release snapshots with a fraction of physical stick travel.
- **Anti-Deadzone (Slop Eliminator)**: Bypasses the game's internal deadzone floor (0%–35%). Subtle thumb movements immediately translate into on-ice puck movement.
- **Outer Deadzone / Early Saturation (70%–100%)**: Triggers 100% stick output before the physical stick hits the outer rim, preventing thumb fatigue and missed shot releases.
- **Custom Response Curves**:
  - **Snappy Flick (Recommended)**: Aggressive sub-linear power curve for instant puck twitches and lightning wrist shots.
  - **Linear (1:1)**: Standard direct response.
  - **Exponential**: Fine-precision center control with explosive outer deflection.
  - **S-Curve**: Smooth center glide, fast mid-range action, clean saturation.

### 2. Left Stick (Skating & Movement) Tuning
- Independent sensitivity multiplier, anti-deadzone, and response curves for tighter edge-work, quicker pivots, and agile breakout skating.

### 3. Controller Button & Trigger Remapping
- **Full 16-Input Remapper**: Remap any physical button or analog trigger to an alternative in-game output:
  - Face buttons (`A`, `B`, `X`, `Y`)
  - Bumpers & Triggers (`LB`, `RB`, `LT`, `RT`)
  - Stick Clicks (`L3`, `R3`)
  - Menu & Directional (`BACK`, `START`, `D-PAD`)
- **Cross-Type Mapping**: Supports swapping analog triggers with digital bumpers (e.g. `LB <-> LT`, `RB <-> RT`), allowing you to shoot and pass on bumpers with zero trigger travel latency.
- **Quick Presets**:
  - `Default (1:1)`: Restores standard controller layout.
  - `Flipped Bumpers & Triggers (LB/LT & RB/RT)`: Popular competitive hockey layout.
  - `Swap Stick Clicks (L3 <-> R3)`: Swaps hustle sprint and shot fake click.
  - `Invert Face Buttons (A<->B, X<->Y)`: Inverts face buttons.
- **Live Input Tester**: Buttons light up vibrant cyan in real-time as you press them on your controller.

### 4. Direct In-Memory Input Injection (Keeps Your RinkSide Account on Player 1)
- **Direct Engine Injection**: When `nhllegacy.exe` runs, RinkStick attaches to the running process and writes transformed stick and remapped button values directly into ReXGlue's `SDLInputDriver::GetState` for the existing pad in RAM.
- **No Virtual Device Conflicts**: Your physical controller stays on **input0** (Player 1) so RinkSide can register your signed-in account.
- **Zero Game File Tampering**: Files on disk (`nhllegacy.exe`, `rexruntime.dll`) remain completely untouched and SHA-256 hash verified for online matchmaking.


