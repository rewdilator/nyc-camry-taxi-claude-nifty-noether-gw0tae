# NYC Taxi – Toyota Camry 2020

A New York City yellow cab built from the Sketchfab
[Toyota Camry 2020](https://sketchfab.com/3d-models/toyota-camry-2020-236a5a6e2fa6420fbdf641f4800cd544) model.

![Front three-quarter](renders/front_three_quarter.png)
![Side](renders/side_left.png)
![Rear](renders/rear.png)
![Interior from the rear seat](renders/interior_rear_seat.png)

## Files

| File | What it is |
| --- | --- |
| `NYC_Taxi_Camry_2020.blend` | The taxi. Textures are packed, units are metres, and the car is centred on the origin with its tyres on z = 0. |
| `NYC_Taxi_Camry_2020.glb` | The same taxi as a glTF binary for game engines and web viewers (car only, no studio). |
| `Untitled.blend`, `toyota_camry_2020.fbx` | The original sources, unchanged. |
| `textures/` | Livery textures and interior textures (`interior_*.png`). Edit them and rebuild to change the medallion number, plate, ad, fare screen or notices. |
| `scripts/` | Scripts that rebuild everything from `Untitled.blend`. |
| `renders/` | Cycles preview renders. `original_before.png` shows the source model. |

## What changed

**Real-world scale.** The source was about 1:1000 scale: the car was 4.9 cm long, inside nested
glTF empties scaled 0.01 and 0.1. The empties are removed and the transform is applied to the
meshes. The car now measures the same as a 2020 Camry LE:

| | Model | 2020 Camry LE |
| --- | --- | --- |
| Length | 4.879 m | 4,879 mm |
| Body width | 1.84 m (2.13 m with mirrors) | 1,839 mm |
| Height | 1.47 m | 1,445 mm |
| Wheelbase | ~2.82 m | 2,825 mm |

**Texture fix.** The atlas textures were stored upside-down relative to the UVs. That made the
windows sample the amber indicator swatch (the red-tinted glass) and the tyres sample a white
swatch. The V coordinate is flipped, so the glass is dark-tinted, the tyres are black and the
tail and indicator lenses are the right colours.

**NYC taxi livery.**
- Body paint: NYC taxi yellow (sRGB 247/181/0) with a glossy clear coat.
- Front doors, both sides: the NYC TAXI logo. It is a black square with "NYC" cut out so the
  yellow paint shows through, followed by "TAXI".
- Rear doors, both sides: the rate-of-fare decal ($3.00 initial charge, 70¢ per 1/5 mile or per
  minute, 311 for complaints and lost property).
- Rear quarter panels and trunk: medallion number **5J47**. The trunk also has a small NYC TAXI
  logo.
- Roof: an NYC-style ad topper. It is a two-sided backlit (emissive) ad panel on a black housing,
  with lit medallion-number windows at the front and rear. It sits on aluminium roof bars with
  rubber feet.
- Plates: New York **TAXI** plates (`T640852C`) front and rear, 12 × 6 in, in black brackets. The
  model author's "ItsDiyor" banner front plate was removed.

**Interior (NYC taxi fit-out).** The source cabin is a low-poly shell: seat backs, a dash and a
flat floor tub, with no cushions or console. `scripts/build_interior.py` adds a `Taxi_Interior`
collection fitted out like a real NYC yellow-cab Camry:
- Seat cushions with side bolsters for the front seats, a rear bench cushion with seat-belt
  buckles, and a centre console with an armrest and a shifter.
- The partition behind the front seats. Its outline is traced from the cabin's cross-section, so it
  fits the door panels and headliner. It has an opaque black lower panel and a clear polycarbonate
  upper pane in a black aluminium frame, with a sliding pass-through window on the passenger side
  and a cash tray on the driver's side.
- On the partition, facing the rear seat: the Passenger Information Monitor ("Taxi TV") showing the
  map and fare, and a tap/chip card reader. Both are lit (emissive).
- The TLC notices: the driver's hack licence in a frame (the name and number are placeholders), the
  Taxi Rider Bill of Rights, a "Buckle up" sticker and a no-smoking sticker.
- For the driver: a taximeter on the dash top showing $3.00 and HIRED in red LEDs, and the T-PEP
  driver monitor on an arm at the centre stack.

![Taxi TV and card reader](renders/interior_taxi_tv.png)
![Taximeter and driver monitor](renders/interior_dashboard.png)

The decals are separate meshes (`Decal_*`) projected onto the body with ray casts. They follow
the panel curvature 1.8 mm above the paint, and each has its own simple 0–1 UVs. They export to
FBX and glTF as they are and do not depend on the body's UV layout.

## Scene layout

```
NYC_Taxi_Camry_2020 (collection)
├── NYC_Taxi_Camry_2020   ← root empty; move this to move the whole taxi
├── Car            Camry_Body_Paint, Camry_Trim_Interior, Camry_Wheels_Chassis,
│                  Camry_Glass_Lamps, Camry_Lamp_Lenses
├── Taxi_Livery    Decal_Logo_*, Decal_RateOfFare_*, Decal_Medallion_*
├── Roof_Topper    Topper_Housing, Topper_Ad_L/R, Topper_MedallionLight_*, rack bars, feet, posts
├── License_Plates Plate_Front/Rear + brackets
└── Taxi_Interior  Seat_*, Console_*, Partition_* (panels, frame, Taxi TV, card reader, notices),
                   Taximeter_*, Driver_Monitor_*
Studio (collection) Camera, Sun, Ground, plus the sky world. Delete it if you don't need it.
```

## Rebuilding / customising

The pipeline uses the `bpy` Python module (`pip install bpy pillow`) or Blender itself:

```bash
python3 scripts/make_textures.py      # edit MEDALLION / PLATE / ad text at the top first
python3 scripts/build_taxi.py         # writes NYC_Taxi_Camry_2020.blend and .glb
python3 scripts/make_interior_textures.py   # edit FARE / HACK_NO / DRIVER at the top first
python3 scripts/build_interior.py     # adds Taxi_Interior to the .blend and re-exports the .glb
python3 scripts/render_previews.py 48 fl,side,rear,cabin,tv,dash   # optional Cycles previews into renders/
```

`build_interior.py` works on `NYC_Taxi_Camry_2020.blend` directly and rebuilds its collection each
time, so you can run it without the original sources.

`Untitled.blend` was saved in Blender 5.2. The output was produced with Blender 5.0.1 (`bpy`), so
it opens in Blender 5.0 and newer.
