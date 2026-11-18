"""Thumbnails for bundles, in two styles being tried out side by side.

* ``collage``: the articles' own pictures in a grid (two side by side, three as
  one large and two stacked, four as a 2x2). An article without a usable
  picture gets a coloured tile carrying its label and publication instead.
* ``list``: a card with the bundle number and the articles' short labels.

Images are 1200x800 JPEGs. Pictures are downloaded from the addresses Readwise
recorded for each article; they are untrusted files, so downloads are capped in
size and anything Pillow cannot read safely is treated as missing.
"""
from __future__ import annotations

import io
import urllib.request
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .picking import Article

WIDTH, HEIGHT = 1200, 800
GUTTER = 8
FONTS = Path(__file__).parent / "fonts"
CREAM = (246, 240, 230)
# (background, accent), chosen by bundle number so neighbouring bundles differ.
PALETTE: List[Tuple[Tuple[int, int, int], Tuple[int, int, int]]] = [
    ((28, 39, 64), (233, 186, 104)),   # navy and gold
    ((32, 64, 54), (226, 200, 140)),   # forest and sand
    ((88, 28, 42), (240, 190, 160)),   # burgundy and blush
    ((40, 42, 60), (150, 200, 220)),   # ink and ice
    ((22, 74, 88), (245, 205, 120)),   # teal and amber
    ((84, 58, 28), (238, 214, 170)),   # walnut and cream
]
STYLES = ("collage", "list")

Fetch = Callable[[str], Optional[Image.Image]]


def style_for(setting: str, number: int) -> Optional[str]:
    """``alternate`` gives odd-numbered bundles a collage and even-numbered ones a list."""
    if setting in STYLES:
        return setting
    if setting == "alternate":
        return "collage" if number % 2 else "list"
    return None  # "none"


def render(style: str, number: int, articles: Sequence[Article], labels: Sequence[str],
           *, fetch: Optional[Fetch] = None) -> bytes:
    if style == "collage":
        return make_collage(number, articles, labels, fetch=fetch or fetch_image)
    return make_list_card(number, labels)


# ------------------------------------------------------------------ collage

def make_collage(number: int, articles: Sequence[Article], labels: Sequence[str],
                 *, fetch: Fetch) -> bytes:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), (16, 17, 20))  # the gutters between tiles
    for i, (box, article) in enumerate(zip(_boxes(len(articles)), articles)):
        size = (box[2] - box[0], box[3] - box[1])
        picture = fetch(article.image_url) if article.image_url else None
        if picture is not None:
            tile = ImageOps.fit(picture, size, method=Image.LANCZOS, centering=(0.5, 0.4))
        else:
            label = labels[i] if i < len(labels) else article.title
            tile = _stand_in_tile(size, label, article.site_name, palette(number + i + 1))
        canvas.paste(tile, box[:2])
    return _jpeg(canvas)


def _boxes(n: int) -> List[Tuple[int, int, int, int]]:
    w, h, g = WIDTH, HEIGHT, GUTTER
    half_w, half_h = (w - g) // 2, (h - g) // 2
    if n <= 1:
        return [(0, 0, w, h)]
    if n == 2:
        return [(0, 0, half_w, h), (half_w + g, 0, w, h)]
    if n == 3:
        return [(0, 0, half_w, h), (half_w + g, 0, w, half_h), (half_w + g, half_h + g, w, h)]
    return [(0, 0, half_w, half_h), (half_w + g, 0, w, half_h),
            (0, half_h + g, half_w, h), (half_w + g, half_h + g, w, h)]


def _stand_in_tile(size, label: str, site: str, colours) -> Image.Image:
    background, accent = colours
    tile = Image.new("RGB", size, background)
    draw = ImageDraw.Draw(tile)
    width, height = size
    lines, big = _wrap_to_fit(draw, label, "Bold", width - 80, max_size=72, max_lines=3)
    line_height = big.size * 1.15
    top = height / 2 - (len(lines) * line_height) / 2 - (20 if site else 0)
    for k, line in enumerate(lines):
        draw.text((width / 2, top + k * line_height + line_height / 2), line, font=big,
                  fill=CREAM, anchor="mm")
    if site:
        small = font("Medium", 28)
        draw.text((width / 2, top + len(lines) * line_height + 36), site.upper()[:40], font=small,
                  fill=accent, anchor="mm")
    return tile


# --------------------------------------------------------------- list card

def make_list_card(number: int, labels: Sequence[str]) -> bytes:
    background, accent = palette(number)
    card = Image.new("RGB", (WIDTH, HEIGHT), background)
    draw = ImageDraw.Draw(card)
    margin = 84

    _tracked_text(draw, (margin, 92), f"BUNDLE {number}", font("SemiBold", 30), accent, tracking=6)
    draw.line([(margin, 128), (margin + 64, 128)], fill=accent, width=4)

    top, bottom = 176, HEIGHT - 72
    rows = max(1, len(labels))
    row_height = (bottom - top) / rows
    numeral_font = font("Medium", 34)
    numeral_width = 96
    text_width = WIDTH - 2 * margin - numeral_width
    size = int(min(104, row_height * 0.6))
    while size > 36 and any(draw.textlength(label, font=font("Bold", size)) > text_width
                            for label in labels):
        size -= 2
    label_font = font("Bold", size)
    rule_colour = _mix(background, CREAM, 0.18)

    for i, label in enumerate(labels):
        middle = top + row_height * (i + 0.5)
        draw.text((margin, middle), f"{i + 1:02d}", font=numeral_font, fill=accent, anchor="lm")
        draw.text((margin + numeral_width, middle), label, font=label_font, fill=CREAM, anchor="lm")
        if i < rows - 1:
            y = top + row_height * (i + 1)
            draw.line([(margin, y), (WIDTH - margin, y)], fill=rule_colour, width=2)
    return _jpeg(card)


# ----------------------------------------------------------------- helpers

def palette(number: int):
    return PALETTE[number % len(PALETTE)]


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / f"Inter-{weight}.otf"), size)


def fetch_image(url: str, *, timeout: int = 15, max_bytes: int = 8_000_000) -> Optional[Image.Image]:
    if not url or not url.lower().startswith(("http://", "https://")):
        return None
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; readwise-bundler)"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            return None
        picture = Image.open(io.BytesIO(data))
        picture.load()
        if picture.width < 120 or picture.height < 80:  # icons and tracking pixels
            return None
        return picture.convert("RGB")
    except Exception:  # unreachable, not an image, too large to decode safely: treat as missing
        return None


def _wrap_to_fit(draw, text: str, weight: str, width: int, *, max_size: int, max_lines: int):
    size = max_size
    while True:
        face = font(weight, size)
        lines: List[str] = []
        for word in text.split():
            if lines and draw.textlength(f"{lines[-1]} {word}", font=face) <= width:
                lines[-1] = f"{lines[-1]} {word}"
            else:
                lines.append(word)
        if (len(lines) <= max_lines and all(draw.textlength(l, font=face) <= width for l in lines)) or size <= 24:
            return lines[:max_lines], face
        size -= 4


def _tracked_text(draw, xy, text: str, face, fill, *, tracking: int) -> None:
    x, y = xy
    for char in text:
        draw.text((x, y), char, font=face, fill=fill, anchor="ls")
        x += draw.textlength(char, font=face) + tracking


def _mix(a, b, amount: float):
    return tuple(round(x + (y - x) * amount) for x, y in zip(a, b))


def _jpeg(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=86, optimize=True, progressive=True)
    return buffer.getvalue()
