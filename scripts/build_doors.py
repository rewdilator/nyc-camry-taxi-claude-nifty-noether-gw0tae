"""Cut the four doors and the trunk lid out of the car meshes so each one opens on its own hinge.

    python3 scripts/build_doors.py      # (bpy) edits NYC_Taxi_Cemel_2020.blend in place

Run it once, after rebrand_cemel.py and before build_interior.py. It refuses to run twice.

The source model merges each material into one mesh, so a door is scattered over the paint, trim,
glass and chassis meshes. Every loose part (a connected piece of a mesh) that fits inside a door's
volume moves to that door whole. Parts that span two doors, such as the window frame strips, are
cut face by face at the shut line between the doors.

Below the window sill the source's door trim is a low-poly side wall shared with the pillars; it is
deleted inside the doors and build_interior.py builds real door cards. Above the sill the trim is the
A-pillar, roof-rail and B-pillar trim, which stays on the body; the doors keep their black sashes.

Each opening part becomes an object whose origin is on its hinge axis:
    Door_FL, Door_FR, Door_RL, Door_RR   rotate about their local Z axis (hinge line)
    Trunk_Lid                            rotates about its local X axis
A Limit Rotation constraint keeps them between closed (0) and fully open. Each also gets an
"<name>_Open" action (closed -> open over 30 frames) that exports to glTF as a separate animation.
"""
import math
import os

import bpy  # noqa: I001  (bpy must be imported before bmesh when run as a module)
import bmesh
import numpy as np
from mathutils import Matrix, Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLEND = os.path.join(ROOT, "NYC_Taxi_Cemel_2020.blend")
GLB = os.path.join(ROOT, "NYC_Taxi_Cemel_2020.glb")

if bpy.data.filepath != BLEND:
    bpy.ops.wm.open_mainfile(filepath=BLEND)
if "Door_FL" in bpy.data.objects:
    raise SystemExit("Doors are already split in %s; nothing to do." % BLEND)

scene = bpy.context.scene
root = bpy.data.objects["NYC_Taxi_Cemel_2020"]
car_col = bpy.data.collections["Car"]
SOURCES = ["Cemel_Body_Paint", "Cemel_Trim_Interior", "Cemel_Wheels_Chassis", "Cemel_Glass_Lamps",
           "Cemel_Lamp_Lenses"]

# ---------------------------------------------------------------------------
# 1. Opening volumes (car axes: -Y forward, +X = left/driver's side)
# ---------------------------------------------------------------------------
SHUT_Y = 0.19            # shut line between front and rear doors
DOOR_Y = {"F": (-1.075, SHUT_Y), "R": (SHUT_Y, 1.285)}
DOOR_Z = (0.24, 1.41)    # sill top to just under the roof rail
TRUNK = dict(y=(1.90, 2.45), z=(0.665, 1.20), x=0.668, top_z=0.975, rear_y=2.24, lamp_z=0.83, lower_x=0.57)
TOL = 0.012


def door_inner_x(z):
    """Inboard limit of the door: the door card at the waist, the glass line up to the roof rail."""
    return 0.66 if z < 0.98 else 0.66 - (z - 0.98) * (0.66 - 0.565) / (1.41 - 0.98)


PROFILE = {}   # "F"/"R" -> (z bins, y edge per bin, top of skin); filled from the door skins below


def edge_y(fr, z):
    """Free edge of a door at height z: front edge of the front door, rear edge of the rear door.
    Below the waist it follows the door skin (the rear door's cut-out around the wheel arch);
    above it, the window frame: the A-pillar line in front, the quarter-window slope at the back."""
    zs, ys, top = PROFILE[fr]
    # near the top of a skin its cross-section gets short, so the window frame takes over there
    if fr == "F":
        if z <= 0.85:
            return float(np.interp(z, zs, ys))
        # A-pillar: the door frame runs up and back just ahead of the door glass (measured front
        # edge of the glass: y -0.86 at z 1.10, slope 1.82); the A-pillar trim ahead of it is body
        return max(DOOR_Y["F"][0], -0.88 + (z - 1.10) * 1.82)
    if z <= 0.95:
        return float(np.interp(z, zs, ys))
    return min(float(ys.max()), 1.285 - (z - 1.10) * 1.083)   # quarter-window frame slope


