"""
AnimeOngoingBot entry point.
Starts: MongoDB -> web server (/health for Render) -> Kurigram client (plugins auto-load)
-> startup checks -> API poller -> keep-alive. Shuts everything down cleanly on SIGINT/SIGTERM.
"""
import asyncio
import logging
import signal
import time

from aiohttp import web
from pyrogram import Client, enums, idle

import config
from Plugins.logger_error_handler import alert, notify_bg, setup_logging

setup_logging()
log = logging.getLogger("AnimeBot")

from Database.mongodata import db  # noqa: E402
from Plugins import api_handler  # noqa: E402
from Plugins.chnl_handler import poller  # noqa: E402
from Plugins.UI_design import LINE, fmt_duration, sc  # noqa: E402


# ------------------------------------------------------------------ web server (Render health check)
async def start_web():
    if not config.WEB_SERVER:
        return None

    async def health(_):
        return web.json_response({
            "status": "ok",
            "bot": config.CHANNEL_NAME,
            "version": config.VERSION,
            "uptime": fmt_duration(time.time() - config.START_TIME),
            "posting": "paused" if db.get("paused") else "active",
        })

    app = web.Application()
    app.add_routes([web.get("/", health), web.get("/health", health)])
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, "0.0.0.0", config.PORT).start()
        log.info("web server listening on :%s", config.PORT)
    except OSError as e:
        log.warning("web server could not bind port %s: %s", config.PORT, e)
    return runner


async def keep_alive():
    """Render's free tier sleeps without inbound traffic; ping our own public URL."""
    url = f"{config.PUBLIC_URL}/health"
    while True:
        await asyncio.sleep(600)
        try:
            s = await api_handler.get_session()
            async with s.get(url) as r:
                log.debug("keep-alive %s -> %s", url, r.status)
        except Exception as e:
            log.warning("keep-alive failed: %s", e)


# ------------------------------------------------------------------ startup checks
async def check_channel(app: Client):
    try:
        chat = await app.get_chat(config.CHANNEL_ID)
        member = await app.get_chat_member(config.CHANNEL_ID, "me")
        can_post = getattr(getattr(member, "privileges", None), "can_post_messages", None)
        if member.status != enums.ChatMemberStatus.ADMINISTRATOR and member.status != enums.ChatMemberStatus.OWNER:
            raise RuntimeError("the bot is not an admin of the channel")
        if can_post is False:
            raise RuntimeError("the bot is admin but lacks the 'Post messages' permission")
        log.info("channel OK: %s", chat.title)
    except Exception as e:
        await alert(app, "Channel check failed", f"{config.CHANNEL_ID}: {e}\nAdd the bot as admin with permission to post.", key="channel-check")


async def announce_start(app: Client, me):
    note = db.get("restart_notify")
    text = (
        f"❐ <b>{sc('Bot online')}</b>\n{LINE}\n›› @{me.username} · v{config.VERSION}\n"
        f"›› {sc('Posting')} : {sc('paused') if db.get('paused') else sc('active')} · {db.get('interval')}{sc('s')}"
    )
    if note:
        await db.set("restart_notify", None)
        took = time.time() - note.get("ts", time.time())
        try:
            await app.edit_message_text(note["chat_id"], note["message_id"], f"❐ <b>{sc('Restarted')}</b> · {took:.0f}{sc('s')}\n{LINE}\n›› {sc('All settings kept.')} {sc('Posting')} : {sc('paused') if db.get('paused') else sc('active')}")
            return
        except Exception as e:
            log.warning("could not edit restart message: %s", e)
    for owner in config.OWNER_IDS:
        try:
            await app.send_message(owner, text)
        except Exception as e:
            log.info("startup DM to %s not delivered (owner must press /start once): %s", owner, e)


# ------------------------------------------------------------------ main
async def main():
    loop = asyncio.get_running_loop()
    app = Client(
        config.SESSION_NAME,
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        bot_token=config.BOT_TOKEN,
        plugins=dict(root="Plugins"),
        workdir=config.BASE_DIR,
        in_memory=True,
        parse_mode=enums.ParseMode.HTML,
        sleep_threshold=60,
        workers=16,
    )

    def on_loop_error(_loop, ctx):
        err = ctx.get("exception")
        log.error("unhandled asyncio error: %s", ctx.get("message"), exc_info=err)
        notify_bg(app, "Unhandled asyncio error", str(ctx.get("message")), key="asyncio", exc=err)

    loop.set_exception_handler(on_loop_error)

    await db.connect()
    log.info("MongoDB connected")
    web_runner = await start_web()

    await app.start()
    me = await app.get_me()
    log.info("started as @%s (Kurigram, plugins loaded)", me.username)

    await check_channel(app)
    poller.start(app)
    ka_task = asyncio.create_task(keep_alive()) if (config.KEEP_ALIVE and config.PUBLIC_URL) else None
    await announce_start(app, me)

    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass
    idle_task = asyncio.create_task(idle())
    await asyncio.wait({idle_task, asyncio.create_task(stop.wait())}, return_when=asyncio.FIRST_COMPLETED)

    log.info("shutting down...")
    if ka_task:
        ka_task.cancel()
    await poller.stop()
    await api_handler.close_session()
    await db.close()
    if web_runner:
        await web_runner.cleanup()
    try:
        await app.stop()
    except Exception:
        pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
