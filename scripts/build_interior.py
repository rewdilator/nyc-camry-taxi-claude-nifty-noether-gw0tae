"""Fit out the taxi's cabin the way NYC yellow-cab Cemels are equipped.

    python3 scripts/make_interior_textures.py   # (Pillow) interior textures -> textures/
    python3 scripts/build_interior.py           # (bpy) adds the Taxi_Interior collection to
                                                #       NYC_Taxi_Cemel_2020.blend and re-exports the .glb

Run it after build_taxi.py. It is safe to re-run: the Taxi_Interior collection is rebuilt from scratch.

What it adds (the source model's cabin only has seat backs, a dash and a flat floor tub):
- Seat cushions for the front seats and the rear bench, rear seat-belt buckles, a centre console
  with armrest and shifter.
- The partition behind the front seats: an opaque lower panel and a clear polycarbonate upper panel
  in a black frame, with a sliding pass-through window and a cash tray.
- The Passenger Information Monitor ("Taxi TV") and the tap/chip card reader in the partition.
- The dash-top taximeter and the driver's T-PEP monitor.
- The TLC notices facing the rear seat: the driver's hack licence, the Taxi Rider Bill of Rights,
  a "Buckle up" sticker and a no-smoking sticker.
"""
import math
import os

import bpy  # noqa: I001  (bpy must be imported before bmesh when run as a module)
import bmesh
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLEND = os.path.join(ROOT, "NYC_Taxi_Cemel_2020.blend")
GLB = os.path.join(ROOT, "NYC_Taxi_Cemel_2020.glb")
TEX = os.path.join(ROOT, "textures")

if bpy.data.filepath != BLEND:
    bpy.ops.wm.open_mainfile(filepath=BLEND)
scene = bpy.context.scene
root = bpy.data.objects["NYC_Taxi_Cemel_2020"]
taxi_col = bpy.data.collections["NYC_Taxi_Cemel_2020"]

# Car axes: -Y is forward, +X is the driver's (left) side, z = 0 is the ground.
Z = Vector((0, 0, 1))
REAR = Vector((0, 1, 0))      # faces that the rear-seat passengers look at point this way
FWD = Vector((0, -1, 0))

# ---------------------------------------------------------------------------
# 0. Rebuild the collection from scratch
# ---------------------------------------------------------------------------
col = bpy.data.collections.get("Taxi_Interior")
if col:
    for o in list(col.objects):
        me = o.data if o.type == "MESH" else None
        bpy.data.objects.remove(o)
        if me and me.users == 0:
            bpy.data.meshes.remove(me)
else:
    col = bpy.data.collections.new("Taxi_Interior")
    taxi_col.children.link(col)


def add(ob, parent=None):
    col.objects.link(ob)
    ob.parent = parent or root
    if parent:
        ob.matrix_parent_inverse = parent.matrix_world.inverted()
    return ob


# ---------------------------------------------------------------------------
# 1. Materials
# ---------------------------------------------------------------------------
def load_image(fname):
    img = bpy.data.images.get(fname)
    if img:
        img.filepath = os.path.join(TEX, fname)
        img.reload()
    else:
        img = bpy.data.images.load(os.path.join(TEX, fname))
        img.name = fname
    img.alpha_mode = "STRAIGHT"
    img.pack()
    return img


def material(name, color=(0.8, 0.8, 0.8, 1), rough=0.5, metal=0.0, image=None, emission=0.0,
             alpha=False, transmission=0.0, ior=1.5, coat=0.0, sheen=0.0):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (400, 0)
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(b.outputs[0], out.inputs[0])
    b.inputs["Base Color"].default_value = color
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    b.inputs["Transmission Weight"].default_value = transmission
    b.inputs["IOR"].default_value = ior
    b.inputs["Coat Weight"].default_value = coat
    b.inputs["Sheen Weight"].default_value = sheen
    if image:
        t = nt.nodes.new("ShaderNodeTexImage")
        t.location = (-400, 0)
        t.image = load_image(image)
        t.extension = "CLIP"
        t.interpolation = "Cubic"
        nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
        if alpha:
            nt.links.new(t.outputs["Alpha"], b.inputs["Alpha"])
        if emission:
            nt.links.new(t.outputs["Color"], b.inputs["Emission Color"])
    b.inputs["Emission Strength"].default_value = emission
    return m


cloth = material("Interior_Black_Cloth", (0.016, 0.016, 0.018, 1), rough=0.92)
trim = material("Interior_Black_Trim", (0.02, 0.02, 0.022, 1), rough=0.6)
abs_black = material("Partition_Black_Panel", (0.012, 0.012, 0.013, 1), rough=0.5)
frame_mat = material("Partition_Frame_Black_Aluminium", (0.03, 0.03, 0.032, 1), rough=0.35, metal=1.0)
poly = material("Partition_Polycarbonate", (0.95, 0.97, 0.98, 1), rough=0.03, transmission=1.0,
                ior=1.58)
chrome = bpy.data.materials["Taxi_Aluminium"]
black_plastic = bpy.data.materials["Taxi_Black_Plastic"]
tv_mat = material("Interior_TaxiTV_Screen", rough=0.12, image="interior_taxi_tv_screen.png", emission=1.0)
reader_mat = material("Interior_Card_Reader", rough=0.3, image="interior_card_reader.png", emission=0.4)
meter_mat = material("Interior_Taximeter_Display", rough=0.15, image="interior_taximeter.png", emission=1.5)
dim_mat = material("Interior_Driver_Monitor", rough=0.12, image="interior_driver_monitor.png", emission=0.8)
hack_mat = material("Interior_Hack_License", rough=0.35, image="interior_hack_license.png")
rights_mat = material("Interior_Passenger_Rights", rough=0.35, image="interior_passenger_rights.png")
buckle_mat = material("Interior_Buckle_Up", rough=0.35, image="interior_buckle_up.png", alpha=True)
smoke_mat = material("Interior_No_Smoking", rough=0.35, image="interior_no_smoking.png", alpha=True)
for m in (buckle_mat, smoke_mat):
    if hasattr(m, "surface_render_method"):
        m.surface_render_method = "DITHERED"

# ---------------------------------------------------------------------------
# 2. Geometry helpers
# ---------------------------------------------------------------------------
FLOOR_Z = 0.33           # footwell floor (the tub is lowered to this below)
SILL_Z = 0.40            # inner edge of the floor along the door sills
SEAT_Z = 0.58            # top of the seat bases = underside of the cushions