def door_mask(co, fr, loose=False):
    """Which points (N x 3, all on one side of the car) lie inside door `fr` ("F" or "R")."""
    t = TOL if loose else 0.0
    x, y, z = np.abs(co[:, 0]), co[:, 1], co[:, 2]
    inner = np.where(z < 0.98, 0.66, 0.66 - (z - 0.98) * (0.66 - 0.565) / (1.41 - 0.98))
    ok = (z >= DOOR_Z[0] - t) & (z <= DOOR_Z[1] + t) & (x >= inner - t)
    edge = np.array([edge_y(fr, zz) for zz in z])
    if fr == "F":
        # the front door's frame carries the black B-pillar applique, which reaches past the shut line
        return ok & (y >= edge - 0.015 - t) & (y <= SHUT_Y + (0.10 if loose else 0.0))
    return ok & (y >= SHUT_Y - (0.04 if loose else 0.0)) & (y <= edge + 0.012 + t)


def door_of_point(p, loose=False):
    co = np.array([p[:]])
    side = "L" if p[0] > 0 else "R"
    for fr in ("F", "R"):
        if door_mask(co, fr, loose)[0]:
            return fr + side
    return None


def in_trunk(p, loose=False):
    """The lid is a shell: its top skin (from the hinge line back) and its rear face (down to the
    plate). Anything lower under the top skin (hinge-area trim, lamp tops) is body."""
    t = TOL if loose else 0
    x, y, z = p
    # below the lid lamps the lid is only as wide as the plate area; the panels beside it, under
    # the body-side tail lamps, are body
    half_w = TRUNK["x"] if z >= TRUNK["lamp_z"] else TRUNK["lower_x"]
    if abs(x) > half_w + t or y > TRUNK["y"][1] + t or z > TRUNK["z"][1] + t:
        return False
    top_skin = y >= TRUNK["y"][0] - t and z >= TRUNK["top_z"] - t
    rear_face = y >= TRUNK["rear_y"] - t and z >= TRUNK["z"][0] - t
    return top_skin or rear_face


WHEELS = [(-1.44, 0.33), (1.36, 0.33)]   # (y, z) of the wheel centres


def near_wheel(co):
    """Rims, tyres and arch liners come within 0.3 m of a wheel centre; door skins never do."""
    return min(np.hypot(co[:, 1] - wy, co[:, 2] - wz).min() for wy, wz in WHEELS) < 0.30


def a_pillar_strip(co):
    """Black strips, trim and glass edge running up the A-pillar, inboard of the front door's chrome
    frame. They follow the door's leading edge in the side view but belong to the pillar: on the
    door they would swing out as loose rods."""
    ax = np.abs(co[:, 0])
    if co[:, 2].min() < 0.95 or co[:, 2].max() - co[:, 2].min() < 0.15 or ax.max() > 0.78 or ax.min() < 0.5:
        return False
    line = np.array([edge_y("F", z) for z in co[:, 2]])
    return bool((np.abs(co[:, 1] - line) < 0.10).all())


def part_owner(co):
    """Owner that holds every vertex of a loose part, else None."""
    mn, mx = co.min(0), co.max(0)
    corners = [(a, b, c) for a in (mn[0], mx[0]) for b in (mn[1], mx[1]) for c in (mn[2], mx[2])]
    if all(in_trunk(c, loose=True) for c in corners):
        return "Trunk"
    if mn[0] < 0 < mx[0] or near_wheel(co):
        return None
    side = "L" if mn[0] > 0 else "R"
    if a_pillar_strip(co):
        return None
    for fr in ("F", "R"):
        if door_mask(co, fr, loose=True).all():
            return fr + side
    return None


def split_candidate(src_name, co):
    """Parts cut face by face: one-sided strips and trim panels running through the door band.
    Parts reaching the ground (wheels, arch liners, underbody) and parts crossing the car's centre
    line (dash, floor tub, headliner) are never cut, nor is anything in the paint shell."""
    mn, mx = co.min(0), co.max(0)
    if mn[0] < 0 < mx[0] or mn[2] < 0.2 or a_pillar_strip(co):
        return False
    if max(abs(mn[0]), abs(mx[0])) < 0.66:
        return False
    if mx[1] < DOOR_Y["F"][0] or mn[1] > DOOR_Y["R"][1]:
        return False
    # The paint shell is already split into panels (door skins, mirrors, handles are whole parts).
    # Its long strips above the doors are the roof-side rails, which belong to the body.
    return src_name != "Cemel_Body_Paint"


