#!/usr/bin/env python3
"""
Build script to compile GamingZoneShiftSetup.exe using Inno Setup (ISCC.exe).
"""

import os
import sys
import shutil
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTALLER_DIR = os.path.join(BASE_DIR, "installer")
ISS_FILE = os.path.join(INSTALLER_DIR, "setup.iss")
OUTPUT_DIR = os.path.join(INSTALLER_DIR, "output")


def find_iscc():
    iscc = shutil.which("iscc") or shutil.which("ISCC.exe")
    if iscc and os.path.isfile(iscc):
        return iscc
    known_paths = [
        r"C:\ProgramData\chocolatey\bin\ISCC.exe",
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    for p in known_paths:
        if os.path.isfile(p):
            return p
    return None


def build():
    # 1. Compile the latest PyInstaller executable
    print("[*] Ensuring latest executable is built with PyInstaller...")
    from build_exe import build as build_pyinstaller
    if not build_pyinstaller():
        print("[ERROR] Failed to compile executable.")
        return False

    # 2. Locate ISCC.exe
    iscc_exe = find_iscc()
    if not iscc_exe:
        print("[ERROR] Inno Setup compiler (ISCC.exe) was not found in PATH or standard directories.")
        return False

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"[*] Compiling Windows installer using: {iscc_exe}")
    cmd = [iscc_exe, ISS_FILE]
    result = subprocess.run(cmd, cwd=INSTALLER_DIR)

    if result.returncode == 0:
        installer_path = os.path.join(OUTPUT_DIR, "GamingZoneShiftSetup.exe")
        root_copy = os.path.join(BASE_DIR, "GamingZoneShiftSetup.exe")
        dist_copy = os.path.join(BASE_DIR, "dist", "GamingZoneShiftSetup.exe")
        try:
            shutil.copy2(installer_path, root_copy)
            shutil.copy2(installer_path, dist_copy)
        except Exception as e:
            print(f"[WARN] Failed to copy installer to root/dist: {e}")

        print(f"\n[SUCCESS] Windows Installer created successfully at:")
        print(f"  -> Project Root: {root_copy}")
        print(f"  -> Dist Folder:  {dist_copy}")
        print(f"  -> Output:       {installer_path}\n")
        return True
    else:
        print(f"\n[ERROR] Inno Setup compilation failed with exit code {result.returncode}\n")
        return False


if __name__ == "__main__":
    success = build()
    sys.exit(0 if success else 1)
