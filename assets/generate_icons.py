#!/usr/bin/env python3
"""
Generate gold and red-accented multi-resolution Windows icons for Gaming Zone Shift Management.
"""

import os
import sys
import colorsys
import numpy as np
from PIL import Image

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
SOURCE_USER_PNG = r"C:\Users\equilibrium\.gemini\antigravity-ide\brain\c0db38d4-9833-4097-9068-ecf50ef54d3e\.user_uploaded\media_1789963742071.png"

LOGO_PNG = os.path.join(ASSETS_DIR, "logo.png")
ICON_ICO = os.path.join(ASSETS_DIR, "icon.ico")
INSTALLER_PNG = os.path.join(ASSETS_DIR, "installer_logo.png")
INSTALLER_ICO = os.path.join(ASSETS_DIR, "installer_icon.ico")

ICON_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def generate_gold_icons(src_img: Image.Image):
    print("[*] Generating primary gold application logo and icon...")
    src_img.save(LOGO_PNG, format="PNG")

    # Generate multi-size ICO
    resized_images = [
        src_img.resize(size, Image.Resampling.LANCZOS)
        for size in ICON_SIZES
    ]
    resized_images[-1].save(
        ICON_ICO,
        format="ICO",
        sizes=ICON_SIZES,
        append_images=resized_images[:-1]
    )
    print(f"  -> Saved {LOGO_PNG}")
    print(f"  -> Saved {ICON_ICO}")


def generate_red_installer_icons(src_img: Image.Image):
    print("[*] Generating red-outline installer logo and icon...")
    arr = np.array(src_img.convert("RGBA"), dtype=np.float32)
    h, w, _ = arr.shape

    # Outer border region: x < 110 or x > 914 or y < 110 or y > 914
    for y in range(h):
        for x in range(w):
            if x < 115 or x > (w - 115) or y < 115 or y > (h - 115):
                r, g, b, a = arr[y, x] / 255.0
                # If pixel is part of the glowing gold border (significant red/green, low blue)
                if r > 0.2 and g > 0.15:
                    h_val, s_val, v_val = colorsys.rgb_to_hsv(r, g, b)
                    # Shift hue to pure ruby crimson red (0.005) with saturated metallic punch
                    new_h = 0.005
                    new_s = min(1.0, s_val * 1.08)
                    nr, ng, nb = colorsys.hsv_to_rgb(new_h, new_s, v_val)
                    arr[y, x, 0] = nr * 255
                    arr[y, x, 1] = ng * 255
                    arr[y, x, 2] = nb * 255

    red_img = Image.fromarray(arr.astype(np.uint8))
    red_img.save(INSTALLER_PNG, format="PNG")

    # Generate multi-size installer ICO
    resized_red = [
        red_img.resize(size, Image.Resampling.LANCZOS)
        for size in ICON_SIZES
    ]
    resized_red[-1].save(
        INSTALLER_ICO,
        format="ICO",
        sizes=ICON_SIZES,
        append_images=resized_red[:-1]
    )
    print(f"  -> Saved {INSTALLER_PNG}")
    print(f"  -> Saved {INSTALLER_ICO}")


def main():
    if not os.path.isfile(SOURCE_USER_PNG):
        print(f"[ERROR] Source image not found at: {SOURCE_USER_PNG}")
        sys.exit(1)

    src = Image.open(SOURCE_USER_PNG)
    generate_gold_icons(src)
    generate_red_installer_icons(src)
    print("\n[SUCCESS] All application and installer icons successfully generated!")


if __name__ == "__main__":
    main()