# ---------------------------------------------------------------------------
# 2. Split every source mesh into body / door / trunk pieces
# ---------------------------------------------------------------------------
OWNERS = ["FL", "FR", "RL", "RR", "Trunk"]
pieces = {o: [] for o in OWNERS}      # owner -> list of new mesh objects


def loose_parts(bm):
    bm.verts.ensure_lookup_table()
    seen, parts = set(), []
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
        parts.append(comp)
    return parts


def door_profiles():
    """Edge of each door skin per 1 cm of height (left side; the car is symmetric)."""
    bm = bmesh.new()
    bm.from_mesh(bpy.data.objects["Cemel_Body_Paint"].data)
    skins = {}
    for comp in loose_parts(bm):
        co = np.array([v.co[:] for v in comp])
        mn, mx = co.min(0), co.max(0)
        if mn[0] < 0.7 or mx[2] - mn[2] < 0.6:
            continue
        for fr, (y0, y1) in DOOR_Y.items():
            if mn[1] > y0 - 0.05 and mx[1] < y1 + 0.05 and (fr not in skins or len(co) > len(skins[fr][0])):
                edges = {e for v in comp for e in v.link_edges}
                seg = np.array([(e.verts[0].co[1], e.verts[0].co[2], e.verts[1].co[1], e.verts[1].co[2])
                                for e in edges])
                skins[fr] = (co, seg)
    bm.free()
    for fr, (co, seg) in skins.items():
        # exact cross-section of the skin at each height: where its edges cross the plane z = const
        zs = np.arange(co[:, 2].min(), co[:, 2].max() + 0.005, 0.005)
        y1, z1, y2, z2 = seg.T
        ys = []
        for z in zs:
            m = (np.minimum(z1, z2) <= z) & (np.maximum(z1, z2) >= z) & (z1 != z2)
            t = (z - z1[m]) / (z2[m] - z1[m])
            yy = np.concatenate([y1[m] + t * (y2[m] - y1[m]), co[np.abs(co[:, 2] - z) < 0.004, 1]])
            ys.append(np.nan if not len(yy) else (yy.min() if fr == "F" else yy.max()))
        ys = np.array(ys)
        good = ~np.isnan(ys)
        ys = np.interp(zs, zs[good], ys[good])
        PROFILE[fr] = (zs, ys, co[:, 2].max())
        print("door skin %s: z %.3f..%.3f, edge y %.3f..%.3f" % (fr, zs[0], zs[-1], ys.min(), ys.max()))


door_profiles()


def cut_planes():
    """Planes along every door boundary, so no face straddles one after cutting."""
    planes = [((0, y, 0), (0, 1, 0)) for y in (DOOR_Y["F"][0], SHUT_Y, DOOR_Y["R"][1])]
    planes += [((0, 0, z), (0, 0, 1)) for z in DOOR_Z]
    for s_ in (1, -1):
        planes.append(((s_ * 0.66, 0, 0), (1, 0, 0)))
        planes.append(((s_ * 0.66, 0, 0.98), (0.43, 0, s_ * (0.66 - 0.565))))
    # the free edge of each door as a polyline in the side view (planes contain the X axis)
    for fr, margin in (("F", -0.015), ("R", 0.012)):
        zs = np.linspace(DOOR_Z[0], DOOR_Z[1], 25)
        ys = [edge_y(fr, z) + margin for z in zs]
        for i in range(len(zs) - 1):
            dy, dz = ys[i + 1] - ys[i], zs[i + 1] - zs[i]
            planes.append(((0, ys[i], zs[i]), (0, dz, -dy)))
    return planes


def adopt_lid_flanks(comps, owners):
    """The paint shell models the lid's shut line as a groove, with the lid panels on one side and
    the quarter panels on the other. The lid's curved side flanks reach into the groove, past the
    lid's nominal width, so the width test leaves them on the body. Any paint panel on the rear deck
    that is stitched mostly to lid panels (and hardly to the body's) is part of the lid."""
    def rim(comp):
        return np.array([v.co[:] for v in comp if v.is_boundary]).reshape(-1, 3)
    lid_rim = np.concatenate([rim(c) for c, o in zip(comps, owners) if o == "Trunk"])
    for i, (comp, owner) in enumerate(zip(comps, owners)):
        co = np.array([v.co[:] for v in comp])
        mn, mx = co.min(0), co.max(0)
        if owner or mn[0] < -0.72 or mx[0] > 0.72 or mn[1] < TRUNK["y"][0] or mn[2] < 0.95:
            continue
        r = rim(comp)
        if not len(r):
            continue
        d_lid = np.array([np.abs(lid_rim - p).sum(1).min() for p in r])
        if (d_lid < 0.003).mean() > 0.3:
            owners[i] = "Trunk"
            print("lid flank adopted: x %.3f..%.3f y %.3f..%.3f" % (mn[0], mx[0], mn[1], mx[1]))


