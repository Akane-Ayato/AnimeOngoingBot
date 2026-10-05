"""
API access: resilient fetching (retries, backoff, fallback endpoint), data
normalisation (episode / language logic) and health checks.
"""
import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

import config

log = logging.getLogger("AnimeBot.api")

_session: Optional[aiohttp.ClientSession] = None
HEADERS = {"Accept": "application/json", "User-Agent": f"AnimeOngoingBot/{config.VERSION}"}


class ApiError(Exception):
    pass


async def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=20, connect=8),
            connector=aiohttp.TCPConnector(limit=20, ttl_dns_cache=300),
        )
    return _session


async def close_session():
    if _session and not _session.closed:
        await _session.close()


async def fetch_url(url: str, params: Optional[dict] = None, retries: int = 3) -> Any:
    """GET + JSON with exponential backoff. Raises ApiError when every attempt fails."""
    last: Optional[Exception] = None
    for attempt in range(retries):
        try:
            s = await get_session()
            async with s.get(url, params=params) as r:
                if r.status >= 500 or r.status == 429:
                    raise ApiError(f"HTTP {r.status}")
                if r.status >= 400:
                    raise ApiError(f"HTTP {r.status} (not retrying)")
                return await r.json(content_type=None)
        except ApiError as e:
            last = e
            if "not retrying" in str(e):
                break
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            last = e
        if attempt < retries - 1:
            await asyncio.sleep(1.5 * (2 ** attempt))
    raise ApiError(f"{url} failed: {last}")


async def _first_ok(candidates: List[Tuple[str, Optional[dict]]]) -> Any:
    errors = []
    for url, params in candidates:
        try:
            data = await fetch_url(url, params)
            if isinstance(data, dict) and data.get("ok") is False:
                raise ApiError(data.get("message") or "ok=false")
            return data
        except ApiError as e:
            errors.append(str(e))
            log.warning("endpoint failed, trying next: %s", e)
    raise ApiError(" | ".join(errors))


async def fetch_recent(page: int = 1, per_page: int = config.PER_PAGE) -> Tuple[List[dict], dict]:
    cands = [(f"{config.API_BASE}/recent-anime", {"page": page, "per_page": per_page})]
    if config.USE_SITE_FALLBACK:
        cands.append((f"{config.SITE_URL}/api/recent", {"page": page, "per_page": per_page}))
    data = await _first_ok(cands)
    items = data.get("data")
    if not isinstance(items, list):
        raise ApiError("recent-anime returned no data list")
    return items, data.get("pagination") or {}


async def fetch_series(anime_id) -> dict:
    cands = [(f"{config.API_BASE}/series/{anime_id}", None)]
    if config.USE_SITE_FALLBACK:
        cands.append((f"{config.SITE_URL}/api/series/{anime_id}", None))
    data = await _first_ok(cands)
    body = data.get("data")
    if not isinstance(body, dict):
        raise ApiError("series returned no data")
    return body


def extract_items(payload: Any) -> List[dict]:
    """Accepts any recent-anime style JSON (or a /series/{id} body) and returns anime dicts."""
    if isinstance(payload, dict):
        data = payload.get("data", payload)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            if isinstance(data.get("anime"), dict):
                return [data["anime"]]
            if isinstance(data.get("items"), list):
                return [x for x in data["items"] if isinstance(x, dict)]
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    return []


# ------------------------------------------------------------------ normalisation
def _to_int(v) -> Optional[int]:
    try:
        if v is None or v == "":
            return None
        return int(float(v))
    except (TypeError, ValueError):
        return None


def compute_episode(a: dict) -> Optional[int]:
    """
    Released episode number.
      base  = next_air_ep - 1   (if next_air_ep == 1 the episode is next_air_ep)
      sub   = is_sub counter    (number of released sub episodes)
    The real data shows next_air_ep lags right after an episode airs (and on finished
    shows it still points at the last episode), so the answer is max(base, sub).
    With no next_air_ep the released counters decide. verify_episode() double-checks
    the embed exists before anything is posted.
    """
    nxt = _to_int(a.get("next_air_ep"))
    sub = _to_int(a.get("is_sub")) or 0
    dub = _to_int(a.get("is_dub")) or 0
    if nxt is not None:
        base = nxt - 1 if nxt > 1 else nxt
        return max(base, sub) or None
    return max(sub, dub) or None


