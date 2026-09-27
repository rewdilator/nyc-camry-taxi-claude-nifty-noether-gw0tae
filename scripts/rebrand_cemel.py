"""Rename the car to "Cemel": object, mesh and collection names, file names and the trunk badge.

    python3 scripts/rebrand_cemel.py    # (bpy) edits NYC_Taxi_Cemel_2020.blend

Run it after build_taxi.py. It also converts an older NYC_Taxi_Camry_2020.blend (renaming its
objects and saving it under the new name), and it is safe to run again.

The trunk badge is lettering in the model's texture atlas (colour map, two alpha maps and the
normal map). The C and M are kept; A, R and Y are erased and redrawn as E, E and L in the same
thin, wide geometric style, so the badge reads CEMEL.
"""
import os

import bpy
import numpy as np
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OLD = os.path.join(ROOT, "NYC_Taxi_Camry_2020.blend")
NEW = os.path.join(ROOT, "NYC_Taxi_Cemel_2020.blend")

src = NEW if os.path.exists(NEW) else OLD
if bpy.data.filepath != src:
    bpy.ops.wm.open_mainfile(filepath=src)

# ---------------------------------------------------------------------------
# 1. Names
# ---------------------------------------------------------------------------
for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.collections):
    for idb in coll:
        if "Camry" in idb.name:
            idb.name = idb.name.replace("Camry", "Cemel")

# ---------------------------------------------------------------------------
# 2. Trunk badge in the atlas (pixel rows counted from the top of the 2048 x 2048 image)
# ---------------------------------------------------------------------------
TOP, BOTTOM = 1806, 1821                 # cap height of the badge letters
REPLACE = {                              # letter box (x0, x1) -> new letter
    (665, 702): "E",                     # A
    (829, 870): "E",                     # R
    (903, 954): "L",                     # Y
}
V_STROKE, H_STROKE = 6, 3                # vertical / horizontal stroke widths of the originals
SS = 8                                   # supersampling for anti-aliased edges


def letter_mask(shape):
    """Coverage (0..1) of the new letters, same size as the atlas."""
    h, w = shape
    big = Image.new("L", (w * SS, (BOTTOM - TOP + 1) * SS), 0)
    d = ImageDraw.Draw(big)
    ht = (BOTTOM - TOP + 1) * SS
    for (x0, x1), ch in REPLACE.items():
        x1 = x0 + 37 if ch == "L" else x1 - 2          # same advance as C and M
        X0, X1 = x0 * SS, (x1 + 1) * SS
        d.rectangle((X0, 0, X0 + V_STROKE * SS - 1, ht - 1), fill=255)       # stem
        d.rectangle((X0, ht - H_STROKE * SS, X1 - 1, ht - 1), fill=255)      # bottom bar
        if ch == "E":
            d.rectangle((X0, 0, X1 - 1, H_STROKE * SS - 1), fill=255)        # top bar
            mid = ht // 2 - H_STROKE * SS // 2
            d.rectangle((X0, mid, X1 - SS * 3, mid + H_STROKE * SS - 1), fill=255)
    small = big.resize((w, BOTTOM - TOP + 1), Image.LANCZOS)
    m = np.zeros(shape, np.float32)
    m[TOP:BOTTOM + 1] = np.asarray(small, np.float32) / 255.0
    return m


def pixels(img):
    w, h = img.size
    a = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(a)
    return a.reshape(h, w, 4)[::-1].copy()      # Blender stores rows bottom-up


def store(img, px):
    img.pixels.foreach_set(px[::-1].ravel())
    img.update()
    img.pack()


def erase_boxes(px, value):
    for (x0, x1) in REPLACE:
        px[TOP - 4:BOTTOM + 5, x0 - 3:x1 + 4] = value


colour = bpy.data.images["Index_0_2_map"]
mask = None
for name in ("Index_0_2_map", "Index_0_2_map.001", "Index_0_2_map.002"):
    img = bpy.data.images[name]
    px = pixels(img)
    if mask is None:
        mask = letter_mask(px.shape[:2])
    # sample the existing lettering (the C) for colour and opacity
    c_box = px[TOP:BOTTOM + 1, 586:623]
    ink = c_box[c_box[..., 3] > 0.5].mean(0) if (c_box[..., 3] > 0.5).any() else np.array([1, 1, 1, 1])
    bg = px[TOP - 20, 640].copy()
    erase_boxes(px, bg)
    for ch in range(4):
        px[..., ch] = px[..., ch] * (1 - mask) + ink[ch] * mask
    store(img, px)

normal = bpy.data.images["Index_0_2_normalMap"]
npx = pixels(normal)
flat = npx[TOP - 20, 640].copy()
erase_boxes(npx, flat)
# emboss: slope the normals along the edges of the letters
gy, gx = np.gradient(mask)
k = 0.8
n = np.dstack([-gx * k, gy * k, np.ones_like(mask)])
n /= np.linalg.norm(n, axis=2, keepdims=True)
edge = (np.abs(gx) + np.abs(gy)) > 1e-4
npx[..., :3][edge] = n[edge] * 0.5 + 0.5
store(normal, npx)

# ---------------------------------------------------------------------------
# 3. Save under the new name
# ---------------------------------------------------------------------------
bpy.ops.wm.save_as_mainfile(filepath=NEW, compress=True)
if os.path.exists(NEW + "1"):
    os.remove(NEW + "1")
print("Saved", NEW)
