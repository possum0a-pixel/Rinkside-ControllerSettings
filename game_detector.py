"""
RinkStick Game Process & Window Monitor
Detects RinkSide launcher and NHL Legacy runtime processes.
"""

import ctypes
from ctypes import wintypes
from typing import Optional, Tuple

class GameDetector:
    def __init__(self):
        self.user32 = ctypes.WinDLL('user32')
        self.kernel32 = ctypes.WinDLL('kernel32')
        
    def find_game_process(self) -> Tuple[bool, str, Optional[int]]:
        """
        Scans top-level windows to locate NHL Legacy or RinkSide.
        Returns: (is_running, name, hwnd)
        """
        found = [False, "", None]
        
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        
        def enum_windows_callback(hwnd, lparam):
            if not self.user32.IsWindowVisible(hwnd):
                return True
            length = self.user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            self.user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            
            # Check window titles
            if "NHL Legacy" in title or "nhllegacy" in title.lower():
                found[0] = True
                found[1] = "NHL Legacy (Active Game)"
                found[2] = hwnd
                return False # Stop enumerating
            elif "RinkSide" in title:
                found[0] = True
                found[1] = "RinkSide Launcher"
                found[2] = hwnd
                return False
                
            return True

        self.user32.EnumWindows(WNDENUMPROC(enum_windows_callback), 0)
        return found[0], found[1], found[2]
