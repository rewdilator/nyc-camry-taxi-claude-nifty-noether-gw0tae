"""Turn the Sketchfab "Toyota Camry 2020" scene into a real-world-scale NYC yellow cab, the Cemel.

    python3 scripts/make_textures.py        # (Pillow) livery textures -> textures/
    python3 scripts/build_taxi.py           # (bpy)    Untitled.blend -> NYC_Taxi_Cemel_2020.blend
    python3 scripts/rebrand_cemel.py        # (bpy)    Cemel badge on the trunk
    python3 scripts/build_doors.py          # (bpy)    doors and trunk lid on hinges
    python3 scripts/build_interior.py       # (bpy)    NYC taxi interior

Can also be run inside Blender:  blender -b Untitled.blend -P scripts/build_taxi.py
"""
import math
import os

import bpy  # noqa: I001  (bpy must be imported before bmesh when run as a module)
import bmesh
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "Untitled.blend")
DST = os.path.join(ROOT, "NYC_Taxi_Cemel_2020.blend")
TEX = os.path.join(ROOT, "textures")

# Real-world length of the source car (a 2020 mid-size sedan, LE trim): 4,879 mm.
REAL_LENGTH_M = 4.879

# NYC taxi yellow (Dupont M6284-style), sRGB 247/181/0.
TAXI_YELLOW_SRGB = (247, 181, 0)


