"""
Channel posting engine.
  - post_anime():   banner + caption + buttons + sticker, with a fallback ladder
  - Poller:         interval API checking, dedupe, seeding, pause/resume, health alerts
  - /post /batch_post /check commands
One asyncio.Lock guards every posting path so the poller, /post and /batch_post
can never post the same anime twice or interleave.
"""
import asyncio
import logging
import time
from typing import List, Optional

from pyrogram import Client, filters
from pyrogram.errors import FloodWait, RPCError
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
from Database.mongodata import db
from Plugins import api_handler as api
from Plugins import postmaker
from Plugins.buttonhandler import build_markup
from Plugins.logger_error_handler import alert, safe
from Plugins.UI_design import LINE, esc, fmt_duration, sc, NO_PREVIEW

log = logging.getLogger("AnimeBot.channel")


# ------------------------------------------------------------------ sending
async def _flood_safe(coro_fn, *args, **kwargs):
    """Run a Telegram call, sleeping through FloodWait (up to 3 times)."""
    for _ in range(3):
        try:
            return await coro_fn(*args, **kwargs)
        except FloodWait as e:
            log.warning("FloodWait %ss", e.value)
            await asyncio.sleep(e.value + 1)
    return await coro_fn(*args, **kwargs)


async def post_anime(client, anime: api.Anime, source: str = "auto"):
    """
    Posts one anime episode to the channel. Fallback ladder:
      1. banner + custom style + custom buttons
      2. banner + default style + Watch Now only      (bad template / bad buttons)
      3. text post with the default style             (no image / photo upload failed)
    Returns the sent Message. Raises only if even the text post fails.
    """
    banner = await postmaker.make_banner(anime)
    custom_style = db.get("post_style")
    attempts = []
    if banner is not None:
        attempts.append(("banner+custom", True, custom_style, True))
        if custom_style or db.get("c_btn_rows"):
            attempts.append(("banner+default", True, None, False))
    attempts.append(("text-only", False, None, False))

    last_err: Optional[Exception] = None
    for label, with_photo, style, custom_btns in attempts:
        caption = postmaker.build_caption(anime, style)
        markup = build_markup(anime.id, use_custom=custom_btns)
        try:
            if with_photo:
                banner.seek(0)
                msg = await _flood_safe(
                    client.send_photo, config.CHANNEL_ID, banner, caption=caption, reply_markup=markup
                )
            else:
                msg = await _flood_safe(
                    client.send_message, config.CHANNEL_ID, caption, reply_markup=markup, link_preview_options=NO_PREVIEW
                )
            if label != attempts[0][0]:
                log.warning("posted %s via fallback '%s' (last error: %s)", anime.title, label, last_err)
                await alert(client, f"Post used fallback '{label}'", f"{anime.title} ep {anime.episode}: {last_err}", key=f"fallback:{label}")
            await _after_post(client, anime, msg)
            return msg
        except RPCError as e:
            last_err = e
            log.warning("send attempt '%s' failed for %s: %s", label, anime.title, e)
    raise last_err or RuntimeError("post failed")


async def _after_post(client, anime: api.Anime, msg):
    await db.set_posted(anime.id, anime.episode or 0, anime.title, msg.id)
    sticker = db.get("sticker_id")
    if sticker:
        try:
            await _flood_safe(client.send_sticker, config.CHANNEL_ID, sticker)
        except Exception as e:  # never fail a post because of the sticker
            log.warning("sticker send failed: %s", e)


