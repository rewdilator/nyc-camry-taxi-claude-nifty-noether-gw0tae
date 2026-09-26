"""Render Cycles (CPU) preview images of NYC_Taxi_Cemel_2020.blend into ./renders/.

    python3 scripts/render_previews.py [samples] [view,view,...]
Views: fl side rr rside door rdoor rear front top
Interior views (lit by a temporary cabin light): cabin tv dash pdash wheel seats shifter fseat
Add "_open" to any view to render it with all four doors and the trunk open (e.g. fl_open).
Output: renders/preview_<view>.png
"""
import math
import os
import sys

import bpy
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bpy.ops.wm.open_mainfile(filepath=os.path.join(ROOT, "NYC_Taxi_Cemel_2020.blend"))

samples = int(sys.argv[1]) if len(sys.argv) > 1 else 48
views = sys.argv[2].split(",") if len(sys.argv) > 2 else ["fl", "side", "rr", "rear"]

sc = bpy.context.scene
sc.cycles.device = "CPU"
sc.cycles.samples = samples
sc.cycles.use_denoising = True
sc.render.resolution_x, sc.render.resolution_y = 1100, 650
cam = sc.camera

# azimuth, elevation (deg), distance (m), target
VIEWS = {
    "fl": (-55, 12, 9.5, (0, 0, 0.75)),
    "side": (0, 4, 9.0, (0, 0, 0.75)),
    "rr": (125, 18, 9.5, (0, 0, 0.75)),
    "rside": (180, 4, 9.0, (0, 0, 0.75)),
    "door": (10, 5, 3.6, (0, -0.1, 0.7)),
    "rdoor": (170, 5, 3.6, (0, 0.8, 0.7)),
    "rear": (90, 4, 4.2, (0, 0, 0.85)),
    "front": (-90, 8, 6.5, (0, 0, 0.6)),
    "top": (-60, 35, 4.0, (0, 0.4, 1.6)),
    "trunk": (75, 30, 4.5, (0, 1.9, 0.9)),
}
# camera position, target, lens (mm)
INTERIOR = {
    "cabin": ((0.30, 1.05, 1.12), (0.0, 0.0, 0.92), 22),    # from the rear seat
    "tv": ((-0.05, 0.85, 1.0), (-0.05, 0.3, 0.86), 30),     # Taxi TV and card reader
    "dash": ((0.36, -0.1, 1.18), (0.0, -0.8, 0.95), 22),    # driver's seat: taximeter, monitor
    "pdash": ((0.20, -0.18, 1.12), (-0.40, -0.85, 0.90), 26),  # centre stack and passenger dash
    "wheel": ((0.38, -0.12, 1.02), (0.375, -0.485, 0.90), 40),  # steering wheel close-up
    "seats": ((0.0, 0.28, 1.25), (0.0, -0.35, 0.75), 24),      # front seats from behind (partition hidden)
    "shifter": ((0.12, -0.25, 1.00), (0.0, -0.49, 0.80), 35),  # console and shift lever
    "fseat": ((0.42, -0.62, 1.02), (-0.38, -0.02, 0.78), 24),   # passenger seat seen from the driver's side
}
light = bpy.data.objects.new("CabinLight", bpy.data.lights.new("CabinLight", "AREA"))
light.data.energy, light.data.size = 10, 0.5
light.location = (0, 0.75, 1.24)
light.visible_camera = False
light.visible_glossy = False          # a preview fill light, not something to see in the glass
light.visible_transmission = False
light.hide_render = True
sc.collection.objects.link(light)
# a second soft fill over the front seats, standing in for daylight through the windscreen
front_fill = light.copy()
front_fill.data = light.data.copy()
front_fill.name = front_fill.data.name = "CabinLightFront"
front_fill.location = (0, -0.45, 1.26)
front_fill.data.energy, front_fill.data.size = 10, 0.6
sc.collection.objects.link(front_fill)
bg = sc.world.node_tree.nodes["Background"].inputs["Strength"]
bg_day = bg.default_value
OPENINGS = [o for o in bpy.data.objects if "open" in o.keys()]
lens, clip = cam.data.lens, cam.data.clip_start
for name in views:
    v = name[:-5] if name.endswith("_open") else name
    for o in OPENINGS:
        o["open"] = 1.0 if name.endswith("_open") else 0.0
    light.hide_render = v not in INTERIOR and v != "trunk"
    light.location = (0, 1.85, 1.25) if v == "trunk" else (0, 0.75, 1.24)
    light.data.energy = 40 if v == "trunk" else 13
    front_fill.hide_render = v not in INTERIOR
    # inside the car, the sky only reaches the cabin through tinted glass: brighten it for the shot
    bg.default_value = bg_day * (1.8 if v in INTERIOR else 1.0)
    if v in INTERIOR:
        loc, t, cam.data.lens = INTERIOR[v]
        cam.data.clip_start = 0.03
        t = Vector(t)
        cam.location = loc
    else:
        az, el, dist, target = VIEWS[v]
        cam.data.lens, cam.data.clip_start = lens, clip
        t = Vector(target)
        a, e = math.radians(az), math.radians(el)
        cam.location = t + Vector((math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e))) * dist
    cam.rotation_euler = (t - cam.location).to_track_quat("-Z", "Y").to_euler()
    sc.render.filepath = os.path.join(ROOT, "renders", f"preview_{name}.png")
    bpy.ops.render.render(write_still=True)