def lower_floor():
    """The source tub is a flat sheet at seat height (z ~0.56-0.61) from the dash to the rear seat.
    Drop it to footwell height, keeping a raised strip along the sills. Absolute heights, so a
    second run changes nothing."""
    me = bpy.data.objects["Cemel_Trim_Interior"].data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    seen = set()
    for v in bm.verts:
        if v.index in seen:
            continue
        stack, comp = [v], []
        seen.add(v.index)
        while stack:
            a = stack.pop()
            comp.append(a)
            for e in a.link_edges:
                b = e.other_vert(a)
                if b.index not in seen:
                    seen.add(b.index)
                    stack.append(b)
        co = np.array([c.co[:] for c in comp])
        mn, mx = co.min(0), co.max(0)
        if mn[0] < -0.8 and mx[0] > 0.8 and mn[1] < -0.85 and mx[1] > 1.3 and 0.5 < mn[2] < 0.6 and mx[2] < 0.9:
            for c in comp:
                if c.co.y < 0.95 and (0.545 < c.co.z < 0.615 or (abs(c.co.x) > 0.74 and 0.615 <= c.co.z < 0.72)):
                    c.co.z = SILL_Z if abs(c.co.x) > 0.74 else FLOOR_Z
    bm.to_mesh(me)
    bm.free()


lower_floor()
openings = [o for o in bpy.data.collections["Doors_Trunk"].objects if o.type == "MESH"]
bm_car = bmesh.new()
for ob in [bpy.data.objects[n] for n in ("Cemel_Body_Paint", "Cemel_Trim_Interior", "Cemel_Glass_Lamps")] + openings:
    tmp = bmesh.new()
    tmp.from_mesh(ob.data)
    tmp.transform(ob.matrix_world)
    me_tmp = bpy.data.meshes.new("_tmp")
    tmp.to_mesh(me_tmp)
    tmp.free()
    bm_car.from_mesh(me_tmp)
    bpy.data.meshes.remove(me_tmp)
car_bvh = BVHTree.FromBMesh(bm_car)
bm_trim = bmesh.new()
bm_trim.from_mesh(bpy.data.objects["Cemel_Trim_Interior"].data)
trim_bvh = BVHTree.FromBMesh(bm_trim)


def cast(origin, direction, bvh=car_bvh, dist=3.0):
    return bvh.ray_cast(Vector(origin), Vector(direction).normalized(), dist)[0]


def box(name, size, loc, mat, bevel=0.0, segments=3, rot=None):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    if rot:
        ob.rotation_euler = rot
    me.materials.append(mat)
    if bevel:
        mod = ob.modifiers.new("Bevel", "BEVEL")
        mod.width = bevel
        mod.segments = segments
        mod.limit_method = "ANGLE"
        me.shade_smooth()
    return add(ob)


def frame_axes(normal):
    """Viewer's right and up for a face seen from the side `normal` points to."""
    n = Vector(normal).normalized()
    up = (Z - n * Z.dot(n)).normalized()
    return up.cross(n), up, n


def quad(name, center, w, h, normal, mat, offset=0.0):
    """Textured w x h rectangle facing `normal`, texture upright and unmirrored for the viewer."""
    right, up, n = frame_axes(normal)
    c = Vector(center) + n * offset
    corners = [c - right * w / 2 - up * h / 2, c + right * w / 2 - up * h / 2,
               c + right * w / 2 + up * h / 2, c - right * w / 2 + up * h / 2]
    me = bpy.data.meshes.new(name)
    me.from_pydata([v[:] for v in corners], [], [(0, 1, 2, 3)])
    layer = me.uv_layers.new(name="UVMap")
    for li, t in zip(me.polygons[0].loop_indices, ((0, 0), (1, 0), (1, 1), (0, 1))):
        layer.data[li].uv = t
    me.materials.append(mat)
    return add(bpy.data.objects.new(name, me))


def device(name, center, size, normal, housing_mat, face_mat, face_wh, face_shift=(0, 0), bevel=0.006):
    """A box-shaped device whose front (the face along `normal`) carries a textured screen."""
    right, up, n = frame_axes(normal)
    w, h, d = size
    rot = Matrix((right, -n, up)).transposed().to_euler()   # local x: right, -y: front, z: up
    ob = box(f"{name}_Housing", (w, d, h), Vector(center), housing_mat, bevel=bevel, rot=rot)
    fc = Vector(center) + right * face_shift[0] + up * face_shift[1] + n * (d / 2 + 0.0008)
    quad(f"{name}_Screen", fc, face_wh[0], face_wh[1], n, face_mat)
    return ob


# ---------------------------------------------------------------------------
# 3. Floor, pedals, seats, belts and console
# ---------------------------------------------------------------------------
carpet = material("Interior_Carpet_Charcoal", (0.05, 0.05, 0.053, 1), rough=1.0)
rubber = material("Interior_Rubber_Mat", (0.008, 0.008, 0.009, 1), rough=0.75)
webbing = material("Interior_Seat_Belt_Webbing", (0.014, 0.014, 0.016, 1), rough=0.7)
steel = material("Interior_Dark_Steel", (0.05, 0.05, 0.055, 1), rough=0.4, metal=1.0)


def sheet(name, pts, faces, mat, thickness=0.006, parent=None):
    """A thin panel from explicit corner points (quads), solidified towards the cabin."""
    me = bpy.data.meshes.new(name)
    me.from_pydata([Vector(p)[:] for p in pts], [], faces)
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    sol = ob.modifiers.new("Solidify", "SOLIDIFY")
    sol.thickness = thickness
    return add(ob, parent)


def strap(name, p0, p1, width, mat, thick=0.004, face=Vector((0, 1, 0))):
    """A flat strap (seat-belt webbing) from p0 to p1, its flat side facing roughly `face`."""
    p0, p1 = Vector(p0), Vector(p1)
    d = (p1 - p0).normalized()
    side = d.cross(face).normalized()
    n = side.cross(d)
    rot = Matrix((side, n, d)).transposed().to_euler()
    return box(name, (width, thick, (p1 - p0).length), (p0 + p1) / 2, mat, rot=rot)