LAMP_SPLIT = 0.625       # |x| where the lid's inner tail lamps meet the quarter panels' outer ones
LAMP_BACK = 2.20         # lamp housing further forward than this is inside the trunk, on the body
LAMP_CUT = 96


def lamp_zone(mn, mx):
    """Tail lamp glass, lenses, bulbs and housings on one side of the car."""
    ax0, ax1 = (mn[0], mx[0]) if mn[0] > 0 else (-mx[0], -mn[0])
    return ax0 > 0.2 and mx[1] > 2.1 and mn[1] > 1.7 and mn[2] > 0.78 and mx[2] < 1.0


def lamp_side(src_name, co):
    """"lid", "body" or "delete" for a lamp part, or "cut" for a housing running through both lamps. The
    source already splits the lamp glass and lenses where the lid meets the quarter panel, so those
    go whole (by where most of the part is); only the housings behind them are cut."""
    ax = np.abs(co[:, 0])
    if ax.min() >= LAMP_SPLIT - 0.03:
        return "body"
    if ax.max() <= LAMP_SPLIT + 0.01:
        if co[:, 1].min() >= LAMP_BACK:
            return "lid"
        if co[:, 1].max() < LAMP_BACK and src_name not in ("Cemel_Glass_Lamps", "Cemel_Lamp_Lenses"):
            return "delete"
    if src_name in ("Cemel_Glass_Lamps", "Cemel_Lamp_Lenses"):
        return "lid" if np.median(ax) < LAMP_SPLIT and co[:, 1].min() >= LAMP_BACK else "body"
    return "cut"