def srgb_to_linear(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


TAXI_YELLOW = tuple(srgb_to_linear(c) for c in TAXI_YELLOW_SRGB) + (1.0,)

if bpy.data.filepath != SRC:
    bpy.ops.wm.open_mainfile(filepath=SRC)
scene = bpy.context.scene

# ---------------------------------------------------------------------------
# 1. Flatten the glTF/Sketchfab hierarchy and scale to real-world metres
# ---------------------------------------------------------------------------
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
pts = np.array([(o.matrix_world @ v.co)[:] for o in meshes for v in o.data.vertices])
mn, mx = pts.min(0), pts.max(0)
scale = REAL_LENGTH_M / (mx[1] - mn[1])
to_world = Matrix.Scale(scale, 4) @ Matrix.Translation(
    (-(mn[0] + mx[0]) / 2, -(mn[1] + mx[1]) / 2, -mn[2]))  # centred, tyres on z=0
for o in meshes:
    o.data.transform(to_world @ o.matrix_world)
    o.parent = None
    o.matrix_world = Matrix.Identity(4)
for o in [o for o in bpy.data.objects if o.type == "EMPTY"]:
    bpy.data.objects.remove(o)

RENAME = {
    "Object_13": "Cemel_Body_Paint",
    "Object_5": "Cemel_Trim_Interior",
    "Object_6": "Cemel_Wheels_Chassis",
    "Object_9": "Cemel_Glass_Lamps",
    "Object_11": "Cemel_Lamp_Lenses",
}
for old, new in RENAME.items():
    bpy.data.objects[old].name = new
    bpy.data.objects[new].data.name = new

# The atlas textures of these meshes are stored upside-down relative to their UVs
# (windows sampled the amber lens swatch, tyres the white swatch). Flip V.
for name in ("Cemel_Trim_Interior", "Cemel_Wheels_Chassis", "Cemel_Glass_Lamps", "Cemel_Lamp_Lenses"):
    for uv in bpy.data.objects[name].data.uv_layers:
        a = np.zeros(len(uv.data) * 2)
        uv.data.foreach_get("uv", a)
        a[1::2] = 1.0 - a[1::2]
        uv.data.foreach_set("uv", a)

# Wide EU-style front plate carrying the model author's banner -> replaced by a NY plate.
bpy.data.objects.remove(bpy.data.objects["Object_7"])

body = bpy.data.objects["Cemel_Body_Paint"]

# ---------------------------------------------------------------------------
# 2. Collections / root
# ---------------------------------------------------------------------------
def collection(name, parent=None):
    c = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    if c.name not in (parent or scene.collection).children:
        (parent or scene.collection).children.link(c)
    return c


taxi_col = collection("NYC_Taxi_Cemel_2020")
car_col = collection("Car", taxi_col)
livery_col = collection("Taxi_Livery", taxi_col)
topper_col = collection("Roof_Topper", taxi_col)
plate_col = collection("License_Plates", taxi_col)
studio_col = collection("Studio")

root = bpy.data.objects.new("NYC_Taxi_Cemel_2020", None)
root.empty_display_type = "PLAIN_AXES"
root.empty_display_size = 0.5
taxi_col.objects.link(root)


def move_to(obj, col):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    col.objects.link(obj)
    if obj is not root:
        obj.parent = root


for o in [o for o in bpy.data.objects if o.type == "MESH"]:
    move_to(o, car_col)
ours = {c.name for c in (taxi_col, car_col, livery_col, topper_col, plate_col, studio_col)}
for c in list(bpy.data.collections):
    if c.name not in ours and not c.all_objects:
        bpy.data.collections.remove(c)

# ---------------------------------------------------------------------------
# 3. Materials
# ---------------------------------------------------------------------------
def principled(name, color=(0.8, 0.8, 0.8, 1), rough=0.5, metal=0.0, coat=0.0, image=None,
               alpha_from_image=False, emission=0.0, emission_image=False):
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
    b.inputs["Coat Weight"].default_value = coat
    b.inputs["Coat Roughness"].default_value = 0.03
    if image:
        t = nt.nodes.new("ShaderNodeTexImage")
        t.location = (-400, 0)
        t.image = image
        t.extension = "CLIP"
        t.interpolation = "Cubic"
        nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
        if alpha_from_image:
            nt.links.new(t.outputs["Alpha"], b.inputs["Alpha"])
        if emission_image:
            nt.links.new(t.outputs["Color"], b.inputs["Emission Color"])
    b.inputs["Emission Strength"].default_value = emission
    return m


def load_image(fname):
    img = bpy.data.images.get(fname)
    if img:
        return img
    img = bpy.data.images.load(os.path.join(TEX, fname))
    img.name = fname
    img.alpha_mode = "STRAIGHT"
    img.pack()
    return img


paint = bpy.data.materials["Paint_Color"]
paint.name = "NYC_Taxi_Yellow_Paint"
principled("NYC_Taxi_Yellow_Paint", TAXI_YELLOW, rough=0.28, coat=1.0)
bsdf = paint.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Specular IOR Level"].default_value = 0.5

black_plastic = principled("Taxi_Black_Plastic", (0.012, 0.012, 0.013, 1), rough=0.45)
alu = principled("Taxi_Aluminium", (0.75, 0.75, 0.76, 1), rough=0.3, metal=1.0)

# ---------------------------------------------------------------------------
# 4. Projected decals: a grid is ray-cast onto the paint shell so it hugs the panel
# ---------------------------------------------------------------------------
bm_body = bmesh.new()
bm_body.from_mesh(body.data)
bvh = BVHTree.FromBMesh(bm_body)


def project_decal(name, image_name, center, size, axis, side, up=Vector((0, 0, 1)),
                  offset=0.0018, step=0.008, coat=1.0):
    """center: world point on the decal plane; axis: 'X' for car sides, 'Y' for front/rear.
    side: +1/-1, the side of the car the decal is viewed from."""
    img = load_image(image_name)
    view = Vector((side, 0, 0)) if axis == "X" else Vector((0, side, 0))
    right = up.cross(view).normalized()           # viewer's right, so text reads correctly
    w, h = size
    nu = max(2, int(math.ceil(w / step)) + 1)
    nv = max(2, int(math.ceil(h / step)) + 1)
    verts, uvs, ok = [], [], []
    c = Vector(center)
    for j in range(nv):
        for i in range(nu):
            u, v = i / (nu - 1), j / (nv - 1)
            p = c + right * ((u - 0.5) * w) + up * ((v - 0.5) * h)
            origin = p + view * 2.0
            hit, normal, _, _ = bvh.ray_cast(origin, -view, 4.0)
            if hit is None:
                verts.append(p)
                ok.append(False)
            else:
                if normal.dot(view) < 0:
                    normal = -normal
                verts.append(hit + normal * offset)
                ok.append(True)
            uvs.append((u, v))
    faces = []
    for j in range(nv - 1):
        for i in range(nu - 1):
            a = j * nu + i
            q = (a, a + 1, a + nu + 1, a + nu)
            if all(ok[k] for k in q):
                faces.append(q)
    me = bpy.data.meshes.new(name)
    me.from_pydata([v[:] for v in verts], [], faces)
    uv_layer = me.uv_layers.new(name="UVMap")
    for poly in me.polygons:
        for li in poly.loop_indices:
            uv_layer.data[li].uv = uvs[me.loops[li].vertex_index]
    # drop unused (missed) vertices
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.to_mesh(me)
    bm.free()
    me.shade_smooth()
    mat_name = "Decal_" + os.path.splitext(image_name)[0]
    mat = bpy.data.materials.get(mat_name) or principled(
        mat_name, rough=0.3, coat=coat, image=img, alpha_from_image=True)
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    move_to(ob, livery_col)
    return ob


# Panel positions measured from the paint shell's loose parts: front door
# y -1.04..0.20, rear door y 0.16..1.26, rear quarter y 1.65..2.36, door handles z ~0.85.
for side, tag in ((1, "L"), (-1, "R")):
    x = 0.95 * side
    project_decal(f"Decal_Logo_FrontDoor_{tag}", "decal_nyc_taxi_logo.png",
                  (x, -0.43, 0.62), (0.566, 0.24), "X", side)
    project_decal(f"Decal_RateOfFare_RearDoor_{tag}", "decal_rate_of_fare.png",
                  (x, 0.66, 0.65), (0.46, 0.27), "X", side)
    project_decal(f"Decal_Medallion_RearQuarter_{tag}", "decal_medallion_number.png",
                  (x, 1.90, 0.64), (0.22, 0.085), "X", side)

# Rear: medallion number (required on the rear) + small logo on the trunk's rear face
project_decal("Decal_Medallion_Trunk", "decal_medallion_number.png",
              (-0.34, 2.45, 1.02), (0.17, 0.065), "Y", 1)
project_decal("Decal_Logo_Trunk", "decal_nyc_taxi_logo.png",
              (0.34, 2.45, 1.02), (0.17, 0.072), "Y", 1)

bm_body.free()

# ---------------------------------------------------------------------------
# 5. Geometry helpers
# ---------------------------------------------------------------------------
def all_bvh():
    bm = bmesh.new()
    for o in (bpy.data.objects[n] for n in RENAME.values()):
        bm.from_mesh(o.data)
    return BVHTree.FromBMesh(bm), bm


full_bvh, full_bm = all_bvh()


def surface(origin, direction):
    hit, normal, _, _ = full_bvh.ray_cast(Vector(origin), Vector(direction), 10.0)
    return hit


def box(name, size, loc, mat, bevel=0.0, segments=3, col=None):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    me.materials.append(mat)
    if bevel:
        mod = ob.modifiers.new("Bevel", "BEVEL")
        mod.width = bevel
        mod.segments = segments
        mod.limit_method = "ANGLE"
        me.shade_smooth()
    move_to(ob, col or topper_col)
    return ob


def textured_quad(name, corners, mat, col, uv=((0, 0), (1, 0), (1, 1), (0, 1))):
    """corners in order bottom-left, bottom-right, top-right, top-left as seen by the viewer."""
    me = bpy.data.meshes.new(name)
    me.from_pydata([Vector(c)[:] for c in corners], [], [(0, 1, 2, 3)])
    layer = me.uv_layers.new(name="UVMap")
    for li, t in zip(me.polygons[0].loop_indices, uv):
        layer.data[li].uv = t
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    move_to(ob, col)
    return ob


# ---------------------------------------------------------------------------
# 6. License plates (NY taxi "T...C" plates, 12 x 6 in)
# ---------------------------------------------------------------------------
plate_img = load_image("plate_ny_taxi.png")
plate_mat = principled("NY_Taxi_Plate", rough=0.35, metal=0.3, image=plate_img)
PW, PH = 0.305, 0.152


def plate(tag, z, side):
    # stand off from the most protruding point of the plate area (recess lips, grille bars)
    hits = [surface((x, side * 4.0, z + dz), (0, -side, 0))
            for x in np.linspace(-PW / 2, PW / 2, 7) for dz in np.linspace(-PH / 2, PH / 2, 5)]
    ys = [h.y for h in hits if h is not None]
    y = (max(ys) if side > 0 else min(ys)) + side * 0.012
    view = Vector((0, side, 0))
    right = Vector((0, 0, 1)).cross(view)
    c = Vector((0, y, z))
    bl = c - right * PW / 2 - Vector((0, 0, PH / 2))
    corners = [bl, bl + right * PW, bl + right * PW + Vector((0, 0, PH)), bl + Vector((0, 0, PH))]
    textured_quad(f"Plate_{tag}", corners, plate_mat, plate_col)
    box(f"Plate_Bracket_{tag}", (PW + 0.02, 0.010, PH + 0.02), (0, y - side * 0.0058, z),
        black_plastic, bevel=0.004, col=plate_col)


plate("Front", 0.385, -1)
plate("Rear", 0.805, 1)

# ---------------------------------------------------------------------------
# 7. Roof topper (two-sided backlit ad sign with medallion-number lights at the ends)
# ---------------------------------------------------------------------------
roof_y = 0.42
L, WB, WT, H = 1.02, 0.20, 0.13, 0.30  # length, bottom width, top width, height
BARS = (-0.32, 0.32)
BAR_H = 0.028
bar_z = {}
for dy in BARS:  # clear the roof crown by 3 cm along the whole bar
    crown = max(surface((x, roof_y + dy, 3.0), (0, 0, -1)).z for x in np.linspace(-0.5, 0.5, 21))
    bar_z[dy] = crown + 0.03
z0 = max(bar_z.values()) + BAR_H / 2 + 0.04  # underside of the sign

bm = bmesh.new()
prof = [(-WB / 2, 0), (WB / 2, 0), (WT / 2, H), (-WT / 2, H)]
vs = [bm.verts.new((x, y, z0 + z)) for y in (-L / 2, L / 2) for x, z in prof]
bm.faces.new(vs[0:4][::-1])
bm.faces.new(vs[4:8])
for i in range(4):
    j = (i + 1) % 4
    bm.faces.new((vs[i], vs[j], vs[4 + j], vs[4 + i]))
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
me = bpy.data.meshes.new("Topper_Housing")
bm.to_mesh(me)
bm.free()
housing = bpy.data.objects.new("Topper_Housing", me)
housing.location = (0, roof_y, 0)
me.materials.append(black_plastic)
bev = housing.modifiers.new("Bevel", "BEVEL")
bev.width, bev.segments, bev.limit_method = 0.015, 4, "ANGLE"
me.shade_smooth()
move_to(housing, topper_col)

ad_img = load_image("topper_ad_panel.png")
ad_mat = principled("Topper_Ad_Panel_Backlit", rough=0.15, image=ad_img, emission=1.2,
                    emission_image=True)
end_img = load_image("topper_medallion_light.png")
end_mat = principled("Topper_Medallion_Light", rough=0.15, image=end_img, emission=2.5,
                     emission_image=True)

m = 0.035  # frame margin around the panels
for side, tag in ((1, "L"), (-1, "R")):
    # sloped side face, from bottom edge (x=WB/2) to top edge (x=WT/2)
    def pt(y, t, out=0.002):
        x = (WB / 2 + (WT / 2 - WB / 2) * t) * side
        n = Vector((H * side, 0, (WB - WT) / 2)).normalized()
        return Vector((x, roof_y + y, z0 + H * t)) + n * out
    t0, t1 = m / H, 1 - m / H
    y0, y1 = -L / 2 + m, L / 2 - m
    a, b = (y0, y1) if side > 0 else (y1, y0)   # left side reads front->rear
    textured_quad(f"Topper_Ad_{tag}", [pt(a, t0), pt(b, t0), pt(b, t1), pt(a, t1)], ad_mat, topper_col)

for side, tag in ((-1, "Front"), (1, "Rear")):
    y = roof_y + side * (L / 2 + 0.002)
    view = Vector((0, side, 0))
    right = Vector((0, 0, 1)).cross(view)
    zc, hw, hh = z0 + H / 2, 0.045, 0.10   # 0.09 x 0.20 m lit window
    corners = [Vector((0, y, zc - hh)) - right * hw, Vector((0, y, zc - hh)) + right * hw,
               Vector((0, y, zc + hh)) + right * hw, Vector((0, y, zc + hh)) - right * hw]
    textured_quad(f"Topper_MedallionLight_{tag}", corners, end_mat, topper_col)

# Mounting: two aluminium cross bars on rubber feet, centre posts up to the sign
for dy in BARS:
    y, bz, fb = roof_y + dy, bar_z[dy], "F" if dy < 0 else "R"
    box(f"Topper_RackBar_{fb}", (1.0, 0.045, BAR_H), (0, y, bz), alu, bevel=0.008)
    for x in (-0.45, 0.45):
        zf = surface((x, y, 3.0), (0, 0, -1)).z
        top = bz - BAR_H / 2
        box(f"Topper_Foot_{fb}{'L' if x > 0 else 'R'}", (0.07, 0.08, top - zf + 0.004),
            (x, y, (top + zf) / 2), black_plastic, bevel=0.008)
    box(f"Topper_Post_{fb}", (0.06, 0.05, z0 - (bz + BAR_H / 2) + 0.01),
        (0, y, (z0 + bz + BAR_H / 2) / 2), black_plastic, bevel=0.006)

full_bm.free()

# ---------------------------------------------------------------------------
# 8. Studio: camera, sun, sky (optional, in its own collection)
# ---------------------------------------------------------------------------
w = scene.world or bpy.data.worlds.new("World")
scene.world = w
w.use_nodes = True
nt = w.node_tree
nt.nodes.clear()
out = nt.nodes.new("ShaderNodeOutputWorld")
bg = nt.nodes.new("ShaderNodeBackground")
sky = nt.nodes.new("ShaderNodeTexSky")
if "HOSEK_WILKIE" in sky.bl_rna.properties["sky_type"].enum_items.keys():
    sky.sky_type = "HOSEK_WILKIE"
sky.sun_direction = (0.4, -0.6, 0.7)
bg.inputs["Strength"].default_value = 0.6
nt.links.new(sky.outputs[0], bg.inputs[0])
nt.links.new(bg.outputs[0], out.inputs[0])

sun_data = bpy.data.lights.new("Sun", "SUN")
sun_data.energy = 3.5
sun_data.angle = math.radians(2)
sun = bpy.data.objects.new("Sun", sun_data)
sun.rotation_euler = (math.radians(50), 0, math.radians(35))
studio_col.objects.link(sun)

cam_data = bpy.data.cameras.new("Camera")
cam_data.lens = 50
cam = bpy.data.objects.new("Camera", cam_data)
target = Vector((0, 0, 0.75))
cam.location = target + Vector((math.cos(math.radians(-55)), math.sin(math.radians(-55)),
                                math.sin(math.radians(12)))) * 9.5
cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
studio_col.objects.link(cam)
scene.camera = cam

ground_me = bpy.data.meshes.new("Ground")
bm = bmesh.new()
bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=15)
bm.to_mesh(ground_me)
bm.free()
ground = bpy.data.objects.new("Ground", ground_me)
ground_me.materials.append(principled("Asphalt", (0.035, 0.035, 0.038, 1), rough=0.85))
studio_col.objects.link(ground)

scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 1.0
scene.render.engine = "CYCLES"
scene.cycles.samples = 128
scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
scene.view_settings.view_transform = "AgX"

# ---------------------------------------------------------------------------
# 9. Clean up and save
# ---------------------------------------------------------------------------
for m in list(bpy.data.materials):
    if m.users == 0:
        bpy.data.materials.remove(m)
for img in list(bpy.data.images):
    if img.users == 0 and img.name not in ("Render Result", "Viewer Node"):
        bpy.data.images.remove(img)

bpy.ops.file.pack_all()
GLB = os.path.join(ROOT, "NYC_Taxi_Cemel_2020.glb")
bpy.ops.object.select_all(action="DESELECT")
for o in taxi_col.all_objects:
    o.select_set(True)
bpy.ops.export_scene.gltf(filepath=GLB, export_format="GLB", use_selection=True,
                          export_apply=True, export_cameras=False, export_lights=False)
print("Exported", GLB)
bpy.ops.wm.save_as_mainfile(filepath=DST, compress=True)
dims = np.array([(o.matrix_world @ v.co)[:] for o in bpy.data.objects
                 if o.type == "MESH" and o.name in RENAME.values() for v in o.data.vertices])
print("Saved", DST)
print("Car dimensions (m): L=%.3f W=%.3f H=%.3f" % tuple(
    (dims.max(0) - dims.min(0))[[1, 0, 2]]))