# Toe board and kick panels close the open space under the dash down to the new floor.
TOE = [(-0.90, FLOOR_Z), (-1.10, 0.66), (-1.13, 0.95)]      # (y, z) from floor to under the dash
TW = 0.73
pts = [(x, y, z) for (y, z) in TOE for x in (-TW, TW)]
sheet("Floor_Toe_Board", pts, [(0, 1, 3, 2), (2, 3, 5, 4)], carpet, 0.01)
for s_ in (-1, 1):
    sheet(f"Floor_Kick_Panel_{'L' if s_ > 0 else 'R'}",
          [(s_ * TW, -1.13, FLOOR_Z), (s_ * TW, -0.88, FLOOR_Z), (s_ * TW, -0.88, 0.95), (s_ * TW, -1.13, 0.95)],
          [(0, 1, 2, 3)], trim, 0.01)

# Pedals on the driver's side (+X): accelerator right of the brake, footrest far left.
toe_dir = Vector((0, TOE[1][0] - TOE[0][0], TOE[1][1] - TOE[0][1])).normalized()
toe_n = Vector((0, -toe_dir.z, toe_dir.y)) * -1           # points up and back, into the cabin
if toe_n.y < 0:
    toe_n = -toe_n


def on_toe(t, x, lift):
    y = TOE[0][0] + (TOE[1][0] - TOE[0][0]) * t
    z = TOE[0][1] + (TOE[1][1] - TOE[0][1]) * t
    return Vector((x, y, z)) + toe_n * lift


toe_rot = Matrix((Vector((1, 0, 0)), toe_n, toe_dir)).transposed().to_euler()
box("Pedal_Accelerator", (0.06, 0.018, 0.21), on_toe(0.45, 0.25, 0.035), rubber, bevel=0.008, rot=toe_rot)
box("Pedal_Brake", (0.11, 0.022, 0.075), on_toe(0.40, 0.43, 0.13), rubber, bevel=0.01, rot=toe_rot)
strap("Pedal_Brake_Arm", on_toe(0.40, 0.43, 0.13), (0.43, -0.93, 0.93), 0.025, steel, thick=0.012)
box("Pedal_Footrest", (0.08, 0.015, 0.22), on_toe(0.5, 0.62, 0.02), rubber, bevel=0.006, rot=toe_rot)

# Seat bases (the source seat backs float above the new floor) and rails
for x, tag in ((0.38, "Driver"), (-0.38, "Passenger")):
    box(f"Seat_Base_{tag}", (0.44, 0.58, SEAT_Z - FLOOR_Z - 0.04), (x, -0.08, (SEAT_Z + FLOOR_Z + 0.04) / 2),
        trim, bevel=0.02)
    for dx in (-0.17, 0.17):
        box(f"Seat_Rail_{tag}_{'O' if dx * x > 0 else 'I'}", (0.035, 0.66, 0.035),
            (x + dx, -0.10, FLOOR_Z + 0.0175), steel, bevel=0.004)

# Cushions on the bases, overlapping the foot of each source seat back.
CUSH_T = 0.075
for x, tag in ((0.38, "Driver"), (-0.38, "Passenger")):
    box(f"Seat_Cushion_{tag}", (0.50, 0.52, CUSH_T), (x, -0.16, SEAT_Z + CUSH_T / 2), cloth,
        bevel=0.03, segments=4)
    for s in (-1, 1):  # side bolsters
        box(f"Seat_Bolster_{tag}_{'O' if s * x > 0 else 'I'}", (0.07, 0.46, 0.035),
            (x + s * 0.215, -0.17, SEAT_Z + CUSH_T + 0.012), cloth, bevel=0.016, segments=4)
    # front belt: stowed down the B-pillar from the D-ring; buckle stalk on the console side
    xo = math.copysign(1, x)
    box(f"Seat_Belt_DRing_{tag}", (0.012, 0.03, 0.06), (xo * 0.665, 0.235, 1.22), black_plastic, bevel=0.004)
    strap(f"Seat_Belt_{tag}", (xo * 0.66, 0.225, 1.20), (xo * 0.715, 0.225, SEAT_Z - 0.05), 0.048, webbing,
          face=Vector((-xo, 0, 0)))
    box(f"Seat_Belt_Buckle_{tag}", (0.03, 0.022, 0.075), (xo * 0.13, 0.04, SEAT_Z + 0.07), black_plastic,
        bevel=0.006, rot=(math.radians(15), 0, 0))

rear_hw = min(abs(cast((0, 0.7, SEAT_Z + 0.12), (s, 0, 0)).x) for s in (-1, 1)) - 0.02
REAR_Y0, REAR_Y1 = 0.46, 0.96
box("Seat_Base_Rear", (2 * rear_hw - 0.04, REAR_Y1 - REAR_Y0 - 0.02, SEAT_Z - FLOOR_Z),
    (0, (REAR_Y0 + REAR_Y1) / 2 + 0.01, (SEAT_Z + FLOOR_Z) / 2), cloth, bevel=0.02)
box("Seat_Cushion_Rear", (2 * rear_hw, REAR_Y1 - REAR_Y0, CUSH_T + 0.01),
    (0, (REAR_Y0 + REAR_Y1) / 2, SEAT_Z + (CUSH_T + 0.01) / 2), cloth, bevel=0.035, segments=4)
for x in (-0.43, 0.43):  # outboard seat contours
    box(f"Seat_Rear_Bolster_{'L' if x > 0 else 'R'}", (0.05, 0.40, 0.022),
        (x + math.copysign(0.2, x), 0.73, SEAT_Z + CUSH_T + 0.014), cloth, bevel=0.01)
for i, x in enumerate((-0.45, -0.28, 0.0, 0.14, 0.28, 0.45)):  # seat-belt buckles and latches
    box(f"Seat_Belt_Buckle_Rear_{i}", (0.03, 0.02, 0.07), (x, REAR_Y1 - 0.03, SEAT_Z + CUSH_T + 0.03),
        black_plastic, bevel=0.006, rot=(math.radians(-20), 0, 0))
# rear belts come out of the parcel shelf and lie down the seat back
for x, tag in ((0.47, "L"), (0.0, "C"), (-0.47, "R")):
    # anchor on the parcel shelf just behind the head restraints (cast down, below the rear glass)
    top = cast((x, 1.33, 1.27), -Z, trim_bvh, 0.4) or Vector((x, 1.33, 1.16))
    strap(f"Seat_Belt_Rear_{tag}", top + Vector((0, -0.01, 0.005)),
          (x * 1.12, REAR_Y1 - 0.04, SEAT_Z + CUSH_T + 0.02), 0.048, webbing, face=Vector((0, -1, 0.6)))
    box(f"Seat_Belt_Guide_Rear_{tag}", (0.07, 0.03, 0.015), top + Vector((0, 0, 0.004)), black_plastic,
        bevel=0.004)