# ------------------------------------------------------------------ poller
class Poller:
    def __init__(self):
        self.client = None
        self.task: Optional[asyncio.Task] = None
        self.lock = asyncio.Lock()
        self.wake = asyncio.Event()
        self.cycles = 0
        self.posted_session = 0
        self.last_check: Optional[float] = None
        self.last_ok: Optional[float] = None
        self.last_result = "not run yet"
        self.next_check: Optional[float] = None
        self.fail_streak = 0
        self.alerted_down = False
        self.running_cycle = False

    def start(self, client):
        self.client = client
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._loop(), name="poller")

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass

    def poke(self):
        """Wake the loop now (after /resume, /set_int, /check)."""
        self.wake.set()

    async def _loop(self):
        log.info("poller started")
        while True:
            try:
                if not db.get("paused"):
                    await self.run_cycle()
                interval = max(config.MIN_INTERVAL, int(db.get("interval") or config.DEFAULT_INTERVAL))
                self.next_check = None if db.get("paused") else time.time() + interval
                self.wake.clear()
                try:
                    await asyncio.wait_for(self.wake.wait(), timeout=interval if not db.get("paused") else 3600)
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                raise
            except Exception as e:  # the loop itself must never die
                log.exception("poller loop error")
                await alert(self.client, "Poller loop error", exc=e, key="poller-loop")
                await asyncio.sleep(30)

    async def _fetch_all(self) -> List[dict]:
        items: List[dict] = []
        seen = set()
        for page in range(1, config.RECENT_PAGES + 1):
            page_items, _ = await api.fetch_recent(page, config.PER_PAGE)
            for it in page_items:
                if it.get("id") not in seen:
                    seen.add(it.get("id"))
                    items.append(it)
        return items

    async def run_cycle(self) -> dict:
        async with self.lock:
            self.running_cycle = True
            self.last_check = time.time()
            self.cycles += 1
            summary = {"posted": 0, "deferred": 0, "skipped": 0, "failed": 0}
            try:
                try:
                    items = await self._fetch_all()
                except api.ApiError as e:
                    await self._on_api_failure(e)
                    summary["error"] = str(e)
                    return summary
                await self._on_api_ok()

                if not db.get("seeded"):
                    await self._seed(items)
                    summary["seeded"] = len(items)
                    return summary

                # oldest update first so the channel reads chronologically
                for raw in reversed(items):
                    if db.get("paused"):
                        break
                    try:
                        await self._process(raw, summary)
                    except Exception as e:
                        summary["failed"] += 1
                        log.exception("processing %s failed", raw.get("id"))
                        await alert(self.client, f"Posting failed: {raw.get('title')}", exc=e, key=f"post:{raw.get('id')}")
                self.last_result = (
                    f"{summary['posted']} posted, {summary['deferred']} waiting for embed, "
                    f"{summary['failed']} failed"
                )
                return summary
            finally:
                self.running_cycle = False

    async def _process(self, raw: dict, summary: dict):
        a = api.normalize(raw)
        if a.episode is None:
            summary["skipped"] += 1
            return
        doc = await db.get_posted(a.id)
        if doc and a.episode <= int(doc.get("last_ep", 0)):
            summary["skipped"] += 1
            return
        if not doc and not a.is_airing:
            # never seen + not airing = an old show with a metadata edit, not a new episode
            await db.set_posted(a.id, a.episode, a.title, silent=True)
            summary["skipped"] += 1
            return
        ok, why = await api.verify_episode(a)
        if not ok:
            log.info("defer %s ep %s: %s", a.title, a.episode, why)
            summary["deferred"] += 1
            return
        await post_anime(self.client, a, source="auto")
        self.posted_session += 1
        summary["posted"] += 1
        log.info("posted %s ep %s", a.title, a.episode)
        await asyncio.sleep(config.POST_DELAY)

    async def _seed(self, items: List[dict]):
        """First run: remember what already exists so the channel is not flooded."""
        for raw in items:
            a = api.normalize(raw)
            if a.episode is not None:
                await db.set_posted(a.id, a.episode, a.title, silent=True)
        await db.set("seeded", True)
        self.last_result = f"seeded {len(items)} shows without posting"
        log.info(self.last_result)
        for owner in config.OWNER_IDS:
            try:
                await self.client.send_message(
                    owner,
                    f"❐ <b>{sc('First run complete')}</b>\n{LINE}\n"
                    f"›› {sc('Remembered')} {len(items)} {sc('current shows without posting them.')}\n"
                    f"›› {sc('From now on only new episodes are posted.')}",
                )
            except Exception:
                pass

    async def _on_api_failure(self, e: Exception):
        self.fail_streak += 1
        self.last_result = f"api error ({self.fail_streak} in a row)"
        log.error("api check failed (%s in a row): %s", self.fail_streak, e)
        if self.fail_streak >= 3 and not self.alerted_down:
            self.alerted_down = True
            await alert(self.client, "API is down", f"{self.fail_streak} checks failed in a row.\n{e}", key="api-down")

    async def _on_api_ok(self):
        self.last_ok = time.time()
        if self.alerted_down:
            self.alerted_down = False
            await alert(self.client, "API recovered", "Checks are working again.", key=f"api-up:{int(time.time())}")
        self.fail_streak = 0


poller = Poller()


# ------------------------------------------------------------------ /check
@Client.on_message(filters.command("check") & filters.private & config.owner_only)
@safe
async def check_cmd(client, message):
    if poller.lock.locked():
        return await message.reply_text(f"❐ {sc('A check or batch is already running.')}")
    status = await message.reply_text(f"❐ {sc('Checking the api...')}")
    s = await poller.run_cycle()
    if "error" in s:
        return await status.edit_text(f"❐ <b>{sc('API check failed')}</b>\n<pre>{esc(s['error'])[:600]}</pre>")
    if "seeded" in s:
        return await status.edit_text(f"❐ {sc('First run: remembered')} {s['seeded']} {sc('shows without posting.')}")
    await status.edit_text(
        f"❐ <b>{sc('Check done')}</b>\n{LINE}\n"
        f"›› {sc('Posted')} : {s['posted']}\n›› {sc('Waiting for embed')} : {s['deferred']}\n"
        f"›› {sc('Up to date')} : {s['skipped']}\n›› {sc('Failed')} : {s['failed']}"
    )


