# SalomeMCP example prompts

These are end-to-end prompts that should be resolvable via the SalomeMCP
tools alone. Each one mixes one of the three input modalities (description,
picture, vibrational target) with the geometry / mesh tool surface.

## 1. Pure description — bracket

> Make me an L-shaped mounting bracket: a 100 × 60 × 8 mm vertical plate with
> two 6 mm bolt holes 30 mm apart, joined to a 60 × 60 × 8 mm horizontal foot
> with a single central 8 mm hole. Fillet the inside corner with R = 4 mm.

Tool sequence the model should produce:

```
record_design_intent("L-bracket, 100x60x8 mm vertical, 60x60x8 mm foot, ...",
                     source="user_text")
create_box("vert", dx=0.100, dy=0.060, dz=0.008)
create_box("horiz", dx=0.060, dy=0.060, dz=0.008, cz=-0.008)
boolean("bracket_raw", "fuse", "vert", "horiz")
create_cylinder("h1", radius=0.003, height=0.020, cx=0.020, cy=0.030, cz=-0.001, axis="Z")
create_cylinder("h2", radius=0.003, height=0.020, cx=0.050, cy=0.030, cz=-0.001, axis="Z")
create_cylinder("h3", radius=0.004, height=0.020, cx=0.030, cy=0.030, cz=-0.009, axis="Z")
boolean("b1", "cut", "bracket_raw", "h1")
boolean("b2", "cut", "b1", "h2")
boolean("b3", "cut", "b2", "h3")
fillet_all_edges("bracket", "b3", radius=0.004)
export_step("bracket", "/tmp/bracket.step")
build()
```

## 2. Picture — gear blank from a photograph

The user sends a top-down photo of a spur gear blank. The model interprets
the image, then:

```
record_design_intent(
    "Spur gear blank: 24 teeth, ~70 mm OD, 20 mm bore, 12 mm thick. "
    "Counted teeth visually; estimated diameters from the ruler in frame.",
    source="image")
create_cylinder("blank", radius=0.035, height=0.012)
create_cylinder("bore",  radius=0.010, height=0.014, cz=-0.001)
boolean("blank_with_bore", "cut", "blank", "bore")
# tooth profile (simplified involute approximation, one tooth + circular pattern)
create_polygon_face("tooth", points=[
    [0.034, -0.0030], [0.040, -0.0010],
    [0.040,  0.0010], [0.034,  0.0030],
])
extrude("tooth_solid", "tooth", height=0.012, direction="Z")
circular_pattern("teeth", source="tooth_solid", axis="Z", count=24)
boolean("gear", "fuse", "blank_with_bore", "teeth")
export_step("gear", "/tmp/gear.step")
build()
```

## 3. Vibrational target — singing bar

> I need a free-free aluminium bar that rings at 1 kHz on its first
> longitudinal mode... actually no, first bending mode in air, simple support.

```
record_design_intent("1 kHz first bending mode, simply-supported aluminium bar.",
                     source="vibrational")
list_materials()                     # confirm aluminum_6061 keys
beam_length_for_target_frequency(
    target_hz=1000, width=0.010, thickness=0.005,
    material="aluminum_6061", end_condition="simply-supported", mode=1
)
# -> {"length_m": 0.111..., ...}
create_box("bar", dx=0.111, dy=0.010, dz=0.005)
cantilever_beam_modes(length=0.111, width=0.010, thickness=0.005,
                      material="aluminum_6061",
                      end_condition="simply-supported", n_modes=3)
# -> verify f1 ≈ 1000 Hz, gives f2/f3 for design margin
create_mesh("bar_mesh", "bar", max_size=0.002, fineness="fine", second_order=True)
export_mesh("bar_mesh", "/tmp/bar.med")
build()
```

## 4. Plate target — drum head

> Pick the thickness for a 300 × 200 mm steel plate so the (1,1) mode is
> around 200 Hz.

The model iterates over thickness with `plate_modes` until the (1,1) mode
matches, then commits the geometry:

```
record_design_intent("Steel plate 300x200, simply supported, target f_11 ≈ 200 Hz.",
                     source="vibrational")
plate_modes(a=0.300, b=0.200, h=0.0030, material="structural_steel")
plate_modes(a=0.300, b=0.200, h=0.0040, material="structural_steel")
# converge to e.g. h = 3.7 mm
create_box("plate", dx=0.300, dy=0.200, dz=0.0037)
create_mesh("plate_mesh", "plate", max_size=0.005, fineness="fine")
export_step("plate", "/tmp/plate.step")
export_mesh("plate_mesh", "/tmp/plate.med")
build()
```