# Rubber floor mats
for x0, x1, tag in ((0.12, 0.70, "Driver"), (-0.70, -0.12, "Passenger")):
    box(f"Floor_Mat_{tag}", (x1 - x0, 0.50, 0.008), ((x0 + x1) / 2, -0.64, FLOOR_Z + 0.004), rubber,
        bevel=0.004)
box("Floor_Mat_Rear", (2 * rear_hw - 0.1, 0.10, 0.008), (0, (0.36 + REAR_Y0) / 2, FLOOR_Z + 0.004), rubber,
    bevel=0.003)

box("Console_Base", (0.18, 0.86, 0.74 - FLOOR_Z), (0, -0.44, (0.74 + FLOOR_Z) / 2), trim, bevel=0.02)
box("Console_Armrest", (0.19, 0.30, 0.05), (0, -0.10, SEAT_Z + 0.185), cloth, bevel=0.018, segments=4)
box("Console_Shifter_Boot", (0.07, 0.10, 0.04), (0, -0.50, SEAT_Z + 0.18), trim, bevel=0.015)
box("Console_Shifter_Knob", (0.04, 0.05, 0.10), (0, -0.50, SEAT_Z + 0.24), trim, bevel=0.018, segments=4)

# ---------------------------------------------------------------------------
# 3a. Dash, console and roof details (the source dash is a bare black shell)
# ---------------------------------------------------------------------------
cluster_mat = material("Interior_Gauge_Cluster", rough=0.1, image="interior_gauge_cluster.png", emission=1.2)
screen_mat = material("Interior_Touchscreen", rough=0.1, image="interior_infotainment.png", emission=0.9)
climate_mat = material("Interior_Climate_Panel", rough=0.3, image="interior_climate_panel.png", emission=0.25)
lens_mat = material("Interior_Lamp_Lens", (0.85, 0.85, 0.8, 1), rough=0.35)
mirror_mat = material("Interior_Vanity_Mirror", (0.9, 0.9, 0.9, 1), rough=0.05, metal=1.0)


def cylinder(name, r, depth, loc, mat, segments=24):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segments, radius1=r, radius2=r, depth=depth)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    return add(ob)


def dash_face_y(x, z):
    h = cast((x, -0.3, z), FWD, trim_bvh, 1.0)
    return h.y if h is not None else -0.70


def vent(name, x, z, w=0.10, h=0.035, depth=0.02):
    y = dash_face_y(x, z)
    box(f"{name}_Housing", (w, depth, h), (x, y + depth / 2 - 0.004, z), black_plastic, bevel=0.006)
    for k in range(3):                     # adjustable slats
        box(f"{name}_Slat_{k}", (w - 0.012, 0.012, 0.003), (x, y + depth - 0.006, z - h / 3 + k * h / 3),
            steel, bevel=0.001)


# instrument cluster in the recess under the cluster hood, facing the driver through the wheel
quad("Dash_Gauge_Cluster", (0.38, -0.765, 0.985), 0.30, 0.1125, Vector((0, 1, 0.28)), cluster_mat)
box("Dash_Gauge_Cluster_Backing", (0.32, 0.02, 0.13), (0.38, -0.78, 0.985), black_plastic,
    rot=(math.radians(-15.6), 0, 0))
# 8 in touchscreen on the centre of the dash, vents below it and at both ends, climate controls
scr_x, scr_z = -0.06, 0.955
device("Dash_Touchscreen", (scr_x, dash_face_y(scr_x, scr_z) + 0.012, scr_z), (0.215, 0.13, 0.02),
       Vector((0, 1, 0.12)), black_plastic, screen_mat, (0.195, 0.113))
vent("Dash_Vent_Centre_L", -0.12, 0.83)
vent("Dash_Vent_Centre_R", 0.00, 0.83)
vent("Dash_Vent_Outer_L", 0.62, 0.95, w=0.09, h=0.055)
vent("Dash_Vent_Outer_R", -0.62, 0.95, w=0.09, h=0.055)
cz = 0.775
quad("Dash_Climate_Panel", (-0.06, dash_face_y(-0.06, cz) + 0.004, cz), 0.20, 0.05, Vector((0, 1, 0.35)),
     climate_mat)
box("Dash_Start_Button", (0.03, 0.012, 0.03), (0.16, dash_face_y(0.16, 0.80) + 0.004, 0.80), chrome, bevel=0.008)
# cup holders between the shifter and the armrest
for x in (-0.045, 0.045):
    cylinder(f"Console_Cup_Holder_{'L' if x > 0 else 'R'}", 0.038, 0.004, (x, -0.33, 0.742), black_plastic)
    cylinder(f"Console_Cup_Ring_{'L' if x > 0 else 'R'}", 0.042, 0.002, (x, -0.33, 0.741), steel)


def roof_z(x, y):
    h = cast((x, y, 1.1), Z, car_bvh, 0.6)
    return h.z if h is not None else 1.40


# fabric headliner over the source roof lining (a near-white atlas swatch that blows out in renders)
headliner = material("Interior_Headliner_Fabric", (0.30, 0.30, 0.29, 1), rough=0.95)
xs = np.linspace(-0.66, 0.66, 27)
ys = np.linspace(-0.40, 1.30, 35)
hl = {}
for i, x in enumerate(xs):
    for j, y in enumerate(ys):
        # from above, onto the source lining itself (casting up would catch the head restraints)
        h = cast((x, y, 1.60), -Z, trim_bvh, 0.35)
        hl[i, j] = h - Z * 0.006 if h is not None and h.z > 1.28 else None
vi, verts, faces = {}, [], []
for k, p_ in hl.items():
    if p_ is not None:
        vi[k] = len(verts)
        verts.append(p_)
for i in range(len(xs) - 1):
    for j in range(len(ys) - 1):
        q = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
        if all(k in vi for k in q):
            faces.append(tuple(vi[k] for k in q[::-1]))
sheet("Roof_Headliner", verts, faces, headliner, 0.004).data.shade_smooth()

