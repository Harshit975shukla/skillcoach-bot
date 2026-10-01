"""Draw SkillCoach's app icons into skillcoach/static (run: python tools/app_icons.py).

The mark is a geometric "S" for SkillCoach: two stacked bowls with round ends, white on the app's
accent blue. It is drawn at four times the size and scaled down for smooth edges. No font is used.
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

STATIC = Path(__file__).resolve().parent.parent / "skillcoach" / "static"
ACCENT = (7, 95, 155, 255)
WHITE = (255, 255, 255, 255)
SUPER = 4


def mark(draw: ImageDraw.ImageDraw, size: int, scale: float, color):
    """The S, centred in a `size` canvas; `scale` 1.0 makes it about 63% of the canvas height."""
    cx = cy = size / 2
    r = 0.13 * size * scale
    w = 0.11 * size * scale
    upper, lower = (cx, cy - r), (cx, cy + r)

    def arc(center, start, end):
        x, y = center
        draw.arc(
            [x - r - w / 2, y - r - w / 2, x + r + w / 2, y + r + w / 2],
            start,
            end,
            fill=color,
            width=round(w),
        )

    def dot(center, angle, diameter):
        x = center[0] + r * math.cos(math.radians(angle))
        y = center[1] + r * math.sin(math.radians(angle))
        draw.ellipse([x - diameter / 2, y - diameter / 2, x + diameter / 2, y + diameter / 2], fill=color)

    # Upper bowl from its bottom, round the left and over the top to the upper right.
    arc(upper, 90, 330)
    # Lower bowl from its top, round the right and the bottom to the lower left.
    arc(lower, 270, 360)
    arc(lower, 0, 150)
    dot(upper, 330, w)
    dot(upper, 90, w)
    dot(lower, 150, w)


def icon(size: int, *, scale: float, background: str, foreground=WHITE) -> Image.Image:
    big = size * SUPER
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if background == "rounded":
        draw.rounded_rectangle([0, 0, big - 1, big - 1], radius=round(big * 0.22), fill=ACCENT)
    elif background == "square":
        draw.rectangle([0, 0, big, big], fill=ACCENT)
    mark(draw, big, scale, foreground)
    return image.resize((size, size), Image.LANCZOS)


def main():
    outputs = {
        "icon-192.png": icon(192, scale=1.0, background="rounded"),
        "icon-512.png": icon(512, scale=1.0, background="rounded"),
        # Maskable: full bleed, with the mark inside the central safe zone.
        "icon-maskable-512.png": icon(512, scale=0.8, background="square"),
        # iOS rounds the corners itself and shows transparency as black.
        "apple-touch-icon.png": icon(180, scale=0.9, background="square").convert("RGB"),
        # Android status-bar badge: a white silhouette on transparent.
        "badge-72.png": icon(72, scale=1.3, background="none"),
    }
    for name, image in outputs.items():
        image.save(STATIC / name, optimize=True)
        print(name, image.size)


if __name__ == "__main__":
    main()
