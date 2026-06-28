"""Procedural art — sigils and frequency portraits, rendered to PNG with Pillow.

Deterministic: the same intent / numbers always render the same image. No AI, no
network. Returns raw PNG bytes for a discord.File.
"""
from __future__ import annotations

import hashlib
import io
import math

from PIL import Image, ImageDraw

SIZE = 720
_BG = (10, 10, 16)

# Planet-number palette (Vedic numerology rulers) for portraits.
_NUMBER_COLOR = {
    1: (255, 196, 64), 2: (170, 200, 255), 3: (255, 215, 120), 4: (140, 120, 220),
    5: (120, 230, 180), 6: (255, 150, 200), 7: (180, 160, 255), 8: (110, 130, 160),
    9: (255, 110, 90), 11: (210, 220, 255), 22: (160, 140, 230), 33: (255, 230, 160),
}


def _seed(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)


def sigil(intent: str) -> bytes:
    """A 'rose-wheel' sigil: nodes for each distinct letter, joined into a glyph."""
    img = Image.new("RGB", (SIZE, SIZE), _BG)
    d = ImageDraw.Draw(img)
    cx = cy = SIZE / 2
    r = SIZE * 0.36
    seed = _seed(intent)

    # outer rings
    for i, rr in enumerate((r + 40, r + 20, r)):
        shade = 40 + i * 20
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=(shade, shade, shade + 30), width=2)

    # 24 nodes around the wheel
    nodes = []
    for i in range(24):
        ang = (i / 24) * 2 * math.pi - math.pi / 2
        nodes.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))

    # map the intent's letters to node indices and connect them in order
    letters = [c for c in intent.lower() if c.isalnum()]
    path = [(seed >> (i * 3)) % 24 for i in range(max(len(letters), 6))]
    hue = (seed % 360)
    line_col = _hsv((hue) % 360, 0.7, 1.0)
    for a, b in zip(path, path[1:]):
        d.line([nodes[a], nodes[b]], fill=line_col, width=3)
    # accent the start (circle) and end (cross-bar) of the glyph
    sx, sy = nodes[path[0]]
    d.ellipse([sx - 10, sy - 10, sx + 10, sy + 10], outline=line_col, width=3)
    ex, ey = nodes[path[-1]]
    d.line([ex - 12, ey, ex + 12, ey], fill=line_col, width=3)

    return _png(img)


def frequency_portrait(name: str, numbers: list[int]) -> bytes:
    """Concentric rings coloured by a person's numerology numbers."""
    img = Image.new("RGB", (SIZE, SIZE), _BG)
    d = ImageDraw.Draw(img)
    cx = cy = SIZE / 2
    seed = _seed(name)
    nums = [n for n in numbers if n] or [1]

    base = SIZE * 0.45
    for i, n in enumerate(nums):
        rr = base * (1 - i / (len(nums) + 1))
        col = _NUMBER_COLOR.get(n, (200, 200, 200))
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=col, width=6)
        # petals seeded by the number
        petals = max(n, 3)
        for p in range(petals):
            ang = (p / petals) * 2 * math.pi + (seed % 100) / 100
            px, py = cx + rr * math.cos(ang), cy + rr * math.sin(ang)
            d.ellipse([px - 6, py - 6, px + 6, py + 6], fill=col)

    d.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], fill=(255, 255, 255))
    return _png(img)


def _hsv(h: float, s: float, v: float) -> tuple[int, int, int]:
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(h / 360, s, v)
    return int(r * 255), int(g * 255), int(b * 255)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