# sun visors stowed against the headliner (vanity mirror on the passenger's)
for x, tag in ((0.34, "Driver"), (-0.34, "Passenger")):
    z0, z1 = roof_z(x, -0.37), roof_z(x, -0.21)
    tilt = math.atan2(z1 - z0, 0.16)
    zc = (z0 + z1) / 2 - 0.016
    box(f"Roof_Sun_Visor_{tag}", (0.36, 0.165, 0.022), (x, -0.29, zc), cloth, bevel=0.008,
        rot=(tilt, 0, 0))
    box(f"Roof_Visor_Clip_{tag}", (0.02, 0.02, 0.02), (x * 0.18, -0.36, roof_z(x * 0.18, -0.36) - 0.01),
        black_plastic, bevel=0.004)
    if x < 0:
        box("Roof_Vanity_Mirror", (0.13, 0.07, 0.002), (x, -0.29, zc - 0.0115), mirror_mat, rot=(tilt, 0, 0))
# overhead console with map lamps, dome lamp over the rear seat
zc = roof_z(0, -0.27)
box("Roof_Overhead_Console", (0.20, 0.12, 0.03), (0, -0.27, zc - 0.012), black_plastic, bevel=0.008)
for x in (-0.05, 0.05):
    box(f"Roof_Map_Lamp_{'L' if x > 0 else 'R'}", (0.06, 0.045, 0.004), (x, -0.26, zc - 0.028), lens_mat,
        bevel=0.001)
zc = roof_z(0, 0.60)
box("Roof_Dome_Lamp", (0.16, 0.09, 0.016), (0, 0.60, zc - 0.006), black_plastic, bevel=0.005)
box("Roof_Dome_Lamp_Lens", (0.13, 0.065, 0.004), (0, 0.60, zc - 0.015), lens_mat, bevel=0.001)
# grab handles on the roof rails above the passenger doors
for sgn_, y in ((-1, -0.05), (1, 0.70), (-1, 0.70)):
    h = cast((0, y, 1.37), Vector((sgn_, 0, 0)), car_bvh, 1.0)
    xr = abs(h.x) if h is not None else 0.55
    tag = f"{'L' if sgn_ > 0 else 'R'}{'F' if y < 0.3 else 'R'}"
    box(f"Roof_Grab_Handle_{tag}", (0.022, 0.20, 0.02), (sgn_ * (xr - 0.05), y, 1.315), black_plastic,
        bevel=0.007, rot=(0, math.radians(-30 * sgn_), 0))
    for dy_ in (-0.085, 0.085):
        box(f"Roof_Grab_Handle_{tag}_Mount_{'F' if dy_ < 0 else 'R'}", (0.035, 0.025, 0.045),
            (sgn_ * (xr - 0.03), y + dy_, 1.34), black_plastic, bevel=0.006, rot=(0, math.radians(-30 * sgn_), 0))

# Door cards. build_doors.py deletes the source's low-poly side wall inside each door, so every door
# gets a real card: a moulded panel following the door's inner skin, a window-sill ledge up to the
# glass, a cloth insert, armrest with pull cup, chrome interior handle, window switches, speaker grille,
# map pocket and a courtesy reflector. All of it is parented to the door and swings with it.
card_mat = material("Interior_Door_Card", (0.028, 0.028, 0.03, 1), rough=0.55)
reflector = material("Interior_Door_Reflector", (0.35, 0.01, 0.01, 1), rough=0.3)
CARD_OFF = 0.065          # card surface this far inside the outer skin
cards = []


def door_child(ob, door):
    ob.parent = door
    ob.matrix_parent_inverse = door.matrix_world.inverted()
    return ob


def grid_sheet(name, grid, nu, nv, mat, sgn, thickness, parent):
    vi, verts, faces = {}, [], []
    for k, p_ in grid.items():
        if p_ is not None:
            vi[k] = len(verts)
            verts.append(p_)
    for i in range(nu - 1):
        for j in range(nv - 1):
            q = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
            if all(k in vi for k in q):
                faces.append(tuple(vi[k] for k in (q if sgn < 0 else q[::-1])))
    ob = sheet(name, verts, faces, mat, thickness, parent=parent)
    ob.data.shade_smooth()
    return ob


