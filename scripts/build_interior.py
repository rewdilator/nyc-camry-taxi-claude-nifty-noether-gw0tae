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
             alpha=False, transmission=0.0, ior=1.5, coat=0.0, sheen=0.0, grain=None):
    """Principled material; `grain` = (scale, strength) adds a fine procedural surface texture (the
    weave of seat cloth and headliner, the stipple on moulded plastic)."""
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
    if grain:
        tc = nt.nodes.new("ShaderNodeTexCoord")
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = grain[0]
        noise.inputs["Detail"].default_value = 6.0
        bump = nt.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = grain[1]
        bump.inputs["Distance"].default_value = 0.0005
        nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
        nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    return m


cloth = material("Interior_Black_Cloth", (0.034, 0.034, 0.037, 1), rough=0.9, sheen=0.4, grain=(900, 0.35))
trim = material("Interior_Black_Trim", (0.036, 0.036, 0.039, 1), rough=0.55, grain=(1400, 0.15))
abs_black = material("Partition_Black_Panel", (0.025, 0.025, 0.027, 1), rough=0.45, grain=(1400, 0.12))
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


def remove_source_parts():
    """Delete the source's low-poly front seat backs and head restraints, the rear bench back and the
    oversized steering wheel; section 3 builds proper ones. Parts are matched by their bounding box,
    so a second run finds nothing left to delete."""
    def front_seat(mn, mx):
        return (mn[0] * mx[0] > 0 and 0.04 < mn[1] and mx[1] < 0.29 and mn[2] > 0.43 and mx[2] < 1.31
                and 0.07 < min(abs(mn[0]), abs(mx[0])) and max(abs(mn[0]), abs(mx[0])) < 0.66)

    def rear_back(mn, mx):
        return 0.83 < mn[1] and mx[1] < 1.27 and mn[2] > 0.49 and mx[2] < 1.27 and max(abs(mn[0]), abs(mx[0])) < 0.67

    def wheel(mn, mx):
        return mn[0] > 0.10 and mx[0] < 0.65 and mn[1] > -0.58 and mx[1] < -0.36 and mn[2] > 0.64 and mx[2] < 1.11

    me = bpy.data.objects["Cemel_Trim_Interior"].data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    seen, doomed = set(), []
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
        if front_seat(mn, mx) or rear_back(mn, mx) or wheel(mn, mx):
            doomed.extend(comp)
    bmesh.ops.delete(bm, geom=doomed, context="VERTS")
    bm.to_mesh(me)
    bm.free()


remove_source_parts()
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
carpet = material("Interior_Carpet_Charcoal", (0.05, 0.05, 0.053, 1), rough=1.0, sheen=0.5, grain=(600, 0.6))
rubber = material("Interior_Rubber_Mat", (0.02, 0.02, 0.021, 1), rough=0.75)
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
insert_mat = material("Interior_Seat_Insert", (0.052, 0.052, 0.056, 1), rough=0.95, sheen=0.5, grain=(700, 0.5))


def smoothstep(a, b, v):
    t = min(max((v - a) / (b - a), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def pad_mesh(name, W, L, T, bolster=0.0, bol_start=0.62, bol_fade=(0.72, 0.95), lumbar=0.0, lumbar_t=0.3,
             taper=0.0, round_end=True, round_start=False, insert_u=0.56, insert_t=(0.06, 0.86), rise=0.0,
             nx=16, nt=18, mats=None):
    """An upholstered pad (seat back, cushion or head restraint), lofted from cross-sections.

    Local frame: x across, n through the pad (the sitting face is -n), t along its length (0..1 over
    L). Each cross-section has a flat-ish centre, side bolsters that rise and curl back at the edges,
    and a flatter back; the ends roll over. Subdivision smooths it into sewn upholstery, and the centre
    of the sitting face takes the insert fabric (material 1)."""
    bm_ = bmesh.new()
    rings = []
    for j in range(nt):
        t = j / (nt - 1)
        w = W / 2 * (1 - taper * smoothstep(0.62, 1.0, t))
        sc = 1.0
        if round_end and t > 0.78:
            sc = math.sqrt(max(0.04, 1 - ((t - 0.78) / 0.22) ** 2))
        if round_start and t < 0.22:
            sc = min(sc, math.sqrt(max(0.04, 1 - ((0.22 - t) / 0.22) ** 2)))
        fade = 1 - smoothstep(bol_fade[0], bol_fade[1], t)
        front, back = [], []
        for i in range(nx):
            u = -math.cos(math.pi * i / (nx - 1))
            au = abs(u)
            n = -(T / 2) * sc - bolster * smoothstep(bol_start, 0.9, au) * fade * sc
            n -= lumbar * math.exp(-((t - lumbar_t) / 0.16) ** 2)
            n -= rise * smoothstep(0.55, 0.9, t) * sc
            n += T * 0.45 * smoothstep(0.9, 1.0, au) * sc          # the edge curls round to the back
            front.append((u * w, n, t * L))
        for i in reversed(range(nx)):
            u = -math.cos(math.pi * i / (nx - 1))
            back.append((u * w * 0.97, (T / 2) * sc + 0.008 * (1 - u * u) * sc, t * L))
        rings.append([bm_.verts.new(p_) for p_ in front + back])
    m_ = 2 * nx
    for j in range(nt - 1):
        t = (j + 0.5) / (nt - 1)
        for k in range(m_):
            f = bm_.faces.new((rings[j][k], rings[j][(k + 1) % m_], rings[j + 1][(k + 1) % m_], rings[j + 1][k]))
            if k < nx - 1:
                u = -math.cos(math.pi * (k + 0.5) / (nx - 1))
                if abs(u) < insert_u and insert_t[0] < t < insert_t[1]:
                    f.material_index = 1
    bm_.faces.new(rings[0][::-1])
    bm_.faces.new(rings[-1])
    bmesh.ops.recalc_face_normals(bm_, faces=bm_.faces)
    me_ = bpy.data.meshes.new(name)
    bm_.to_mesh(me_)
    bm_.free()
    for m in (mats or (cloth, insert_mat)):
        me_.materials.append(m)
    me_.shade_smooth()
    ob = bpy.data.objects.new(name, me_)
    sub = ob.modifiers.new("Subsurf", "SUBSURF")
    sub.levels = sub.render_levels = 2
    return add(ob)


def place_back(ob, pivot, tilt, x, z0=0.0):
    """Seat-back frame: upright pad reclined by `tilt` about its foot at `pivot`."""
    ob.matrix_world = Matrix.Translation(pivot) @ Matrix.Rotation(tilt, 4, "X") @ Matrix.Translation((x, 0, z0))


def place_cushion(ob, x, y_rear, z, pitch=math.radians(5)):
    """Cushion frame: the pad's length runs forward (-Y) from the backrest, its sitting face up."""
    to_car = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, -1, 0, 0), (0, 0, 0, 1)))   # x, n, t -> x, -t, -n
    ob.matrix_world = (Matrix.Translation((x, y_rear, z)) @ Matrix.Rotation(-pitch, 4, "X") @ to_car)


