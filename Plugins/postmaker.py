"""
Post maker: caption values for the anime and manhwa posts, image download (temp files that are
deleted after TMP_TTL seconds) and poster rendering with the new designs.
  anime  -> Plugins/poster_anime.py   (white / red corner design, API poster in a cover card)
  manhwa -> Plugins/poster_manhwa.py  (red block + landscape cover card, MMWC VOID header)
Rendering runs in a worker thread, one poster at a time, so the bot stays responsive and
RAM stays low on small hosts.
"""
import asyncio
import html
import logging
import os
from typing import List, Optional
from urllib.parse import quote

import aiohttp
from PIL import Image, ImageFile

import config
from Plugins import api_handler, poster_anime, poster_manhwa, tempfiles
from Plugins.textclean import clean_text
from Plugins.UI_design import esc, render_caption, sc

log = logging.getLogger("AnimeBot.postmaker")

ImageFile.LOAD_TRUNCATED_IMAGES = True   # render what we have rather than lose the poster
MAX_IMAGE_BYTES = 12 * 1024 * 1024
_render_sem = asyncio.Semaphore(1)


# ------------------------------------------------------------------ anime caption
def watch_url(anime_id) -> str:
    return f"{config.SITE_URL}/watch.html?id={anime_id}"


def build_values(a: "api_handler.Anime") -> dict:
    na = "N/A"
    return {
        "title": esc(a.title),
        "episode": str(a.episode if a.episode is not None else "?"),
        "language": sc("Dual") if a.language == "Dual" else sc("Sub") + " | E-" + sc("Sub"),
        "status": esc(sc(a.status)),
        "description": esc(clean_text(a.description) or "No synopsis available."),
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


def build_caption(a: "api_handler.Anime", template: Optional[str] = None) -> str:
    return render_caption(template, build_values(a))


# ------------------------------------------------------------------ manhwa caption
def series_url(m: "api_handler.Manhwa") -> str:
    return f"{config.MANHWA_SITE}/title/{quote(m.slug, safe='-._~')}"


def chapter_url(m: "api_handler.Manhwa") -> str:
    return f"{series_url(m)}/chapter/{quote(m.chapter, safe='-._~')}"


def build_manhwa_caption(m: "api_handler.Manhwa") -> str:
    title = esc(m.title)[:400]
    ch = html.escape(chapter_url(m), quote=True)
    sr = html.escape(series_url(m), quote=True)
    return (
        f"<blockquote><b>{title}</b></blockquote>\n"
        f"» <b><a href=\"{ch}\">{sc('Chapter')} {esc(m.chapter)}</a> {sc('Updated')}</b>\n"
        f"» <b><a href=\"{sr}\">{sc('Read Here')}</a></b>"
    )


# ------------------------------------------------------------------ image download (temp files)
async def download_image(url: str) -> Optional[str]:
    """Download to TMP_DIR and return the file path. The janitor deletes it after TMP_TTL seconds."""
    if not url or not url.startswith("http"):
        return None
    headers = {"Accept": "image/avif,image/webp,image/*,*/*;q=0.8", "User-Agent": "Mozilla/5.0 (compatible; AnimeOngoingBot)"}
    for attempt in (1, 2):                                   # one retry for flaky CDNs
        path = tempfiles.new_path(".img")
        try:
            s = await api_handler.get_session()
            async with s.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=25)) as r:
                if r.status != 200:
                    log.warning("image %s -> HTTP %s", url, r.status)
                    return None
                if r.content_length and r.content_length > MAX_IMAGE_BYTES:
                    log.warning("image %s too large (%s bytes)", url, r.content_length)
                    return None
                size = 0
                with open(path, "wb") as f:
                    async for chunk in r.content.iter_chunked(65536):
                        size += len(chunk)
                        if size > MAX_IMAGE_BYTES:
                            raise ValueError("image too large")
                        f.write(chunk)
                if r.content_length and size < r.content_length:
                    raise aiohttp.ClientPayloadError(f"short body {size}/{r.content_length}")
            return path
        except Exception as e:
            log.warning("image download failed (try %s) %s: %s", attempt, url, e)
            try:
                os.remove(path)
            except OSError:
                pass
            await asyncio.sleep(0.8)
    return None


def _open_rgb(path: str) -> Image.Image:
    with Image.open(path) as im:
        return im.convert("RGB")


async def load_first(urls: List[str]) -> Optional[Image.Image]:
    """Try each URL in order until one downloads and decodes."""
    for url in urls:
        path = await download_image(url)
        if not path:
            continue
        try:
            return await asyncio.to_thread(_open_rgb, path)
        except Exception as e:
            log.warning("image %s could not be decoded: %s", url, e)
    return None


# ------------------------------------------------------------------ rendering
def _render_to_file(fn, meta: dict, cover: Image.Image) -> str:
    img = fn(meta, cover)
    path = tempfiles.new_path(".jpg")
    img.save(path, "JPEG", quality=92, optimize=True)
    return path


async def _render(fn, meta: dict, cover: Image.Image) -> Optional[str]:
    async with _render_sem:
        try:
            return await asyncio.to_thread(_render_to_file, fn, meta, cover)
        except Exception:
            log.exception("poster render failed for %r", meta.get("title"))
            return None


async def make_poster(a: "api_handler.Anime") -> Optional[str]:
    """Anime poster file path (in TMP_DIR), or None -> caller falls back to a text post."""
    cover = await load_first([a.poster, a.background])
    if cover is None:
        return None
    meta = {"title": a.title, "genres": a.genres, "description": clean_text(a.description, 330)}
    return await _render(poster_anime.render_poster, meta, cover)


async def make_manhwa_poster(m: "api_handler.Manhwa") -> Optional[str]:
    cover = await load_first(m.covers)
    if cover is None:
        return None
    meta = {
        "title": m.title,
        "genres": m.genres,
        "score": int(round(m.rating * 10)) if m.rating else None,
        "description": clean_text(m.description, 330),
    }
    return await _render(poster_manhwa.render_poster, meta, cover)
