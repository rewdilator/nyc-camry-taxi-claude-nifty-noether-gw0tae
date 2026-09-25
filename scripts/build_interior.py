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
carpet = material("Interior_Carpet_Charcoal", (0.022, 0.022, 0.024, 1), rough=1.0)
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
    top = cast((x, 1.2, 1.4), (0, 0.35, -1), trim_bvh) or Vector((x, 1.30, 1.16))
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
box("Console_Shifter_Boot", (0.07, 0.10, 0.04), (0, -0.66, SEAT_Z + 0.18), trim, bevel=0.015)
box("Console_Shifter_Knob", (0.04, 0.05, 0.10), (0, -0.66, SEAT_Z + 0.24), trim, bevel=0.018, segments=4)

# Lower door cards: the source door trim stops at the old floor height, which leaves the inside of
# the painted door skin showing once the floor is lowered. A panel is ray-cast onto each door's
# inner skin (door closed) and parented to the door, so it swings with it.
for door in [bpy.data.objects[n] for n in ("Door_FL", "Door_FR", "Door_RL", "Door_RR")]:
    sgn = 1 if door.name.endswith("L") else -1
    bm_d = bmesh.new()
    bm_d.from_mesh(door.data)
    bm_d.transform(door.matrix_world)
    d_bvh = BVHTree.FromBMesh(bm_d)
    dy = np.array([v.co.y for v in bm_d.verts if 0.30 < v.co.z < 0.62 and abs(v.co.x) > 0.78])
    bm_d.free()
    ys = np.linspace(dy.min() + 0.035, dy.max() - 0.035, 24)
    zs = np.linspace(FLOOR_Z + 0.07, 0.64, 10)
    grid = {}
    for j, z in enumerate(zs):
        for i, y in enumerate(ys):
            h = d_bvh.ray_cast(Vector((sgn * 0.3, y, z)), Vector((sgn, 0, 0)), 1.0)[0]
            grid[i, j] = h - Vector((sgn * 0.012, 0, 0)) if h is not None and abs(h.x) > 0.72 else None
    vi, verts, faces = {}, [], []
    for k, p_ in grid.items():
        if p_ is not None:
            vi[k] = len(verts)
            verts.append(p_)
    for (i, j) in grid:
        q = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
        if all(k in vi for k in q):
            faces.append(tuple(vi[k] for k in (q if sgn < 0 else q[::-1])))
    card = sheet(f"{door.name}_Lower_Card", verts, faces, trim, 0.008, parent=door)
    card.data.shade_smooth()
    if door.name.startswith("Door_F"):   # speaker grille low in the front door cards
        c = Vector((sgn * 0.0, (ys[0] + ys[-1]) / 2 - 0.12, 0.47))
        h = d_bvh.ray_cast(Vector((sgn * 0.3, c.y, c.z)), Vector((sgn, 0, 0)), 1.0)[0]
        if h is not None:
            g = box(f"{door.name}_Speaker_Grille", (0.012, 0.17, 0.17), h - Vector((sgn * 0.024, 0, 0)),
                    black_plastic, bevel=0.03, segments=6)
            g.parent = door
            g.matrix_parent_inverse = door.matrix_world.inverted()

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

# ---------------------------------------------------------------------------
# 4. Partition: traced from the cabin cross-section just behind the front head restraints
# ---------------------------------------------------------------------------
PY = 0.32                  # front face of the partition
SPLIT_Z = 0.98             # opaque lower panel below, polycarbonate above
centre = Vector((0, PY, 1.0))
contour = []
for a in np.linspace(0, 2 * math.pi, 96, endpoint=False):
    d = Vector((math.cos(a), 0, math.sin(a)))
    hit = cast(centre, d)
    if hit is None:
        continue
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
