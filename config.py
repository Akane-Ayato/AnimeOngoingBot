"""
Central configuration. Everything comes from environment variables / .env so the
same code runs on Render, a VPS or your local machine without edits.
"""
import os
import time

from dotenv import load_dotenv
from pyrogram import filters

load_dotenv()

VERSION = "2.1.0"
START_TIME = time.time()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _req(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name} (see .env.example)")
    return value


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except ValueError:
        return default


def _flag(name: str, default: bool) -> bool:
    return os.getenv(name, "1" if default else "0").strip().lower() in ("1", "true", "yes", "on")


def _chat(value: str):
    value = value.strip()
    if value.lstrip("-").isdigit():
        return int(value)
    return value if value.startswith("@") else "@" + value


# ---- Telegram ----
API_ID = int(_req("API_ID"))
API_HASH = _req("API_HASH")
BOT_TOKEN = _req("BOT_TOKEN")
SESSION_NAME = os.getenv("SESSION_NAME", "AnimeOngoingBot")

OWNER_IDS = {int(x) for x in _req("OWNER_ID").replace(" ", "").split(",") if x.lstrip("-").isdigit()}
CHANNEL_ID = _chat(_req("CHANNEL_ID"))
LOG_CHANNEL = _chat(os.environ["LOG_CHANNEL"]) if os.getenv("LOG_CHANNEL", "").strip() else None

# ---- Database ----
MONGO_URI = _req("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "AnimeOngoingBot")

# ---- Site / API ----
SITE_URL = os.getenv("SITE_URL", "https://ani-void-tv.vercel.app").rstrip("/")
API_BASE = os.getenv("API_BASE", "https://anikotoapi.site").rstrip("/")
# Your own Vercel proxy is used automatically when the upstream API fails.
USE_SITE_FALLBACK = _flag("USE_SITE_FALLBACK", True)

DEFAULT_INTERVAL = _int("DEFAULT_INTERVAL", 300)  # seconds, changeable with /set_int
MIN_INTERVAL = 30
RECENT_PAGES = max(1, _int("RECENT_PAGES", 2))  # pages of /recent-anime scanned per check
PER_PAGE = max(1, _int("PER_PAGE", 40))
POST_DELAY = max(1, _int("POST_DELAY", 5))  # seconds between channel posts

# ---- Manhwa monitor (optional: leave MANHWA_CHANNEL_ID empty to disable it) ----
MANHWA_CHANNEL_ID = _chat(os.environ["MANHWA_CHANNEL_ID"]) if os.getenv("MANHWA_CHANNEL_ID", "").strip() else None
MANHWA_API = os.getenv("MANHWA_API", "https://b.toonking.xyz/api/local-manga").strip()
MANHWA_IMG_BASE = os.getenv("MANHWA_IMG_BASE", "https://b.toonking.xyz").rstrip("/")   # covers are relative paths
MANHWA_SITE = os.getenv("MANHWA_SITE", "https://manhwavoid.space").rstrip("/")
MANHWA_BRAND = os.getenv("MANHWA_BRAND", "MMWC VOID")      # header text on the manhwa poster
ANIME_CREDIT = os.getenv("ANIME_CREDIT", "Anime Void")     # small credit on the anime poster
MANHWA_PAGES = max(1, _int("MANHWA_PAGES", 2))             # API pages (20 items each) scanned per check
MANHWA_MAX_PER_CYCLE = max(1, _int("MANHWA_MAX_PER_CYCLE", 20))
# Only post these formats (comma separated, e.g. "Manhwa,Manhua"). Empty = everything the API returns.
MANHWA_FORMATS = {x.strip().lower() for x in os.getenv("MANHWA_FORMATS", "").split(",") if x.strip()}

# ---- Posters / temp files ----
POSTER_SS = max(1, min(3, _int("POSTER_SS", 2)))   # supersampling: 2 = crisp, 1 = half the RAM
TMP_DIR = os.path.join(BASE_DIR, "tmp")
TMP_TTL = max(30, _int("TMP_TTL", 300))             # downloaded covers + rendered posters are deleted after this many seconds

# ---- Branding ----
CHANNEL_NAME = os.getenv("CHANNEL_NAME", "Aɳιɱҽ Oɳɠσιɳɠ")
POWERED_BY_NAME = os.getenv("POWERED_BY_NAME", "𝙰𝚗𝚒𝚖𝚎 𝚅𝚘𝚒𝚍")
POWERED_BY_URL = os.getenv("POWERED_BY_URL", "https://t.me/Index_void")
SUPPORT_URL = os.getenv("SUPPORT_URL", "https://t.me/Anime_Void_x")

# Comma separated image URLs, one is chosen at random for /start and /help
IMG = [u.strip() for u in os.getenv("IMG", "").split(",") if u.strip()]

# ---- Hosting ----
PORT = _int("PORT", 8080)
WEB_SERVER = _flag("WEB_SERVER", True)
PUBLIC_URL = (os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
KEEP_ALIVE = _flag("KEEP_ALIVE", bool(os.getenv("RENDER")))  # self-ping so Render's free tier stays awake

LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "bot.log")
FONT_DIR = os.path.join(BASE_DIR, "assets", "fonts")
LOGO_PATH = os.path.join(BASE_DIR, "assets", "logo.jpg")


def host_type() -> str:
    if os.getenv("RENDER"):
        return "Render"
    if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("DYNO"):
        return "PaaS"
    return "VPS / Local"


# ---- Filters ----
async def _is_owner(_, __, update) -> bool:
    user = getattr(update, "from_user", None)
    return bool(user and user.id in OWNER_IDS)


owner_only = filters.create(_is_owner, "OwnerOnly")
