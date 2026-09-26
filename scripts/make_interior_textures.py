"""Generate the NYC taxi interior textures (Taxi TV, card reader, taximeter, TLC notices).

Run with any Python that has Pillow installed:
    python3 scripts/make_interior_textures.py
Output PNGs go to ./textures/ and are packed into the .blend by build_interior.py.
"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont


# Shared with make_textures.py (kept in sync by hand so running this does not rewrite the livery).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "textures")
os.makedirs(OUT, exist_ok=True)

FONT_DIR = "/usr/share/fonts/truetype/liberation"
BOLD = os.path.join(FONT_DIR, "LiberationSans-Bold.ttf")
REG = os.path.join(FONT_DIR, "LiberationSans-Regular.ttf")

MEDALLION = "5J47"

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



WHITE = (255, 255, 255, 255)
GREY = (150, 156, 166, 255)
DARK = (22, 26, 34, 255)
RED_LED = (255, 40, 24, 255)
TLC_BLUE = (18, 45, 110, 255)

FARE = "$3.00"          # meter reading at the start of a trip (initial charge)
HACK_NO = "5512847"     # driver's TLC licence number (fictional)
DRIVER = "DOE, JOHN"    # placeholder name


def text_left(d, xy, text, f, fill):
    l, t, _, _ = f.getbbox(text)
    d.text((xy[0] - l, xy[1] - t), text, font=f, fill=fill)


def text_right(d, xy, text, f, fill):
    l, t, r, _ = f.getbbox(text)
    d.text((xy[0] - r, xy[1] - t), text, font=f, fill=fill)


# 1. Passenger Information Monitor ("Taxi TV") in the partition, 16:10
W, H = 1600, 1000
tv = Image.new("RGBA", (W, H), (12, 14, 20, 255))
d = ImageDraw.Draw(tv)
# top bar
d.rectangle((0, 0, W, 96), fill=(28, 30, 38, 255))
lg = nyc_taxi_logo(80, with_bg=TAXI_YELLOW)
bar = Image.new("RGBA", (lg.width + 16, 96), TAXI_YELLOW)
bar.paste(lg, (8, 8), lg)
tv.paste(bar, (0, 0))
text_left(d, (bar.width + 30, 30), f"MEDALLION {MEDALLION}", font(BOLD, 38), WHITE)
text_right(d, (W - 30, 30), "10:42 AM", font(BOLD, 38), WHITE)
# map panel (left): Manhattan-style street grid with the route
mx0, my0, mx1, my1 = 0, 96, 1040, H - 110
mp = Image.new("RGBA", (mx1 - mx0, my1 - my0), (232, 228, 218, 255))
m = ImageDraw.Draw(mp)
MW, MH = mp.size
m.polygon([(0, 0), (120, 0), (40, MH), (0, MH)], fill=(160, 196, 222, 255))          # Hudson
m.polygon([(MW - 90, 0), (MW, 0), (MW, MH), (MW - 200, MH)], fill=(160, 196, 222, 255))  # East River
ang = math.radians(29)                                  # Manhattan's street grid is tilted ~29 deg
ca, sa = math.cos(ang), math.sin(ang)
for i in range(-20, 30):
    s0 = i * 60                                         # streets
    m.line(((s0 * ca - 1500 * sa, s0 * sa + 1500 * ca), (s0 * ca + 1500 * sa, s0 * sa - 1500 * ca)),
           fill=WHITE, width=5)
    s0 = i * 180                                        # avenues
    m.line(((s0 * sa - 1500 * ca, -s0 * ca - 1500 * sa), (s0 * sa + 1500 * ca, -s0 * ca + 1500 * sa)),
           fill=WHITE, width=12)
m.polygon([(0, 0), (120, 0), (40, MH), (0, MH)], fill=(160, 196, 222, 255))
m.polygon([(MW - 90, 0), (MW, 0), (MW, MH), (MW - 200, MH)], fill=(160, 196, 222, 255))
m.polygon([(430, 260), (560, 190), (700, 520), (570, 590)], fill=(170, 214, 150, 255))  # park
route = [(250, 700), (330, 560), (420, 600), (560, 330), (700, 170), (820, 230)]
m.line(route, fill=(30, 110, 230, 255), width=16, joint="curve")
x, y = route[0]
m.ellipse((x - 20, y - 20, x + 20, y + 20), fill=(30, 110, 230, 255), outline=WHITE, width=6)
x, y = route[-1]
m.ellipse((x - 26, y - 26, x + 26, y + 26), fill=(220, 40, 40, 255), outline=WHITE, width=6)
tv.paste(mp, (mx0, my0))
d.line((mx1, my0, mx1, my1), fill=(40, 44, 54, 255), width=6)
# fare panel (right)
fx = 1080
text_left(d, (fx, 140), "FARE", font(BOLD, 44), GREY)
text_left(d, (fx, 200), FARE, font(BOLD, 150), WHITE)
rows = [("Distance", "0.0 mi"), ("Time", "00:00"), ("Extras", "$0.00"), ("Surcharges", "$1.00"),
        ("Congestion", "$2.50")]
y = 410
for k, v in rows:
    text_left(d, (fx, y), k, font(REG, 40), GREY)
    text_right(d, (W - 40, y), v, font(BOLD, 40), WHITE)
    y += 66
d.rounded_rectangle((fx, 770, W - 40, 870), radius=22, fill=TAXI_YELLOW)
draw_centered(d, (fx, 770, W - 40, 870), "PAY & TIP", font(BOLD, 54), BLACK)
# bottom ticker
d.rectangle((0, H - 110, W, H), fill=(28, 30, 38, 255))
draw_centered(d, (0, H - 110, W, H), "TAP, INSERT OR SWIPE TO PAY  •  PLEASE BUCKLE UP  •  CALL 311 FOR LOST PROPERTY",
              font(BOLD, 36), WHITE)
save(tv, "interior_taxi_tv_screen.png")

# 2. Credit card reader face (tap / chip / swipe), 2:3 portrait
W, H = 600, 900
cr = Image.new("RGBA", (W, H), (26, 26, 28, 255))
d = ImageDraw.Draw(cr)
d.rounded_rectangle((40, 40, W - 40, 330), radius=18, fill=(16, 40, 60, 255))
draw_centered(d, (40, 60, W - 40, 180), "TAP OR", font(BOLD, 60), WHITE)
draw_centered(d, (40, 170, W - 40, 300), "INSERT CARD", font(BOLD, 60), WHITE)
cx, cy = W // 2, 470                                  # contactless symbol
for r in (40, 75, 110):
    d.arc((cx - r - 40, cy - r, cx + r - 40, cy + r), -55, 55, fill=WHITE, width=14)
keys = "123456789C0E"
for i, k in enumerate(keys):
    kx, ky = 80 + (i % 3) * 150, 600 + (i // 3) * 70
    d.rounded_rectangle((kx, ky, kx + 130, ky + 56), radius=10, fill=(60, 62, 66, 255))
    draw_centered(d, (kx, ky, kx + 130, ky + 56), k, font(BOLD, 36), WHITE)
save(cr, "interior_card_reader.png")

# 3. Taximeter face (red LED digits), 5:2
W, H = 1000, 400
tm = Image.new("RGBA", (W, H), (10, 10, 10, 255))
d = ImageDraw.Draw(tm)
d.rectangle((24, 24, W - 24, H - 24), outline=(60, 60, 60, 255), width=6)
glow = Image.new("RGBA", (W, H), CLEAR)
g = ImageDraw.Draw(glow)
draw_centered(g, (40, 30, 700, 300), FARE, fit_font(BOLD, FARE, 620, 230), RED_LED)
for i, lab in enumerate(("VACANT", "HIRED", "TIME OFF")):
    lit = lab == "HIRED"
    g.rounded_rectangle((730, 50 + i * 100, 960, 130 + i * 100), radius=10,
                        fill=RED_LED if lit else (60, 14, 10, 255))
    draw_centered(g, (730, 50 + i * 100, 960, 130 + i * 100), lab, font(BOLD, 44),
                  (20, 0, 0, 255) if lit else (120, 30, 20, 255))
draw_centered(g, (40, 300, 700, 370), "EXTRAS 0.00   RATE 1", font(BOLD, 44), RED_LED)
tm = Image.alpha_composite(tm, glow.filter(ImageFilter.GaussianBlur(6)))
tm = Image.alpha_composite(tm, glow)
save(tm, "interior_taximeter.png")

# 4. Driver's hack licence in its partition holder, 3:2
W, H = 1200, 800
hl = Image.new("RGBA", (W, H), (244, 242, 236, 255))
d = ImageDraw.Draw(hl)
d.rectangle((0, 0, W, 150), fill=TLC_BLUE)
draw_centered(d, (0, 10, W, 80), "NYC TAXI & LIMOUSINE COMMISSION", font(BOLD, 52), WHITE)
draw_centered(d, (0, 80, W, 145), "TAXICAB DRIVER'S LICENSE", font(BOLD, 44), TAXI_YELLOW)
d.rectangle((60, 200, 420, 680), fill=(176, 186, 198, 255))            # photo
d.ellipse((170, 260, 310, 420), fill=(96, 104, 116, 255))
d.pieslice((100, 430, 380, 760), 180, 360, fill=(96, 104, 116, 255))
d.rectangle((60, 680, 420, 700), fill=(244, 242, 236, 255))
text_left(d, (470, 210), "LICENSE NO.", font(REG, 40), (80, 80, 80, 255))
text_left(d, (470, 260), HACK_NO, font(BOLD, 110), BLACK)
text_left(d, (470, 420), "NAME", font(REG, 40), (80, 80, 80, 255))
text_left(d, (470, 470), DRIVER, font(BOLD, 72), BLACK)
text_left(d, (470, 590), "EXPIRES 09/30/2028", font(BOLD, 48), BLACK)
d.rectangle((0, H - 60, W, H), fill=TAXI_YELLOW)
draw_centered(d, (0, H - 60, W, H), "THIS LICENSE MUST BE DISPLAYED AT ALL TIMES", font(BOLD, 36), BLACK)
save(hl, "interior_hack_license.png")

# 5. Passenger Bill of Rights, portrait
W, H = 1000, 1400
pb = Image.new("RGBA", (W, H), (250, 248, 240, 255))
d = ImageDraw.Draw(pb)
d.rectangle((0, 0, W, 220), fill=TAXI_YELLOW)
draw_centered(d, (0, 20, W, 120), "TAXI RIDER", font(BOLD, 86), BLACK)
draw_centered(d, (0, 110, W, 210), "BILL OF RIGHTS", font(BOLD, 86), BLACK)
rights = [
    "Go to any destination in the five boroughs",
    "A safe, courteous driver who obeys traffic laws",
    "Direct your route, or ask for the fastest one",
    "A clean, smoke-free, scent-free car",
    "A driver who does not use a phone while driving",
    "Air conditioning or heat on request",
    "Quiet: no horn honking or loud radio",
    "Pay by credit or debit card",
    "Receive a printed or emailed receipt",
    "Decline to tip for poor service",
]
fr = font(REG, 38)
y = 270
for r in rights:
    d.ellipse((60, y + 10, 84, y + 34), fill=BLACK)
    text_left(d, (110, y), r, fr, BLACK)
    y += 92
d.line((60, y + 10, W - 60, y + 10), fill=BLACK, width=6)
draw_centered(d, (0, y + 30, W, y + 110), "Complaints or lost items: call 311", font(BOLD, 48), BLACK)
draw_centered(d, (0, y + 110, W, y + 170), f"Medallion {MEDALLION}", font(BOLD, 44), BLACK)
save(pb, "interior_passenger_rights.png")

# 6. "Buckle up" seat-belt sticker, square
W = H = 700
bu = Image.new("RGBA", (W, H), CLEAR)
d = ImageDraw.Draw(bu)
d.rounded_rectangle((0, 0, W - 1, H - 1), radius=60, fill=TAXI_YELLOW)
d.rounded_rectangle((24, 24, W - 25, H - 25), radius=44, outline=BLACK, width=12)
draw_centered(d, (0, 50, W, 200), "BUCKLE UP", fit_font(BOLD, "BUCKLE UP", W * 0.8, 120), BLACK)
cx, cy = W // 2, 370                                   # seated figure with a belt
d.ellipse((cx - 50, cy - 150, cx + 50, cy - 50), fill=BLACK)
d.rounded_rectangle((cx - 80, cy - 40, cx + 80, cy + 120), radius=30, fill=BLACK)
d.line((cx - 70, cy - 30, cx + 80, cy + 110), fill=TAXI_YELLOW, width=22)
draw_centered(d, (0, 520, W, 620), "EVERY RIDE, EVERY SEAT", fit_font(BOLD, "EVERY RIDE, EVERY SEAT", W * 0.82, 70), BLACK)
save(bu, "interior_buckle_up.png")

# 7. No-smoking sticker, round
W = H = 500
ns = Image.new("RGBA", (W, H), CLEAR)
d = ImageDraw.Draw(ns)
d.ellipse((0, 0, W - 1, H - 1), fill=WHITE)
d.rounded_rectangle((90, 215, 410, 285), radius=8, fill=BLACK)
d.rectangle((350, 215, 410, 285), fill=(200, 90, 30, 255))
d.ellipse((20, 20, W - 21, H - 21), outline=(210, 20, 30, 255), width=44)
d.line((95, 95, 405, 405), fill=(210, 20, 30, 255), width=44)
save(ns, "interior_no_smoking.png")

# 8. Driver Information Monitor (driver's T-PEP tablet), 16:10
W, H = 800, 500
dm = Image.new("RGBA", (W, H), (14, 16, 22, 255))
d = ImageDraw.Draw(dm)
d.rectangle((0, 0, W, 64), fill=(28, 30, 38, 255))
text_left(d, (20, 18), "DRIVER", font(BOLD, 30), TAXI_YELLOW)
text_right(d, (W - 20, 18), "HIRED", font(BOLD, 30), (60, 220, 90, 255))
text_left(d, (30, 100), "TRIP FARE", font(BOLD, 30), GREY)
text_left(d, (30, 145), FARE, font(BOLD, 110), WHITE)
for i, (lab, col) in enumerate((("START", (40, 150, 70, 255)), ("EXTRAS", (60, 64, 76, 255)),
                                 ("END TRIP", (190, 40, 40, 255)))):
    x = 30 + i * 250
    d.rounded_rectangle((x, 360, x + 220, 460), radius=16, fill=col)
    draw_centered(d, (x, 360, x + 220, 460), lab, font(BOLD, 34), WHITE)
save(dm, "interior_driver_monitor.png")

# 9. Instrument cluster (behind the steering wheel), 8:3
W, H = 1200, 450
ic = Image.new("RGBA", (W, H), (6, 8, 12, 255))
d = ImageDraw.Draw(ic)


def dial(cx, cy, r, lo, hi, val, label, unit, ticks):
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(70, 80, 95, 255), width=6)
    a0, a1 = 135, 405
    for k in range(ticks + 1):
        a = math.radians(a0 + (a1 - a0) * k / ticks)
        r0 = r - (26 if k % 2 == 0 else 14)
        d.line((cx + r0 * math.cos(a), cy + r0 * math.sin(a), cx + (r - 6) * math.cos(a),
                cy + (r - 6) * math.sin(a)), fill=WHITE, width=4 if k % 2 == 0 else 2)
        if k % 2 == 0:
            v = lo + (hi - lo) * k / ticks
            draw_centered(d, (cx + (r - 56) * math.cos(a) - 30, cy + (r - 56) * math.sin(a) - 20,
                              cx + (r - 56) * math.cos(a) + 30, cy + (r - 56) * math.sin(a) + 20),
                          str(int(v)), font(BOLD, 26), GREY)
    a = math.radians(a0 + (a1 - a0) * (val - lo) / (hi - lo))
    d.line((cx, cy, cx + (r - 30) * math.cos(a), cy + (r - 30) * math.sin(a)), fill=(255, 70, 40, 255), width=8)
    d.ellipse((cx - 16, cy - 16, cx + 16, cy + 16), fill=(40, 44, 54, 255))
    draw_centered(d, (cx - 90, cy + 70, cx + 90, cy + 115), label, font(BOLD, 30), WHITE)
    draw_centered(d, (cx - 90, cy + 112, cx + 90, cy + 145), unit, font(REG, 24), GREY)


def hybrid_indicator(cx, cy, r):
    """Toyota's hybrid system indicator: CHG (regeneration), ECO and PWR zones instead of a rev
    counter; the needle rests at the CHG/ECO boundary with the car in READY."""
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(70, 80, 95, 255), width=6)
    zones = ((135, 175, (60, 140, 255, 255), "CHG"), (175, 300, (60, 200, 110, 255), "ECO"),
             (300, 405, (235, 235, 240, 255), "PWR"))
    for a0_, a1_, col, lab in zones:
        rr = r - 22
        d.arc((cx - rr, cy - rr, cx + rr, cy + rr), a0_, a1_, fill=col, width=18)
        am = math.radians((a0_ + a1_) / 2)
        draw_centered(d, (cx + (r - 72) * math.cos(am) - 40, cy + (r - 72) * math.sin(am) - 20,
                          cx + (r - 72) * math.cos(am) + 40, cy + (r - 72) * math.sin(am) + 20),
                      lab, font(BOLD, 28), col)
    a = math.radians(175)
    d.line((cx, cy, cx + (r - 30) * math.cos(a), cy + (r - 30) * math.sin(a)), fill=(255, 70, 40, 255), width=8)
    d.ellipse((cx - 16, cy - 16, cx + 16, cy + 16), fill=(40, 44, 54, 255))
    draw_centered(d, (cx - 110, cy + 70, cx + 110, cy + 110), "HYBRID SYSTEM", font(BOLD, 22), WHITE)
    # fuel gauge along the bottom of the dial
    d.text((cx - 95, cy + 128), "E", font=font(BOLD, 22), fill=GREY)
    d.text((cx + 82, cy + 128), "F", font=font(BOLD, 22), fill=GREY)
    for k in range(8):
        x = cx - 70 + k * 19
        d.rectangle((x, cy + 134, x + 13, cy + 148), fill=(230, 230, 235, 255) if k < 6 else (60, 66, 80, 255))


hybrid_indicator(215, 225, 190)
dial(W - 215, 225, 190, 0, 160, 0, "0", "MPH", 16)
d.rounded_rectangle((440, 60, 760, 390), radius=22, fill=(18, 22, 30, 255), outline=(60, 66, 80, 255), width=3)
draw_centered(d, (440, 80, 760, 150), "READY", font(BOLD, 52), (60, 220, 90, 255))
draw_centered(d, (440, 160, 760, 220), "P", font(BOLD, 60), WHITE)
draw_centered(d, (440, 235, 760, 280), "RANGE  412 mi", font(REG, 30), GREY)
draw_centered(d, (440, 285, 760, 330), "ODO  84,215 mi", font(REG, 30), GREY)
draw_centered(d, (440, 335, 760, 380), "72°F   10:42", font(REG, 30), GREY)
save(ic, "interior_gauge_cluster.png")

# 10. Centre touchscreen (8 in, 16:9-ish) on the dash
W, H = 1000, 580
it = Image.new("RGBA", (W, H), (12, 14, 20, 255))
d = ImageDraw.Draw(it)
d.rectangle((0, 0, W, 64), fill=(24, 28, 38, 255))
text_left(d, (24, 16), "10:42", font(BOLD, 32), WHITE)
text_right(d, (W - 24, 16), "72°F", font(BOLD, 32), WHITE)
# Entune-style split screen: map on the left, radio on the right, soft keys along the bottom
mp = Image.new("RGBA", (600, 436), (214, 218, 210, 255))          # map panel, drawn on its own canvas
dm_ = ImageDraw.Draw(mp)
for k in range(-4, 12):                                   # Manhattan grid, rotated like the island
    dm_.line((k * 70, 0, k * 70 + 260, 436), fill=(250, 250, 248, 255), width=10)
    dm_.line((0, k * 60, 600, k * 60 - 120), fill=(250, 250, 248, 255), width=6)
dm_.polygon(((140, 96), (260, 56), (330, 236), (210, 276)), fill=(170, 210, 160, 255))   # park
dm_.line((60, 406, 180, 266, 300, 216, 430, 86), fill=(40, 120, 230, 255), width=12)     # route
dm_.ellipse((418, 74, 442, 98), fill=(230, 60, 50, 255))
dm_.polygon(((52, 416), (68, 416), (60, 394)), fill=(20, 20, 30, 255))
it.paste(mp, (0, 64))
d.rectangle((600, 64, W, 500), fill=(20, 24, 32, 255))
text_left(d, (630, 100), "FM", font(BOLD, 34), GREY)
text_left(d, (630, 150), "101.1", font(BOLD, 96), WHITE)
text_left(d, (630, 270), "WCBS-FM", font(REG, 34), GREY)
d.rounded_rectangle((630, 350, W - 30, 362), radius=6, fill=(60, 66, 80, 255))
d.rounded_rectangle((630, 350, 800, 362), radius=6, fill=(230, 180, 60, 255))
for k, lab in enumerate(("MAP", "AUDIO", "PHONE", "APPS", "SETUP")):
    x0 = k * W // 5
    d.rectangle((x0 + 2, 504, x0 + W // 5 - 2, H), fill=(28, 32, 42, 255))
    draw_centered(d, (x0, 504, x0 + W // 5, H), lab, font(BOLD, 30), WHITE if k else (230, 180, 60, 255))
save(it, "interior_infotainment.png")

# 11. Climate control panel (under the centre vents), 4:1
W, H = 800, 200
cp = Image.new("RGBA", (W, H), (20, 21, 24, 255))
d = ImageDraw.Draw(cp)
for cx in (110, W - 110):                          # temperature knobs
    d.ellipse((cx - 70, 30, cx + 70, 170), fill=(40, 42, 46, 255), outline=(150, 152, 158, 255), width=6)
    draw_centered(d, (cx - 60, 70, cx + 60, 130), "72", font(BOLD, 44), WHITE)
labels = ["AUTO", "A/C", "FAN", "MODE", "DEF", "RECIRC"]
for k, lab in enumerate(labels):
    x0 = 210 + (k % 3) * 130
    y0 = 30 + (k // 3) * 80
    d.rounded_rectangle((x0, y0, x0 + 115, y0 + 62), radius=10, fill=(44, 46, 52, 255))
    draw_centered(d, (x0, y0, x0 + 115, y0 + 62), lab, font(BOLD, 24), WHITE)
save(cp, "interior_climate_panel.png")

# 12. Shift gate panel on the console (Camry Hybrid: P-R-N-D-B in a staggered gate), 1:2
W, H = 300, 600
sg = Image.new("RGBA", (W, H), (8, 8, 9, 255))
d = ImageDraw.Draw(sg)
d.rounded_rectangle((6, 6, W - 6, H - 6), radius=26, outline=(120, 122, 128, 255), width=6)   # satin rim
gate = [(150, 110), (150, 190), (110, 190), (110, 270), (150, 270), (150, 350), (150, 430), (190, 430),
        (190, 500)]                                         # P down to R, across to N, D, then B
d.line(gate, fill=(0, 0, 0, 255), width=26, joint="curve")
d.line(gate, fill=(30, 30, 34, 255), width=14, joint="curve")
for lab, (x, y), lit in (("P", (60, 110), True), ("R", (60, 190), False), ("N", (60, 270), False),
                         ("D", (60, 350), False), ("B", (240, 500), False)):
    draw_centered(d, (x - 30, y - 30, x + 30, y + 30), lab, font(BOLD, 44),
                  (255, 255, 255, 255) if lit else (150, 152, 158, 255))
draw_centered(d, (0, 530, W, 580), "HYBRID", font(REG, 22), (120, 122, 128, 255))
save(sg, "interior_shift_gate.png")
