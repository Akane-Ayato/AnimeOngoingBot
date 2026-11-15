"""
Manhwa poster (style from the user's manhwa-poster.py): white left panel, dark blurred right panel,
red block with a landscape cover card, genre chips + rating chip, cleaned description.
Header text is the MMWC VOID brand.
"""
from Plugins.poster_kit import (
    BASE, Canvas, H, Image, ImageDraw, ImageFilter, W, draw_description, draw_tags, draw_title,
    finish, prepare_meta,
)
import config

# ======================================================================
# style 6: colours + layout   (white left panel, dark blurred right panel, red block + landscape cover card)
# ======================================================================
RED_TOP, RED_BOT = (198, 50, 40), (222, 96, 84)
ACC, DARK, LT = (210, 48, 48, 255), (40, 41, 52, 255), (242, 150, 140, 255)
THEME = dict(BASE,
    accent=ACC, mid=ACC, g1=RED_TOP, g2=RED_BOT, title1=DARK, title2=ACC, body=(60, 64, 76, 255),
    tag_text=(130, 134, 146, 255), box_fill=(241, 241, 241, 255), box_border=(226, 226, 230, 255))
BRAND = config.MANHWA_BRAND.upper()   # header text (MANHWA_BRAND env var, default "MMWC VOID")


def _cross(cv, cx, cy, r, color, w):
    cv.polyline([(cx - r, cy - r), (cx + r, cy + r)], color, w)
    cv.polyline([(cx - r, cy + r), (cx + r, cy - r)], color, w)


def _blurred_panel(cv, cover, x0=1372):
    """Dark, blurred copy of the cover filling the right edge of the poster."""
    if cover is None:
        cv.base.paste((60, 62, 70, 255), (x0, 0, W, H))
        return
    pw = W - x0
    img = cover.convert("RGB")
    sc = H / img.height
    img = img.resize((max(pw, int(img.width * sc)), H), Image.LANCZOS)
    l = (img.width - pw) // 2
    img = img.crop((l, 0, l + pw, H)).filter(ImageFilter.GaussianBlur(7)).point(lambda v: int(v * 0.38))
    cv.base.paste(img.convert("RGBA"), (x0, 0))


def _card(cv, cover, character, box, r=60):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if cover is not None:                                  # landscape crop, biased up so faces stay in frame
        img = cover.convert("RGB")
        ch = min(img.height, int(img.width * h / w))
        top = min(int(img.height * 0.047), img.height - ch)
        img = img.crop((0, top, img.width, top + ch)).resize((w, h), Image.LANCZOS).convert("RGBA")
    else:
        img = Image.new("RGBA", (w, h), (246, 246, 248, 255))
        if character is not None:
            ch = character.convert("RGBA")
            bb = ch.getchannel("A").getbbox()
            ch = ch.crop(bb) if bb else ch
            sc = min(w * 0.8 / ch.width, h * 0.92 / ch.height)
            ch = ch.resize((int(ch.width * sc), int(ch.height * sc)), Image.LANCZOS)
            img.paste(ch, ((w - ch.width) // 2, h - ch.height), ch)
    cv.shadow(box, r, (0, 22), 28, (40, 20, 20, 110))
    m = Image.new("L", (w * 4, h * 4), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w * 4, h * 4], radius=r * 4, fill=255)
    cv.paste(img, (x0, y0), m.resize((w, h), Image.LANCZOS))


def _draw(cv, th, meta, character, cover, button):
    X, MAXW = 120, 950

    # --- right side: dark blurred panel, red block, cover card ---
    _blurred_panel(cv, cover)
    red_box = (1184, 187, 1562, 892)
    cv.shadow(red_box, 60, (0, 20), 26, (120, 40, 30, 90))
    cv.gradient_rounded_box(red_box, 60, RED_TOP, RED_BOT, "v")
    _card(cv, cover, character, (1214, 295, 1908, 784))

    # --- decoration ---
    for x0, y0, sz, col in [(760, -40, 110, LT), (865, 22, 90, ACC)]:
        cv.rounded_box((x0, y0, x0 + sz, y0 + sz), sz * 0.26, outline=col, width=3)
    cv.star(1010, 125, 20, ACC)
    _cross(cv, 640, 105, 12, DARK, 8)
    cv.polyline([(120 + i * 17, 975 + (14 if i % 2 else 0)) for i in range(8)], ACC, 6)
    for i in range(5):
        for j in range(4):
            cv.circle(470 + i * 20, 930 + j * 20, 3, fill=LT)
    t, pts = [i / 120 for i in range(121)], []
    for u in t:
        a, b, c, d = (520, 1085), (690, 930), (790, 1090), (920, 965)
        v = 1 - u
        pts.append((v**3 * a[0] + 3 * v * v * u * b[0] + 3 * v * u * u * c[0] + u**3 * d[0],
                    v**3 * a[1] + 3 * v * v * u * b[1] + 3 * v * u * u * c[1] + u**3 * d[1]))
    cv.polyline(pts, DARK, 3)
    cv.star(330, 1015, 16, LT)
    cv.circle(930, 850, 11, outline=ACC, width=3)

    # --- header ---
    cv.circle(X + 39, 72, 39, fill=(0, 0, 0, 255))
    for yy in (60, 72, 84):
        cv.rounded_box((X + 24, yy - 3, X + 56, yy + 3), 3, fill=(255, 255, 255, 255))
    cv.text((X + 98, 74), BRAND, cv.font("Lilita", 40), DARK, anchor="lm")

    # --- text column ---
    last = draw_title(cv, th, meta, X, MAXW, 290, mode="first", pitch=1.02, font="Lilita", tracking_em=0.0,
                      three_line_below=60)
    ty = last + 40
    draw_tags(cv, th, meta, X, ty, size=20, h=56, pad=22, gap=16, radius=10)
    by0 = ty + 56 + 30
    h = draw_description(cv, th, meta, X, by0, MAXW, size=22, lh=40, pad_x=26, pad_y=17, radius=10, hl=ACC, limit=330)
    by = by0 + h + 36
    cv.shadow((X, by, X + 320, by + 80), 40, (0, 14), 16, (120, 40, 30, 110))
    cv.gradient_rounded_box((X, by, X + 320, by + 80), 40, (196, 48, 38), (222, 84, 72), "v")
    white = (255, 255, 255, 255)
    cv.text((X + 38, by + 40), button, cv.font("Bold", 23), white, anchor="lm")
    cx, cy = X + 320 - 50, by + 40
    cv.circle(cx, cy, 24, fill=white)
    cv.arrow(cx - 10, cx + 10, cy, ACC, width=3, head=8)

def render_poster(meta, cover=None, button="READ NOW"):
    """meta: title, genres[], score (0-100, optional), description.  cover: PIL image.  Returns a 1920x1080 RGB image."""
    cv = Canvas()
    _draw(cv, THEME, prepare_meta(meta), None, cover, button)
    return finish(cv)
