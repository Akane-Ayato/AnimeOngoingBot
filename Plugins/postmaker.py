"""
Post maker: caption values + the 16:9 glassmorphism banner (Pillow).
Minimal layout: poster, title, channel logo + name, short description.
Everything CPU-heavy runs in a worker thread so the bot stays responsive.
"""
import asyncio
import html
import io
import logging
import os
import re
from functools import lru_cache
from typing import List, Optional

import aiohttp
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageEnhance, ImageFile, ImageFilter, ImageFont, ImageOps

import config
from Plugins import api_handler
from Plugins.UI_design import esc, render_caption, sc

log = logging.getLogger("AnimeBot.postmaker")

ImageFile.LOAD_TRUNCATED_IMAGES = True  # render what we have rather than lose the banner

W, H = 1920, 1080
PURPLE = (150, 100, 255)

# ------------------------------------------------------------------ caption values
def build_values(a: "api_handler.Anime") -> dict:
    na = "N/A"
    return {
        "title": esc(a.title),
        "episode": str(a.episode if a.episode is not None else "?"),
        "language": sc("Dual") if a.language == "Dual" else sc("Sub") + " | E-" + sc("Sub"),
        "status": esc(sc(a.status)),
        "description": esc(a.description or "No synopsis available."),
        "season": esc(a.season or na),
        "year": esc(a.year or na),
        "score": esc(a.score or na),
        "genres": esc(", ".join(a.genres) or na),
        "studio": esc(a.studio or na),
        "type": esc(a.type or na),
        "aired": esc(a.aired or na),
        "total_eps": esc(a.total_eps or na),
        "id": esc(a.id),
        "url": watch_url(a.id),
        "channel": esc(config.CHANNEL_NAME),
        "powered_name": esc(config.POWERED_BY_NAME),
        "powered_url": html.escape(config.POWERED_BY_URL, quote=True),
    }


def watch_url(anime_id) -> str:
    return f"{config.SITE_URL}/watch.html?id={anime_id}"


def build_caption(a: "api_handler.Anime", template: Optional[str] = None) -> str:
    return render_caption(template, build_values(a))


# ------------------------------------------------------------------ fonts
_FALLBACK_FILES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "C:\\Windows\\Fonts\\seguisym.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]


@lru_cache(maxsize=None)
def _cmap(path: str) -> frozenset:
    try:
        return frozenset(TTFont(path, lazy=True).getBestCmap().keys())
    except Exception:
        return frozenset()


@lru_cache(maxsize=64)
def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _fp(name: str) -> str:
    return os.path.join(config.FONT_DIR, name)


class Stack:
    """A font family with per-character fallback (title font -> Inter -> DejaVu)."""

    def __init__(self, *files: str):
        chain = [f for f in files if os.path.exists(f)]
        chain += [f for f in _FALLBACK_FILES if os.path.exists(f)][:1]
        if not chain:
            raise RuntimeError("No usable fonts found in assets/fonts")
        self.chain = chain

    def runs(self, text: str, size: int):
        out, cur, cur_path = [], "", None
        for ch in text:
            path = next((p for p in self.chain if ord(ch) in _cmap(p)), None)
            if path is None:
                if ch.isspace():
                    path = cur_path or self.chain[0]
                else:
                    continue  # glyph exists nowhere: drop it instead of drawing a box
            if path != cur_path and cur:
                out.append((cur, _font(cur_path, size)))
                cur = ""
            cur_path = path
            cur += ch
        if cur:
            out.append((cur, _font(cur_path, size)))
        return out

    def width(self, text: str, size: int, spacing: float = 0) -> float:
        return sum(f.getlength(t) for t, f in self.runs(text, size)) + spacing * max(0, len(text) - 1)

    def draw(self, d: ImageDraw.ImageDraw, xy, text: str, size: int, fill, spacing: float = 0):
        x, y = xy
        for t, f in self.runs(text, size):
            if spacing:
                for ch in t:
                    d.text((x, y), ch, font=f, fill=fill)
                    x += f.getlength(ch) + spacing
            else:
                d.text((x, y), t, font=f, fill=fill)
                x += f.getlength(t)


def _title_stack():
    return Stack(_fp("Unbounded-Bold.ttf"), _fp("Inter-SemiBold.ttf"))


def _inter(weight="Regular"):
    return Stack(_fp(f"Inter-{weight}.ttf"))


# ------------------------------------------------------------------ drawing helpers
def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    return ImageOps.fit(img.convert("RGB"), (w, h), Image.LANCZOS, centering=(0.5, 0.35))


def _rounded_mask(size, radius):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius, fill=255)
    return m