CODE = {o: i + 1 for i, o in enumerate(OWNERS)}      # 0 = stays on the body
CANDIDATE = 99
DELETE = 97
SILL_Z = 0.97             # door trim below the window sill is rebuilt as a proper door card
B_PILLAR = (0.12, 0.27)   # inner B-pillar trim between the doors stays on the body
BELT_TOP = 1.06           # the sill garnish along the door's belt line goes too (the card has its own)
report = {}
for src_name in SOURCES:
    src = bpy.data.objects[src_name]
    bm = bmesh.new()
    bm.from_mesh(src.data)
    tag = bm.faces.layers.int.new("opening")
    cand_faces = set()
    comps = loose_parts(bm)
    owners = [part_owner(np.array([v.co[:] for v in comp])) for comp in comps]
    if src_name == "Cemel_Body_Paint":
        adopt_lid_flanks(comps, owners)
    lamp_faces = set()
    for comp, owner in zip(comps, owners):
        co = np.array([v.co[:] for v in comp])
        mn, mx = co.min(0), co.max(0)
        faces = {f for v in comp for f in v.link_faces}
        if owner and owner != "Trunk" and src_name == "Cemel_Trim_Interior" and mx[2] < SILL_Z:
            for f in faces:
                f[tag] = DELETE          # original door-card pieces: replaced by a door card
        elif src_name != "Cemel_Body_Paint" and lamp_zone(mn, mx):
            # tail lamps: the lid carries the inner lamps, the quarter panels the outer ones
            side = lamp_side(src_name, co)
            if side == "cut":
                for f in faces:
                    f[tag] = LAMP_CUT
                lamp_faces |= faces
            else:
                for f in faces:
                    f[tag] = {"lid": CODE["Trunk"], "delete": DELETE}.get(side, 0)
        elif owner:
            for f in faces:
                f[tag] = CODE[owner]
        elif not near_wheel(co) and split_candidate(src_name, co):
            for f in faces:
                f[tag] = CANDIDATE
            cand_faces |= faces
    if cand_faces:
        geom = list(cand_faces) + list({e for f in cand_faces for e in f.edges}) + \
            list({v for f in cand_faces for v in f.verts})
        for co_, no_ in cut_planes():
            res = bmesh.ops.bisect_plane(bm, geom=geom, plane_co=co_, plane_no=Vector(no_).normalized(),
                                         dist=1e-5)
            geom = [g for g in res["geom"] if g.is_valid]
        for f in bm.faces:
            if f[tag] == CANDIDATE:
                o = door_of_point(f.calc_center_median())
                c = f.calc_center_median()
                if o and src_name == "Cemel_Trim_Interior":
                    # below the sill: low-poly side wall, replaced by a door card; above it: A-pillar,
                    # roof-rail and B-pillar trim inside the glass line, which stays on the body
                    in_b_pillar = B_PILLAR[0] < c.y < B_PILLAR[1]
                    belt = c.z < BELT_TOP and abs(c.x) > 0.70     # the source's window-sill garnish
                    f[tag] = DELETE if (c.z < SILL_Z or belt) and not in_b_pillar else 0
                else:
                    f[tag] = CODE[o] if o else 0
    if lamp_faces:
        geom = list(lamp_faces) + list({e for f in lamp_faces for e in f.edges}) + \
            list({v for f in lamp_faces for v in f.verts})
        for co_, no_ in [((LAMP_SPLIT, 0, 0), (1, 0, 0)), ((-LAMP_SPLIT, 0, 0), (1, 0, 0)),
                         ((0, LAMP_BACK, 0), (0, 1, 0))]:
            res = bmesh.ops.bisect_plane(bm, geom=geom, plane_co=co_, plane_no=no_, dist=1e-5)
            geom = [g for g in res["geom"] if g.is_valid]
        for f in bm.faces:
            if f[tag] == LAMP_CUT:
                c = f.calc_center_median()
                # behind the lid's lamps, the housings' forward flanges would stick into the trunk
                # opening as shelves; the trunk trim built in build_interior.py covers that corner
                f[tag] = 0 if abs(c.x) >= LAMP_SPLIT else CODE["Trunk"] if c.y > LAMP_BACK else DELETE
    counts = {o: sum(1 for f in bm.faces if f[tag] == CODE[o]) for o in OWNERS}
    report[src_name] = counts
    bm.to_mesh(src.data)
    bm.free()

    for owner in OWNERS:
        if not counts[owner]:
            continue
        me = src.data.copy()
        me.name = f"{owner}_{src_name}"
        bm = bmesh.new()
        bm.from_mesh(me)
        tag = bm.faces.layers.int["opening"]
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if f[tag] != CODE[owner]], context="FACES")
        bm.faces.layers.int.remove(tag)
        bm.to_mesh(me)
        bm.free()
        pieces[owner].append(bpy.data.objects.new(me.name, me))
    bm = bmesh.new()
    bm.from_mesh(src.data)
    tag = bm.faces.layers.int["opening"]
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f[tag] != 0], context="FACES")   # incl. DELETE
    bm.faces.layers.int.remove(tag)
    bm.to_mesh(src.data)
    bm.free()

for k, v in report.items():
    print(k, v)

# ---------------------------------------------------------------------------
# 3. One object per opening, origin on the hinge
# ---------------------------------------------------------------------------
open_col = bpy.data.collections.new("Doors_Trunk")
bpy.data.collections["NYC_Taxi_Cemel_2020"].children.link(open_col)
NAMES = {"FL": "Door_FL", "FR": "Door_FR", "RL": "Door_RL", "RR": "Door_RR", "Trunk": "Trunk_Lid"}
OPEN_DEG = {"F": 65.0, "R": 70.0, "Trunk": 72.0}


def join(owner):
    obs = pieces[owner]
    for o in obs:
        open_col.objects.link(o)
    with bpy.context.temp_override(active_object=obs[0], selected_editable_objects=obs,
                                   selected_objects=obs):
        bpy.ops.object.join()
    ob = obs[0]
    ob.name = ob.data.name = NAMES[owner]
    return ob


def world_verts(ob):
    return np.array([v.co[:] for v in ob.data.vertices])


def skin_verts(owner):
    """Painted outer skin of an opening. For doors, only below the waist: the painted window
    frame above it sits further inboard and would pull the hinge line into the cabin."""
    me = [o for o in pieces[owner] if o.name.endswith("Cemel_Body_Paint")][0].data
    co = np.array([v.co[:] for v in me.vertices])
    return co if owner == "Trunk" else co[(co[:, 2] < 0.95) & (np.abs(co[:, 0]) > 0.74)]


