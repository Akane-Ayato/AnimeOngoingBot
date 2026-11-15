"""
Anime poster (style from the user's Anime-poster.py): white page, red / dark corner bands,
Lilita One title, genre chips, description box and a WATCH NOW button; the API poster sits in a
rounded cover card on the right. A small black credit sits in the lower-right corner.
"""
from Plugins.poster_kit import (
    BASE, Canvas, H, Image, ImageDraw, ImageFilter, W, draw_description, draw_tags, draw_title,
    finish, menu_icon, place_cover_card, prepare_meta,
)
import config

# ======================================================================
# style 4: colours + layout   (white page, red/dark corner bands, Lilita One title)
# ======================================================================
RED, DARK = (232, 38, 66, 255), (40, 41, 52, 255)
THEME = dict(BASE,
    accent=RED, mid=RED, g1=RED[:3], g2=RED[:3], title1=DARK, title2=RED, body=(60, 64, 76, 255),
    tag_text=(130, 134, 146, 255), box_fill=(241, 241, 241, 255), box_border=(226, 226, 230, 255),
    dots=(236, 120, 138, 255))


def _corner(cv, rot, scale=0.6):
    """Red band + dark triangle in the top-right corner; rot=True mirrors it (180 deg) to the bottom-left."""
    dark = [(1920 - 450 * scale, 0), (1920, 0), (1920, 450 * scale)]
    band = [(1920 - 590 * scale, 0), (1920 - 450 * scale, 0), (1920, 450 * scale), (1920, 600 * scale)]
    f = (lambda p: (1920 - p[0], 1080 - p[1])) if rot else (lambda p: p)
    cv.polygon([f(p) for p in band], RED)
    cv.polygon([f(p) for p in dark], DARK)


def _cross(cv, cx, cy, r, color, w):
    cv.polyline([(cx - r, cy - r), (cx + r, cy + r)], color, w)
    cv.polyline([(cx - r, cy + r), (cx + r, cy - r)], color, w)


def _character_with_shadow(cv, character, cx, bottom, max_w, max_h):
    ch = character.convert("RGBA")
    bbox = ch.getchannel("A").getbbox()
    if bbox:
        ch = ch.crop(bbox)
    sc = min(max_w / ch.width, max_h / ch.height)
    ch = ch.resize((max(1, int(ch.width * sc)), max(1, int(ch.height * sc))), Image.LANCZOS)
    x, y = int(cx - ch.width / 2), int(bottom - ch.height)
    cv.flush()
    sh = Image.new("RGBA", cv.base.size, (0, 0, 0, 0))
    sh.paste(Image.new("RGBA", ch.size, (60, 20, 30, 255)), (x + 14, y + 10), ch.getchannel("A").point(lambda v: int(v * 0.30)))
    cv.base = Image.alpha_composite(cv.base, sh.filter(ImageFilter.GaussianBlur(10)))
    cv.paste(ch, (x, y))


def _draw(cv, th, meta, character, cover, button):
    X, MAXW = 120, 950

    # --- background shapes ---
    _corner(cv, False)
    _corner(cv, True)
    _cross(cv, 1215, 150, 13, RED, 8)
    _cross(cv, 1180, 700, 17, DARK, 10)
    _cross(cv, 1100, 960, 11, RED, 7)
    _cross(cv, 420, 60, 12, DARK, 8)
    cv.polyline([(640 + i * 18, 985 + (14 if i % 2 else 0)) for i in range(8)], RED, 6)
    for i in range(7):
        for j in range(5):
            cv.circle(1700 + i * 24, 850 + j * 24, 4, fill=th["dots"])

    # --- character (or cover card as fallback) ---
    if character is not None:
        _character_with_shadow(cv, character, 1495, 1075, 520, 1040)
    elif cover is not None:
        place_cover_card(cv, cover, 1330, 190)
    menu_icon(cv, "bars")

    # --- text column ---
    last = draw_title(cv, th, meta, X, MAXW, 290, mode="first", pitch=1.02, font="Lilita", tracking_em=0.0,
                      three_line_below=60)
    ty = last + 40
    draw_tags(cv, th, meta, X, ty, size=20, h=56, pad=22, gap=16, radius=10)
    by0 = ty + 56 + 30
    h = draw_description(cv, th, meta, X, by0, MAXW, size=22, lh=40, pad_x=26, pad_y=17, radius=10, hl=RED, limit=330)
    by = by0 + h + 36
    cv.rounded_box((X, by, X + 320, by + 80), 40, fill=RED)
    white = (255, 255, 255, 255)
    cv.text((X + 38, by + 40), button, cv.font("Bold", 23), white, anchor="lm")
    cx, cy = X + 320 - 50, by + 40
    cv.circle(cx, cy, 24, fill=white)
    cv.arrow(cx - 10, cx + 10, cy, RED, width=3, head=8)

    # small black credit, lower-right corner
    cv.text((1880, 1050), config.ANIME_CREDIT, cv.font("Medium", 24), (20, 20, 24, 255), anchor="rs")


def render_poster(meta, character=None, cover=None, button="WATCH NOW"):
    """Returns a 1920x1080 PIL RGB image."""
    cv = Canvas()
    _draw(cv, THEME, meta, character, cover, button)
    return finish(cv)


def render_poster_bytes(meta, character=None, cover=None, fmt="PNG"):
    return to_bytes(render_poster(meta, character, cover), fmt)


def render_poster(meta, cover=None, button="WATCH NOW"):
    """meta: title, genres[], description.  cover: PIL image of the API poster.  Returns a 1920x1080 RGB image."""
    cv = Canvas()
    _draw(cv, THEME, prepare_meta(meta), None, cover, button)
    return finish(cv)
