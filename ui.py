"""
RinkStick Graphical User Interface
Modern dark-themed desktop application with real-time stick radars,
anti-deadzone slop elimination, response curve tuning, and button remapping.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import math
from typing import Optional, Dict

from config import AppConfig, StickSettings, PRESETS, REMAP_PRESETS, BUTTON_NAMES, save_config
from controller_io import ControllerIO, XINPUT_BUTTON_MASKS
from game_detector import GameDetector

CONTROLLER_TYPE_OPTIONS = [
    ("Auto-Detect",      "auto"),
    ("Xbox / XInput",    "xinput"),
    ("PlayStation 4",    "ps4"),
    ("PlayStation 5",    "ps5"),
    ("Switch Pro",       "switch"),
    ("Generic / Other",  "generic"),
]
# Display label → config value
_CTYPE_LABEL_TO_VAL = {label: val for label, val in CONTROLLER_TYPE_OPTIONS}
_CTYPE_VAL_TO_LABEL = {val: label for label, val in CONTROLLER_TYPE_OPTIONS}

# Color Palette (Dark Ice / Cyber Hockey)
BG_MAIN       = "#0f172a"  # Slate 900
BG_CARD       = "#1e293b"  # Slate 800
BG_INPUT      = "#334155"  # Slate 700
ACCENT_CYAN   = "#38bdf8"  # Sky 400 (Ice Cyan)
ACCENT_BLUE   = "#0284c7"  # Sky 600
ACCENT_GREEN  = "#22c55e"  # Emerald 500
ACCENT_RED    = "#ef4444"  # Red 500
ACCENT_GOLD   = "#eab308"  # Yellow 500
TEXT_WHITE    = "#f8fafc"
TEXT_MUTED    = "#94a3b8"

class StickRadar(tk.Canvas):
    """Draws a circular analog stick radar with deadzones, raw, and boosted vectors."""
    def __init__(self, parent, title="Stick", size=150, **kwargs):
        super().__init__(parent, width=size, height=size, bg=BG_MAIN, highlightthickness=1, highlightbackground=BG_INPUT, **kwargs)
        self.size = size
        self.center = size / 2
        self.radius = (size / 2) - 14
        self.title = title
        
        # Current data
        self.raw_x = 0.0
        self.raw_y = 0.0
        self.boost_x = 0.0
        self.boost_y = 0.0
        self.anti_dz = 0.12
        self.outer_dz = 0.88
        
        self.redraw()

    def update_values(self, rx, ry, bx, by, anti_dz=0.12, outer_dz=0.88):
        self.raw_x = rx
        self.raw_y = ry
        self.boost_x = bx
        self.boost_y = by
        self.anti_dz = anti_dz
        self.outer_dz = outer_dz
        self.redraw()

    def redraw(self):
        self.delete("all")
        c = self.center
        r = self.radius
        
        # Outer boundary ring
        self.create_oval(c - r, c - r, c + r, c + r, outline="#475569", width=1)
        
        # Outer deadzone saturation ring
        r_out = r * self.outer_dz
        self.create_oval(c - r_out, c - r_out, c + r_out, c + r_out, outline="#334155", dash=(3, 3), width=1)
        
        # Anti-deadzone ring
        r_anti = r * self.anti_dz
        if r_anti > 2:
            self.create_oval(c - r_anti, c - r_anti, c + r_anti, c + r_anti, outline="#f59e0b", dash=(2, 2), width=1)
            
        # Crosshair axes
        self.create_line(c - r, c, c + r, c, fill="#1e293b", width=1)
        self.create_line(c, c - r, c, c + r, fill="#1e293b", width=1)
        
        # Title
        self.create_text(c, 10, text=self.title, fill=TEXT_MUTED, font=("Segoe UI", 9, "bold"))
        
        # Raw physical stick position (gray hollow dot)
        raw_px = c + (self.raw_x * r)
        raw_py = c - (self.raw_y * r)  # Y inverted in UI canvas
        self.create_oval(raw_px - 4, raw_py - 4, raw_px + 4, raw_py + 4, outline="#64748b", width=1)
        
        # Boosted/Transformed stick position (vibrant cyan solid dot + vector trace)
        boost_px = c + (self.boost_x * r)
        boost_py = c - (self.boost_y * r)
        
        if math.hypot(self.boost_x, self.boost_y) > 0.03:
            self.create_line(c, c, boost_px, boost_py, fill=ACCENT_CYAN, width=2)
            self.create_oval(boost_px - 5, boost_py - 5, boost_px + 5, boost_py + 5, fill=ACCENT_CYAN, outline=TEXT_WHITE, width=1)
        else:
            self.create_oval(c - 3, c - 3, c + 3, c + 3, fill="#475569", outline="")


class RinkStickUI:
    def __init__(self, root: tk.Tk, config: AppConfig, controller: ControllerIO):
        self.root = root
        self.config = config
        self.controller = controller
        self.detector = GameDetector()
        
        self.root.title("RinkStick Pro // NHL Legacy Controller Engine")
        self.root.geometry("980x680")
        self.root.minsize(920, 620)
        self.root.configure(bg=BG_MAIN)
        
        # UI variable bindings
        self.rs_sens_var = tk.DoubleVar(value=config.right_stick.sensitivity)
        self.rs_anti_var = tk.DoubleVar(value=config.right_stick.anti_deadzone * 100)
        self.rs_outer_var = tk.DoubleVar(value=config.right_stick.outer_deadzone * 100)
        self.rs_curve_var = tk.StringVar(value=config.right_stick.curve_type)
        
        self.ls_sens_var = tk.DoubleVar(value=config.left_stick.sensitivity)
        self.ls_anti_var = tk.DoubleVar(value=config.left_stick.anti_deadzone * 100)
        self.ls_outer_var = tk.DoubleVar(value=config.left_stick.outer_deadzone * 100)
        self.ls_curve_var = tk.StringVar(value=config.left_stick.curve_type)
        
        self.status_game_var = tk.StringVar(value="Searching for NHL Legacy...")
        self.status_vpad_var = tk.StringVar(value="HOOK: WAITING FOR GAME...")
        self.status_ctrl_var = tk.StringVar(value="Connecting...")
        
        # Controller type selector variable
        init_ctype_label = _CTYPE_VAL_TO_LABEL.get(config.controller_type, "Auto-Detect")
        self.controller_type_var = tk.StringVar(value=init_ctype_label)
        
        # Button remap UI widgets
        self.remap_vars: Dict[str, tk.StringVar] = {}
        self.remap_labels: Dict[str, tk.Label] = {}
        self.remap_dots: Dict[str, tk.Label] = {}
        
        self._build_styles()
        self._build_header()
        self._build_main_layout()
        self._build_status_bar()
        
        # Start periodic GUI updater (30 FPS)
        self._update_ui_loop()

    def _build_styles(self):
        style = ttk.Style()
        style.theme_use('default')
        style.configure(".", background=BG_MAIN, foreground=TEXT_WHITE, font=("Segoe UI", 9))
        style.configure("TNotebook", background=BG_MAIN, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG_CARD, foreground=TEXT_MUTED, padding=[18, 7], font=("Segoe UI", 9, "bold"))
        style.map("TNotebook.Tab", background=[("selected", BG_INPUT)], foreground=[("selected", TEXT_WHITE)])
        
        # Crisp black text on white/light background for Comboboxes
        style.configure("TCombobox", fieldbackground="#ffffff", background="#e2e8f0", foreground="#000000")
        style.map("TCombobox", fieldbackground=[("readonly", "#ffffff")], foreground=[("readonly", "#000000")])
        self.root.option_add("*TCombobox*Listbox.foreground", "#000000")
        self.root.option_add("*TCombobox*Listbox.background", "#ffffff")
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_BLUE)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

    def _build_header(self):
        header = tk.Frame(self.root, bg=BG_CARD, height=65, padx=20, pady=10)
        header.pack(fill=tk.X, side=tk.TOP)
        
        title_box = tk.Frame(header, bg=BG_CARD)
        title_box.pack(side=tk.LEFT)
        
        lbl_title = tk.Label(title_box, text="🏒 RINKSIDE // RINKSTICK PRO", font=("Segoe UI", 15, "bold"), fg=ACCENT_CYAN, bg=BG_CARD)
        lbl_title.pack(anchor="w")
        lbl_sub = tk.Label(title_box, text="Analog Stick Sensitivity Tuning & Controller Button Remapping", font=("Segoe UI", 8), fg=TEXT_MUTED, bg=BG_CARD)
        lbl_sub.pack(anchor="w")
        
        badges = tk.Frame(header, bg=BG_CARD)
        badges.pack(side=tk.RIGHT)
        
        # Game status badge
        self.lbl_game_badge = tk.Label(
            badges,
            textvariable=self.status_game_var,
            font=("Segoe UI", 8, "bold"),
            fg=TEXT_WHITE,
            bg="#374151",
            padx=10,
            pady=4
        )
        self.lbl_game_badge.pack(side=tk.RIGHT, padx=4)

        # In-game hook status badge
        self.lbl_vpad_badge = tk.Label(
            badges,
            textvariable=self.status_vpad_var,
            font=("Segoe UI", 8, "bold"),
            fg=TEXT_WHITE,
            bg="#374151",
            padx=10,
            pady=4
        )
        self.lbl_vpad_badge.pack(side=tk.RIGHT, padx=4)
        
        # Controller status badge
        self.lbl_ctrl_badge = tk.Label(
            badges,
            textvariable=self.status_ctrl_var,
            font=("Segoe UI", 8, "bold"),
            fg=TEXT_WHITE,
            bg="#374151",
            padx=10,
            pady=4
        )
        self.lbl_ctrl_badge.pack(side=tk.RIGHT, padx=4)

    def _build_main_layout(self):
        container = tk.Frame(self.root, bg=BG_MAIN, padx=16, pady=12)
        container.pack(fill=tk.BOTH, expand=True)
        
        # Left Side: Real-time Telemetry Radars & Preset Profiles
        left_box = tk.Frame(container, bg=BG_CARD, width=330, padx=14, pady=14)
        left_box.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 12))
        
        lbl_radar_sec = tk.Label(left_box, text="REAL-TIME STICK TELEMETRY", font=("Segoe UI", 10, "bold"), fg=TEXT_WHITE, bg=BG_CARD)
        lbl_radar_sec.pack(anchor="w", pady=(0, 10))
        
        # Radars row: Left Stick on left, Right Stick on right
        radars_frame = tk.Frame(left_box, bg=BG_CARD)
        radars_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.radar_ls = StickRadar(radars_frame, title="LEFT STICK (Skating)", size=142)
        self.radar_ls.pack(side=tk.LEFT, padx=3)
        
        self.radar_rs = StickRadar(radars_frame, title="RIGHT STICK (SkillStick)", size=142)
        self.radar_rs.pack(side=tk.RIGHT, padx=3)
        
        # Legend
        legend = tk.Frame(left_box, bg=BG_CARD)
        legend.pack(fill=tk.X, pady=(0, 16))
        tk.Label(legend, text="● Cyan = Boosted Output", fg=ACCENT_CYAN, bg=BG_CARD, font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=4)
        tk.Label(legend, text="○ Gray = Physical Input", fg=TEXT_MUTED, bg=BG_CARD, font=("Segoe UI", 8)).pack(side=tk.RIGHT, padx=4)
        
        # Presets selector
        lbl_presets = tk.Label(left_box, text="PRESET PROFILES", font=("Segoe UI", 10, "bold"), fg=TEXT_WHITE, bg=BG_CARD)
        lbl_presets.pack(anchor="w", pady=(5, 8))
        
        for name in PRESETS.keys():
            btn = tk.Button(
                left_box,
                text=name,
                command=lambda p=name: self._apply_preset(p),
                bg="#e2e8f0",
                fg="#000000",
                activebackground=ACCENT_BLUE,
                activeforeground="#ffffff",
                font=("Segoe UI", 9, "bold"),
                relief=tk.FLAT,
                anchor="w",
                padx=12,
                pady=6,
                cursor="hand2"
            )
            btn.pack(fill=tk.X, pady=3)

        # ---- Controller Type selector -----------------------------------
        tk.Frame(left_box, bg="#334155", height=1).pack(fill=tk.X, pady=(14, 10))

        lbl_ctype = tk.Label(left_box, text="CONTROLLER TYPE", font=("Segoe UI", 10, "bold"), fg=TEXT_WHITE, bg=BG_CARD)
        lbl_ctype.pack(anchor="w", pady=(0, 6))

        ctype_labels = [label for label, _ in CONTROLLER_TYPE_OPTIONS]
        cb_ctype = ttk.Combobox(
            left_box,
            values=ctype_labels,
            textvariable=self.controller_type_var,
            state="readonly",
            width=20
        )
        cb_ctype.pack(fill=tk.X, pady=(0, 4))
        cb_ctype.bind("<<ComboboxSelected>>",
                      lambda e, c=cb_ctype: self._on_controller_type_change(c))
        cb_ctype.bind("<FocusOut>", lambda e, c=cb_ctype: c.selection_clear())

        tk.Label(
            left_box,
            text="Choose your pad type for correct\nbutton & axis mapping.",
            font=("Segoe UI", 8),
            fg=TEXT_MUTED,
            bg=BG_CARD,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(0, 6))

        # Right Side: Notebook with Tabs
        right_box = tk.Frame(container, bg=BG_MAIN)
        right_box.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        nb = ttk.Notebook(right_box)
        nb.pack(fill=tk.BOTH, expand=True)
        
        # Tab 1: Left Stick (Skating / Movement / Pivots)
        tab_ls = tk.Frame(nb, bg=BG_CARD, padx=18, pady=14)
        nb.add(tab_ls, text="Left Stick (Skating)")
        self._build_stick_tab(tab_ls, "ls", "Skating stick controls stride direction, tight turns, and breakout agility.")

        # Tab 2: Right Stick (SkillStick / Shooting / Puckhandling)
        tab_rs = tk.Frame(nb, bg=BG_CARD, padx=18, pady=14)
        nb.add(tab_rs, text="Right Stick (SkillStick)")
        self._build_stick_tab(tab_rs, "rs", "SkillStick controls puckhandling angle, toe drags, and shot releases.")

        # Tab 3: Button Remapping
        tab_remap = tk.Frame(nb, bg=BG_CARD, padx=18, pady=14)
        nb.add(tab_remap, text="🎮 Button Remapping")
        self._build_remap_tab(tab_remap)

    def _build_stick_tab(self, parent: tk.Frame, stick_prefix: str, description: str):
        is_rs = (stick_prefix == "rs")
        sens_var = self.rs_sens_var if is_rs else self.ls_sens_var
        anti_var = self.rs_anti_var if is_rs else self.ls_anti_var
        outer_var = self.rs_outer_var if is_rs else self.ls_outer_var
        curve_var = self.rs_curve_var if is_rs else self.ls_curve_var
        
        desc_lbl = tk.Label(parent, text=description, font=("Segoe UI", 9), fg=TEXT_MUTED, bg=BG_CARD, anchor="w")
        desc_lbl.pack(fill=tk.X, pady=(0, 12))
        
        # Row 1: Sensitivity Multiplier
        r1 = tk.Frame(parent, bg=BG_CARD)
        r1.pack(fill=tk.X, pady=6)
        tk.Label(r1, text="Sensitivity Multiplier:", font=("Segoe UI", 9, "bold"), fg=TEXT_WHITE, bg=BG_CARD, width=24, anchor="w").pack(side=tk.LEFT)
        scale_sens = tk.Scale(r1, from_=1.0, to=3.0, resolution=0.05, orient=tk.HORIZONTAL, variable=sens_var, bg=BG_CARD, fg=TEXT_WHITE, highlightthickness=0, command=self._on_slider_change)
        scale_sens.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        
        # Row 2: Anti-Deadzone
        r2 = tk.Frame(parent, bg=BG_CARD)
        r2.pack(fill=tk.X, pady=6)
        tk.Label(r2, text="Anti-Deadzone:", font=("Segoe UI", 9, "bold"), fg=TEXT_WHITE, bg=BG_CARD, width=24, anchor="w").pack(side=tk.LEFT)
        scale_anti = tk.Scale(r2, from_=0, to=35, resolution=1, orient=tk.HORIZONTAL, variable=anti_var, bg=BG_CARD, fg=TEXT_WHITE, highlightthickness=0, command=self._on_slider_change)
        scale_anti.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        
        # Row 3: Early Saturation / Outer Deadzone
        r3 = tk.Frame(parent, bg=BG_CARD)
        r3.pack(fill=tk.X, pady=6)
        tk.Label(r3, text="Outer Deadzone:", font=("Segoe UI", 9, "bold"), fg=TEXT_WHITE, bg=BG_CARD, width=24, anchor="w").pack(side=tk.LEFT)
        scale_outer = tk.Scale(r3, from_=70, to=100, resolution=1, orient=tk.HORIZONTAL, variable=outer_var, bg=BG_CARD, fg=TEXT_WHITE, highlightthickness=0, command=self._on_slider_change)
        scale_outer.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        
        # Row 4: Curve Preset
        r4 = tk.Frame(parent, bg=BG_CARD)
        r4.pack(fill=tk.X, pady=6)
        tk.Label(r4, text="Response Curve Preset:", font=("Segoe UI", 9, "bold"), fg=TEXT_WHITE, bg=BG_CARD, width=24, anchor="w").pack(side=tk.LEFT)
        combo = ttk.Combobox(r4, values=["snappy", "linear", "exponential", "s_curve"], textvariable=curve_var, state="readonly", width=18)
        combo.pack(side=tk.LEFT, padx=8)
        combo.bind("<<ComboboxSelected>>", lambda e, c=combo: [self._on_slider_change(), c.selection_clear(), self.root.focus_set()])
        combo.bind("<FocusOut>", lambda e, c=combo: c.selection_clear())

        # Explanatory Info Card
        info_card = tk.Frame(parent, bg=BG_INPUT, padx=12, pady=10)
        info_card.pack(fill=tk.X, pady=(16, 0))
        
        curve_info = (
            "• Snappy: Aggressive center responsiveness; triggers instant deke twitches and quick snaps.\n"
            "• Linear: 1:1 direct analog output.\n"
            "• Exponential: High center precision with extreme acceleration at stick edges.\n"
            "• S-Curve: Smooth center control, rapid mid-range, and early saturation."
        )
        tk.Label(info_card, text=curve_info, font=("Segoe UI", 8), fg=TEXT_WHITE, bg=BG_INPUT, justify=tk.LEFT, anchor="w").pack(anchor="w")

    def _build_remap_tab(self, parent: tk.Frame):
        """Builds the comprehensive button & trigger remapping menu."""
        # Top header with title and a single clean Reset button
        top_bar = tk.Frame(parent, bg=BG_CARD)
        top_bar.pack(fill=tk.X, pady=(0, 12))

        title_desc = tk.Frame(top_bar, bg=BG_CARD)
        title_desc.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(title_desc, text="CONTROLLER BUTTON & TRIGGER REMAPPING", font=("Segoe UI", 10, "bold"), fg=ACCENT_CYAN, bg=BG_CARD).pack(anchor="w")
        tk.Label(title_desc, text="Remap any physical button or trigger using the dropdowns below.", font=("Segoe UI", 8), fg=TEXT_MUTED, bg=BG_CARD).pack(anchor="w")

        btn_reset = tk.Button(
            top_bar,
            text="↺ Reset (1:1)",
            command=lambda: [self._apply_remap_preset("Default (1:1)"), self.remap_preset_var.set("Default (1:1)")],
            bg="#e2e8f0",
            fg="#000000",
            activebackground=ACCENT_BLUE,
            activeforeground="#ffffff",
            font=("Segoe UI", 8, "bold"),
            relief=tk.FLAT,
            padx=10,
            pady=4,
            cursor="hand2"
        )
        btn_reset.pack(side=tk.RIGHT, padx=4)

        preset_box = tk.Frame(top_bar, bg=BG_CARD)
        preset_box.pack(side=tk.RIGHT, padx=4)
        tk.Label(preset_box, text="Preset:", font=("Segoe UI", 8, "bold"), fg=TEXT_MUTED, bg=BG_CARD).pack(side=tk.LEFT, padx=(0, 4))
        self.remap_preset_var = tk.StringVar(value="Default (1:1)")
        cb_preset = ttk.Combobox(preset_box, values=list(REMAP_PRESETS.keys()), textvariable=self.remap_preset_var, state="readonly", width=22)
        cb_preset.pack(side=tk.LEFT)
        cb_preset.bind("<<ComboboxSelected>>", lambda e: [self._apply_remap_preset(self.remap_preset_var.get()), cb_preset.selection_clear(), self.root.focus_set()])
        cb_preset.bind("<FocusOut>", lambda e: cb_preset.selection_clear())

        # Two columns for buttons (8 per column)
        columns_frame = tk.Frame(parent, bg=BG_CARD)
        columns_frame.pack(fill=tk.BOTH, expand=True)

        col_left = tk.Frame(columns_frame, bg=BG_CARD)
        col_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))

        col_right = tk.Frame(columns_frame, bg=BG_CARD)
        col_right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(8, 0))

        left_buttons = [
            ("LB", "Left Bumper (Pass / Poke Check)"),
            ("LT", "Left Trigger (Vision / Pivot)"),
            ("L3", "Left Stick Click (Hustle / Sprint)"),
            ("BACK", "Back / View (Timeout / Lines)"),
            ("DPAD_UP", "D-Pad Up (Line Change)"),
            ("DPAD_DOWN", "D-Pad Down (Def Pairing)"),
            ("DPAD_LEFT", "D-Pad Left (Strat Change)"),
            ("DPAD_RIGHT", "D-Pad Right (Strat Change)"),
        ]

        right_buttons = [
            ("RB", "Right Bumper (Stick Lift / Saucer)"),
            ("RT", "Right Trigger (Pass / Manual Shot)"),
            ("R3", "Right Stick Click (Shot Fake)"),
            ("START", "Start / Menu (Pause Game)"),
            ("A", "A Button (Pass / Protect Puck)"),
            ("B", "B Button (Body Check / Slap Shot)"),
            ("X", "X Button (Stick Lift / Dive)"),
            ("Y", "Y Button (Board Pin / Fight)"),
        ]

        target_options = BUTTON_NAMES + ["DISABLED"]

        for col_parent, btn_list in [(col_left, left_buttons), (col_right, right_buttons)]:
            for key, display_name in btn_list:
                row = tk.Frame(col_parent, bg="#e2e8f0", padx=8, pady=3)
                row.pack(fill=tk.X, pady=2)

                dot = tk.Label(
                    row,
                    text="●",
                    font=("Segoe UI", 9, "bold"),
                    fg="#cbd5e1",
                    bg="#e2e8f0",
                    width=2
                )
                dot.pack(side=tk.LEFT, padx=(0, 4))
                self.remap_dots[key] = dot

                lbl = tk.Label(
                    row,
                    text=f"{key}: {display_name}",
                    font=("Segoe UI", 8, "bold"),
                    fg="#000000",
                    bg="#e2e8f0",
                    anchor="w"
                )
                lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
                self.remap_labels[key] = lbl

                cur_val = self.config.button_mappings.get(key, key)
                var = tk.StringVar(value=cur_val)
                self.remap_vars[key] = var

                cb = ttk.Combobox(row, values=target_options, textvariable=var, state="readonly", width=11)
                cb.pack(side=tk.RIGHT)
                cb.bind("<<ComboboxSelected>>", lambda e, k=key, v=var, c=cb: self._on_remap_change(k, v, c))
                cb.bind("<FocusOut>", lambda e, c=cb: c.selection_clear())

    def _on_remap_change(self, key: str, var: tk.StringVar, cb: ttk.Combobox):
        new_val = var.get()
        self.config.button_mappings[key] = new_val
        save_config(self.config)
        cb.selection_clear()
        self.root.focus_set()

    def _apply_remap_preset(self, preset_name: str):
        if preset_name in REMAP_PRESETS:
            new_map = dict(REMAP_PRESETS[preset_name])
            self.config.button_mappings = new_map
            for k, v in new_map.items():
                if k in self.remap_vars:
                    self.remap_vars[k].set(v)
            save_config(self.config)

    def _build_status_bar(self):
        bar = tk.Frame(self.root, bg="#0b1120", height=28, padx=12, pady=4)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        
        self.lbl_status_footer = tk.Label(
            bar,
            text="Ready. Stick sensitivity & button remappings stream directly onto Player 1 in RAM. RinkSide account remains intact.",
            font=("Segoe UI", 8),
            fg=TEXT_MUTED,
            bg="#0b1120"
        )
        self.lbl_status_footer.pack(side=tk.LEFT)

    def _on_slider_change(self, *args):
        self.config.right_stick.sensitivity = self.rs_sens_var.get()
        self.config.right_stick.anti_deadzone = self.rs_anti_var.get() / 100.0
        self.config.right_stick.outer_deadzone = self.rs_outer_var.get() / 100.0
        self.config.right_stick.curve_type = self.rs_curve_var.get()
        
        self.config.left_stick.sensitivity = self.ls_sens_var.get()
        self.config.left_stick.anti_deadzone = self.ls_anti_var.get() / 100.0
        self.config.left_stick.outer_deadzone = self.ls_outer_var.get() / 100.0
        self.config.left_stick.curve_type = self.ls_curve_var.get()
        save_config(self.config)

    def _on_controller_type_change(self, cb):
        label = self.controller_type_var.get()
        val = _CTYPE_LABEL_TO_VAL.get(label, "auto")
        self.config.controller_type = val
        # Reset DirectInput device cache so the new type is re-scanned immediately
        if hasattr(self.controller, "_dinput_idx"):
            self.controller._dinput_idx = None
        save_config(self.config)
        cb.selection_clear()
        self.root.focus_set()

    def _apply_preset(self, preset_name: str):
        if preset_name not in PRESETS:
            return
        p = PRESETS[preset_name]
        
        # Update Right Stick
        rs = p["right_stick"]
        self.rs_sens_var.set(rs["sensitivity"])
        self.rs_anti_var.set(rs["anti_deadzone"] * 100)
        self.rs_outer_var.set(rs["outer_deadzone"] * 100)
        self.rs_curve_var.set(rs["curve_type"])
        
        # Update Left Stick
        ls = p["left_stick"]
        self.ls_sens_var.set(ls["sensitivity"])
        self.ls_anti_var.set(ls["anti_deadzone"] * 100)
        self.ls_outer_var.set(ls["outer_deadzone"] * 100)
        self.ls_curve_var.set(ls["curve_type"])
        
        self.config.active_profile = preset_name
        self._on_slider_change()

    def _update_ui_loop(self):
        # Update Radars (Left Stick, then Right Stick)
        self.radar_ls.update_values(
            self.controller.norm_raw_lx,
            self.controller.norm_raw_ly,
            self.controller.norm_out_lx,
            self.controller.norm_out_ly,
            self.config.left_stick.anti_deadzone,
            self.config.left_stick.outer_deadzone
        )
        self.radar_rs.update_values(
            self.controller.norm_raw_rx,
            self.controller.norm_raw_ry,
            self.controller.norm_out_rx,
            self.controller.norm_out_ry,
            self.config.right_stick.anti_deadzone,
            self.config.right_stick.outer_deadzone
        )
        
        # Live visual indicator for pressed buttons in Remap tab
        if hasattr(self, "remap_dots"):
            raw_btns = self.controller.raw_buttons
            raw_lt = self.controller.raw_lt
            raw_rt = self.controller.raw_rt

            for key, dot in self.remap_dots.items():
                is_active = False
                if key == "LT":
                    is_active = (raw_lt > 30)
                elif key == "RT":
                    is_active = (raw_rt > 30)
                else:
                    mask = XINPUT_BUTTON_MASKS.get(key, 0)
                    is_active = bool(raw_btns & mask)
                
                if is_active:
                    dot.configure(fg=ACCENT_GREEN)
                else:
                    dot.configure(fg="#cbd5e1")

        # Update Controller Badge
        if self.controller.connected:
            backend = getattr(self.controller, "controller_backend", "")
            idx = self.controller.controller_index
            if backend == "dinput":
                # Show WinMM device index (subtract offset) and type
                dinput_idx = idx - 10
                ctype_label = _CTYPE_VAL_TO_LABEL.get(self.config.controller_type, "DirectInput")
                self.status_ctrl_var.set(f"PAD: CONNECTED ({ctype_label}, Dev {dinput_idx})")
            else:
                self.status_ctrl_var.set(f"PAD: CONNECTED (Port {idx})")
            self.lbl_ctrl_badge.configure(bg=ACCENT_GREEN)
        else:
            self.status_ctrl_var.set("PAD: DISCONNECTED")
            self.lbl_ctrl_badge.configure(bg="#64748b")
            
        # Hook / Input path badge
        if getattr(self.controller, "hook_active", False):
            self.status_vpad_var.set("HOOK: PLAYER 1 (input0)")
            self.lbl_vpad_badge.configure(bg=ACCENT_GREEN)
        elif self.controller.vpad_active:
            self.status_vpad_var.set("VPAD: input0 (ACCOUNT RISK)")
            self.lbl_vpad_badge.configure(bg=ACCENT_RED)
        else:
            msg = getattr(self.controller.hook, "status_message", "HOOK: WAITING FOR GAME...")
            self.status_vpad_var.set(msg[:64])
            self.lbl_vpad_badge.configure(bg="#374151")

        # Periodic game detection check (every 30 ticks ~ 1 sec)
        if not hasattr(self, "_tick_count"):
            self._tick_count = 0
        self._tick_count += 1
        
        if self._tick_count % 30 == 0:
            is_running, name, _ = self.detector.find_game_process()
            if is_running:
                self.status_game_var.set(f"GAME: {name}")
                self.lbl_game_badge.configure(bg=ACCENT_GREEN)
            else:
                self.status_game_var.set("GAME: NOT RUNNING")
                self.lbl_game_badge.configure(bg="#64748b")

        # Schedule next frame in 33ms (~30 FPS)
        self.root.after(33, self._update_ui_loop)