CUSH_T = 0.075
for x, tag in ((0.38, "Driver"), (-0.38, "Passenger")):
    # sculpted cushion: thigh bolsters, a slight dish, and a raised, rolled front edge
    place_cushion(pad_mesh(f"Seat_Cushion_{tag}", 0.51, 0.52, CUSH_T + 0.02, bolster=0.035, bol_start=0.6,
                           bol_fade=(0.8, 1.0), rise=0.012, taper=0.06, insert_u=0.52, insert_t=(0.1, 0.84)),
                  x, 0.10, SEAT_Z + CUSH_T / 2 + 0.005)
    # front belt: stowed down the B-pillar from the D-ring; buckle stalk on the console side
    xo = math.copysign(1, x)
    box(f"Seat_Belt_DRing_{tag}", (0.012, 0.03, 0.06), (xo * 0.665, 0.235, 1.22), black_plastic, bevel=0.004)
    strap(f"Seat_Belt_{tag}", (xo * 0.66, 0.225, 1.20), (xo * 0.715, 0.225, SEAT_Z - 0.05), 0.048, webbing,
          face=Vector((-xo, 0, 0)))
    box(f"Seat_Belt_Buckle_{tag}", (0.03, 0.022, 0.075), (xo * 0.13, 0.04, SEAT_Z + 0.07), black_plastic,
        bevel=0.006, rot=(math.radians(15), 0, 0))

# rear bench half-width: inside the door cards (the ray now reaches the door skin, the source's side
# trim having been replaced by door cards 6.5 cm inside it)
rear_hw = min(min(abs(cast((0, 0.7, SEAT_Z + 0.12), (s, 0, 0)).x) for s in (-1, 1)) - 0.12, 0.68)
REAR_Y0, REAR_Y1 = 0.46, 0.96
box("Seat_Base_Rear", (2 * rear_hw - 0.04, REAR_Y1 - REAR_Y0 - 0.02, SEAT_Z - FLOOR_Z),
    (0, (REAR_Y0 + REAR_Y1) / 2 + 0.01, (SEAT_Z + FLOOR_Z) / 2), cloth, bevel=0.02)
# rear bench: two contoured outboard seats and a flatter centre seat, each its own cushion
RW_OUT = 0.47
RW_C = 2 * rear_hw - 2 * RW_OUT
for x, w, tag, bol in ((rear_hw - RW_OUT / 2, RW_OUT, "L", 0.022), (0.0, RW_C, "C", 0.006),
                       (-(rear_hw - RW_OUT / 2), RW_OUT, "R", 0.022)):
    place_cushion(pad_mesh(f"Seat_Cushion_Rear_{tag}", w + 0.01, REAR_Y1 - REAR_Y0, CUSH_T + 0.02, bolster=bol,
                           bol_fade=(0.8, 1.0), rise=0.008, insert_u=0.5, insert_t=(0.1, 0.84)),
                  x, REAR_Y1, SEAT_Z + CUSH_T / 2 + 0.005, pitch=math.radians(7))
for i, x in enumerate((-0.45, -0.28, 0.0, 0.14, 0.28, 0.45)):  # seat-belt buckles and latches
    box(f"Seat_Belt_Buckle_Rear_{i}", (0.03, 0.02, 0.07), (x, REAR_Y1 - 0.03, SEAT_Z + CUSH_T + 0.03),
        black_plastic, bevel=0.006, rot=(math.radians(-20), 0, 0))
# ---------------------------------------------------------------------------
# 3d. Seat backs, head restraints, steering wheel (replacing the source's low-poly ones)
# ---------------------------------------------------------------------------
# the LE's wheel and shift knob are urethane, not leather: matte, with a fine moulded grain
leather = material("Interior_Wheel_Urethane", (0.032, 0.032, 0.034, 1), rough=0.62, grain=(2600, 0.18))
accent = material("Interior_Dash_Accent_Satin", (0.22, 0.22, 0.23, 1), rough=0.3, metal=1.0, grain=(2500, 0.08))


def tilted(name, size, pivot, local, tilt, mat, bevel=0.0, segments=3, subsurf=0):
    """A box placed in a frame tilted back by `tilt` (radians, about X) around `pivot`."""
    R = Matrix.Rotation(tilt, 4, "X")
    ob = box(name, size, (0, 0, 0), mat, bevel=bevel, segments=segments)
    ob.matrix_world = Matrix.Translation(pivot) @ R @ Matrix.Translation(local)
    if subsurf:
        m = ob.modifiers.new("Subsurf", "SUBSURF")
        m.levels = m.render_levels = subsurf
    return ob


def seat_back(tag, x, pivot, tilt, width, height, thick, headrest=(0.27, 0.10, 0.18), bolsters=True):
    """Sculpted backrest (bolsters, lumbar bulge, shoulders narrowing to the top) with a head restraint
    on two chrome posts, reclined about its foot."""
    back = pad_mesh(f"Seat_Back_{tag}", width, height, thick, bolster=0.05 if bolsters else 0.012,
                    bol_start=0.6, lumbar=0.014, taper=0.2 if bolsters else 0.05,
                    insert_u=0.55, insert_t=(0.05, 0.8))
    place_back(back, pivot, tilt, x)
    if headrest:
        hw, hd, hh = headrest
        hr = pad_mesh(f"Seat_Headrest_{tag}", hw, hh, hd, taper=0.12, round_start=True, insert_u=0.0, nx=12, nt=12)
        place_back(hr, pivot, tilt, x, height + 0.06)
        for px in (-0.06, 0.06):
            post = cylinder(f"Seat_Headrest_Post_{tag}_{'L' if px > 0 else 'R'}", 0.0055, 0.09, (0, 0, 0), chrome, 10)
            post.matrix_world = (Matrix.Translation(pivot) @ Matrix.Rotation(tilt, 4, "X")
                                 @ Matrix.Translation((x + px, 0.01, height + 0.03)))
            box(f"Seat_Headrest_Guide_{tag}_{'L' if px > 0 else 'R'}", (0.02, 0.02, 0.012), (0, 0, 0), black_plastic,
                bevel=0.004).matrix_world = (Matrix.Translation(pivot) @ Matrix.Rotation(tilt, 4, "X")
                                             @ Matrix.Translation((x + px, 0.01, height - 0.004)))


# front seats: foot of the backrest on the rear of the cushion, reclined 10 degrees
for x, tag in ((0.38, "Driver"), (-0.38, "Passenger")):
    seat_back(tag, x, Vector((0, 0.165, SEAT_Z + 0.05)), math.radians(-10), 0.52, 0.60, 0.10)
    xo = x + math.copysign(0.265, x)
    box(f"Seat_Side_Shield_{tag}", (0.022, 0.34, 0.10), (xo, -0.10, SEAT_Z + 0.02), trim, bevel=0.008)
    box(f"Seat_Recline_Lever_{tag}", (0.018, 0.10, 0.02), (xo + math.copysign(0.012, x), 0.02, SEAT_Z + 0.045),
        black_plastic, bevel=0.006)