for door in [bpy.data.objects[n] for n in ("Door_FL", "Door_FR", "Door_RL", "Door_RR")]:
    sgn = 1 if door.name.endswith("L") else -1
    front = door.name.startswith("Door_F")
    bm_d = bmesh.new()
    bm_d.from_mesh(door.data)
    bm_d.transform(door.matrix_world)
    d_bvh = BVHTree.FromBMesh(bm_d)
    dy = np.array([v.co.y for v in bm_d.verts if 0.40 < v.co.z < 0.90 and abs(v.co.x) > 0.78])
    bm_d.free()
    y_a, y_b = dy.min() + 0.05, dy.max() - 0.05

    def skin_x(y, z):
        h = d_bvh.ray_cast(Vector((sgn * 0.3, y, z)), Vector((sgn, 0, 0)), 1.0)[0]
        return abs(h.x) if h is not None and abs(h.x) > 0.76 else None

    def card_x(y, z, extra=0.0):
        sx = skin_x(y, z)
        return None if sx is None else max(sx - CARD_OFF - extra, 0.72)

    zs = list(np.linspace(FLOOR_Z + 0.03, 0.93, 16))
    fine = np.linspace(y_a - 0.04, y_b + 0.04, 120)

    def row_span(z):
        """Where the skin exists at height z (the rear door's lower edge curves round the wheel arch),
        so each row's points spread over its own span and the card edge follows the door's shape."""
        ok = [y for y in fine if skin_x(y, z) is not None]
        return (max(min(ok), y_a), min(max(ok), y_b)) if ok else None

    NU = 30
    grid = {}
    for j, z in enumerate(zs):
        sp = row_span(z)
        for i in range(NU):
            if sp is None:
                grid[i, j] = None
                continue
            y = sp[0] + (sp[1] - sp[0]) * i / (NU - 1)
            cx = card_x(y, z)
            grid[i, j] = Vector((sgn * cx, y, z)) if cx is not None else None
    # window-sill ledge from the top of the card out to the glass
    for i in range(NU):
        top = grid[i, len(zs) - 1]
        g = d_bvh.ray_cast(Vector((sgn * 0.3, top.y, 0.99)), Vector((sgn, 0, 0)), 1.0)[0] if top else None
        grid[i, len(zs)] = (Vector((sgn * (abs(g.x) - 0.012), top.y, 0.965))
                            if g is not None and abs(g.x) - 0.012 > abs(top.x) else None)
    ys = np.linspace(y_a, y_b, NU)
    cards.append(grid_sheet(f"{door.name}_Door_Card", grid, NU, len(zs) + 1, card_mat, sgn, 0.01, door))

    # cloth insert across the middle of the card
    zi = np.linspace(0.71, 0.86, 5)
    ins = {}
    for i, y in enumerate(ys[3:-3]):
        for j, z in enumerate(zi):
            cx = card_x(y, z, 0.004)
            ins[i, j] = Vector((sgn * cx, y, z)) if cx is not None else None
    grid_sheet(f"{door.name}_Card_Insert", ins, len(ys) - 6, len(zi), cloth, sgn, 0.004, door)

    def at(y, z, out):
        cx = card_x(y, z) or 0.78
        return Vector((sgn * (cx - out), y, z))

    span = y_b - y_a
    if front:
        ar0, ar1 = y_a + 0.38 * span, y_b - 0.06
    else:
        ar0, ar1 = y_a + 0.06, y_a + 0.06 + min(0.42, 0.6 * span)
    arm_x = min((card_x(y, 0.665) or 0.78) for y in np.linspace(ar0, ar1, 6))
    arm_c = Vector((sgn * (arm_x - 0.036), (ar0 + ar1) / 2, 0.665))
    door_child(box(f"{door.name}_Armrest", (0.075, ar1 - ar0, 0.045), arm_c, cloth, bevel=0.012, segments=3), door)
    door_child(box(f"{door.name}_Pull_Cup", (0.045, 0.11, 0.012), arm_c + Vector((0, (ar1 - ar0) / 2 - 0.10, 0.02)),
                   black_plastic, bevel=0.004), door)
    # window switches on the armrest front: the driver's door has the four-window pack
    n_sw = 4 if door.name == "Door_FL" else 1
    sw_y = ar0 + 0.05 if not front else ar0 + 0.06
    door_child(box(f"{door.name}_Switch_Panel", (0.05, 0.045 * n_sw + 0.02, 0.01),
                   Vector((arm_c.x, sw_y + 0.0225 * n_sw, 0.692)), trim, bevel=0.003), door)
    for k in range(n_sw):
        door_child(box(f"{door.name}_Window_Switch_{k}", (0.018, 0.03, 0.012),
                       Vector((arm_c.x, sw_y + 0.02 + 0.045 * k, 0.699)), black_plastic, bevel=0.003), door)
    # chrome interior handle in its recess, near the front of the door
    hy = y_a + 0.11
    door_child(box(f"{door.name}_Handle_Recess", (0.02, 0.13, 0.05), at(hy, 0.84, 0.008), black_plastic,
                   bevel=0.006), door)
    door_child(box(f"{door.name}_Interior_Handle", (0.016, 0.085, 0.02), at(hy, 0.84, 0.02), chrome,
                   bevel=0.005), door)
    # speaker grille and map pocket low on the card, reflector at the bottom rear corner
    sp_y, sp_s = (y_a + 0.17, 0.17) if front else (y_a + 0.20, 0.14)
    door_child(box(f"{door.name}_Speaker_Grille", (0.01, sp_s, sp_s), at(sp_y, 0.47, 0.006), black_plastic,
                   bevel=0.004), door)
    if front:
        mp0, mp1 = y_a + 0.30, y_b - 0.08
        door_child(box(f"{door.name}_Map_Pocket", (0.045, mp1 - mp0, 0.07), at((mp0 + mp1) / 2, 0.40, 0.025),
                       card_mat, bevel=0.008), door)
    door_child(box(f"{door.name}_Reflector", (0.006, 0.07, 0.02), at(y_b - 0.03, FLOOR_Z + 0.05, 0.004),
                   reflector, bevel=0.002), door)

# ---------------------------------------------------------------------------
# 3b. Trunk: carpeted liner, wheel-arch humps, load floor; lid liner rides with the lid
# ---------------------------------------------------------------------------
TY0, TY1, TX, TZ = 1.47, 2.25, 0.57, 0.48
tp = [(-TX, TY0, TZ), (TX, TY0, TZ), (TX, TY1, TZ), (-TX, TY1, TZ),          # floor 0-3
      (-TX, TY0, 1.02), (TX, TY0, 1.02), (TX, TY1, 0.70), (-TX, TY1, 0.70),  # tops 4-7
      (-TX, TY1, 0.98), (TX, TY1, 0.98)]                                     # side-wall rear tops
sheet("Trunk_Liner", tp, [(0, 1, 2, 3), (1, 0, 4, 5), (3, 2, 6, 7), (0, 3, 8, 4), (2, 1, 5, 9)], carpet, 0.008)
for s_ in (-1, 1):
    box(f"Trunk_Wheel_Arch_{'L' if s_ > 0 else 'R'}", (0.12, 0.30, 0.24),
        (s_ * (TX - 0.06), TY0 + 0.15, TZ + 0.12), carpet, bevel=0.04, segments=4)
box("Trunk_Load_Floor", (2 * TX - 0.26, TY1 - TY0 - 0.04, 0.012), (0, (TY0 + TY1) / 2, TZ + 0.02), carpet,
    bevel=0.004)
box("Trunk_Load_Floor_Handle", (0.14, 0.03, 0.006), (0, TY1 - 0.06, TZ + 0.029), black_plastic, bevel=0.002)
box("Trunk_Striker", (0.05, 0.02, 0.03), (0, TY1 + 0.02, 0.72), steel, bevel=0.004)

lid = bpy.data.objects["Trunk_Lid"]
bm_lid = bmesh.new()
bm_lid.from_mesh(lid.data)
bm_lid.transform(lid.matrix_world)
lid_bvh = BVHTree.FromBMesh(bm_lid)
xs = np.linspace(-0.56, 0.56, 23)
ys = np.linspace(1.97, 2.27, 11)
grid = {}
for j, y in enumerate(ys):
    for i, x in enumerate(xs):
        h = lid_bvh.ray_cast(Vector((x, y, 0.85)), Z, 0.5)[0]
        grid[i, j] = h - Z * 0.018 if h is not None else None
vi, verts, faces = {}, [], []
for (i, j), p in grid.items():
    if p is not None:
        vi[i, j] = len(verts)
        verts.append(p)
for (i, j) in grid:
    q = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
    if all(k in vi for k in q):
        faces.append(tuple(vi[k] for k in q))
bm_lid.free()
sheet("Trunk_Lid_Liner", verts, faces, carpet, 0.006, parent=lid).data.shade_smooth()

