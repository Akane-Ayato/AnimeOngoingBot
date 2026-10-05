"""
Button maker: parses the /c_btn syntax, builds the post keyboard
([Watch Now] + custom rows) and owns the 'next message' capture used by
/c_btn and /post_design.
"""
import hashlib
import logging
import re
import time
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
from Database.mongodata import db
from Plugins.logger_error_handler import safe
from Plugins.UI_design import C_BTN_PROMPT, LINE, esc, sc, NO_PREVIEW

log = logging.getLogger("AnimeBot.buttons")

MAIN_LABEL = "▷ " + sc("Watch Now")
_URL = re.compile(r"^(.+?)\s+-\s+((?:https?://|tg://)\S+)$", re.I)
_ALERT = re.compile(r"^(.+?)\s+-\s+(.+)$", re.S)
MAX_PER_ROW = 3


# ------------------------------------------------------------------ parsing
def parse_buttons(raw: str) -> Tuple[List[List[dict]], Dict[str, str], List[str]]:
    rows: List[List[dict]] = []
    alerts: Dict[str, str] = {}
    errors: List[str] = []
    for n, line in enumerate(raw.strip().splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        cells = [c.strip() for c in line.split("|") if c.strip()]
        if len(cells) > MAX_PER_ROW:
            errors.append(f"line {n}: max {MAX_PER_ROW} buttons per row")
            continue
        row = []
        for cell in cells:
            m = _URL.match(cell)
            if m:
                row.append({"text": m.group(1).strip()[:60], "url": m.group(2).strip()})
                continue
            m = _ALERT.match(cell)
            if m:
                text, popup = m.group(1).strip()[:60], m.group(2).strip()[:200]
                key = hashlib.md5(f"{text}|{popup}".encode()).hexdigest()[:10]
                alerts[key] = popup
                row.append({"text": text, "alert": key})
                continue
            errors.append(f"line {n}: '{cell[:30]}' needs the format  text - link  or  text - popup text")
        if row:
            rows.append(row)
    return rows, alerts, errors


def rows_to_markup(rows: List[List[dict]]) -> List[List[InlineKeyboardButton]]:
    out = []
    for row in rows:
        btns = []
        for b in row:
            if b.get("url"):
                btns.append(InlineKeyboardButton(b["text"], url=b["url"]))
            else:
                btns.append(InlineKeyboardButton(b["text"], callback_data=f"alert:{b['alert']}"))
        out.append(btns)
    return out


def build_markup(anime_id, use_custom: bool = True) -> InlineKeyboardMarkup:
    """[Watch Now] on its own row, custom rows below it (when any are set)."""
    from Plugins.postmaker import watch_url  # local import avoids a cycle at plugin load
    keyboard = [[InlineKeyboardButton(MAIN_LABEL, url=watch_url(anime_id))]]
    if use_custom:
        keyboard += rows_to_markup(db.get("c_btn_rows") or [])
    return InlineKeyboardMarkup(keyboard)


# ------------------------------------------------------------------ "send me the next message" capture
PENDING: Dict[int, dict] = {}
PENDING_TTL = 600
_handlers: Dict[str, Callable[..., Awaitable]] = {}


def expect(user_id: int, kind: str):
    PENDING[user_id] = {"kind": kind, "ts": time.time()}


def register_pending(kind: str, fn: Callable[..., Awaitable]):
    _handlers[kind] = fn


def _not_command(_, __, m) -> bool:
    return bool(m.text and not m.text.startswith("/"))


plain_text = filters.create(_not_command, "PlainText")


@Client.on_message(filters.private & config.owner_only & plain_text, group=5)
@safe
async def capture_next(client, message):
    state = PENDING.get(message.from_user.id)
    if not state:
        return
    if time.time() - state["ts"] > PENDING_TTL:
        PENDING.pop(message.from_user.id, None)
        return await message.reply_text(f"❐ {sc('That request expired. Run the command again.')}")
    fn = _handlers.get(state["kind"])
    if fn:
        await fn(client, message)


@Client.on_message(filters.command("cancel") & filters.private & config.owner_only)
@safe
async def cancel_cmd(client, message):
    had = PENDING.pop(message.from_user.id, None)
    await message.reply_text(f"❐ {sc('Cancelled.') if had else sc('Nothing to cancel.')}")


# ------------------------------------------------------------------ /c_btn
async def apply_buttons(client, message, raw: str) -> bool:
    rows, alerts, errors = parse_buttons(raw)
    if errors or not rows:
        msg = "\n".join(f"›› {esc(e)}" for e in errors) or f"›› {sc('No buttons found.')}"
        await message.reply_text(f"❐ <b>{sc('Could not read the buttons')}</b>\n{LINE}\n{msg}")
        return False
    preview = InlineKeyboardMarkup([[InlineKeyboardButton(MAIN_LABEL, url=config.SITE_URL)]] + rows_to_markup(rows))
    try:  # Telegram is the final validator: if it accepts the preview, it will accept the post
        await message.reply_text(f"❐ <b>{sc('Preview')}</b>", reply_markup=preview)
    except Exception as e:
        await message.reply_text(f"❐ <b>{sc('Telegram rejected these buttons')}</b>\n<pre>{esc(e)}</pre>")
        return False
    await db.set("c_btn_raw", raw.strip())
    await db.set("c_btn_rows", rows)
    await db.set("btn_alerts", alerts)
    total = sum(len(r) for r in rows)
    await message.reply_text(f"❐ <b>{sc('Saved')}</b> — {total} {sc('custom buttons in')} {len(rows)} {sc('rows.')}")
    return True


async def _capture_c_btn(client, message):
    if await apply_buttons(client, message, message.text):
        PENDING.pop(message.from_user.id, None)


register_pending("c_btn", _capture_c_btn)


@Client.on_message(filters.command("c_btn") & filters.private & config.owner_only)
@safe
async def c_btn_cmd(client, message):
    args = message.text.split(None, 1)
    arg = args[1].strip() if len(args) > 1 else ""

    if arg.lower() == "clear":
        await db.set("c_btn_raw", None)
        await db.set("c_btn_rows", [])
        await db.set("btn_alerts", {})
        return await message.reply_text(f"❐ {sc('Custom buttons removed. Posts now carry only the Watch Now button.')}")

    if arg.lower() == "show":
        raw = db.get("c_btn_raw")
        if not raw:
            return await message.reply_text(f"❐ {sc('No custom buttons are set.')}")
        return await message.reply_text(f"❐ <b>{sc('Current custom buttons')}</b>\n<pre>{esc(raw)}</pre>")

    if message.reply_to_message and (message.reply_to_message.text or message.reply_to_message.caption):
        raw = message.reply_to_message.text or message.reply_to_message.caption
        return await apply_buttons(client, message, raw)

    if arg:
        return await apply_buttons(client, message, args[1])

    expect(message.from_user.id, "c_btn")
    await message.reply_text(C_BTN_PROMPT, link_preview_options=NO_PREVIEW)