def _glass(base: Image.Image, box, radius: int, blur: int = 26, fill_alpha: int = 34, border_alpha: int = 90):
    """Frosted-glass rectangle: blurred + lifted backdrop, white veil, light border."""
    x0, y0, x1, y1 = box
    region = base.crop(box).convert("RGB").filter(ImageFilter.GaussianBlur(blur))
    region = ImageEnhance.Brightness(region).enhance(1.18)
    veil = Image.new("RGBA", region.size, (255, 255, 255, fill_alpha))
    region = Image.alpha_composite(region.convert("RGBA"), veil)
    mask = _rounded_mask(region.size, radius)
    base.paste(region, (x0, y0), mask)
    border = Image.new("RGBA", base.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(border)
    bd.rounded_rectangle(box, radius, outline=(255, 255, 255, border_alpha), width=2)
    # brighter top edge for a light-catching rim
    bd.rounded_rectangle((x0 + 1, y0 + 1, x1 - 1, y1 - 1), radius, outline=(255, 255, 255, 30), width=1)
    base.alpha_composite(border)


def _background(src: Image.Image) -> Image.Image:
    bg = _cover(src, W, H).filter(ImageFilter.GaussianBlur(16))
    bg = ImageEnhance.Color(bg).enhance(1.15)
    tint = Image.new("RGB", (W, H), (62, 32, 104))
    bg = Image.blend(bg, tint, 0.62).convert("RGBA")
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-200, -220, 700, 520), fill=(170, 90, 255, 120))
    gd.ellipse((1300, 650, 2200, 1350), fill=(255, 90, 170, 85))
    bg.alpha_composite(glow.filter(ImageFilter.GaussianBlur(140)))
    vig = Image.radial_gradient("L").resize((W, H)).point(lambda v: min(255, int(v * 0.85)))
    dark = Image.new("RGBA", (W, H), (8, 4, 18, 255))
    dark.putalpha(vig)
    bg.alpha_composite(dark)
    return bg


@lru_cache(maxsize=1)
def _logo(size: int) -> Optional[Image.Image]:
    try:
        im = ImageOps.fit(Image.open(config.LOGO_PATH).convert("RGB"), (size * 3, size * 3), Image.LANCZOS)
        mask = Image.new("L", im.size, 0)
        ImageDraw.Draw(mask).ellipse((0, 0, im.size[0] - 1, im.size[1] - 1), fill=255)
        out = Image.new("RGBA", im.size)
        out.paste(im, (0, 0), mask)
        return out.resize((size, size), Image.LANCZOS)
    except Exception as e:
        log.warning("logo unavailable: %s", e)
        return None