# Inner panel behind the lid's rear face (a real lid is a closed shell), ray-cast from inside.
xs = np.linspace(-0.52, 0.52, 21)
zs = np.linspace(0.72, 1.02, 9)
grid = {}
for j, z in enumerate(zs):
    for i, x in enumerate(xs):
        h = lid_bvh.ray_cast(Vector((x, 2.0, z)), Vector((0, 1, 0)), 0.6)[0]
        grid[i, j] = h - Vector((0, 0.022, 0)) if h is not None and h.y > 2.2 else None
vi, verts, faces = {}, [], []
for k, p_ in grid.items():
    if p_ is not None:
        vi[k] = len(verts)
        verts.append(p_)
for (i, j) in grid:
    q = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
    if all(k in vi for k in q):
        faces.append(tuple(vi[k] for k in q))
sheet("Trunk_Lid_Inner_Panel", verts, faces, trim, 0.006, parent=lid).data.shade_smooth()

# Trunk opening surround. With the lid up, the source body is open to the lamp cavities: a painted
# gutter runs along each side of the opening under the lid edge, and dark lamp-housing backs close
# the lower corners behind the lid.
paint = bpy.data.materials["NYC_Taxi_Yellow_Paint"]
bm_body = bmesh.new()
for n in ("Cemel_Body_Paint", "Cemel_Trim_Interior", "Cemel_Glass_Lamps", "Cemel_Lamp_Lenses"):
    bm_body.from_mesh(bpy.data.objects[n].data)
body_bvh = BVHTree.FromBMesh(bm_body)
bm_lid = bmesh.new()
bm_lid.from_mesh(lid.data)
bm_lid.transform(lid.matrix_world)
lid_bvh = BVHTree.FromBMesh(bm_lid)
for s_, tag in ((1, "L"), (-1, "R")):
    inner, outer = [], []
    for y in np.linspace(1.95, 2.28, 12):
        top = lid_bvh.ray_cast(Vector((s_ * 0.60, y, 0.80)), Z, 0.6)[0]
        zg = (top.z if top is not None else 1.0) - 0.035
        hit = body_bvh.ray_cast(Vector((s_ * 0.45, y, zg)), Vector((s_, 0, 0)), 0.35)[0]
        xo = min(abs(hit.x) - 0.004, 0.76) if hit is not None else 0.70
        inner.append((s_ * (TX - 0.005), y, zg))
        outer.append((s_ * xo, y, zg))
    pts = inner + outer
    n_ = len(inner)
    faces = [(i, i + 1, n_ + i + 1, n_ + i) if s_ > 0 else (i, n_ + i, n_ + i + 1, i + 1) for i in range(n_ - 1)]
    sheet(f"Trunk_Gutter_{tag}", pts, faces, paint, 0.004).data.shade_smooth()
    # lamp-housing back behind the lid's lower corner
    yb = 2.27
    zs_ = np.linspace(0.60, 0.90, 7)
    left, right = [], []
    for z in zs_:
        hit = body_bvh.ray_cast(Vector((s_ * 0.40, yb, z)), Vector((s_, 0, 0)), 0.40)[0]
        xo = min(abs(hit.x) - 0.004, 0.76) if hit is not None else 0.72
        left.append((s_ * (TX - 0.005), yb, z))
        right.append((s_ * xo, yb, z))
    pts = left + right
    n_ = len(left)
    faces = [(i, n_ + i, n_ + i + 1, i + 1) if s_ > 0 else (i, i + 1, n_ + i + 1, n_ + i) for i in range(n_ - 1)]
    sheet(f"Trunk_Lamp_Housing_Back_{tag}", pts, faces, black_plastic, 0.006)
bm_body.free()
bm_lid.free()

# ---------------------------------------------------------------------------
# 4. Partition: traced from the cabin cross-section just behind the front head restraints
# ---------------------------------------------------------------------------
PY = 0.32                  # front face of the partition
SPLIT_Z = 0.98             # opaque lower panel below, polycarbonate above
centre = Vector((0, PY, 1.0))
bm_cards = bmesh.new()
for c_ in cards:
    tmp = bmesh.new()
    tmp.from_mesh(c_.data)
    tmp.transform(c_.matrix_world)
    me_tmp = bpy.data.meshes.new("_tmp")
    tmp.to_mesh(me_tmp)
    tmp.free()
    bm_cards.from_mesh(me_tmp)
    bpy.data.meshes.remove(me_tmp)
card_bvh = BVHTree.FromBMesh(bm_cards)
bm_cards.free()
contour = []
for a in np.linspace(0, 2 * math.pi, 96, endpoint=False):
    d = Vector((math.cos(a), 0, math.sin(a)))
    hits = [h for h in (cast(centre, d), card_bvh.ray_cast(centre, d, 3.0)[0]) if h is not None]
    if not hits:
        continue
    hit = min(hits, key=lambda h: (h - centre).length)
    p = centre + d * ((hit - centre).length - 0.012)
    p.z = max(p.z, FLOOR_Z + 0.002)
    p.y = PY
    contour.append(p)


def clip(poly_pts, z, keep_above):
    """Sutherland-Hodgman clip of a closed loop against the plane z = const."""
    out = []
    inside = (lambda p: p.z >= z) if keep_above else (lambda p: p.z <= z)
    for i, cur in enumerate(poly_pts):
        prev = poly_pts[i - 1]
        if inside(cur) != inside(prev):
            t = (z - prev.z) / (cur.z - prev.z)
            out.append(prev.lerp(cur, t))
        if inside(cur):
            out.append(cur)
    return out


def half_width(z):
    xs = [p.x for p in clip(clip(contour, z - 0.005, True), z + 0.005, False)]
    return (max(xs) - min(xs)) / 2 if xs else 0.0


def slab(name, pts, thickness, mat, inset=None, inset_mat=None):
    bm = bmesh.new()
    face = bm.faces.new([bm.verts.new(p[:]) for p in pts])
    bmesh.ops.recalc_face_normals(bm, faces=[face])
    if face.normal.y < 0:
        face.normal_flip()
    if inset:
        res = bmesh.ops.inset_region(bm, faces=[face], thickness=inset, depth=0.0)
        for f in res["faces"]:
            f.material_index = 1          # the ring around the pane is the frame
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    if inset_mat:
        me.materials.append(inset_mat)
    ob = bpy.data.objects.new(name, me)
    sol = ob.modifiers.new("Solidify", "SOLIDIFY")
    sol.thickness = thickness
    sol.offset = 1.0                      # grow towards the rear seat (+Y)
    sol.use_even_offset = True
    return add(ob)


