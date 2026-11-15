"""/start (registers users) and /help, with a random image from the IMG config."""
import logging
import random

from pyrogram import Client, filters

import config
from Database.mongodata import db
from Plugins.logger_error_handler import safe
from Plugins.UI_design import help_text, nav_markup, sc, start_markup, start_text, NO_PREVIEW

log = logging.getLogger("AnimeBot.start")


def pick_img():
    return random.choice(config.IMG) if config.IMG else None


async def send_screen(message, text: str, markup):
    """Photo + caption + buttons; if the image is dead, fall back to plain text."""
    img = pick_img()
    if img:
        try:
            return await message.reply_photo(img, caption=text, reply_markup=markup)
        except Exception as e:
            log.warning("start/help image failed (%s): %s", img, e)
    return await message.reply_text(text, reply_markup=markup, link_preview_options=NO_PREVIEW)


@Client.on_message(filters.command("start") & filters.private)
@safe
async def start_cmd(client, message):
    user = message.from_user
    if not user:
        return
    is_new = await db.add_user(user)
    if is_new:
        log.info("new user %s (@%s)", user.id, user.username)
    await send_screen(message, start_text(user.first_name or "there"), start_markup())


@Client.on_message(filters.command("help") & filters.private)
@safe
async def help_cmd(client, message):
    user = message.from_user
    if user:
        await db.add_user(user)
    await send_screen(message, help_text(bool(user and user.id in config.OWNER_IDS)), nav_markup())


OWNER_COMMANDS = [
    "pause", "resume", "check", "status", "logs", "post", "batch_post", "set_int",
    "post_design", "set_sticker", "c_btn", "m_btn", "restart", "cancel",
]


@Client.on_message(filters.command(OWNER_COMMANDS) & filters.private & ~config.owner_only)
@safe
async def not_owner(client, message):
    await message.reply_text(f"❐ {sc('Only the owner can use this command.')}")