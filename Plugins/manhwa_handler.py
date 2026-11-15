"""
Manhwa posting engine: monitors the local-manga API and posts every new chapter to the
manhwa channel (MANHWA_CHANNEL_ID) with a poster, a short caption and the /m_btn buttons.
Same safety rules as the anime engine: MongoDB dedupe, first-run seeding, retries, fallbacks,
alerts. One asyncio.Lock guards every manhwa posting path.
"""
import asyncio
import logging
import time
from typing import List, Optional

from pyrogram.errors import RPCError

import config
from Database.mongodata import db
from Plugins import api_handler as api
from Plugins import postmaker
from Plugins.buttonhandler import build_manhwa_markup
from Plugins.logger_error_handler import alert
from Plugins.tg_utils import flood_safe
from Plugins.UI_design import LINE, NO_PREVIEW, sc

log = logging.getLogger("AnimeBot.manhwa")


def enabled() -> bool:
    return config.MANHWA_CHANNEL_ID is not None


# ------------------------------------------------------------------ sending
async def post_manhwa(client, m: "api.Manhwa", source: str = "auto"):
    """
    Posts one chapter update. Fallback ladder:
      poster + buttons -> poster only -> text + buttons -> text only
    Raises only if even the plain text post fails.
    """
    if not enabled():
        raise RuntimeError("MANHWA_CHANNEL_ID is not set")
    poster = await postmaker.make_manhwa_poster(m)
    caption = postmaker.build_manhwa_caption(m)
    has_btns = bool(db.get("m_btn_rows"))

    attempts = []
    if poster:
        attempts.append(("poster+buttons" if has_btns else "poster", True, True))
        if has_btns:
            attempts.append(("poster-only", True, False))
    attempts.append(("text+buttons" if has_btns else "text", False, True))
    if has_btns:
        attempts.append(("text-only", False, False))

    last_err: Optional[Exception] = None
    for idx, (label, with_photo, with_btns) in enumerate(attempts):
        markup = build_manhwa_markup() if with_btns else None
        try:
            if with_photo:
                msg = await flood_safe(
                    client.send_photo, config.MANHWA_CHANNEL_ID, poster, caption=caption, reply_markup=markup
                )
            else:
                msg = await flood_safe(
                    client.send_message, config.MANHWA_CHANNEL_ID, caption,
                    reply_markup=markup, link_preview_options=NO_PREVIEW,
                )
            if idx > 0:
                log.warning("posted %s via fallback '%s' (last error: %s)", m.title, label, last_err)
                await alert(client, f"Manhwa post used fallback '{label}'", f"{m.title} ch {m.chapter}: {last_err}", key=f"m-fallback:{label}")
            await db.set_manhwa(m.slug, m.chapter, m.num, m.title, msg.id)
            return msg
        except RPCError as e:
            last_err = e
            log.warning("manhwa send attempt '%s' failed for %s: %s", label, m.title, e)
    raise last_err or RuntimeError("manhwa post failed")


