"""Generate the NYC taxi livery textures (decals, plates, roof topper panels).

Run with any Python that has Pillow installed:
    python3 scripts/make_textures.py
Output PNGs go to ./textures/ and are packed into the .blend by build_taxi.py.
"""
import os
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "textures")
os.makedirs(OUT, exist_ok=True)

FONT_DIR = "/usr/share/fonts/truetype/liberation"
BOLD = os.path.join(FONT_DIR, "LiberationSans-Bold.ttf")
REG = os.path.join(FONT_DIR, "LiberationSans-Regular.ttf")

MEDALLION = "5J47"
PLATE = "T640852C"

BLACK = (12, 12, 12, 255)
TAXI_YELLOW = (247, 181, 0, 255)
CLEAR = (0, 0, 0, 0)


def font(path, px):
    return ImageFont.truetype(path, px)


def fit_font(path, text, max_w, max_h):
    """Largest font size whose rendered text fits in max_w x max_h."""
    lo, hi = 4, 2000
    while lo < hi:
        mid = (lo + hi + 1) // 2
        l, t, r, b = font(path, mid).getbbox(text)
        if r - l <= max_w and b - t <= max_h:
            lo = mid
        else:
            hi = mid - 1
    return font(path, lo)


def draw_centered(d, box, text, f, fill):
    x0, y0, x1, y1 = box
    l, t, r, b = f.getbbox(text)
    d.text(((x0 + x1) / 2 - (l + r) / 2, (y0 + y1) / 2 - (t + b) / 2), text, font=f, fill=fill)


def nyc_taxi_logo(h_px, with_bg=None):
    """Black square with 'NYC' knocked out (paint shows through) + 'TAXI' in black."""
    pad = int(h_px * 0.06)
    sq = h_px - 2 * pad
    gap = int(h_px * 0.16)
    f_taxi = font(BOLD, int(sq * 0.62))
    l, t, r, b = f_taxi.getbbox("TAXI")
    w = pad + sq + gap + (r - l) + pad
    img = Image.new("RGBA", (w, h_px), with_bg or CLEAR)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((pad, pad, pad + sq, pad + sq), radius=int(sq * 0.06), fill=BLACK)
    # knock the letters out of the square so the yellow paint shows through
    mask = Image.new("L", img.size, 0)
    md = ImageDraw.Draw(mask)
    f_nyc = fit_font(BOLD, "NYC", sq * 0.82, sq * 0.5)
    draw_centered(md, (pad, pad, pad + sq, pad + sq), "NYC", f_nyc, 255)
    knock = Image.new("RGBA", img.size, with_bg or CLEAR)
    img.paste(knock, (0, 0), mask)
    # TAXI, cap height matched to NYC and baseline-aligned with the square's centre
    ty = pad + sq / 2 - (t + b) / 2
    d.text((pad + sq + gap - l, ty), "TAXI", font=f_taxi, fill=BLACK)
    return img


def save(img, name):
    p = os.path.join(OUT, name)
    img.save(p)
    print("wrote", p, img.size)


# 1. Front-door logo decal (0.60 m x 0.20 m on the car)
logo = nyc_taxi_logo(700)
save(logo, "decal_nyc_taxi_logo.png")

# 2. Rear-door rate-of-fare decal (0.46 m x 0.27 m)
W, H = 1840, 1080
fare = Image.new("RGBA", (W, H), CLEAR)
d = ImageDraw.Draw(fare)
lines = [
    ("RATE OF FARE", BOLD, 130),
    ("$3.00 INITIAL CHARGE", BOLD, 104),
    ("PLUS 70¢ PER 1/5 MILE", REG, 84),
    ("OR 70¢ PER MINUTE IN SLOW TRAFFIC", REG, 70),
    ("OR WHEN THE VEHICLE IS STOPPED", REG, 70),
    ("ADDITIONAL SURCHARGES MAY APPLY", REG, 58),
]
y = 40
for text, fp, px in lines:
    f = font(fp, px)
    l, t, r, b = f.getbbox(text)
    d.text(((W - (r - l)) / 2 - l, y - t), text, font=f, fill=BLACK)
    y += (b - t) + int(px * 0.42)
