"""Inline button callbacks: home / help / about / close, popup alerts, batch stop."""
import logging

from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified

import config
from Database.mongodata import db
from Plugins.chnl_handler import batch
from Plugins.logger_error_handler import safe
from Plugins.UI_design import about_text, help_text, nav_markup, start_markup, start_text, NO_PREVIEW

log = logging.getLogger("AnimeBot.callbacks")


async def _edit(cq, text: str, markup):
    try:
        if cq.message.photo:
            await cq.message.edit_caption(text, reply_markup=markup)
        else:
            await cq.message.edit_text(text, reply_markup=markup, link_preview_options=NO_PREVIEW)
    except MessageNotModified:
        pass


@Client.on_callback_query(filters.regex(r"^(home|help|about|close)$"))
@safe
async def nav_cb(client, cq):
    action = cq.data
    if action == "close":
        await cq.message.delete()
        return await cq.answer()
    if action == "home":
        await _edit(cq, start_text(cq.from_user.first_name or "there"), start_markup())
    elif action == "help":
        await _edit(cq, help_text(cq.from_user.id in config.OWNER_IDS), nav_markup())
    elif action == "about":
        await _edit(cq, about_text(), nav_markup())
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^alert:"))
@safe
async def alert_cb(client, cq):
    key = cq.data.split(":", 1)[1]
    text = (db.get("btn_alerts") or {}).get(key)
    if not text:
        return await cq.answer("This button is no longer available.", show_alert=True)
    await cq.answer(text, show_alert=True)


@Client.on_callback_query(filters.regex(r"^batch_stop$"))
@safe
async def batch_stop_cb(client, cq):
    if cq.from_user.id not in config.OWNER_IDS:
        return await cq.answer("Owner only.", show_alert=True)
    if not batch["running"]:
        return await cq.answer("No batch is running.")
    batch["cancel"] = True
    await cq.answer("Stopping after the current post...")