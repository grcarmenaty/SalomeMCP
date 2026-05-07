# Pymodal-bound demo: Los Alamos-style 3-storey benchmark

This walkthrough mirrors the
[`examples/los_alamos_3story/salome_build.py`](https://github.com/grcarmenaty/pymodal/tree/master/examples/los_alamos_3story)
shipped with pymodal, but built turn-by-turn through the SalomeMCP tool
surface. The output is the exact triplet pymodal's downstream Code_Aster
extractor and `pymodal.frf` builder expect:

* `building.med` — MED v4.1 mesh with named face groups
* `nodes.json`  — `{node_id: [x, y, z]}` for `pymodal.load_nodes_json`
* `groups.json` — `{groups, space_units, mesh, geometry, rail_direction}`

All lengths are in **millimetres** (the SalomeMCP / pymodal default).

## Tool sequence

```
record_design_intent(
    "Los Alamos 3-storey shear-frame mini benchmark. "
    "4 columns per storey, +Y rail BC at base.",
    source="user_text")
set_units("millimeter")

# --- Plates (slabs) ------------------------------------------------------
create_box("plate_0", dx=300, dy=300, dz=10, cz=0)
create_box("plate_1", dx=300, dy=300, dz=10, cz=300)
create_box("plate_2", dx=300, dy=300, dz=10, cz=600)
create_box("plate_3", dx=300, dy=300, dz=10, cz=900)

# --- Columns (4 corners x 3 storeys) ------------------------------------
for storey in (0, 1, 2):
    z0 = 10 + 300 * storey
    create_box(f"col_NW_s{storey}", dx=10, dy=10, dz=290, cx=0,   cy=0,   cz=z0)
    create_box(f"col_NE_s{storey}", dx=10, dy=10, dz=290, cx=290, cy=0,   cz=z0)
    create_box(f"col_SW_s{storey}", dx=10, dy=10, dz=290, cx=0,   cy=290, cz=z0)
    create_box(f"col_SE_s{storey}", dx=10, dy=10, dz=290, cx=290, cy=290, cz=z0)

# --- Single-shot fuse for a clean meshable solid ------------------------
fuse_list("building",
    ["plate_0","plate_1","plate_2","plate_3",
     "col_NW_s0","col_NE_s0","col_SW_s0","col_SE_s0",
     "col_NW_s1","col_NE_s1","col_SW_s1","col_SE_s1",
     "col_NW_s2","col_NE_s2","col_SW_s2","col_SE_s2"])

# --- BC anchors ---------------------------------------------------------
add_face_group("base_rails", "building",
               near_x=150, near_y=150, near_z=0)     # bottom of plate_0
add_face_group("top_face",   "building",
               near_x=150, near_y=150, near_z=910)   # top of plate_3

# --- Mesh + propagate groups into MED -----------------------------------
create_mesh("building_mesh", "building",
            max_size=20, min_size=4, fineness="moderate",
            inherit_groups=["base_rails", "top_face"])

# --- Pymodal-bound exports ---------------------------------------------
export_mesh("building_mesh", "/work/building.med",
            format="med", med_version=41, auto_groups=False)
export_nodes_json("building_mesh", "/work/nodes.json")
export_groups_json("building_mesh", "/work/groups.json",
                   extras={"rail_direction": "Y"})

# --- Confirm the bridge is wired correctly ------------------------------
pymodal_handoff_summary()
build()
```

## Resolving user-supplied excitation/measurement points

Once `nodes.json` exists on disk, the model can map continuous coordinates
straight to mesh node ids:

```
closest_node("/work/nodes.json", x=150, y=0, z=900)
# -> {"node_id": <int>, "xyz": [<x>, <y>, <z>], "n_nodes": ..., ...}
```

This is exactly what `pymodal.scenarios.closest_node` does after
`pymodal.load_nodes_json`, so the answer the agent gets here is the same
node id pymodal will use to drop a hammer or place an accelerometer.

## What pymodal sees on the other side

```python
import pymodal
ids, coords = pymodal.load_nodes_json("/work/nodes.json")
top_node, _ = pymodal.closest_node((150, 0, 900), ids, coords)

# After Code_Aster computes FRFs (using the base_rails BC),
# package the per-scenario FRF tensors into a labelled collection:
coll = pymodal.frf(
    measurements=frfs_per_scenario,         # list of (n_freq, n_outputs, n_inputs)
    freq_array=freqs,
    measurements_units="millimeter / second ** 2 / newton",
    space_units="millimeter",               # matches SalomeMCP session
    method="SIMO",
    labels=damage_labels,
    path="/work/los_alamos.h5",
)
```

The `space_units` value pymodal stores on the HDF5 attrs is exactly the
string SalomeMCP wrote into `groups.json["space_units"]` — so the chain
from `add_face_group` through MED → FRF → `pymodal.frf` collection stays
unit-consistent.