# rear bench back: two outboard seats and a narrower centre with a fold-down armrest, three restraints
RB_PIVOT = Vector((0, REAR_Y1 - 0.02, SEAT_Z + CUSH_T - 0.01))
RB_TILT = math.radians(-26)
RB_H, RB_T = 0.54, 0.11
for x, w, tag, bol in ((rear_hw - RW_OUT / 2, RW_OUT, "L", True), (-(rear_hw - RW_OUT / 2), RW_OUT, "R", True)):
    seat_back(f"Rear_{tag}", x, RB_PIVOT, RB_TILT, w + 0.01, RB_H, RB_T, bolsters=bol)
seat_back("Rear_C", 0.0, RB_PIVOT, RB_TILT, RW_C + 0.01, RB_H - 0.03, RB_T, headrest=(0.20, 0.085, 0.13),
          bolsters=False)
tilted("Seat_Rear_Armrest", (0.26, 0.012, RB_H * 0.72), RB_PIVOT, (0, -RB_T / 2 - 0.004, RB_H * 0.45), RB_TILT,
       insert_mat, bevel=0.006)
tilted("Seat_Rear_Armrest_Pull", (0.06, 0.012, 0.018), RB_PIVOT, (0, -RB_T / 2 - 0.01, RB_H * 0.78), RB_TILT,
       black_plastic, bevel=0.004)
for x in (-0.25, 0.25):     # child-seat anchor tags in the seat bight
    box(f"Seat_Rear_Isofix_{'L' if x > 0 else 'R'}", (0.035, 0.012, 0.03), (x, REAR_Y1 - 0.045, SEAT_Z + CUSH_T + 0.02),
        black_plastic, bevel=0.004)

# rear belts: from guides on the parcel shelf, down the face of the outboard backrests
n_rb = Matrix.Rotation(RB_TILT, 4, "X") @ Vector((0, -1, 0))
for x, tag in ((0.60, "L"), (0.0, "C"), (-0.60, "R")):
    top = cast((x, 1.33, 1.27), -Z, trim_bvh, 0.4) or Vector((x, 1.33, 1.16))
    face_top = RB_PIVOT + Matrix.Rotation(RB_TILT, 4, "X") @ Vector((x, 0, RB_H)) + n_rb * (RB_T / 2 + 0.012)
    face_bot = RB_PIVOT + Matrix.Rotation(RB_TILT, 4, "X") @ Vector((x * 0.8, 0, 0.06)) + n_rb * (RB_T / 2 + 0.012)
    strap(f"Seat_Belt_Rear_{tag}_Upper", top + Vector((0, -0.01, 0.005)), face_top, 0.048, webbing,
          face=Vector((0, -1, 0.6)))
    strap(f"Seat_Belt_Rear_{tag}", face_top, face_bot, 0.048, webbing, face=n_rb)
    box(f"Seat_Belt_Guide_Rear_{tag}", (0.07, 0.03, 0.015), top + Vector((0, 0, 0.004)), black_plastic, bevel=0.004)

# steering wheel: 375 mm leather rim, three spokes, airbag hub with badge, column shroud and stalks.
# Local frame: the wheel lies in its XZ plane, +Y points at the driver, the column goes to -Y.
WC = Vector((0.375, -0.485, 0.895))
W_TILT = math.radians(24)                   # top of the wheel leans forward
WM = Matrix.Translation(WC) @ Matrix.Rotation(W_TILT, 4, "X")
R_RIM, r_rim, r_rim_y = 0.1875, 0.0155, 0.0185     # rim section is oval, deeper than it is wide
bm = bmesh.new()
nu, nv = 72, 12
ring = []
for i in range(nu):
    a = 2 * math.pi * i / nu
    row = []
    for j in range(nv):
        b = 2 * math.pi * j / nv
        # thumb rests: the rim swells where the spokes meet it at 9 and 3 o'clock
        g = 1 + 0.28 * max(math.exp(-((a - math.radians(-8)) / 0.30) ** 2),
                           math.exp(-((a - math.radians(188)) / 0.30) ** 2))
        rr = R_RIM + r_rim * g * math.cos(b)
        row.append(bm.verts.new((rr * math.cos(a), r_rim_y * g * math.sin(b), rr * math.sin(a))))
    ring.append(row)
for i in range(nu):
    for j in range(nv):
        bm.faces.new((ring[i][j], ring[(i + 1) % nu][j], ring[(i + 1) % nu][(j + 1) % nv], ring[i][(j + 1) % nv]))
me = bpy.data.meshes.new("Steering_Wheel_Rim")
bm.to_mesh(me)
bm.free()
me.materials.append(leather)
me.shade_smooth()
rim = add(bpy.data.objects.new(me.name, me))
rim.matrix_world = WM


def wheel_part(name, size, local, mat, bevel=0.0, segments=3, rot_y=0.0):
    ob = box(name, size, (0, 0, 0), mat, bevel=bevel, segments=segments)
    ob.matrix_world = WM @ Matrix.Translation(local) @ Matrix.Rotation(rot_y, 4, "Y")
    return ob


def wheel_slab(name, outline, y0, y1, mat, bevel=0.006, smooth=True):
    """A flat moulding in the wheel plane: `outline` (x, z) extruded from local y0 to y1 (toward the
    driver), edges rounded."""
    bm_ = bmesh.new()
    back = [bm_.verts.new((x, y0, z)) for x, z in outline]
    front = [bm_.verts.new((x, y1, z)) for x, z in outline]
    n_ = len(outline)
    bm_.faces.new(back[::-1])
    bm_.faces.new(front)
    for k in range(n_):
        bm_.faces.new((back[k], back[(k + 1) % n_], front[(k + 1) % n_], front[k]))
    bmesh.ops.recalc_face_normals(bm_, faces=bm_.faces)
    me_ = bpy.data.meshes.new(name)
    bm_.to_mesh(me_)
    bm_.free()
    me_.materials.append(mat)
    ob = bpy.data.objects.new(name, me_)
    if bevel:
        mod = ob.modifiers.new("Bevel", "BEVEL")
        mod.width, mod.segments, mod.limit_method = bevel, 3, "ANGLE"
    if smooth:
        me_.shade_smooth()
    add(ob)
    ob.matrix_world = WM
    return ob


def rounded(poly, r=0.012, n=4):
    """Round the corners of a convex polygon (x, z) with arcs of radius r."""
    out = []
    m_ = len(poly)
    for k in range(m_):
        p0, p1, p2 = (Vector((*poly[k - 1], 0)), Vector((*poly[k], 0)), Vector((*poly[(k + 1) % m_], 0)))
        a_ = (p0 - p1).normalized()
        b_ = (p2 - p1).normalized()
        s0, s1 = p1 + a_ * r, p1 + b_ * r
        for t in np.linspace(0, 1, n).tolist():
            q = (1 - t) ** 2 * s0 + 2 * (1 - t) * t * p1 + t ** 2 * s1     # quadratic corner
            out.append((q.x, q.y))
    return out


# airbag pad: a rounded trapezoid, wider at the top, with the badge in the middle
# airbag cover: a domed pad, wider at the top than the bottom, lofted from top (t=0) to bottom
hub = pad_mesh("Steering_Wheel_Hub", 0.165, 0.122, 0.05, taper=0.3, round_start=True, insert_u=0.0,
               nx=14, nt=14, mats=(leather, leather))