d.line((140, y + 6, W - 140, y + 6), fill=BLACK, width=8)
f = font(BOLD, 78)
text = "COMPLAINTS & LOST PROPERTY: CALL 311"
l, t, r, b = f.getbbox(text)
d.text(((W - (r - l)) / 2 - l, y + 40 - t), text, font=f, fill=BLACK)
save(fare, "decal_rate_of_fare.png")

# 3. Medallion number decal for rear quarters / trunk (0.26 m x 0.10 m)
W, H = 1040, 400
med = Image.new("RGBA", (W, H), CLEAR)
d = ImageDraw.Draw(med)
draw_centered(d, (0, 0, W, H), MEDALLION, fit_font(BOLD, MEDALLION, W * 0.94, H * 0.86), BLACK)
save(med, "decal_medallion_number.png")

# 4. NY taxi license plate (12 in x 6 in, 2:1)
W, H = 1200, 600
plate = Image.new("RGBA", (W, H), (246, 244, 236, 255))
d = ImageDraw.Draw(plate)
blue = (18, 45, 110, 255)
gold = (232, 170, 30, 255)
d.rectangle((0, 0, W, 118), fill=blue)
d.rectangle((0, 118, W, 136), fill=gold)
d.rectangle((0, H - 110, W, H), fill=blue)
draw_centered(d, (0, 4, W, 116), "NEW YORK", font(BOLD, 92), (255, 255, 255, 255))
draw_centered(d, (0, H - 108, W, H - 4), "TAXI", font(BOLD, 88), gold)
draw_centered(d, (0, 150, W, H - 124), PLATE, fit_font(BOLD, PLATE, W * 0.9, 260), blue)
for cx in (W * 0.14, W * 0.86):  # mounting holes
    d.ellipse((cx - 22, 160 - 22, cx + 22, 160 + 22), fill=(160, 160, 160, 255))
d.rounded_rectangle((6, 6, W - 7, H - 7), radius=40, outline=(30, 30, 30, 255), width=10)
save(plate, "plate_ny_taxi.png")

# 5. Roof topper side ad panel (backlit, 1.00 m x 0.28 m)
W, H = 2400, 672
ad = Image.new("RGBA", (W, H), (16, 24, 48, 255))
d = ImageDraw.Draw(ad)
for i in range(H):  # subtle vertical gradient
    c = int(16 + 30 * i / H)
    d.line((0, i, W, i), fill=(c, c + 10, c + 34, 255))
lg = nyc_taxi_logo(430, with_bg=TAXI_YELLOW)
tile = Image.new("RGBA", (lg.width + 60, lg.height + 60), TAXI_YELLOW)
tile.paste(lg, (30, 30), lg)
ad.paste(tile, (70, (H - tile.height) // 2))
x0 = 70 + tile.width + 90
draw_centered(d, (x0, 60, W - 60, 380), "SEE THE CITY", fit_font(BOLD, "SEE THE CITY", W - x0 - 120, 240), (255, 255, 255, 255))
draw_centered(d, (x0, 400, W - 60, 600), "HAIL • RIDE • TAP TO PAY", fit_font(REG, "HAIL • RIDE • TAP TO PAY", W - x0 - 160, 120), (247, 181, 0, 255))
save(ad, "topper_ad_panel.png")

# 6. Roof topper end panel: lit medallion number (0.09 m x 0.20 m)
W, H = 450, 1000
end = Image.new("RGBA", (W, H), (255, 246, 214, 255))
d = ImageDraw.Draw(end)
d.rectangle((0, 0, W, 300), fill=(20, 20, 20, 255))
draw_centered(d, (0, 20, W, 150), "NYC", fit_font(BOLD, "NYC", W * 0.7, 110), TAXI_YELLOW)
draw_centered(d, (0, 160, W, 290), "TAXI", fit_font(BOLD, "TAXI", W * 0.7, 110), TAXI_YELLOW)
f = fit_font(BOLD, "5J", W * 0.8, 300)
draw_centered(d, (0, 320, W, 650), MEDALLION[:2], f, (15, 15, 15, 255))
draw_centered(d, (0, 660, W, 990), MEDALLION[2:], f, (15, 15, 15, 255))
save(end, "topper_medallion_light.png")
