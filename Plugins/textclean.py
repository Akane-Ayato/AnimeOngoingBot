"""
Description / synopsis cleaner: fixes encoded characters, removes links, markdown,
source credits and other noise so the text is safe to put on a poster or in a caption.
"""
import html
import re
import unicodedata

_MD_LINK = re.compile(r"\[[^\]]*\]\([^)]*\)")                      # [Original Webtoon](https://...)  -> removed completely
_HTML_TAG = re.compile(r"<[^>]+>")
_URL = re.compile(r"(?:https?://|ftp://|www\.)\S+", re.I)
_DOMAIN = re.compile(r"\b[\w-]+\.(?:com|net|org|io|co|me|xyz|site|app|tv|cc|to|info|space)\b(?:/\S*)?", re.I)
_SOURCE = re.compile(
    r"(?:[\(\[\*_]\s*)?(?:source|written by|written|summary by|adapted from|translated by|credits?)\s*:[^)\]\n]*?(?:[\)\]\*_]|$)",
    re.I,
)
_BRACES = re.compile(r"\{[^}]*\}")
_SPOILER = re.compile(r"~!.*?!~", re.S)
_CTRL = re.compile(r"[\u0000-\u0008\u000b-\u001f\u007f-\u009f\u200b-\u200f\u2028-\u202f\u2060\ufeff]")
_TAIL_NOISE = re.compile(r"\s*(?:original\s+(?:webtoon|manhwa|manga|novel|work)|read\s+more|see\s+more)\s*[.!]?\s*$", re.I)


# a UTF-8 lead character followed by continuation characters, as they look after a cp1252 / latin-1 mis-decode
_MOJIBAKE = re.compile(
    "[\u00c2-\u00f4][\u0080-\u00bf\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u0192\u02c6\u02dc"
    "\u2013\u2014\u2018-\u201e\u2020-\u2022\u2026\u2030\u2039\u203a\u20ac\u2122]+"
)


def _repair(match) -> str:
    chunk = match.group(0)
    raw = bytearray()
    for ch in chunk:                       # cp1252 byte if it has one, otherwise the raw latin-1 byte (e.g. U+009D)
        for enc in ("cp1252", "latin-1"):
            try:
                raw += ch.encode(enc)
                break
            except UnicodeEncodeError:
                continue
        else:
            return chunk
    try:
        return bytes(raw).decode("utf-8") or chunk
    except UnicodeDecodeError:
        return chunk


def fix_encoding(s: str) -> str:
    """Repair mojibake such as 'â€™' or 'Ã©' (UTF-8 text that was decoded as cp1252 / latin-1),
    piece by piece, so correctly encoded text around it is left alone."""
    return _MOJIBAKE.sub(_repair, s)


def clean_text(raw, limit: int = 0) -> str:
    """
    limit=0 keeps everything (for captions, which are trimmed later);
    limit>0 cuts at a sentence / word boundary (for posters).
    """
    if not raw:
        return ""
    s = str(raw)
    s = fix_encoding(s)
    for _ in range(2):                       # &amp;#8217;  ->  &#8217;  ->  ’
        s2 = html.unescape(s)
        if s2 == s:
            break
        s = s2
    s = unicodedata.normalize("NFC", s)
    s = _SPOILER.sub(" ", s)
    s = _MD_LINK.sub(" ", s)
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = _HTML_TAG.sub(" ", s)
    s = _URL.sub(" ", s)
    s = _DOMAIN.sub(" ", s)
    s = _SOURCE.sub(" ", s)
    s = _BRACES.sub(" ", s)
    s = _CTRL.sub(" ", s)
    s = re.sub(r"[*_`#>|~]+", " ", s)       # markdown emphasis / headings / quotes
    s = re.sub(r"\s+", " ", s).strip()
    s = _TAIL_NOISE.sub("", s)
    s = re.sub(r"(?<=[a-z])([.!?])(?=[A-Z])", r"\1 ", s)      # 'charms.As the' -> 'charms. As the'
    s = re.sub(r":(?=[\u201c\"])", ": ", s)
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    s = re.sub(r"\s+", " ", s).strip(" -\u2013\u2014")
    if limit and len(s) > limit:
        cut = s[:limit]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind(".\u201d "), cut.rfind("\u2026 "))
        if end > limit * 0.4:
            return cut[: end + 1].strip()
        cut = cut[: cut.rfind(" ")] if " " in cut else cut
        return cut.rstrip(",;:- ") + "..."
    return s