lower_pts = clip(contour, SPLIT_Z, keep_above=False)
upper_pts = clip(contour, SPLIT_Z, keep_above=True)
LOWER_T = 0.028
slab("Partition_Lower_Panel", lower_pts, LOWER_T, abs_black)
slab("Partition_Upper_Polycarbonate", [p + Vector((0, 0.006, 0)) for p in upper_pts], 0.010, poly,
     inset=0.03, inset_mat=frame_mat)
REAR_FACE = PY + LOWER_T
hw_split = half_width(SPLIT_Z)
box("Partition_Top_Rail", (2 * hw_split, 0.05, 0.022), (0, PY + 0.014, SPLIT_Z + 0.004), frame_mat,
    bevel=0.006)

# Sliding pass-through window in the pane on the passenger side (x < 0) + its track
SW_X, SW_Z, SW_W, SW_H = -0.24, 1.10, 0.26, 0.16
rails = [((SW_W + 0.03, 0.022, 0.014), (SW_X, 0, SW_Z - SW_H / 2)),
         ((SW_W + 0.03, 0.022, 0.014), (SW_X, 0, SW_Z + SW_H / 2)),
         ((0.014, 0.022, SW_H), (SW_X - SW_W / 2, 0, SW_Z)),
         ((0.014, 0.022, SW_H), (SW_X + SW_W / 2, 0, SW_Z))]
for i, (s, (x, _, z)) in enumerate(rails):
    box(f"Partition_Window_Frame_{i}", s, (x, PY + 0.011, z), frame_mat, bevel=0.003)
box("Partition_Window_Handle", (0.012, 0.02, 0.06), (SW_X + SW_W / 2 - 0.03, PY + 0.03, SW_Z), chrome,
    bevel=0.004)

# Cash tray: a drawer through the lower panel on the driver's side
box("Partition_Cash_Tray", (0.20, 0.10, 0.05), (0.30, REAR_FACE + 0.02, SPLIT_Z - 0.06), frame_mat,
    bevel=0.006)
box("Partition_Cash_Tray_Slot", (0.16, 0.004, 0.012), (0.30, REAR_FACE + 0.071, SPLIT_Z - 0.052),
    black_plastic)

# ---------------------------------------------------------------------------
# 5. Passenger Information Monitor (Taxi TV) and card reader, facing the rear seat
# ---------------------------------------------------------------------------
tilt = math.radians(12)                       # angled up towards seated passengers
tv_n = Vector((0, math.cos(tilt), math.sin(tilt)))
device("Partition_TaxiTV", (0, REAR_FACE + 0.022, 0.845), (0.262, 0.175, 0.035), tv_n,
       black_plastic, tv_mat, (0.230, 0.144))
device("Partition_Card_Reader", (-0.215, REAR_FACE + 0.024, 0.83), (0.09, 0.15, 0.04), tv_n,
       black_plastic, reader_mat, (0.078, 0.117))

# ---------------------------------------------------------------------------
# 6. TLC notices on the partition
# ---------------------------------------------------------------------------
# Hack licence in a frame on the pane (behind the driver), stickers on the panel and pane.
hack_c = Vector((0.26, PY + 0.017, 1.11))
box("Partition_Hack_License_Frame", (0.175, 0.006, 0.12), hack_c, frame_mat, bevel=0.003)
quad("Partition_Hack_License", hack_c, 0.156, 0.104, REAR, hack_mat, offset=0.0035)
rw = 0.15
rights_x = -(half_width(0.83) - rw / 2 - 0.05)
quad("Partition_Passenger_Rights", (rights_x, REAR_FACE, 0.83), rw, rw * 1.4, REAR, rights_mat, offset=0.0015)
buckle_x = half_width(0.85) - 0.13
quad("Partition_Buckle_Up", (buckle_x, REAR_FACE, 0.85), 0.11, 0.11, REAR, buckle_mat, offset=0.0015)
quad("Partition_No_Smoking", (-0.24, PY + 0.017, 1.24), 0.08, 0.08, REAR, smoke_mat)

# ---------------------------------------------------------------------------
# 7. Driver's side: dash-top taximeter and the T-PEP driver monitor
# ---------------------------------------------------------------------------
MX, MY = -0.10, -0.80
dash = cast((MX, MY, 1.3), -Z, trim_bvh)
meter_n = Vector((0.35, 1, 0.25)).normalized()      # turned towards the driver
meter_c = Vector((MX, MY, dash.z + 0.045))
box("Taximeter_Bracket", (0.12, 0.08, 0.012), (MX, MY, dash.z + 0.006), black_plastic, bevel=0.003)
device("Taximeter", meter_c, (0.19, 0.075, 0.07), meter_n, black_plastic, meter_mat, (0.175, 0.07),
           bevel=0.008)

DX = 0.15
dash_face = cast((DX, 0.0, 0.93), FWD, trim_bvh)
dim_n = Vector((0.25, 1, 0.35)).normalized()
dim_c = Vector((DX, dash_face.y + 0.06, 0.93))
box("Driver_Monitor_Arm", (0.02, 0.06, 0.02), (DX, dash_face.y + 0.02, 0.93), black_plastic)
device("Driver_Monitor", dim_c, (0.20, 0.13, 0.025), dim_n, black_plastic, dim_mat, (0.184, 0.115))

bm_car.free()
bm_trim.free()

# ---------------------------------------------------------------------------
# 8. Save + re-export the glTF
# ---------------------------------------------------------------------------
for img in list(bpy.data.images):
    if img.users == 0 and img.name not in ("Render Result", "Viewer Node"):
        bpy.data.images.remove(img)
bpy.ops.file.pack_all()
bpy.ops.object.select_all(action="DESELECT")
for o in taxi_col.all_objects:
    o.select_set(True)
bpy.ops.export_scene.gltf(filepath=GLB, export_format="GLB", use_selection=True,
                          export_apply=True, export_cameras=False, export_lights=False)
bpy.ops.wm.save_as_mainfile(filepath=BLEND, compress=True, copy=False)
if os.path.exists(BLEND + "1"):
    os.remove(BLEND + "1")  # Blender's backup of the previous save
print("Taxi_Interior: %d objects; partition at y=%.2f, lower panel half-width at split %.3f m"
      % (len(col.objects), PY, hw_split))
print("Saved", BLEND, "and", GLB)