hub.matrix_world = WM @ Matrix.Translation((0, 0.012, 0.052)) @ Matrix(
    ((1, 0, 0, 0), (0, -1, 0, 0), (0, 0, -1, 0), (0, 0, 0, 1)))      # x, n, t -> x, -n (to driver), -t
# oval emblem: a chrome elliptical ring with a crossbar, set into the pad
bm = bmesh.new()
for k in range(40):
    a = 2 * math.pi * k / 40
    for rr_ in (1.0, 0.78):
        bm.verts.new((0.024 * rr_ * math.cos(a), 0.0, 0.016 * rr_ * math.sin(a)))
bm.verts.ensure_lookup_table()
for k in range(40):
    k2 = (k + 1) % 40
    bm.faces.new((bm.verts[2 * k], bm.verts[2 * k2], bm.verts[2 * k2 + 1], bm.verts[2 * k + 1]))
me = bpy.data.meshes.new("Steering_Wheel_Badge")
bm.to_mesh(me)
bm.free()
me.materials.append(chrome)
badge = add(bpy.data.objects.new(me.name, me))
badge.modifiers.new("Solidify", "SOLIDIFY").thickness = 0.003
badge.matrix_world = WM @ Matrix.Translation((0, 0.040, -0.004))
wheel_part("Steering_Wheel_Badge_Bar", (0.036, 0.003, 0.005), (0, 0.040, -0.004), chrome, bevel=0.0015)
for side in (-1, 1):
    tag = "L" if side > 0 else "R"
    # side spoke: tapers from the pad out to the rim, carrying the switch panel
    wheel_slab(f"Steering_Wheel_Spoke_{tag}", rounded([(side * 0.066, 0.016), (side * 0.182, 0.014),
                                                      (side * 0.182, -0.030), (side * 0.070, -0.048)][::side], 0.008),
               -0.010, 0.020, trim, bevel=0.005)
    panel = [(side * 0.086, 0.022), (side * 0.150, 0.014), (side * 0.150, -0.024), (side * 0.084, -0.036)]
    wheel_slab(f"Steering_Wheel_Switch_Panel_{tag}", rounded(panel[::side], 0.006), 0.020, 0.024, black_plastic,
               bevel=0.002)
    # Camry switch cluster: a round four-way pad (audio on the left spoke, display and cruise on the
    # right) with a satin surround, and two small buttons outboard of it
    pc = Vector((side * 0.108, 0.026, -0.004))
    ring_ = cylinder(f"Steering_Wheel_Pad_Ring_{tag}", 0.0165, 0.004, (0, 0, 0), accent, 24)
    ring_.matrix_world = WM @ Matrix.Translation(pc) @ Matrix.Rotation(math.radians(-90), 4, "X")
    pad_ = cylinder(f"Steering_Wheel_Four_Way_{tag}", 0.0135, 0.006, (0, 0, 0), trim, 24)
    pad_.matrix_world = WM @ Matrix.Translation(pc + Vector((0, 0.002, 0))) @ Matrix.Rotation(math.radians(-90), 4, "X")
    for k, (dx, dz) in enumerate(((0, 0.0085), (0, -0.0085), (0.0085, 0), (-0.0085, 0))):
        wheel_part(f"Steering_Wheel_Arrow_{tag}_{k}", (0.004, 0.002, 0.004), pc + Vector((dx, 0.0055, dz)),
                   accent, bevel=0.001)
    for k in range(2):
        wheel_part(f"Steering_Wheel_Button_{tag}_{k}", (0.013, 0.005, 0.010),
                   (side * 0.138, 0.025, 0.006 - 0.019 * k), trim, bevel=0.003)
    # satin trim along the lower edge of the spoke
    wheel_slab(f"Steering_Wheel_Spoke_Trim_{tag}", [(side * 0.074, -0.046), (side * 0.180, -0.028),
                                                    (side * 0.180, -0.034), (side * 0.072, -0.053)][::side],
               -0.004, 0.021, accent, bevel=0.0015)
    # split lower spoke: two legs from the pad down to the bottom of the rim
    wheel_slab(f"Steering_Wheel_Spoke_Lower_{tag}", [(side * 0.022, -0.064), (side * 0.048, -0.064),
                                                    (side * 0.050, -0.180), (side * 0.020, -0.182)][::side],
               -0.010, 0.016, trim, bevel=0.005)
wheel_slab("Steering_Wheel_Lower_Accent", [(-0.020, -0.120), (0.020, -0.120), (0.022, -0.176), (-0.022, -0.176)],
           -0.004, 0.010, accent, bevel=0.002)
wheel_part("Steering_Column_Shroud", (0.12, 0.24, 0.10), (0, -0.15, -0.03), trim, bevel=0.025, segments=3)
for side, tag in ((1, "Turn"), (-1, "Wiper")):
    st = cylinder(f"Steering_Stalk_{tag}", 0.007, 0.13, (0, 0, 0), black_plastic, 10)
    st.matrix_world = WM @ Matrix.Translation((side * 0.09, -0.06, 0.0)) @ Matrix.Rotation(math.radians(90), 4, "Y")

# Rubber floor mats
for x0, x1, tag in ((0.12, 0.70, "Driver"), (-0.70, -0.12, "Passenger")):
    box(f"Floor_Mat_{tag}", (x1 - x0, 0.50, 0.008), ((x0 + x1) / 2, -0.64, FLOOR_Z + 0.004), rubber,
        bevel=0.004)
box("Floor_Mat_Rear", (2 * rear_hw - 0.1, 0.10, 0.008), (0, (0.36 + REAR_Y0) / 2, FLOOR_Z + 0.004), rubber,
    bevel=0.003)

# carpet over the source floor tub, sill scuff plates, parcel-shelf speakers and brake light
box("Floor_Carpet", (1.46, 1.36, 0.006), (0, -0.22, FLOOR_Z + 0.001), carpet)
for s_ in (1, -1):
    for y0, y1, tag in ((-0.98, 0.14, "F"), (0.24, 1.00, "R")):
        box(f"Sill_Scuff_Plate_{'L' if s_ > 0 else 'R'}{tag}", (0.06, y1 - y0, 0.006),
            (s_ * 0.83, (y0 + y1) / 2, SILL_Z + 0.012), black_plastic, bevel=0.002)
        box(f"Sill_Scuff_Insert_{'L' if s_ > 0 else 'R'}{tag}", (0.02, (y1 - y0) * 0.7, 0.002),
            (s_ * 0.83, (y0 + y1) / 2, SILL_Z + 0.016), chrome)
for x in (-0.42, 0.42):
    h = cast((x, 1.40, 1.30), -Z, trim_bvh, 0.4)
    if h is not None:
        cylinder(f"Parcel_Shelf_Speaker_{'L' if x > 0 else 'R'}", 0.065, 0.006, h + Z * 0.004, black_plastic, 24)
h = cast((0, 1.43, 1.30), -Z, trim_bvh, 0.4)
if h is not None:
    box("Parcel_Shelf_Brake_Light", (0.24, 0.045, 0.03), h + Z * 0.016, black_plastic, bevel=0.006)
    box("Parcel_Shelf_Brake_Light_Lens", (0.22, 0.004, 0.018), h + Vector((0, 0.024, 0.016)),
        material("Interior_Brake_Light_Lens", (0.5, 0.02, 0.02, 1), rough=0.2), bevel=0.001)

