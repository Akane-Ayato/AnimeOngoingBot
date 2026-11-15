"""Small Telegram helpers shared by the anime and manhwa posting engines."""
import asyncio
import logging

from pyrogram.errors import FloodWait

log = logging.getLogger("AnimeBot.tg")


async def flood_safe(coro_fn, *args, **kwargs):
    """Run a Telegram call, sleeping through FloodWait (up to 3 times)."""
    for _ in range(3):
        try:
            return await coro_fn(*args, **kwargs)
        except FloodWait as e:
            log.warning("FloodWait %ss", e.value)
            await asyncio.sleep(e.value + 1)
    return await coro_fn(*args, **kwargs)
