"""Render Cycles (CPU) preview images of NYC_Taxi_Camry_2020.blend into ./renders/.

    python3 scripts/render_previews.py [samples] [view,view,...]
Views: fl side rr rside door rdoor rear front top
Interior views (lit by a temporary cabin light): cabin tv dash
"""
import math
import os
import sys

import bpy
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bpy.ops.wm.open_mainfile(filepath=os.path.join(ROOT, "NYC_Taxi_Camry_2020.blend"))

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
}
# camera position, target, lens (mm)
INTERIOR = {
    "cabin": ((0.30, 1.05, 1.12), (0.0, 0.0, 0.92), 22),    # from the rear seat
    "tv": ((-0.05, 0.85, 1.0), (-0.05, 0.3, 0.86), 30),     # Taxi TV and card reader
    "dash": ((0.36, -0.1, 1.18), (0.0, -0.8, 0.95), 22),    # driver's seat: taximeter, monitor
}
light = bpy.data.objects.new("CabinLight", bpy.data.lights.new("CabinLight", "AREA"))
light.data.energy, light.data.size = 12, 0.6
light.location = (0, 0.75, 1.38)
light.visible_camera = False
light.hide_render = True
sc.collection.objects.link(light)
lens, clip = cam.data.lens, cam.data.clip_start
for v in views:
    light.hide_render = v not in INTERIOR
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
    sc.render.filepath = os.path.join(ROOT, "renders", f"preview_{v}.png")
    bpy.ops.render.render(write_still=True)