box("Console_Base", (0.18, 0.86, 0.74 - FLOOR_Z), (0, -0.44, (0.74 + FLOOR_Z) / 2), trim, bevel=0.02)
box("Console_Armrest", (0.19, 0.30, 0.05), (0, -0.10, SEAT_Z + 0.185), cloth, bevel=0.018, segments=4)
# Camry Hybrid shifter: a piano-black gate panel with the P-R-N-D-B staggered gate and a satin rim,
# and a short lever with an egg-shaped urethane knob and a satin collar
gate_mat = material("Interior_Shift_Gate", rough=0.08, image="interior_shift_gate.png", coat=1.0)
box("Console_Shift_Surround", (0.11, 0.21, 0.02), (0, -0.50, SEAT_Z + 0.19), trim, bevel=0.012)
gate_n = Vector((0, 0.10, 1)).normalized()
quad("Console_Shift_Gate", (0, -0.50, SEAT_Z + 0.2012), 0.085, 0.17, gate_n, gate_mat)
cylinder("Console_Shifter_Stem", 0.008, 0.045, (0, -0.545, SEAT_Z + 0.222), black_plastic, 12)
bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1.0)
knob = bpy.context.active_object
bpy.context.scene.collection.objects.unlink(knob) if knob.name in bpy.context.scene.collection.objects else None
for c_ in list(knob.users_collection):
    c_.objects.unlink(knob)
knob.name = knob.data.name = "Console_Shifter_Knob"
for v in knob.data.vertices:                      # egg: fuller at the top, where the palm rests
    v.co.x *= 0.021 * (1 + 0.12 * v.co.z)
    v.co.y *= 0.026 * (1 + 0.12 * v.co.z)
    v.co.z *= 0.034
knob.data.materials.append(leather)
knob.data.shade_smooth()
add(knob)
knob.location = (0, -0.548, SEAT_Z + 0.272)
knob.rotation_euler = (math.radians(-12), 0, 0)
cylinder("Console_Shifter_Collar", 0.0165, 0.008, (0, -0.546, SEAT_Z + 0.242), accent, 24)
box("Console_Shifter_Button_Trim", (0.012, 0.004, 0.012), (0, -0.522, SEAT_Z + 0.272), accent, bevel=0.003,
    rot=(math.radians(-12), 0, 0))

# ---------------------------------------------------------------------------
# 3a. Dash, console and roof details (the source dash is a bare black shell)
# ---------------------------------------------------------------------------
cluster_mat = material("Interior_Gauge_Cluster", rough=0.1, image="interior_gauge_cluster.png", emission=1.2)
screen_mat = material("Interior_Touchscreen", rough=0.1, image="interior_infotainment.png", emission=0.9)
climate_mat = material("Interior_Climate_Panel", rough=0.3, image="interior_climate_panel.png", emission=0.25)
lens_mat = material("Interior_Lamp_Lens", (0.85, 0.85, 0.8, 1), rough=0.35)
mirror_mat = material("Interior_Vanity_Mirror", (0.9, 0.9, 0.9, 1), rough=0.05, metal=1.0)


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
cl_y = dash_face_y(0.38, 0.975) + 0.004
quad("Dash_Gauge_Cluster", (0.38, cl_y, 0.975), 0.30, 0.1125, Vector((0, 1, 0.28)), cluster_mat)
box("Dash_Gauge_Cluster_Bezel", (0.32, 0.012, 0.13), (0.38, cl_y - 0.004, 0.975), black_plastic, bevel=0.004,
    rot=(math.radians(-15.6), 0, 0))
# Centre stack, as on the XV70 Camry: a triangular piano-black panel angled toward the driver, the
# 7 in touchscreen at its top with silver buttons and two knobs beside it, the centre vents
# flanking it, and the climate strip directly below; the panel tapers down into the console.
piano = material("Interior_Piano_Black", (0.01, 0.01, 0.011, 1), rough=0.08, coat=1.0)
STACK_X = -0.01
stack_n = Vector((0.14, 1, 0.10)).normalized()          # turned a little toward the driver
stack_rows = [(0.975, 0.40), (0.86, 0.34), (0.76, 0.24), (0.66, 0.17), (0.60, 0.15)]   # (z, width)
verts, faces = [], []
for z, w in stack_rows:
    for x in (STACK_X - w / 2, STACK_X + w / 2):
        verts.append(Vector((x, dash_face_y(x, z) + 0.006, z)))
for k in range(len(stack_rows) - 1):
    faces.append((2 * k, 2 * k + 1, 2 * k + 3, 2 * k + 2))
sheet("Dash_Centre_Stack_Panel", verts, faces, piano, 0.004).data.shade_smooth()
scr_x, scr_z = STACK_X, 0.925
scr_y = dash_face_y(scr_x, scr_z) + 0.014
device("Dash_Touchscreen", (scr_x, scr_y, scr_z), (0.19, 0.11, 0.018), stack_n, piano, screen_mat, (0.165, 0.093))
right_, up_, _ = frame_axes(stack_n)
for side in (-1, 1):
    # four silver hard keys in a column on each side of the screen, a knob below them
    for k in range(4):
        c = Vector((scr_x, scr_y, scr_z)) + right_ * side * 0.108 + up_ * (0.036 - k * 0.024) + stack_n * 0.004
        box(f"Dash_Screen_Key_{'L' if side > 0 else 'R'}_{k}", (0.016, 0.006, 0.014), c, chrome, bevel=0.002,
            rot=Matrix((right_, -stack_n, up_)).transposed().to_euler())
    knob = cylinder(f"Dash_Knob_{'Tune' if side < 0 else 'Volume'}", 0.012, 0.018, (0, 0, 0), chrome, 20)
    knob.matrix_world = (Matrix.Translation(Vector((scr_x, scr_y, scr_z)) + right_ * side * 0.108 - up_ * 0.075)
                         @ stack_n.to_track_quat("Z", "Y").to_matrix().to_4x4())
# centre vents either side of the screen (the driver's one sits behind the T-PEP monitor)
vent("Dash_Vent_Centre_L", STACK_X + 0.19, 0.93, w=0.07, h=0.075)
vent("Dash_Vent_Centre_R", STACK_X - 0.19, 0.93, w=0.07, h=0.075)
vent("Dash_Vent_Outer_L", 0.62, 0.95, w=0.09, h=0.055)
vent("Dash_Vent_Outer_R", -0.62, 0.95, w=0.09, h=0.055)
cz = 0.815
quad("Dash_Climate_Panel", (STACK_X, dash_face_y(STACK_X, cz) + 0.009, cz), 0.24, 0.06, stack_n, climate_mat)
# open tray for phone/wireless charging under the climate strip, with the USB port
box("Dash_Stack_Tray", (0.16, 0.05, 0.012), (STACK_X, dash_face_y(STACK_X, 0.715) + 0.02, 0.705), black_plastic,
    bevel=0.004)
