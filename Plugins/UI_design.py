"""
All user-facing text lives here: small-caps helper, default post style, caption
rendering (placeholders + length fitting), start/help/about screens and keyboards.
Text symbols only, no emoji.
"""
import html
import re
from typing import Dict, Optional

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions

import config

# Kurigram 2.2+ replaced disable_web_page_preview with link_preview_options
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

# ------------------------------------------------------------------ small caps
_SC = dict(zip("abcdefghijklmnopqrstuvwxyz", "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ"))
_SKIP = re.compile(r"(<[^>]*>|&[#\w]+;|\{\w+\}|https?://\S+)")


def sc(text: str) -> str:
    """Plain text -> small caps. Capitals stay capitals ('Episode' -> 'Eᴘɪꜱᴏᴅᴇ')."""
    return "".join(_SC.get(c, c) for c in str(text))


def scx(text: str) -> str:
    """Small caps for HTML snippets: tags, entities, {placeholders} and URLs are left alone."""
    parts = _SKIP.split(text)
    return "".join(p if _SKIP.fullmatch(p) else sc(p) for p in parts)


def esc(text) -> str:
    return html.escape(str(text if text is not None else ""), quote=False)


LINE = "✦─━━━━━━━━━━─✦"


def kv(label: str, value: str) -> str:
    return f"›› <b>{sc(label)}</b> : {value}"


# ------------------------------------------------------------------ default post style
DEFAULT_STYLE = (
    "<blockquote>❐ <b>{title}</b></blockquote>\n"
    f"{LINE}\n"
    "<blockquote><b>›› " + sc("Episode") + ": {episode}\n"
    "›› " + sc("Quality") + " : 480ᴘ | 720ᴘ | 1080ᴘ\n"
    "›› " + sc("Language") + ": {language}\n"
    "›› " + sc("Status") + ":</b> {status}</blockquote>\n"
    f"{LINE}\n"
    "<blockquote expandable><b>≡ " + sc("Synopsis") + ":</b> {description}</blockquote>\n"
    "≡ " + sc("Powered By") + ' : <a href="{powered_url}">{powered_name}</a>\n'
    f"{LINE}"
)

PLACEHOLDERS = [
    ("title", "anime title"),
    ("episode", "episode number"),
    ("language", "Dual or Sub | E-Sub"),
    ("status", "airing status"),
    ("description", "synopsis (auto-trimmed to fit)"),
    ("season", "season name"),
    ("year", "year"),
    ("score", "score or N/A"),
    ("genres", "genres, comma separated"),
    ("studio", "studio"),
    ("type", "TV / Movie / ..."),
    ("aired", "air date"),
    ("total_eps", "total episodes"),
    ("id", "anime id"),
    ("url", "watch link"),
    ("channel", "channel name"),
    ("powered_name", "powered-by name"),
    ("powered_url", "powered-by link"),
]

SAMPLE_VALUES = {
    "title": "Hana-Kimi", "episode": "2", "language": sc("Sub") + " | E-" + sc("Sub"),
    "status": sc("Currently Airing"), "description": "Mizuki Ashiya is on a mission: disguise herself as a boy and enroll in a male boarding school to meet her idol.",
    "season": "Fall", "year": "2026", "score": "7.7", "genres": "Comedy, Romance", "studio": "Signal.MD",
    "type": "TV", "aired": "2026-10-04", "total_eps": "25", "id": "0",
    "url": f"{config.SITE_URL}/watch.html?id=0", "channel": config.CHANNEL_NAME,
    "powered_name": config.POWERED_BY_NAME, "powered_url": config.POWERED_BY_URL,
}

_PH = re.compile(r"\{(\w+)\}")
_TAG = re.compile(r"<[^>]*>")


def tg_len(s: str) -> int:
    """Telegram caption length: tags removed, entities decoded, UTF-16 code units."""
    plain = html.unescape(_TAG.sub("", s))
    return len(plain.encode("utf-16-le")) // 2


def _fill(template: str, values: Dict[str, str]) -> str:
    return _PH.sub(lambda m: values.get(m.group(1), m.group(0)), template)


def render_caption(template: Optional[str], values: Dict[str, str], limit: int = 1024) -> str:
    """Fill placeholders (values must already be HTML-safe) and trim the synopsis until it fits."""
    template = template or DEFAULT_STYLE
    vals = dict(values)
    raw_desc = vals.get("description", "")
    text = _fill(template, vals)
    guard = 0
    while tg_len(text) > limit and raw_desc and guard < 60:
        over = tg_len(text) - limit
        cut = max(over + 8, 20)
        plain = html.unescape(raw_desc)
        plain = plain[: max(0, len(plain) - cut)].rstrip(" ,.;:-")
        raw_desc = (html.escape(plain, quote=False) + "…") if plain else ""
        vals["description"] = raw_desc
        text = _fill(template, vals)
        guard += 1
    return text


