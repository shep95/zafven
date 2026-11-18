"""Render a 'Make it a Quote' style image — deterministic, Pillow-only.

Given a user's avatar, a quote, a display name and a handle, produce a 1200×630
PNG: the avatar on the left, desaturated and faded into a near-black ground, with
the quote set in a modern italic on the right, the attribution below it, and a
small footer. No AI, no network — pure image composition.
"""
from __future__ import annotations

import io
import os

from PIL import Image, ImageDraw, ImageFont, ImageOps

W, H = 1200, 630
_BG = (12, 12, 13)
_AVATAR_W = 560            # left region the avatar fills before fading out
_TEXT_X0 = 600            # quote column left edge
_TEXT_X1 = 1150          # quote column right edge
_FG = (238, 238, 240)
_MUTED = (150, 150, 155)
_FAINT = (95, 95, 100)

_FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "fonts")
_ITALIC = os.path.join(_FONT_DIR, "WorkSans-Italic.ttf")
_BOLD_ITALIC = os.path.join(_FONT_DIR, "WorkSans-BoldItalic.ttf")


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except Exception:  # noqa: BLE001 — fall back so rendering never crashes
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size)
        except Exception:  # noqa: BLE001
            return ImageFont.load_default(size=size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    """Greedy word-wrap to a pixel width; very long words are hard-split."""
    words = text.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def _fit_quote(draw: ImageDraw.ImageDraw, text: str, max_w: int, max_h: int) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """Pick the largest italic size whose wrapped quote fits the text box."""
    for size in range(68, 25, -3):
        font = _font(_ITALIC, size)
        lines = _wrap(draw, text, font, max_w)
        line_h = int(size * 1.28)
        if line_h * len(lines) <= max_h:
            return font, lines, line_h
    font = _font(_ITALIC, 26)
    return font, _wrap(draw, text, font, max_w), int(26 * 1.28)


def render_quote(avatar_bytes: bytes | None, text: str, name: str,
                 handle: str = "", footer: str = "zafven") -> bytes:
    text = (text or "").strip() or "…"
    canvas = Image.new("RGB", (W, H), _BG)

    # ── left: desaturated avatar fading into the background ──────────────
    if avatar_bytes:
        try:
            av = Image.open(io.BytesIO(avatar_bytes)).convert("L")
            av = ImageOps.autocontrast(av, cutoff=1)
            av = ImageOps.fit(av, (_AVATAR_W, H), method=Image.LANCZOS).convert("RGB")
            # slightly dim so bright avatars don't blow out
            av = Image.eval(av, lambda p: int(p * 0.82))
            canvas.paste(av, (0, 0))
            # horizontal gradient: avatar on the far left, full background by the
            # right of the region, so it melts into the dark panel.
            grad = Image.new("L", (_AVATAR_W, 1))
            for x in range(_AVATAR_W):
                t = x / (_AVATAR_W - 1)
                grad.putpixel((x, 0), int(max(0, min(255, (t - 0.42) / 0.58 * 255))))
            mask = grad.resize((_AVATAR_W, H))
            canvas.paste(Image.new("RGB", (_AVATAR_W, H), _BG), (0, 0), mask)
        except Exception:  # noqa: BLE001 — a bad avatar shouldn't fail the card
            pass

    draw = ImageDraw.Draw(canvas)
    box_w = _TEXT_X1 - _TEXT_X0
    # reserve room at the bottom for name + handle
    quote_font, lines, line_h = _fit_quote(draw, text, box_w, max_h=360)
    quote_h = line_h * len(lines)

    name_font = _font(_BOLD_ITALIC, 34)
    handle_font = _font(_ITALIC, 24)
    attrib_h = 44 + (34 if handle else 0)
    block_h = quote_h + 40 + attrib_h
    y = max(60, (H - block_h) // 2)

    for line in lines:
        draw.text((_TEXT_X0, y), line, font=quote_font, fill=_FG)
        y += line_h
    y += 28

    draw.text((_TEXT_X0, y), f"- {name}", font=name_font, fill=_FG)
    y += 44
    if handle:
        draw.text((_TEXT_X0, y), handle if handle.startswith("@") else f"@{handle}",
                  font=handle_font, fill=_MUTED)

    if footer:
        ff = _font(_ITALIC, 20)
        fw = draw.textlength(footer, font=ff)
        draw.text((W - fw - 28, H - 40), footer, font=ff, fill=_FAINT)

    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()
