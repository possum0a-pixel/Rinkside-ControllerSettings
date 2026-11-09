"""
RinkStick Pro - Main Application Entry Point
Starts controller polling, launches GUI or CLI mode, and manages clean shutdown.
"""

import sys
import os
import argparse
import tkinter as tk

from config import load_config, save_config
from controller_io import ControllerIO
from ui import RinkStickUI

def parse_args():
    parser = argparse.ArgumentParser(description="RinkStick Pro - NHL Legacy Stick Sensitivity Engine")
    parser.add_argument("--cli", action="store_true", help="Run in headless background CLI mode without GUI")
    parser.add_argument("--profile", type=str, default=None, help="Name of preset profile to activate")
    return parser.parse_args()

def main():
    args = parse_args()
    config = load_config()
    
    if args.profile:
        from config import PRESETS
        if args.profile in PRESETS:
            p = PRESETS[args.profile]
            from config import StickSettings
            config.right_stick = StickSettings(**p["right_stick"])
            config.left_stick = StickSettings(**p["left_stick"])
            config.active_profile = args.profile
            save_config(config)
            print(f"[RinkStick] Activated profile: {args.profile}")

    controller = ControllerIO(config)
    controller.start()
    print("[RinkStick] Controller sensitivity engine started (150Hz polling).")

    if args.cli:
        print("[RinkStick] Running in CLI headless mode. Press Ctrl+C to exit.")
        try:
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[RinkStick] Shutting down...")
            controller.stop()
        return

    # Normal GUI Mode
    root = tk.Tk()
    app = RinkStickUI(root, config, controller)
    
    def on_closing():
        print("[RinkStick] Closing application...")
        save_config(config)
        controller.stop()
        root.destroy()
        
    root.protocol("WM_DELETE_WINDOW", on_closing)
    
    try:
        root.mainloop()
    except KeyboardInterrupt:
        on_closing()

if __name__ == "__main__":
    main()
