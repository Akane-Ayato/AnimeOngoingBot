"""
Owner settings & control: /pause /resume /set_int /set_sticker /post_design /status /restart
All values persist in MongoDB, so a /restart never changes any of them.
"""
import asyncio
import logging
import os
import platform
import sys
import time

import psutil
import pyrogram
from pyrogram import Client, filters

import config
from Database.mongodata import db
from Plugins import api_handler as api
from Plugins import postmaker
from Plugins.buttonhandler import PENDING, expect, register_pending
from Plugins import manhwa_handler, tempfiles
from Plugins.chnl_handler import poller
from Plugins.manhwa_handler import manhwa_poller
from Plugins.logger_error_handler import safe
from Plugins.UI_design import (
    DEFAULT_STYLE, LINE, SAMPLE_VALUES, esc, fmt_bytes, fmt_duration, kv, post_design_prompt, render_caption, sc, tg_len, NO_PREVIEW,
)

log = logging.getLogger("AnimeBot.settings")
OWN = filters.private & config.owner_only


# ------------------------------------------------------------------ pause / resume / interval
@Client.on_message(filters.command("pause") & OWN)
@safe
async def pause_cmd(client, message):
    if db.get("paused"):
        return await message.reply_text(f"❐ {sc('Already paused.')}")
    await db.set("paused", True)
    await message.reply_text(
        f"❐ <b>{sc('Posting paused')}</b>\n{LINE}\n›› {sc('Api checking is stopped, nothing will be posted on the channel.')}\n"
        f"›› {sc('Manual /post and /batch_post still work. Use /resume to continue.')}"
    )


@Client.on_message(filters.command("resume") & OWN)
@safe
async def resume_cmd(client, message):
    if not db.get("paused"):
        return await message.reply_text(f"❐ {sc('Posting is already active.')}")
    await db.set("paused", False)
    poller.poke()
    manhwa_poller.poke()
    await message.reply_text(
        f"❐ <b>{sc('Posting resumed')}</b>\n{LINE}\n›› {sc('Checking the api now, then every')} {db.get('interval')}{sc('s.')}"
    )


@Client.on_message(filters.command("set_int") & OWN)
@safe
async def set_int_cmd(client, message):
    arg = message.command[1] if len(message.command) > 1 else ""
    if not arg.isdigit():
        return await message.reply_text(
            f"❐ <b>{sc('Usage')}</b> <code>/set_int 300</code>\n›› {sc('Now')} : {db.get('interval')}{sc('s')} "
            f"({sc('min')} {config.MIN_INTERVAL}{sc('s')})"
        )
    seconds = int(arg)
    if seconds < config.MIN_INTERVAL or seconds > 86400:
        return await message.reply_text(f"❐ {sc('Pick a value between')} {config.MIN_INTERVAL} {sc('and')} 86400 {sc('seconds.')}")
    await db.set("interval", seconds)
    poller.poke()
    manhwa_poller.poke()
    await message.reply_text(f"❐ <b>{sc('Interval set')}</b> : {seconds}{sc('s')}\n›› {sc('Running a check now with the new interval.')}")


# ------------------------------------------------------------------ sticker
@Client.on_message(filters.command("set_sticker") & OWN)
@safe
async def set_sticker_cmd(client, message):
    arg = message.command[1].lower() if len(message.command) > 1 else ""
    if arg in ("reset", "clear", "off"):
        await db.set("sticker_id", None)
        return await message.reply_text(f"❐ {sc('Sticker removed. Posts are sent without one.')}")
    reply = message.reply_to_message
    if not reply or not reply.sticker:
        state = sc("a sticker is set") if db.get("sticker_id") else sc("no sticker set")
        return await message.reply_text(
            f"❐ <b>{sc('Set sticker')}</b>\n{LINE}\n›› {sc('Reply to a sticker with /set_sticker.')}\n"
            f"›› {sc('Use /set_sticker reset to remove it.')}\n›› {sc('Now')} : {state}"
        )
    await db.set("sticker_id", reply.sticker.file_id)
    await message.reply_text(f"❐ <b>{sc('Sticker saved')}</b>\n›› {sc('It will be sent after every anime post.')}")
    try:
        await message.reply_sticker(reply.sticker.file_id)
    except Exception:
        pass