box("Dash_USB_Port", (0.014, 0.004, 0.007), (STACK_X - 0.05, dash_face_y(STACK_X - 0.05, 0.735) + 0.007, 0.735),
    steel, bevel=0.001)
box("Dash_Start_Button", (0.03, 0.012, 0.03), (0.16, dash_face_y(0.16, 0.80) + 0.004, 0.80), chrome, bevel=0.008)
# the XV70's wave-shaped trim band: across the passenger side of the dash, then down the passenger
# edge of the centre stack into the console
band = []
for x in np.linspace(-0.70, -0.24, 20):
    zc = 0.885 + 0.012 * math.sin((x + 0.70) / 0.46 * math.pi)       # a gentle wave
    band.append((x, zc))
for t in np.linspace(0, 1, 10)[1:]:                                   # sweep down beside the stack
    z = 0.885 - t * (0.885 - 0.64)
    w = 0.40 - (0.40 - 0.15) * (0.975 - z) / (0.975 - 0.60)
    band.append((STACK_X - w / 2 - 0.02, z))
verts, faces = [], []
for k, (x, z) in enumerate(band):
    if k + 1 < len(band):
        dx, dz = band[k + 1][0] - x, band[k + 1][1] - z
    nrm = Vector((-dz, 0, dx)).normalized() * 0.016                   # half-width across the band
    for sgn_ in (-1, 1):
        px, pz = x + sgn_ * nrm.x, z + sgn_ * nrm.z
        verts.append(Vector((px, dash_face_y(px, pz) + 0.004, pz)))
faces = [(2 * i, 2 * i + 2, 2 * i + 3, 2 * i + 1) for i in range(len(band) - 1)]
sheet("Dash_Accent_Band", verts, faces, accent, 0.002).data.shade_smooth()
# stitched, padded leatherette across the mid-dash above the trim band (as in the reviews), with
# tonal stitching along both edges
pad_mat = material("Interior_Dash_Pad_Leatherette", (0.045, 0.045, 0.048, 1), rough=0.5, grain=(2200, 0.3))
stitch_mat = material("Interior_Dash_Stitching", (0.16, 0.16, 0.17, 1), rough=0.8)
pad_x = np.linspace(-0.72, -0.22, 26)


def dash_strip(name, z_of, half_h, mat, lift, thick):
    verts_, faces_ = [], []
    for x in pad_x:
        zc = z_of(x)
        for z in (zc - half_h, zc + half_h):
            verts_.append(Vector((x, dash_face_y(x, z) + lift, z)))
    faces_ = [(2 * i, 2 * i + 2, 2 * i + 3, 2 * i + 1) for i in range(len(pad_x) - 1)]
    sheet(name, verts_, faces_, mat, thick).data.shade_smooth()


def pad_z(x):
    return 0.93 + 0.012 * math.sin((x + 0.70) / 0.46 * math.pi)


dash_strip("Dash_Mid_Pad", pad_z, 0.022, pad_mat, 0.007, 0.006)
for k, dz in enumerate((-0.016, 0.016)):
    dash_strip(f"Dash_Mid_Pad_Stitch_{k}", lambda x, dz=dz: pad_z(x) + dz, 0.0012, stitch_mat, 0.0085, 0.001)

# cup holders between the shifter and the armrest
for x in (-0.045, 0.045):
    cylinder(f"Console_Cup_Holder_{'L' if x > 0 else 'R'}", 0.038, 0.004, (x, -0.33, 0.742), black_plastic)
    cylinder(f"Console_Cup_Ring_{'L' if x > 0 else 'R'}", 0.042, 0.002, (x, -0.33, 0.741), steel)


def roof_z(x, y):
    h = cast((x, y, 1.1), Z, car_bvh, 0.6)
    return h.z if h is not None else 1.40


# fabric headliner over the source roof lining (a near-white atlas swatch that blows out in renders)
headliner = material("Interior_Headliner_Fabric", (0.42, 0.41, 0.39, 1), rough=0.95, sheen=0.4, grain=(800, 0.3))
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
card_mat = material("Interior_Door_Card", (0.04, 0.04, 0.043, 1), rough=0.55, grain=(1400, 0.15))
door_fabric = material("Interior_Door_Insert_Fabric", (0.085, 0.085, 0.088, 1), rough=0.95, sheen=0.5,
                       grain=(800, 0.45))
reflector = material("Interior_Door_Reflector", (0.35, 0.01, 0.01, 1), rough=0.3)
CARD_OFF = 0.065          # card surface this far inside the outer skin
cards = []


