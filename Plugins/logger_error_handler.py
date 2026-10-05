"""
Logging (rotating file + console), owner error alerts (throttled), the @safe
handler wrapper and the /logs command.
"""
import asyncio
import functools
import glob
import html
import io
import logging
import os
import time
import traceback
import zipfile
from logging.handlers import RotatingFileHandler

from pyrogram import Client, filters

import config
from Plugins.UI_design import LINE, esc, sc, NO_PREVIEW

log = logging.getLogger("AnimeBot")
_last_alert: dict = {}
ALERT_COOLDOWN = 600  # same alert key at most once per 10 minutes


def setup_logging():
    os.makedirs(config.LOG_DIR, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    file_h = RotatingFileHandler(config.LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    file_h.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(file_h)
    root.addHandler(console)
    for noisy in ("pyrogram", "aiohttp", "motor", "pymongo", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def alert(client, title: str, detail: str = "", key: str = None, exc: BaseException = None):
    """Log the problem and DM it to every owner (and LOG_CHANNEL). Throttled per key."""
    if exc is not None:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        detail = (detail + "\n" if detail else "") + tb
    log.error("ALERT %s | %s", title, detail[-1500:] if detail else "")

    key = key or title
    now = time.time()
    if now - _last_alert.get(key, 0) < ALERT_COOLDOWN:
        return
    _last_alert[key] = now

    body = html.escape(detail[-2500:]) if detail else ""
    text = f"<blockquote>❐ <b>{sc('Error alert')}</b></blockquote>\n{LINE}\n›› <b>{esc(title)}</b>"
    if body:
        text += f"\n<pre>{body}</pre>"
    text += f"\n{LINE}\n≡ {sc('Check /logs for the full trace.')}"

    targets = list(config.OWNER_IDS) + ([config.LOG_CHANNEL] if config.LOG_CHANNEL else [])
    for chat in targets:
        try:
            await client.send_message(chat, text, link_preview_options=NO_PREVIEW)
        except Exception as e:  # owner never pressed /start, bot blocked, bad channel...
            log.warning("could not deliver alert to %s: %s", chat, e)


def notify_bg(client, title: str, detail: str = "", key: str = None, exc: BaseException = None):
    """Fire-and-forget alert from sync code."""
    try:
        asyncio.get_running_loop().create_task(alert(client, title, detail, key, exc))
    except RuntimeError:
        log.error("ALERT %s | %s", title, detail)


def safe(func):
    """Wrap a handler: log + alert on crashes and tell the user something sane."""
    @functools.wraps(func)
    async def wrapper(client, update, *args, **kwargs):
        try:
            return await func(client, update, *args, **kwargs)
        except Exception as e:
            await alert(client, f"Handler crashed: {func.__name__}", exc=e, key=f"handler:{func.__name__}")
            try:
                text = f"❐ <b>{sc('Something went wrong')}</b>\n{sc('The error was logged and sent to the owner.')}"
                if hasattr(update, "reply_text"):
                    await update.reply_text(text)
                elif hasattr(update, "answer"):
                    await update.answer("Something went wrong", show_alert=True)
            except Exception:
                pass
    return wrapper


@Client.on_message(filters.command("logs") & filters.private & config.owner_only)
@safe
async def logs_cmd(client, message):
    files = sorted(glob.glob(config.LOG_FILE + "*"))
    if not files:
        return await message.reply_text(f"❐ {sc('No log file yet.')}")
    if len(files) == 1:
        return await message.reply_document(files[0], caption=f"❐ <b>{sc('Complete log file')}</b>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, os.path.basename(f))
    buf.seek(0)
    buf.name = "bot-logs.zip"
    await message.reply_document(buf, caption=f"❐ <b>{sc('Complete logs')}</b> ({len(files)} {sc('files')})")