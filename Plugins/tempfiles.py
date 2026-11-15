"""
Temporary files: downloaded covers and rendered posters live in TMP_DIR and are deleted
TMP_TTL seconds (default 300 = 5 minutes) after they were written, so storage stays empty.
"""
import asyncio
import logging
import os
import time
import uuid

import config

log = logging.getLogger("AnimeBot.tmp")


def new_path(suffix: str = ".bin") -> str:
    os.makedirs(config.TMP_DIR, exist_ok=True)
    return os.path.join(config.TMP_DIR, uuid.uuid4().hex + suffix)


def sweep(max_age: float = None, everything: bool = False) -> int:
    """Delete files older than max_age (default TMP_TTL). Returns how many were removed."""
    max_age = config.TMP_TTL if max_age is None else max_age
    removed = 0
    if not os.path.isdir(config.TMP_DIR):
        return 0
    now = time.time()
    for name in os.listdir(config.TMP_DIR):
        path = os.path.join(config.TMP_DIR, name)
        try:
            if os.path.isfile(path) and (everything or now - os.path.getmtime(path) >= max_age):
                os.remove(path)
                removed += 1
        except OSError as e:
            log.warning("could not delete %s: %s", path, e)
    return removed


def usage() -> tuple:
    """(file count, total bytes) currently in TMP_DIR."""
    if not os.path.isdir(config.TMP_DIR):
        return 0, 0
    files = [os.path.join(config.TMP_DIR, n) for n in os.listdir(config.TMP_DIR)]
    files = [f for f in files if os.path.isfile(f)]
    return len(files), sum(os.path.getsize(f) for f in files)


async def janitor():
    """Wipe leftovers from a previous run, then sweep every 30 seconds."""
    n = await asyncio.to_thread(sweep, 0, True)
    if n:
        log.info("startup cleanup removed %s old temp file(s)", n)
    while True:
        await asyncio.sleep(30)
        try:
            n = await asyncio.to_thread(sweep)
            if n:
                log.debug("removed %s expired temp file(s)", n)
        except Exception:
            log.exception("temp cleanup failed")