# ------------------------------------------------------------------ /post and /batch_post
batch = {"running": False, "cancel": False}


async def _load_items(url: str) -> List[dict]:
    if not url.lower().startswith(("http://", "https://")):
        raise api.ApiError("the link must start with http:// or https://")
    items = api.extract_items(await api.fetch_url(url))
    if not items:
        raise api.ApiError("no anime found in that json")
    return items


@Client.on_message(filters.command("post") & filters.private & config.owner_only)
@safe
async def post_cmd(client, message):
    args = message.command[1:]
    if not args:
        return await message.reply_text(
            f"❐ <b>{sc('Usage')}</b>\n<code>/post https://anikotoapi.site/recent-anime?page=2 10</code>\n"
            f"›› {sc('The number is the position on that page (1 = first). Default 1.')}"
        )
    url, pos = args[0], 1
    if len(args) > 1:
        if not args[1].isdigit() or int(args[1]) < 1:
            return await message.reply_text(f"❐ {sc('Position must be a number starting at 1.')}")
        pos = int(args[1])
    status = await message.reply_text(f"❐ {sc('Reading the json...')}")
    try:
        items = await _load_items(url)
    except api.ApiError as e:
        return await status.edit_text(f"❐ <b>{sc('Could not read that link')}</b>\n<pre>{esc(e)[:500]}</pre>")
    if pos > len(items):
        return await status.edit_text(f"❐ {sc('That page has only')} {len(items)} {sc('anime.')}")
    anime = api.normalize(items[pos - 1])
    if anime.episode is None:
        anime.episode = 1  # manual posts are forced; fall back to episode 1
    async with poller.lock:
        await status.edit_text(f"❐ {sc('Posting')} <b>{esc(anime.title)}</b>...")
        msg = await post_anime(client, anime, source="manual")
    link = f"https://t.me/{str(config.CHANNEL_ID).lstrip('@')}/{msg.id}" if isinstance(config.CHANNEL_ID, str) else None
    tail = f"\n<a href=\"{link}\">{sc('Open post')}</a>" if link else ""
    await status.edit_text(f"❐ <b>{sc('Posted')}</b> {esc(anime.title)} — {sc('Episode')} {anime.episode}{tail}", link_preview_options=NO_PREVIEW)


@Client.on_message(filters.command("batch_post") & filters.private & config.owner_only)
@safe
async def batch_post_cmd(client, message):
    args = message.command[1:]
    if not args:
        return await message.reply_text(
            f"❐ <b>{sc('Usage')}</b>\n<code>/batch_post https://anikotoapi.site/recent-anime?page=2</code>\n"
            f"›› {sc('Already posted episodes are skipped. Add')} <code>force</code> {sc('to repost everything.')}"
        )
    if batch["running"]:
        return await message.reply_text(f"❐ {sc('A batch is already running.')}")
    force = len(args) > 1 and args[1].lower() == "force"
    status = await message.reply_text(f"❐ {sc('Reading the json...')}")
    try:
        items = await _load_items(args[0])
    except api.ApiError as e:
        return await status.edit_text(f"❐ <b>{sc('Could not read that link')}</b>\n<pre>{esc(e)[:500]}</pre>")

    batch.update(running=True, cancel=False)
    stop_kb = InlineKeyboardMarkup([[InlineKeyboardButton(sc("Stop"), callback_data="batch_stop")]])
    done = skipped = failed = 0
    started = time.time()
    try:
        async with poller.lock:
            for i, raw in enumerate(items, 1):
                if batch["cancel"]:
                    break
                a = api.normalize(raw)
                a.episode = a.episode or 1
                doc = await db.get_posted(a.id)
                if doc and not doc.get("silent") and not force and a.episode <= int(doc.get("last_ep", 0)):
                    skipped += 1
                    continue
                try:
                    await status.edit_text(
                        f"❐ <b>{sc('Batch posting')}</b> {i}/{len(items)}\n{LINE}\n›› {esc(a.title)}\n"
                        f"›› {sc('Posted')} {done} · {sc('Skipped')} {skipped} · {sc('Failed')} {failed}",
                        reply_markup=stop_kb,
                    )
                except RPCError:
                    pass
                try:
                    await post_anime(client, a, source="batch")
                    done += 1
                except Exception as e:
                    failed += 1
                    log.exception("batch post failed for %s", a.id)
                    await alert(client, f"Batch post failed: {a.title}", str(e), key=f"batch:{a.id}")
                await asyncio.sleep(config.POST_DELAY)
    finally:
        cancelled = batch["cancel"]
        batch.update(running=False, cancel=False)
    await status.edit_text(
        f"❐ <b>{sc('Batch stopped') if cancelled else sc('Batch finished')}</b>\n{LINE}\n"
        f"›› {sc('Posted')} : {done}\n›› {sc('Skipped')} : {skipped}\n›› {sc('Failed')} : {failed}\n"
        f"›› {sc('Time')} : {fmt_duration(time.time() - started)}"
    )