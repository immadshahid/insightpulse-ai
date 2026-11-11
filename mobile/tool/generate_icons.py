"""Generate InsightPulse app icons and launch images for Android, iOS and web.

The mark: a rising "pulse" line with a spark, white on the brand indigo.
Re-run after changing the design:  python tool/generate_icons.py  (from mobile/)
Requires Pillow (installed with Matplotlib in the backend environment).
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).absolute().parents[1]  # absolute(), not resolve(): keeps short subst paths
BRAND = (79, 70, 229, 255)  # #4F46E5
WHITE = (255, 255, 255, 255)
SS = 4  # supersampling factor for smooth edges


def glyph(size: int, scale: float = 1.0, color=WHITE) -> Image.Image:
    """Transparent square with the white mark. ``scale`` shrinks it toward the centre."""
    big = size * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def p(x: float, y: float) -> tuple[float, float]:
        # Design coordinates are on a 1024 grid, centred.
        c = 512
        return ((c + (x - c) * scale) * big / 1024, (c + (y - c) * scale) * big / 1024)

    w = int(64 * scale * big / 1024)
    pts = [p(232, 700), p(420, 520), p(560, 640), p(800, 380)]
    d.line(pts, fill=color, width=w, joint="curve")
    r = w * 0.5
    for x, y in (pts[0], pts[-1]):
        d.ellipse((x - r, y - r, x + r, y + r), fill=color)
    # Four-point spark, top left of the line end.
    cx, cy = p(330, 300)
    R, k = 120 * scale * big / 1024, 0.28
    star = [(cx, cy - R), (cx + R * k, cy - R * k), (cx + R, cy), (cx + R * k, cy + R * k),
            (cx, cy + R), (cx - R * k, cy + R * k), (cx - R, cy), (cx - R * k, cy - R * k)]
    d.polygon(star, fill=color)
    return img.resize((size, size), Image.LANCZOS)


def tile(size: int, rounded: bool = True, bg=BRAND, glyph_scale: float = 1.0,
         transparent_outside: bool = True) -> Image.Image:
    """Brand tile: indigo (optionally rounded) square with the mark on top."""
    big = size * SS
    base = Image.new("RGBA", (big, big), (0, 0, 0, 0) if transparent_outside else bg)
    d = ImageDraw.Draw(base)
    if rounded:
        d.rounded_rectangle((0, 0, big - 1, big - 1), radius=int(big * 0.22), fill=bg)
    else:
        d.rectangle((0, 0, big, big), fill=bg)
    base = base.resize((size, size), Image.LANCZOS)
    base.alpha_composite(glyph(size, glyph_scale))
    return base


def save(img: Image.Image, path: Path, rgb: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    (img.convert("RGB") if rgb else img).save(path, optimize=True)
    print("wrote", path.relative_to(ROOT))


def android() -> None:
    res = ROOT / "android/app/src/main/res"
    densities = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}
    for name, f in densities.items():
        save(tile(round(48 * f), glyph_scale=0.86), res / f"mipmap-{name}/ic_launcher.png")
        # Adaptive icon foreground: 108dp canvas, mark inside the 66dp safe zone.
        save(glyph(round(108 * f), scale=0.7), res / f"mipmap-{name}/ic_launcher_foreground.png")
    (res / "mipmap-anydpi-v26").mkdir(parents=True, exist_ok=True)
    (res / "mipmap-anydpi-v26/ic_launcher.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '    <background android:drawable="@color/ic_launcher_background"/>\n'
        '    <foreground android:drawable="@mipmap/ic_launcher_foreground"/>\n'
        '    <monochrome android:drawable="@mipmap/ic_launcher_foreground"/>\n'
        "</adaptive-icon>\n", encoding="utf-8")
    # Splash logo (pre-Android 12 windowBackground) and Android 12+ splash icon.
    save(tile(288, glyph_scale=0.86), res / "drawable-nodpi/splash_logo.png")
    save(glyph(432, scale=0.5), res / "drawable-nodpi/splash_icon.png")


def ios() -> None:
    folder = ROOT / "ios/Runner/Assets.xcassets/AppIcon.appiconset"
    contents = json.loads((folder / "Contents.json").read_text(encoding="utf-8"))
    for img in contents["images"]:
        if "filename" not in img:
            continue
        points = float(img["size"].split("x")[0])
        px = round(points * int(img["scale"].rstrip("x")))
        # iOS masks the corners itself and rejects transparency in app icons.
        save(tile(px, rounded=False, glyph_scale=0.86, transparent_outside=False),
             folder / img["filename"], rgb=True)
    launch = ROOT / "ios/Runner/Assets.xcassets/LaunchImage.imageset"
    for name, px in (("LaunchImage.png", 96), ("LaunchImage@2x.png", 192),
                     ("LaunchImage@3x.png", 288)):
        save(tile(px, glyph_scale=0.86), launch / name)


def web() -> None:
    icons = ROOT / "web/icons"
    for px in (192, 512):
        save(tile(px, glyph_scale=0.86), icons / f"Icon-{px}.png")
        # Maskable: full-bleed background, mark inside the 80% safe circle.
        save(tile(px, rounded=False, glyph_scale=0.75, transparent_outside=False),
             icons / f"Icon-maskable-{px}.png")
    save(tile(64, glyph_scale=0.86), ROOT / "web/favicon.png")


if __name__ == "__main__":
    android()
    ios()
    web()