hinges = {}
for owner in ("FL", "FR", "RL", "RR"):
    sk = skin_verts(owner)
    sign = 1 if owner[1] == "L" else -1
    y0 = sk[:, 1].min()
    front = sk[sk[:, 1] < y0 + 0.05]
    # hinge line: 2 cm behind the leading edge, 1.5 cm inside the skin, at mid door height
    hinges[owner] = Vector((sign * (np.abs(front[:, 0]).mean() - 0.015), y0 + 0.02,
                            (front[:, 2].min() + front[:, 2].max()) / 2))
lid = skin_verts("Trunk")
top = lid[lid[:, 2] > 1.05]
hinges["Trunk"] = Vector((0.0, top[:, 1].min() - 0.02, top[:, 2][top[:, 1] < top[:, 1].min() + 0.03].mean() - 0.02))

openings = {}
for owner in OWNERS:
    ob = join(owner)
    pivot = hinges[owner]
    ob.data.transform(Matrix.Translation(-pivot))
    ob.location = pivot
    ob.parent = root
    ob.matrix_parent_inverse = root.matrix_world.inverted()
    openings[owner] = ob

bpy.context.view_layer.update()     # hinge objects' world matrices are needed for parenting below

# decals, plate and bracket that sit on a moving panel follow it
FOLLOW = {
    "Decal_Logo_FrontDoor_L": "FL", "Decal_Logo_FrontDoor_R": "FR",
    "Decal_RateOfFare_RearDoor_L": "RL", "Decal_RateOfFare_RearDoor_R": "RR",
    "Decal_Medallion_Trunk": "Trunk", "Decal_Logo_Trunk": "Trunk",
    "Plate_Rear": "Trunk", "Plate_Bracket_Rear": "Trunk",
}
for name, owner in FOLLOW.items():
    ob = bpy.data.objects[name]
    ob.parent = openings[owner]
    ob.matrix_parent_inverse = openings[owner].matrix_world.inverted()

# ---------------------------------------------------------------------------
# 4. Hinges: an "open" slider (0 = shut, 1 = fully open) drives the hinge angle in Blender, and an
#    "<name>_Open" action on a muted NLA track exports to glTF as that part's own animation.
# ---------------------------------------------------------------------------
for owner, ob in openings.items():
    if owner == "Trunk":
        axis, angle = 0, math.radians(OPEN_DEG["Trunk"])           # lid swings up about X
    else:
        axis = 2
        angle = math.radians(OPEN_DEG[owner[0]]) * (-1 if owner[1] == "L" else 1)  # rear edge swings out
    ob.lock_rotation = [True, True, True]
    ob.lock_location = (True, True, True)
    ob["open"] = 0.0
    ui = ob.id_properties_ui("open")
    ui.update(min=0.0, max=1.0, soft_min=0.0, soft_max=1.0, step=5,
              description="0 = shut, 1 = fully open")
    ob["open_axis"] = "XYZ"[axis]
    ob["open_angle_deg"] = round(math.degrees(angle), 1)

    ob.rotation_euler = (0, 0, 0)
    ob.keyframe_insert("rotation_euler", index=axis, frame=1)
    ob.rotation_euler[axis] = angle
    ob.keyframe_insert("rotation_euler", index=axis, frame=30)
    ob.rotation_euler[axis] = 0.0
    act = ob.animation_data.action
    act.name = f"{ob.name}_Open"
    act.use_fake_user = True
    track = ob.animation_data.nla_tracks.new()
    track.name = act.name
    track.strips.new(act.name, 1, act)
    track.mute = True                  # kept for export only; the driver below poses the part
    ob.animation_data.action = None

    fc = ob.driver_add("rotation_euler", axis)
    drv = fc.driver
    drv.type = "SCRIPTED"
    var = drv.variables.new()
    var.name = "open"
    var.targets[0].id = ob
    var.targets[0].data_path = '["open"]'
    drv.expression = "min(max(open, 0), 1) * %.6f" % angle
scene.frame_start, scene.frame_end = 1, 30
scene.frame_set(1)

for owner, ob in openings.items():
    print("%-9s hinge %s  open %s %.0f deg  verts %d" % (ob.name, tuple(round(c, 3) for c in hinges[owner]),
          ob["open_axis"], ob["open_angle_deg"], len(ob.data.vertices)))

bpy.ops.wm.save_as_mainfile(filepath=BLEND, compress=True)
if os.path.exists(BLEND + "1"):
    os.remove(BLEND + "1")
print("Saved", BLEND)
