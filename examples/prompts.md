# SalomeMCP example prompts

These are end-to-end prompts that should be resolvable via the SalomeMCP
tools alone. Each one mixes one of the three input modalities (description,
picture, vibrational target) with the geometry / mesh tool surface.

All examples use the **millimetre** `space_units` default so the produced
artefacts drop straight into the [pymodal](https://github.com/grcarmenaty/pymodal)
pipeline. See `examples/los_alamos_demo.md` for a full pymodal-bound
benchmark.

## 1. Pure description — bracket

> Make me an L-shaped mounting bracket: a 100 × 60 × 8 mm vertical plate with
> two 6 mm bolt holes 30 mm apart, joined to a 60 × 60 × 8 mm horizontal foot
> with a single central 8 mm hole. Fillet the inside corner with R = 4 mm.

Tool sequence the model should produce (default mm `space_units`):

```
record_design_intent("L-bracket, 100x60x8 mm vertical, 60x60x8 mm foot, ...",
                     source="user_text")
create_box("vert",  dx=100, dy=60, dz=8)
create_box("horiz", dx=60,  dy=60, dz=8, cz=-8)
boolean("bracket_raw", "fuse", "vert", "horiz")
create_cylinder("h1", radius=3, height=20, cx=20, cy=30, cz=-1, axis="Z")
create_cylinder("h2", radius=3, height=20, cx=50, cy=30, cz=-1, axis="Z")
create_cylinder("h3", radius=4, height=20, cx=30, cy=30, cz=-9, axis="Z")
cut_list("bracket_drilled", "bracket_raw", ["h1", "h2", "h3"])
fillet_all_edges("bracket", "bracket_drilled", radius=4)
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
create_cylinder("blank", radius=35, height=12)
create_cylinder("bore",  radius=10, height=14, cz=-1)
boolean("blank_with_bore", "cut", "blank", "bore")
# Simplified tooth profile, one tooth + circular pattern
create_polygon_face("tooth", points=[[34,-3], [40,-1], [40, 1], [34, 3]])
extrude("tooth_solid", "tooth", height=12, direction="Z")
circular_pattern("teeth", source="tooth_solid", axis="Z", count=24)
boolean("gear", "fuse", "blank_with_bore", "teeth")
export_step("gear", "/tmp/gear.step")
build()
```

## 3. Vibrational target — singing bar (pymodal-bound)

> I need a simply-supported aluminium bar that rings at 1 kHz on its first
> bending mode, ready to feed a pymodal FRF pipeline.

The vibrational helpers solve in SI metres; we convert into the session's
millimetre `space_units` for the geometry calls and tag both end-faces as
groups so Code_Aster can apply the simple supports.

```
record_design_intent("1 kHz first bending mode, simply-supported aluminium bar.",
                     source="vibrational")
list_materials()
beam_length_for_target_frequency(
    target_hz=1000, width=0.010, thickness=0.005,
    material="aluminum_6061", end_condition="simply-supported", mode=1
)
# -> {"length_m": 0.111..., ...}      => 111 mm in session units

create_box("bar", dx=111, dy=10, dz=5)
cantilever_beam_modes(length=0.111, width=0.010, thickness=0.005,
                      material="aluminum_6061",
                      end_condition="simply-supported", n_modes=3)

add_face_group("support_left",  "bar", near_x=0,   near_y=5, near_z=2.5)
add_face_group("support_right", "bar", near_x=111, near_y=5, near_z=2.5)

create_mesh("bar_mesh", "bar", max_size=2, fineness="fine", second_order=True,
            inherit_groups=["support_left", "support_right"])

export_mesh("bar_mesh", "/work/bar.med",
            format="med", med_version=41, auto_groups=False)
export_nodes_json("bar_mesh", "/work/bar_nodes.json")
export_groups_json("bar_mesh", "/work/bar_groups.json",
                   extras={"boundary": "simply-supported"})
build()

# Map a hammer location to a mesh node for the FRF builder:
closest_node("/work/bar_nodes.json", x=27, y=5, z=2.5)
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