# ------------------------------------------------------------------ poller
class ManhwaPoller:
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

    def start(self, client):
        self.client = client
        if not enabled():
            self.last_result = "disabled (MANHWA_CHANNEL_ID not set)"
            log.info("manhwa monitor disabled: MANHWA_CHANNEL_ID is not set")
            return
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._loop(), name="manhwa-poller")

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass

    def poke(self):
        self.wake.set()

    async def _loop(self):
        log.info("manhwa poller started")
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
            except Exception as e:
                log.exception("manhwa poller loop error")
                await alert(self.client, "Manhwa poller loop error", exc=e, key="m-poller-loop")
                await asyncio.sleep(30)

    async def _fetch_all(self) -> List[dict]:
        items: List[dict] = []
        seen = set()
        for page in range(1, config.MANHWA_PAGES + 1):
            page_items, _ = await api.fetch_manhwa(page)
            for it in page_items:
                key = it.get("slug") or it.get("id")
                if key not in seen:
                    seen.add(key)
                    items.append(it)
        return items

    @staticmethod
    def _decide(m: "api.Manhwa", doc: Optional[dict]) -> str:
        """'post' (new chapter), 'record' (remember silently) or 'skip'."""
        if doc is None:
            return "post"
        last_num, last_ch = doc.get("last_num"), doc.get("last_chapter")
        if m.num is not None and last_num is not None:
            if m.num > last_num:
                return "post"
            if m.num < last_num:
                return "record"          # the source corrected the chapter number downwards
            return "skip"
        return "post" if m.chapter != last_ch else "skip"

    async def run_cycle(self) -> dict:
        async with self.lock:
            self.last_check = time.time()
            self.cycles += 1
            summary = {"posted": 0, "deferred": 0, "skipped": 0, "failed": 0}
            try:
                items = await self._fetch_all()
            except api.ApiError as e:
                await self._on_api_failure(e)
                summary["error"] = str(e)
                return summary
            await self._on_api_ok()

            if not db.get("manhwa_seeded"):
                await self._seed(items)
                summary["seeded"] = len(items)
                return summary

            pending: List["api.Manhwa"] = []
            for raw in reversed(items):                      # oldest update first
                m = api.normalize_manhwa(raw)
                if not m.slug or not m.chapter:
                    summary["skipped"] += 1
                    continue
                if config.MANHWA_FORMATS and m.type.lower() not in config.MANHWA_FORMATS:
                    summary["skipped"] += 1
                    continue
                decision = self._decide(m, await db.get_manhwa(m.slug))
                if decision == "post":
                    pending.append(m)
                elif decision == "record":
                    await db.set_manhwa(m.slug, m.chapter, m.num, m.title, silent=True)
                    summary["skipped"] += 1
                else:
                    summary["skipped"] += 1

            for m in pending[: config.MANHWA_MAX_PER_CYCLE]:
                if db.get("paused"):
                    break
                try:
                    await post_manhwa(self.client, m, source="auto")
                    self.posted_session += 1
                    summary["posted"] += 1
                    log.info("posted manhwa %s chapter %s", m.title, m.chapter)
                except Exception as e:
                    summary["failed"] += 1
                    log.exception("manhwa post failed for %s", m.slug)
                    await alert(self.client, f"Manhwa post failed: {m.title}", exc=e, key=f"mpost:{m.slug}")
                await asyncio.sleep(config.POST_DELAY)
            summary["deferred"] = max(0, len(pending) - config.MANHWA_MAX_PER_CYCLE)   # picked up next cycle
            self.last_result = (
                f"{summary['posted']} posted, {summary['deferred']} queued, {summary['failed']} failed"
            )
            return summary

    async def _seed(self, items: List[dict]):
        """First run: remember what exists so the manhwa channel is not flooded."""
        count = 0
        for raw in items:
            m = api.normalize_manhwa(raw)
            if m.slug and m.chapter:
                await db.set_manhwa(m.slug, m.chapter, m.num, m.title, silent=True)
                count += 1
        await db.set("manhwa_seeded", True)
        self.last_result = f"seeded {count} titles without posting"
        log.info(self.last_result)
        for owner in config.OWNER_IDS:
            try:
                await self.client.send_message(
                    owner,
                    f"❐ <b>{sc('Manhwa monitor ready')}</b>\n{LINE}\n"
                    f"›› {sc('Remembered')} {count} {sc('current titles without posting them.')}\n"
                    f"›› {sc('From now on only new chapters are posted.')}",
                )
            except Exception:
                pass

    async def _on_api_failure(self, e: Exception):
        self.fail_streak += 1
        self.last_result = f"api error ({self.fail_streak} in a row)"
        log.error("manhwa api check failed (%s in a row): %s", self.fail_streak, e)
        if self.fail_streak >= 3 and not self.alerted_down:
            self.alerted_down = True
            await alert(self.client, "Manhwa API is down", f"{self.fail_streak} checks failed in a row.\n{e}", key="m-api-down")

    async def _on_api_ok(self):
        self.last_ok = time.time()
        if self.alerted_down:
            self.alerted_down = False
            await alert(self.client, "Manhwa API recovered", "Checks are working again.", key=f"m-api-up:{int(time.time())}")
        self.fail_streak = 0


manhwa_poller = ManhwaPoller()
