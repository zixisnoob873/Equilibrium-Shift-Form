#!/usr/bin/env python3
"""
Build script to compile GamingZoneShift.exe using PyInstaller.
"""

import os
import sys
import subprocess
from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
LOGO_PNG = os.path.join(ASSETS_DIR, "logo.png")
ICON_ICO = os.path.join(ASSETS_DIR, "icon.ico")


def ensure_icon():
    if not os.path.isfile(ICON_ICO) and os.path.isfile(LOGO_PNG):
        print("[*] Generating assets/icon.ico from assets/logo.png...")
        img = Image.open(LOGO_PNG)
        img.save(
            ICON_ICO,
            format="ICO",
            sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        )
        print("[OK] assets/icon.ico generated.")


def build():
    ensure_icon()
    print("[*] Compiling GamingZoneShift.exe via PyInstaller...")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconsole",
        "--onedir",
        "--name=Equilibrium-Shift-Form",
        f"--icon={ICON_ICO}",
        "--clean",
        "-y",
        "launcher.py"
    ]
    print(f"[*] Executing command: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=BASE_DIR)

    if result.returncode == 0:
        exe_path = os.path.join(BASE_DIR, "dist", "Equilibrium-Shift-Form", "Equilibrium-Shift-Form.exe")
        print(f"\n[SUCCESS] Executable built successfully at:\n  -> {exe_path}\n")
        return True
    else:
        print(f"\n[ERROR] PyInstaller build failed with exit code {result.returncode}\n")
        return False


if __name__ == "__main__":
    success = build()
    sys.exit(0 if success else 1)