def hull2d(pts):
    pts = sorted(set(pts))
    if len(pts) < 3:
        return pts

    def half(seq):
        h = []
        for p in seq:
            while len(h) >= 2 and ((h[-1][0] - h[-2][0]) * (p[1] - h[-2][1]) -
                                   (h[-1][1] - h[-2][1]) * (p[0] - h[-2][0])) <= 0:
                h.pop()
            h.append(p)
        return h
    return half(pts)[:-1] + half(pts[::-1])[:-1]


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
    glass_idx = {i for i, m in enumerate(door.data.materials) if m and m.name == "Index_0_2"}
    glass = np.array([v.co[:] for f in bm_d.faces if f.material_index in glass_idx for v in f.verts])
    bm_d.free()
    y_a, y_b = dy.min() + 0.05, dy.max() - 0.05

    def skin_x(y, z):
        h = d_bvh.ray_cast(Vector((sgn * 0.3, y, z)), Vector((sgn, 0, 0)), 1.0)[0]
        return abs(h.x) if h is not None and abs(h.x) > 0.76 else None

    def card_x(y, z, extra=0.0):
        sx = skin_x(y, z)
        return None if sx is None else max(sx - CARD_OFF - extra, 0.72)

    zs = list(np.linspace(FLOOR_Z + 0.03, 0.93, 16))
    fine = np.arange(dy.min() - 0.03, dy.max() + 0.03, 0.01)

    def refine(y_in, y_out, z):
        """Bisect between a y on the skin and a y off it, to the skin edge within 1 mm."""
        for _ in range(7):
            m = (y_in + y_out) / 2
            y_in, y_out = (m, y_out) if skin_x(m, z) is not None else (y_in, m)
        return y_in

    def skin_edges(z):
        """Front and rear edge of the door skin at height z (the rear door curves round the wheel arch)."""
        ok = [y for y in fine if skin_x(y, z) is not None]
        if not ok:
            return None
        return refine(min(ok), min(ok) - 0.01, z), refine(max(ok), max(ok) + 0.01, z)

    CARD_INSET = 0.04        # the card stops short of the door edge; a shut face closes the gap

    def row_span(z):
        e = skin_edges(z)
        return None if e is None else (e[0] + CARD_INSET, e[1] - CARD_INSET)

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

    # Shut faces: painted door edges from the card out to the skin (front, rear and bottom), so an
    # open door reads as a closed pressed-steel shell rather than a single skin.
    sf_v, sf_f = [], []

    def sf_quad(a, b, c, d):
        base = len(sf_v)
        sf_v.extend([a, b, c, d])
        sf_f.append((base, base + 1, base + 2, base + 3))

    edge_pts = {}
    for j, z in enumerate(zs):
        e = skin_edges(z)
        if e is None or grid[0, j] is None or grid[NU - 1, j] is None:
            continue
        for side, ye in ((0, e[0]), (1, e[1])):
            sx = skin_x(ye + (0.002 if side == 0 else -0.002), z)
            if sx is not None:
                edge_pts[side, j] = (grid[0 if side == 0 else NU - 1, j], Vector((sgn * (sx - 0.002), ye, z)))
    for side in (0, 1):
        for j in range(len(zs) - 1):
            if (side, j) in edge_pts and (side, j + 1) in edge_pts:
                c0, s0 = edge_pts[side, j]
                c1, s1 = edge_pts[side, j + 1]
                sf_quad(c0, c1, s1, s0)
    bottom = []
    for i in range(NU):
        c = grid[i, 0]
        if c is None:
            continue
        zb = None
        for z in np.arange(zs[0], 0.20, -0.01):
            if skin_x(c.y, z) is None:
                break
            zb = z
        if zb is not None and zb < zs[0] - 0.005:
            bottom.append((c, Vector((sgn * (skin_x(c.y, zb) - 0.002), c.y, zb))))
    for (c0, s0), (c1, s1) in zip(bottom, bottom[1:]):
        sf_quad(c0, c1, s1, s0)
    me = bpy.data.meshes.new(f"{door.name}_Shut_Face")
    me.from_pydata([v[:] for v in sf_v], [], sf_f)
    me.materials.append(bpy.data.materials["NYC_Taxi_Yellow_Paint"])
    door_child(add(bpy.data.objects.new(me.name, me)), door)

    # Body jamb on the free edge (hinge side of the front doors, closing side of the rear doors): a
    # painted return with a black rubber seal just outside the door's edge. The B-pillar edge
    # between the two doors already has the pillar and its trim.
    side = 0 if front else 1
    jp, js = [], []
    for j, z in enumerate(zs):
        if (side, j) not in edge_pts:
            continue
        _, s_ = edge_pts[side, j]
        out = -0.006 if side == 0 else 0.006
        xo = abs(s_.x)
        jp.append((Vector((sgn * (xo - 0.004), s_.y + out, z)), Vector((sgn * (xo - 0.055), s_.y + out, z))))
        js.append((Vector((sgn * (xo - 0.055), s_.y + out * 1.5, z)), Vector((sgn * (xo - 0.078), s_.y + out * 1.5, z))))
    for nm, pts, mat in (("Jamb", jp, bpy.data.materials["NYC_Taxi_Yellow_Paint"]), ("Seal", js, rubber)):
        verts, faces = [], []
        for (a0, b0), (a1, b1) in zip(pts, pts[1:]):
            base = len(verts)
            verts.extend([a0, a1, b1, b0])
            faces.append((base, base + 1, base + 2, base + 3))
        me = bpy.data.meshes.new(f"Body_{nm}_{door.name[5:]}")
        me.from_pydata([v[:] for v in verts], [], faces)
        me.materials.append(mat)
        add(bpy.data.objects.new(me.name, me))

    # hinges on the hinge line (they stay put while the door turns about them)
    hx, hy = door.location.x, door.location.y
    for hz in (0.48, 0.80):
        cylinder(f"{door.name}_Hinge_{'Lower' if hz < 0.6 else 'Upper'}", 0.011, 0.07,
                 (hx - sgn * 0.004, hy + 0.004, hz), steel, segments=12)

    # Window frame from inside: a black glass-run channel round the top and ends of the glass, as on
    # a real door, where the frame is a moulded channel rather than just the outer chrome strip.
    glass = glass[(np.abs(glass[:, 0]) < 0.82) & (glass[:, 2] > 0.95)] if len(glass) else glass
    if len(glass) > 3:
        outline = hull2d([(round(p_[1], 4), round(p_[2], 4)) for p_ in glass])
        cy_, cz_ = np.mean([p_[0] for p_ in outline]), np.mean([p_[1] for p_ in outline])
        loop = []
        for y_, z_ in outline:
            if z_ < 1.005:
                continue                        # the belt line has its own sill ledge
            near = glass[np.argmin((glass[:, 1] - y_) ** 2 + (glass[:, 2] - z_) ** 2)]
            d_ = Vector((0, y_ - cy_, z_ - cz_)).normalized()
            gx = abs(near[0]) - 0.007
            loop.append((Vector((sgn * gx, y_, z_)) + d_ * 0.010, Vector((sgn * (gx - 0.004), y_, z_)) - d_ * 0.022))
        # the hull runs round the glass; order the frame from one end of the belt line to the other
        k0 = max(range(len(loop)), key=lambda k: (loop[k][0] - loop[k - 1][0]).length)
        loop = loop[k0:] + loop[:k0]
        verts, faces = [], []
        for (a0, b0), (a1, b1) in zip(loop, loop[1:]):
            base = len(verts)
            verts.extend([a0, a1, b1, b0])
            faces.append((base, base + 1, base + 2, base + 3))
        sheet(f"{door.name}_Glass_Run_Channel", verts, faces, rubber, 0.004, parent=door)

    # fabric insert across the middle of the card, with a satin trim line along its top

    zi = np.linspace(0.71, 0.86, 5)
    ins = {}
    for i, y in enumerate(ys[3:-3]):
        for j, z in enumerate(zi):
            cx = card_x(y, z, 0.004)
            ins[i, j] = Vector((sgn * cx, y, z)) if cx is not None else None
    grid_sheet(f"{door.name}_Card_Insert", ins, len(ys) - 6, len(zi), door_fabric, sgn, 0.004, door)
    trim_line = {}
    for i, y in enumerate(ys[2:-2]):
        for j, z in enumerate((0.872, 0.884)):
            cx = card_x(y, z, 0.005)
            trim_line[i, j] = Vector((sgn * cx, y, z)) if cx is not None else None
    grid_sheet(f"{door.name}_Card_Trim_Line", trim_line, len(ys) - 4, 2, accent, sgn, 0.003, door)

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
    # reflector at the bottom rear corner of the card, where the card actually is at that height
    rz = FLOOR_Z + 0.08
    sp = row_span(rz)
    if sp is not None:
        door_child(box(f"{door.name}_Reflector", (0.006, 0.07, 0.02), at(sp[1] - 0.045, rz, 0.004),
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

# Lid shut faces: painted returns from the liners out to the skin edge along both sides, the front
# edge and the bottom of the rear face, so the lid reads as a pressed shell when it is up.
paint_mat = bpy.data.materials["NYC_Taxi_Yellow_Paint"]


def lid_top(x, y):
    h = lid_bvh.ray_cast(Vector((x, y, 1.5)), -Z, 0.6)[0]
    return h


lv, lf = [], []


def lid_quad(a, b, c, d):
    base = len(lv)
    lv.extend([a, b, c, d])
    lf.append((base, base + 1, base + 2, base + 3))


side_rows = []
for y in np.linspace(1.97, 2.25, 11):
    row = []
    for s_ in (1, -1):
        liner = lid_bvh.ray_cast(Vector((s_ * 0.56, y, 0.85)), Z, 0.5)[0]
        xe = None
        for x in np.arange(0.56, 0.70, 0.004):
            if lid_top(s_ * x, y) is None:
                break
            xe = x
        if liner is None or xe is None:
            row.append(None)
            continue
        top = lid_top(s_ * xe, y)
        row.append((liner - Z * 0.018, Vector((s_ * xe, y, top.z - 0.003))))
    side_rows.append(row)
for a, b in zip(side_rows, side_rows[1:]):
    for k in (0, 1):
        if a[k] and b[k]:
            lid_quad(a[k][0], b[k][0], b[k][1], a[k][1])
front = []
for x in np.linspace(-0.54, 0.54, 19):
    liner = lid_bvh.ray_cast(Vector((x, 1.97, 0.85)), Z, 0.5)[0]
    ye = None
    for y in np.arange(1.97, 1.88, -0.004):
        if lid_top(x, y) is None:
            break
        ye = y
    if liner is not None and ye is not None:
        top = lid_top(x, ye)
        front.append((liner - Z * 0.018, Vector((x, ye, top.z - 0.003))))
for (c0, s0), (c1, s1) in zip(front, front[1:]):
    lid_quad(c0, c1, s1, s0)
# body-side weatherstrip along both sides of the lid opening, just under the lid's edge
for k, tag in ((0, "L"), (1, "R")):
    pts = [r[k][1] for r in side_rows if r[k]]
    verts, faces = [], []
    for a, b in zip(pts, pts[1:]):
        sa, sb = (1 if a.x > 0 else -1), (1 if b.x > 0 else -1)
        base = len(verts)
        verts.extend([Vector((sa * (abs(a.x) + 0.006), a.y, a.z - 0.010)), Vector((sb * (abs(b.x) + 0.006), b.y, b.z - 0.010)),
                      Vector((sb * (abs(b.x) - 0.024), b.y, b.z - 0.022)), Vector((sa * (abs(a.x) - 0.024), a.y, a.z - 0.022))])
        faces.append((base, base + 1, base + 2, base + 3))
    me_s = bpy.data.meshes.new(f"Trunk_Side_Seal_{tag}")
    me_s.from_pydata([v[:] for v in verts], [], faces)
    me_s.materials.append(rubber)
    add(bpy.data.objects.new(me_s.name, me_s))

me = bpy.data.meshes.new("Trunk_Lid_Shut_Face")
me.from_pydata([v[:] for v in lv], [], lf)
me.materials.append(paint_mat)
add(bpy.data.objects.new(me.name, me), lid)

# gooseneck hinge arms under the front of the lid (they turn with it)
for x in (-0.46, 0.46):
    t = lid_top(x, 2.02)
    zt = (t.z if t is not None else 1.12) - 0.03
    for k, (y0, z0, y1, z1) in enumerate(((2.06, zt, 1.97, zt - 0.015), (1.97, zt - 0.015, 1.915, zt - 0.06))):
        ob = strap(f"Trunk_Hinge_{'L' if x > 0 else 'R'}_{k}", (x, y0, z0), (x, y1, z1), 0.025, steel,
                   thick=0.008, face=Vector((1, 0, 0)))
        ob.parent = lid
        ob.matrix_parent_inverse = lid.matrix_world.inverted()

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
        # the gutter tucks under the inboard edge of the quarter panel, at the bottom of the groove
        # that forms the shut line, so it can't show with the lid down
        xo, zg = 0.70, 0.97
        for x in np.arange(0.60, 0.72, 0.003):
            hit = body_bvh.ray_cast(Vector((s_ * x, y, 1.4)), -Z, 0.6)[0]
            if hit is not None and hit.z > 0.9:
                xo, zg = x + 0.004, hit.z - 0.014
                break
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
        xo = min(abs(hit.x) - 0.006, 0.665) if hit is not None else 0.66
        left.append((s_ * (TX - 0.005), yb, z))
        right.append((s_ * xo, yb, z))
    pts = left + right
    n_ = len(left)
    faces = [(i, n_ + i, n_ + i + 1, i + 1) if s_ > 0 else (i, i + 1, n_ + i + 1, n_ + i) for i in range(n_ - 1)]
    sheet(f"Trunk_Lamp_Housing_Back_{tag}", pts, faces, black_plastic, 0.006)
# Tail lamp end caps. The lid carries the inner lamps and the quarter panels the outer ones; the
# source modelled each pair as one lamp, so both halves are open where they meet. Each gets a dark
# housing wall there: the convex outline of the lamp's cross-section just inside the split.
LAMP_SPLIT = 0.625


def section_yz(bms, x, y_min):
    pts = []
    for bm_ in bms:
        for e in bm_.edges:
            a, b = e.verts[0].co, e.verts[1].co
            if (a.x - x) * (b.x - x) >= 0:
                continue
            p = a.lerp(b, (x - a.x) / (b.x - a.x))
            if p.y >= y_min and 0.815 <= p.z <= 0.985:
                pts.append((p.y, p.z))
    return pts


bm_lamps = bmesh.new()
for n in ("Cemel_Trim_Interior", "Cemel_Glass_Lamps", "Cemel_Lamp_Lenses", "Cemel_Wheels_Chassis"):
    bm_lamps.from_mesh(bpy.data.objects[n].data)
for s_, tag in ((1, "L"), (-1, "R")):
    for owner, x_cut, x_cap, y_min, parent in (("Lid", LAMP_SPLIT - 0.006, LAMP_SPLIT - 0.003, 2.24, lid),
                                               ("Body", LAMP_SPLIT + 0.006, LAMP_SPLIT + 0.003, 2.15, None)):
        bm_src = bm_lid if owner == "Lid" else bm_lamps
        outline = hull2d(section_yz([bm_src], s_ * x_cut, y_min))
        if len(outline) < 3:
            continue
        cy = sum(p[0] for p in outline) / len(outline)
        cz = sum(p[1] for p in outline) / len(outline)
        pts = [(s_ * x_cap, cy + (y - cy) * 0.97, cz + (z - cz) * 0.97) for y, z in outline]
        sheet(f"Tail_Lamp_End_Cap_{owner}_{tag}", pts, [tuple(range(len(pts)))], black_plastic, 0.004,
              parent=parent)
bm_lamps.free()

# rear sill under the lid's bottom edge and the front jamb under the rear window, each with a seal
box("Trunk_Rear_Sill", (1.10, 0.09, 0.008), (0, 2.285, 0.668), paint, bevel=0.002)
box("Trunk_Rear_Seal", (1.08, 0.018, 0.018), (0, 2.30, 0.68), rubber, bevel=0.006)
fz = lid_bvh.ray_cast(Vector((0, 1.93, 0.9)), Z, 0.5)[0]
fz = (fz.z if fz is not None else 1.10) - 0.03
box("Trunk_Front_Jamb", (1.20, 0.08, 0.008), (0, 1.90, fz), paint, bevel=0.002)
box("Trunk_Front_Seal", (1.18, 0.018, 0.018), (0, 1.925, fz + 0.01), rubber, bevel=0.006)
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
    p.x = max(-0.775, min(0.775, p.x))    # never past the door cards (below them the ray reaches the skin)
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