@dataclass
class Anime:
    id: str
    title: str
    episode: Optional[int]
    sub: int
    dub: int
    language: str          # "Dual" or "Sub | E-Sub"
    status: str
    is_airing: bool
    description: str = ""
    poster: str = ""
    background: str = ""
    season: str = ""
    year: str = ""
    score: str = ""
    genres: List[str] = field(default_factory=list)
    studio: str = ""
    type: str = ""
    aired: str = ""
    total_eps: str = ""
    alt: str = ""
    raw: dict = field(default_factory=dict)


_SRC = re.compile(r"\(Source:.*?\)", re.I | re.S)


def normalize(a: dict) -> Anime:
    terms = a.get("terms_by_type") or {}
    sub = _to_int(a.get("is_sub")) or 0
    dub = _to_int(a.get("is_dub")) or 0
    language = "Dual" if (sub and dub and sub == dub) else "Sub | E-Sub"
    status = str(a.get("status") or "Unknown")
    desc = _SRC.sub("", str(a.get("description") or "")).strip()
    return Anime(
        id=str(a.get("id")),
        title=str(a.get("title") or a.get("alternative") or "Untitled").strip(),
        episode=compute_episode(a),
        sub=sub, dub=dub, language=language,
        status=status,
        is_airing=bool(re.search(r"airing", status, re.I)) and not re.search(r"finish|complet", status, re.I),
        description=desc,
        poster=str(a.get("poster") or ""),
        background=str(a.get("background_image") or ""),
        season=str(a.get("season") or "").capitalize(),
        year=str(a.get("year") or ""),
        score=str(a.get("score") or ""),
        genres=[str(g) for g in (terms.get("genre") or [])],
        studio=", ".join(str(s) for s in (terms.get("studios") or [])[:2]),
        type=str((terms.get("type") or [""])[0]),
        aired=str(a.get("aired") or ""),
        total_eps=str(a.get("episodes") or ""),
        alt=str(a.get("alternative") or ""),
        raw=a,
    )


# ------------------------------------------------------------------ verification
async def verify_episode(anime: Anime) -> Tuple[bool, str]:
    """
    Before posting, make sure episode N really has a playable embed on /series/{id},
    so the Watch Now button never lands on an empty page.
    If the series endpoint itself is down we fall back to the sub/dub counters.
    """
    if anime.episode is None:
        return False, "no episode number"
    try:
        body = await fetch_series(anime.id)
    except ApiError as e:
        counters_ok = max(anime.sub, anime.dub) >= anime.episode
        return counters_ok, f"series endpoint unavailable ({'counters agree' if counters_ok else 'counters disagree'}): {e}"
    for ep in body.get("episodes") or []:
        num = _to_int(ep.get("number"))
        embed = ep.get("embed_url") or {}
        if num == anime.episode and (embed.get("sub") or embed.get("dub")):
            return True, "embed found"
    return False, f"episode {anime.episode} has no embed yet"


# ------------------------------------------------------------------ health
async def timed_get(url: str, timeout: int = 10, json_check: bool = False) -> Dict[str, Any]:
    t = time.perf_counter()
    try:
        s = await get_session()
        async with s.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            ms = (time.perf_counter() - t) * 1000
            ok = r.status < 400
            if ok and json_check:
                data = await r.json(content_type=None)
                ok = bool(isinstance(data, dict) and data.get("ok", True))
            return {"ok": ok, "status": r.status, "ms": ms, "error": None}
    except Exception as e:
        return {"ok": False, "status": None, "ms": (time.perf_counter() - t) * 1000, "error": type(e).__name__}


async def api_health() -> Dict[str, Any]:
    return await timed_get(f"{config.API_BASE}/recent-anime?page=1&per_page=1", json_check=True)


async def site_health() -> Dict[str, Any]:
    return await timed_get(config.SITE_URL)