# ------------------------------------------------------------------ post design
async def _save_design(client, message, template: str):
    template = template.strip()
    if not template:
        return await message.reply_text(f"❐ {sc('That message is empty.')}")
    shell = render_caption(template, {**SAMPLE_VALUES, "description": ""}, limit=10**6)
    if tg_len(shell) > 1000:
        return await message.reply_text(f"❐ {sc('The design alone is too long for a caption (max 1024). Shorten it.')}")
    preview = render_caption(template, SAMPLE_VALUES)
    try:
        await message.reply_text(preview, link_preview_options=NO_PREVIEW)
    except Exception as e:
        return await message.reply_text(f"❐ <b>{sc('Telegram rejected this design')}</b>\n<pre>{esc(e)}</pre>")
    await db.set("post_style", template)
    PENDING.pop(message.from_user.id, None)
    note = "" if "{title}" in template else f"\n›› {sc('Note: your design has no')} <code>{{title}}</code>."
    await message.reply_text(f"❐ <b>{sc('Post design saved')}</b>{note}\n›› {sc('The message above is a preview with sample data.')}")


async def _capture_design(client, message):
    await _save_design(client, message, message.text.html)


register_pending("post_design", _capture_design)


@Client.on_message(filters.command("post_design") & OWN)
@safe
async def post_design_cmd(client, message):
    arg = message.command[1].lower() if len(message.command) > 1 else ""
    if arg in ("reset", "default"):
        await db.set("post_style", None)
        return await message.reply_text(f"❐ {sc('Back to the default post style.')}")
    if arg == "show":
        style = db.get("post_style") or DEFAULT_STYLE
        return await message.reply_text(f"❐ <b>{sc('Current style')}</b>\n<pre>{esc(style)}</pre>")
    reply = message.reply_to_message
    if reply and (reply.text or reply.caption):
        src = reply.text or reply.caption
        return await _save_design(client, message, src.html)
    expect(message.from_user.id, "post_design")
    await message.reply_text(post_design_prompt(db.get("post_style")), link_preview_options=NO_PREVIEW)


# ------------------------------------------------------------------ /status
def _state(h: dict) -> str:
    if h["ok"]:
        return f"◉ {sc('online')} · {h['status']} · {h['ms']:.0f}ms"
    why = h["error"] or f"HTTP {h['status']}"
    return f"○ {sc('down')} · {esc(why)}"