# ------------------------------------------------------------------ screens
def start_text(name: str) -> str:
    return (
        f"<blockquote>❐ <b>{scx('Hey')} {esc(name)}</b></blockquote>\n{LINE}\n"
        f"<blockquote>{scx('›› I post every new ongoing anime episode on')} <b>{esc(config.CHANNEL_NAME)}</b>\n"
        f"{scx('›› Each post comes with a custom banner and a watch button.')}</blockquote>\n{LINE}\n"
        f"≡ {sc('Stream')} : <a href=\"{config.SITE_URL}\">{sc('Anime Void TV')}</a>\n"
        f"≡ {sc('Powered By')} : <a href=\"{config.POWERED_BY_URL}\">{config.POWERED_BY_NAME}</a>"
    )


def help_text(is_owner: bool) -> str:
    base = (
        f"<blockquote>❐ <b>{sc('How to use')}</b></blockquote>\n{LINE}\n"
        f"<blockquote>{scx('›› Join the channel and turn notifications on.')}\n"
        f"{scx('›› New episodes drop with a banner and a')} <b>{sc('Watch Now')}</b> {scx('button.')}\n"
        f"{scx('›› Tap the button to stream the episode on the site.')}</blockquote>\n{LINE}\n"
    )
    if not is_owner:
        return base + f"≡ {sc('Site')} : <a href=\"{config.SITE_URL}\">{sc('Anime Void TV')}</a>"
    cmds = [
        ("/pause", "stop api checking"),
        ("/resume", "start api checking again"),
        ("/check", "run an api check right now"),
        ("/status", "site, api and bot health"),
        ("/logs", "get the log file"),
        ("/post &lt;url&gt; [position]", "post one anime from a json page"),
        ("/batch_post &lt;url&gt; [force]", "post every anime on that page"),
        ("/set_int &lt;seconds&gt;", "api check interval"),
        ("/post_design", "set the caption style"),
        ("/set_sticker", "reply to a sticker"),
        ("/c_btn", "custom buttons for every post"),
        ("/restart", "refresh the bot"),
    ]
    body = "\n".join(f"›› <code>{c.split(' ')[0]}</code>{c[len(c.split(' ')[0]):]} — {sc(d)}" for c, d in cmds)
    return base + f"<blockquote expandable><b>≡ {sc('Owner commands')}</b>\n{body}</blockquote>"


def about_text() -> str:
    import pyrogram
    return (
        f"<blockquote>❐ <b>{sc('About')}</b></blockquote>\n{LINE}\n"
        f"<blockquote>{kv('Bot', esc(config.CHANNEL_NAME))}\n"
        f"{kv('Version', config.VERSION)}\n"
        f"{kv('Library', 'Kurigram ' + pyrogram.__version__)}\n"
        f"{kv('Database', 'MongoDB')}</blockquote>\n{LINE}\n"
        f"≡ {sc('Powered By')} : <a href=\"{config.POWERED_BY_URL}\">{config.POWERED_BY_NAME}</a>"
    )


def start_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(sc("About"), callback_data="about"),
        InlineKeyboardButton(sc("Help"), callback_data="help"),
    ]])


def nav_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(sc("Home"), callback_data="home"),
        InlineKeyboardButton(sc("Close"), callback_data="close"),
    ]])


C_BTN_PROMPT = (
    "✎ " + sc("send me the buttons") + " :\n\n"
    + sc("Format") + " :\n"
    "<code>Button text 1 - http://example.com/\nButton text 2 - http://example2.com/</code>\n\n"
    + sc("Use") + " | " + sc("for up to 3 buttons per row") + " :\n"
    "<code>Btn 1 - http://x.com/ | Btn 2 - http://y.com/\nBtn 3 - http://z.com/</code>\n\n"
    + sc("Popup alert (no link)") + " — " + sc("use plain text as value") + " :\n"
    "<code>Season 01 - SEASON 01\n480p - https://xxx | 720p - https://xxx\n1080p - https://xxx\n"
    "Season 02 - SEASON 02\n480p - https://xxx | 720p - https://xxx</code>\n\n"
    + sc("Send /cancel to abort, or use /c_btn clear to remove all custom buttons.")
)


def post_design_prompt(current: Optional[str]) -> str:
    ph = "\n".join(f"<code>{{{n}}}</code> — {sc(d)}" for n, d in PLACEHOLDERS)
    state = sc("custom style active") if current else sc("using the default style")
    return (
        f"<blockquote>❐ <b>{sc('Post design')}</b></blockquote>\n{LINE}\n"
        f"›› {sc('Now')} : {state}\n\n"
        f"✎ {sc('Reply to a formatted text message with /post_design to use it as the caption, or just send the new design as your next message.')}\n"
        f"{sc('Use /post_design reset for the default style, /post_design show to see the current one.')}\n\n"
        f"<blockquote expandable><b>≡ {sc('Placeholders')}</b>\n{ph}</blockquote>"
    )


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    d, r = divmod(seconds, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    parts = [f"{d}d"] if d else []
    if h or d:
        parts.append(f"{h}h")
    parts.append(f"{m}m")
    if not d:
        parts.append(f"{s}s")
    return " ".join(parts)


def fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"