def _wrap(text: str, stack: Stack, size: int, max_w: int, spacing: float = 0) -> List[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if stack.width(trial, size, spacing) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _fit_title(title: str, stack: Stack, max_w: int, max_lines: int = 3):
    for size in range(88, 39, -4):
        lines = _wrap(title, stack, size, max_w)
        if len(lines) <= max_lines and all(stack.width(l, size) <= max_w for l in lines):
            return size, lines
    size = 40
    lines = _wrap(title, stack, size, max_w)[:max_lines]
    while lines and stack.width(lines[-1] + "…", size) > max_w:
        lines[-1] = lines[-1][:-1]
    if lines:
        lines[-1] = lines[-1].rstrip() + "…"
    return size, lines


def _short_desc(text: str, limit: int = 230) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:-") + " …"


# ------------------------------------------------------------------ banner
def render_banner(poster: Image.Image, backdrop: Image.Image, title: str, description: str) -> bytes:
    canvas = _background(backdrop or poster)

    # outer glass panel
    panel = (56, 56, W - 56, H - 56)
    _glass(canvas, panel, radius=46, blur=30, fill_alpha=26, border_alpha=80)

    # poster card (right)
    PW, PH = 560, 840
    px, py = W - 56 - 84 - PW, (H - PH) // 2
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((px, py + 26, px + PW, py + PH + 26), 24, fill=(0, 0, 0, 170))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(34)))
    card = _cover(poster, PW, PH).convert("RGBA")
    canvas.paste(card, (px, py), _rounded_mask((PW, PH), 24))
    ring = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    rd.rounded_rectangle((px, py, px + PW, py + PH), 24, outline=(255, 255, 255, 90), width=2)
    # corner brackets
    L, T = 74, 5
    bx0, by0 = px - 28, py - 28
    bx1, by1 = px + PW + 28, py + PH + 28
    rd.line((bx0, by0, bx0 + L, by0), fill=PURPLE + (255,), width=T)
    rd.line((bx0, by0, bx0, by0 + L), fill=PURPLE + (255,), width=T)
    rd.line((bx1, by1, bx1 - L, by1), fill=PURPLE + (255,), width=T)
    rd.line((bx1, by1, bx1, by1 - L), fill=PURPLE + (255,), width=T)
    canvas.alpha_composite(ring)

    # left column
    x0 = 132
    col_w = px - 70 - x0
    title_stack = _title_stack()
    inter_semi, inter = _inter("SemiBold"), _inter("Regular")

    t_size, t_lines = _fit_title(title.upper(), title_stack, col_w)
    t_line_h = int(t_size * 1.28)
    desc = _short_desc(description)
    d_size, d_line_h, d_pad_x, d_pad_y = 30, 48, 44, 34
    d_lines: List[str] = []
    if desc:
        d_lines = _wrap(desc, inter, d_size, col_w - 2 * d_pad_x)
        if len(d_lines) > 4:
            d_lines = d_lines[:4]
            while d_lines[-1] and inter.width(d_lines[-1] + " …", d_size) > col_w - 2 * d_pad_x:
                d_lines[-1] = d_lines[-1][:-1]
            d_lines[-1] = d_lines[-1].rstrip() + " …"
    d_box_h = len(d_lines) * d_line_h + 2 * d_pad_y if d_lines else 0

    pill_h, gap1, gap2 = 72, 52, 46
    total = pill_h + gap1 + len(t_lines) * t_line_h + (gap2 + d_box_h if d_lines else 0)
    y = max(110, (H - total) // 2)

    # channel pill: logo + name
    name = config.CHANNEL_NAME
    n_size, n_space = 30, 1.5
    logo = _logo(56)
    pill_w = 8 + (56 if logo else 0) + 20 + int(inter_semi.width(name, n_size, n_space)) + 40
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.rounded_rectangle((x0, y, x0 + pill_w, y + pill_h), pill_h // 2, fill=(124, 72, 214, 80), outline=PURPLE + (235,), width=2)
    canvas.alpha_composite(layer)
    cx = x0 + 8
    if logo:
        canvas.alpha_composite(logo, (cx, y + (pill_h - 56) // 2))
        cx += 56
    d = ImageDraw.Draw(canvas)
    inter_semi.draw(d, (cx + 20, y + (pill_h - n_size) // 2 - 6), name, n_size, (255, 255, 255, 255), n_space)
    y += pill_h + gap1

    # title with soft glow
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    ty = y
    for line in t_lines:
        title_stack.draw(gd, (x0, ty), line, t_size, (255, 255, 255, 150))
        ty += t_line_h
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(16)))
    d = ImageDraw.Draw(canvas)
    ty = y
    for line in t_lines:
        title_stack.draw(d, (x0, ty), line, t_size, (255, 255, 255, 255))
        ty += t_line_h
    y = ty + gap2 - 8

    # description in an inner glass box
    if d_lines:
        _glass(canvas, (x0, y, x0 + col_w, y + d_box_h), radius=30, blur=18, fill_alpha=30, border_alpha=70)
        d = ImageDraw.Draw(canvas)
        ly = y + d_pad_y - 2
        for line in d_lines:
            inter.draw(d, (x0 + d_pad_x, ly), line, d_size, (238, 232, 248, 255))
            ly += d_line_h

    out = io.BytesIO()
    canvas.convert("RGB").save(out, "JPEG", quality=92, optimize=True)
    return out.getvalue()


# ------------------------------------------------------------------ fetching + public API
MAX_IMAGE_BYTES = 12 * 1024 * 1024


async def _download(url: str) -> Optional[bytes]:
    s = await api_handler.get_session()
    headers = {"Accept": "image/avif,image/webp,image/*,*/*;q=0.8", "User-Agent": "Mozilla/5.0 (compatible; AnimeOngoingBot)"}
    async with s.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as r:
        if r.status != 200:
            log.warning("image %s -> HTTP %s", url, r.status)
            return None
        if r.content_length and r.content_length > MAX_IMAGE_BYTES:
            log.warning("image %s too large (%s bytes)", url, r.content_length)
            return None
        # r.read() waits for the WHOLE body (StreamReader.read(n) returns only what has arrived so far)
        raw = await r.read()
        if r.content_length and len(raw) < r.content_length:
            raise aiohttp.ClientPayloadError(f"short body {len(raw)}/{r.content_length}")
        return raw if len(raw) <= MAX_IMAGE_BYTES else None


async def fetch_image(url: str) -> Optional[Image.Image]:
    if not url or not url.startswith("http"):
        return None
    for attempt in (1, 2):  # one retry for flaky CDNs
        try:
            raw = await _download(url)
            if raw is None:
                return None
            return await asyncio.to_thread(lambda: Image.open(io.BytesIO(raw)).convert("RGB"))
        except Exception as e:
            log.warning("image fetch failed (try %s) %s: %s", attempt, url, e)
            await asyncio.sleep(0.8)
    return None


async def make_banner(a: "api_handler.Anime") -> Optional[io.BytesIO]:
    """Returns a JPEG BytesIO, or None if no image could be loaded (caller falls back to a text post)."""
    poster, backdrop = await asyncio.gather(fetch_image(a.poster), fetch_image(a.background))
    poster = poster or backdrop
    if poster is None:
        return None
    try:
        data = await asyncio.to_thread(render_banner, poster, backdrop or poster, a.title, a.description)
    except Exception:
        log.exception("banner render failed for %s", a.id)
        return None
    buf = io.BytesIO(data)
    buf.name = f"{a.id}_ep{a.episode}.jpg"
    return buf