@Client.on_message(filters.command("status") & OWN)
@safe
async def status_cmd(client, message):
    t0 = time.perf_counter()
    status = await message.reply_text(f"❐ {sc('Collecting status...')}")
    tg_ms = (time.perf_counter() - t0) * 1000
    site, up, mup, dbp = await asyncio.gather(
        api.site_health(), api.api_health(), api.manhwa_health(), db.ping()
    )

    proc = psutil.Process()
    vm = psutil.virtual_memory()
    try:
        du = psutil.disk_usage(config.BASE_DIR)
        disk = f"{fmt_bytes(du.used)} / {fmt_bytes(du.total)} ({du.percent:.0f}%)"
    except Exception:
        disk = "n/a"
    now = time.time()
    if db.get("paused"):
        post_state = f"⏸ {sc('paused')}"
    else:
        nxt = f"{max(0, int(poller.next_check - now))}s" if poller.next_check else "…"
        post_state = f"▶ {sc('active')} · {sc('next check in')} {nxt}"
    last = f"{fmt_duration(now - poller.last_check)} {sc('ago')}" if poller.last_check else sc("never")
    if not manhwa_handler.enabled():
        manhwa_line = f"○ {sc('disabled (MANHWA_CHANNEL_ID not set)')}"
    else:
        m_last = f"{fmt_duration(now - manhwa_poller.last_check)} {sc('ago')}" if manhwa_poller.last_check else sc("never")
        manhwa_line = (
            f"{post_state.split(' ·')[0]} · {sc('last check')} {m_last} · {esc(manhwa_poller.last_result)} · "
            f"{sc('posted this session')} {manhwa_poller.posted_session} · {sc('titles')} {await db.count_manhwa_known()}"
        )
    tmp_n, tmp_b = tempfiles.usage()
    web = config.PUBLIC_URL or (f"http://localhost:{config.PORT}" if config.WEB_SERVER else sc("disabled"))

    text = (
        f"<blockquote>❐ <b>{sc('Bot status')}</b></blockquote>\n{LINE}\n"
        f"<blockquote>{kv('Site', _state(site))}\n"
        f"{kv('Anime api', _state(up))}\n"
        f"{kv('Manhwa api', _state(mup))}\n"
        f"{kv('Database', ('◉ ' + sc('online') + f' · {dbp:.0f}ms') if dbp is not None else '○ ' + sc('down'))}\n"
        f"{kv('Telegram', '◉ ' + sc('online') + f' · {tg_ms:.0f}ms')}</blockquote>\n{LINE}\n"
        f"<blockquote>{kv('Posting', post_state)}\n"
        f"{kv('Interval', str(db.get('interval')) + 's')}\n"
        f"{kv('Last check', last + ' · ' + esc(poller.last_result))}\n"
        f"{kv('Checks', str(poller.cycles))} · {sc('posted this session')} {poller.posted_session}\n"
        f"{kv('Manhwa', manhwa_line)}\n"
        f"{kv('Users', str(await db.count_users()))} · {sc('posts')} {await db.count_posted()} · {sc('known shows')} {await db.count_known()}</blockquote>\n{LINE}\n"
        f"<blockquote expandable>{kv('Version', config.VERSION)}\n"
        f"{kv('Uptime', fmt_duration(now - config.START_TIME))}\n"
        f"{kv('Host', config.host_type() + ' · ' + platform.system())}\n"
        f"{kv('Web server', esc(web))}\n"
        f"{kv('Python', platform.python_version())} · Kurigram {pyrogram.__version__}\n"
        f"{kv('Bot RAM', fmt_bytes(proc.memory_info().rss))}\n"
        f"{kv('System RAM', f'{fmt_bytes(vm.used)} / {fmt_bytes(vm.total)} ({vm.percent:.0f}%)')}\n"
        f"{kv('CPU', f'{psutil.cpu_percent(interval=None):.0f}%')}\n"
        f"{kv('Storage', disk)}\n"
        f"{kv('Temp files', f'{tmp_n} · {fmt_bytes(tmp_b)} · ' + sc('auto-deleted after') + f' {config.TMP_TTL // 60}m')}\n"
        f"{kv('Custom style', sc('yes') if db.get('post_style') else sc('default'))} · "
        f"{sc('sticker')} {sc('yes') if db.get('sticker_id') else sc('no')} · "
        f"{sc('anime buttons')} {sum(len(r) for r in db.get('c_btn_rows') or [])} · "
        f"{sc('manhwa buttons')} {sum(len(r) for r in db.get('m_btn_rows') or [])}</blockquote>"
    )
    await status.edit_text(text, link_preview_options=NO_PREVIEW)


# ------------------------------------------------------------------ /restart
async def _restart_now(client):
    await asyncio.sleep(1.0)
    log.warning("restarting process on owner request")
    for step in (poller.stop(), manhwa_poller.stop(), api.close_session(), db.close()):
        try:
            await asyncio.wait_for(step, 5)
        except Exception:
            pass
    try:
        await asyncio.wait_for(client.stop(block=False), 8)
    except Exception:
        pass
    try:
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception:
        log.exception("execv failed, exiting so the supervisor can restart us")
        os._exit(3)


@Client.on_message(filters.command("restart") & OWN)
@safe
async def restart_cmd(client, message):
    note = await message.reply_text(
        f"❐ <b>{sc('Restarting...')}</b>\n›› {sc('Settings and data stay untouched.')}"
    )
    await db.set("restart_notify", {"chat_id": note.chat.id, "message_id": note.id, "ts": time.time()})
    asyncio.create_task(_restart_now(client))