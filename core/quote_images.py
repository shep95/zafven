"""Local quote cards: supplied text, image backgrounds, and a circular user avatar."""
from __future__ import annotations

import io
import os
import warnings

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, UnidentifiedImageError

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 20_000_000
MAX_QUOTE_CHARS = 700
SIZE = (1200, 900)


class QuoteImageError(ValueError):
    pass


def decode_image(data: bytes):
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise QuoteImageError("Use an image no larger than 8 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.width * source.height > MAX_PIXELS:
                    raise QuoteImageError("That image is too large to process (20 million pixels maximum).")
                source.seek(0)  # Still frame for animated uploads.
                return ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise QuoteImageError("I couldn't read that image. Try PNG, JPEG, WebP, or GIF.") from exc


def vision_image(data: bytes) -> bytes:
    image = decode_image(data)
    image.thumbnail((2000, 2000))
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=92)
    return output.getvalue()


def font(size):
    candidates = [os.getenv("QUOTE_FONT_FILE", ""),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf", "DejaVuSans.ttf"]
    for path in candidates:
        if path:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


def wrap(draw, text, face, width):
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}".strip()
            if draw.textlength(candidate, font=face) <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
                line = ""
            # Split long words/URLs without dropping characters.
            for char in word:
                if draw.textlength(line + char, font=face) > width and line:
                    lines.append(line)
                    line = ""
                line += char
        lines.append(line)
    return lines


def render_quote(text: str, name: str, avatar: bytes | None = None,
                 background: bytes | None = None, label: str = "CUSTOM QUOTE") -> bytes:
    text = text.strip()
    if not text or len(text) > MAX_QUOTE_CHARS:
        raise QuoteImageError(f"Provide 1–{MAX_QUOTE_CHARS} characters of quote text.")
    if background:
        canvas = ImageOps.fit(decode_image(background), SIZE).filter(ImageFilter.GaussianBlur(2)).convert("RGBA")
        canvas.alpha_composite(Image.new("RGBA", SIZE, (8, 13, 23, 190)))
    else:
        canvas = Image.new("RGBA", SIZE, (15, 23, 36, 255))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((46, 42, 1154, 858), radius=30, outline=(96, 119, 147), width=2)
    draw.rounded_rectangle((92, 104, 101, 164), radius=4, fill=(100, 222, 194))
    draw.text((124, 121), label[:50], font=font(22), fill=(172, 191, 210))
    for size in range(58, 21, -2):
        face = font(size)
        lines = wrap(draw, text, face, 970)
        line_height = size + 15
        if len(lines) * line_height <= 450:
            break
    else:
        raise QuoteImageError("That quote doesn't fit cleanly. Use a shorter quote.")
    y = 220 + (450 - len(lines) * line_height) // 2
    for line in lines:
        draw.text((112, y), line, font=face, fill=(245, 247, 252))
        y += line_height
    if avatar:
        portrait = ImageOps.fit(decode_image(avatar), (100, 100)).convert("RGBA")
        mask = Image.new("L", (100, 100), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 99, 99), fill=255)
        canvas.paste(portrait, (106, 713), mask)
    else:
        draw.ellipse((106, 713, 206, 813), fill=(39, 65, 80))
        draw.text((137, 737), (name[:1] or "?").upper(), font=font(36), fill="white")
    # Ellipsize display name only; quote text is never silently shortened.
    display = name.replace("\n", " ")[:100]
    while draw.textlength(display, font=font(31)) > 770:
        display = display[:-2] + "…"
    draw.text((231, 737), display, font=font(31), fill=(238, 244, 250))
    draw.text((231, 780), "made with zafven", font=font(19), fill=(150, 170, 190))
    output = io.BytesIO()
    canvas.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()
