# SalomeMCP

A [Model Context Protocol](https://modelcontextprotocol.io) server that lets a
language model build [Salome](https://www.salome-platform.org) structures from
**descriptions, pictures, and vibrational features**, and hand the resulting
mesh + metadata off to the
[pymodal](https://github.com/grcarmenaty/pymodal) MCP for FRF extraction,
SHM-indicator computation, and PyTorch dataset assembly.

The model interprets the input and issues geometry / mesh tool calls;
SalomeMCP records each call, then renders a runnable `salome -t` script
(and, if Salome is installed, executes it).

## What the model can do through this MCP

| Capability                | Tools                                                                                    |
|---------------------------|------------------------------------------------------------------------------------------|
| Describe & remember intent | `record_design_intent` (text, image, vibrational tag — preserved as script comments)    |
| Pick units                | `set_units` (`millimeter` default, matching pymodal; or `meter`)                         |
| Build primitive solids    | `create_box`, `create_cylinder`, `create_sphere`, `create_cone`, `create_torus`         |
| Sketch & sweep            | `create_polygon_face`, `create_circle_face`, `extrude`, `revolve`                       |
| Combine                   | `boolean` (fuse / cut / common / section), `fuse_list`, `cut_list`, `common_list`        |
| Transform                 | `translate`, `rotate`, `mirror`, `scale`                                                 |
| Pattern                   | `linear_pattern`, `circular_pattern`                                                     |
| Soften edges              | `fillet_all_edges`, `chamfer_all_edges`                                                  |
| **Tag BC anchors**        | `add_face_group`, `add_edge_group`, `add_vertex_group`                                   |
| Import / export           | `import_step`, `export_step`, `export_brep`, `export_stl`                                |
| Mesh                      | `create_mesh` (NETGEN 1D-2D-3D, with `inherit_groups=`), `export_mesh` (med/unv/stl)     |
| **pymodal handoff**       | `export_nodes_json`, `export_groups_json`, `closest_node`, `pymodal_handoff_summary`     |
| Vibrational design        | `cantilever_beam_modes`, `beam_length_for_target_frequency`, `plate_modes`, `list_materials`, `list_beam_end_conditions` |
| Session control           | `set_workdir`, `list_objects`, `get_object_info`, `get_session_script`, `clear_session`, `save_session`, `load_session`, `check_salome`, `build` |

## How the three input modalities are handled

- **Text description.** The model reads the prose and issues construction
  tool calls. Anything worth preserving (assumptions, free dimensions, style
  cues) is captured with `record_design_intent(description, source="user_text")`.
- **Pictures.** The model itself sees the image (it is multimodal). It
  describes what it sees with `record_design_intent(..., source="image")` and
  then constructs the geometry with the standard primitive / sketch / pattern
  tools.
- **Vibrational features.** Targets like "first bending mode at 440 Hz" are
  resolved analytically with `beam_length_for_target_frequency` or
  `plate_modes`, and the resulting dimensions feed into the geometry tools.
  `list_materials` and `list_beam_end_conditions` enumerate the supported
  material/boundary keys.

Vibrational helpers always work in **SI metres** for E, ρ, and dimensions —
the units are physical, not the session's `space_units`. The geometry tools
use the session's `space_units`, defaulting to **millimetre** so coordinates
flow straight into the pymodal pipeline.

## Interop with pymodal

Pymodal ([repo](https://github.com/grcarmenaty/pymodal)) ships its own
FastMCP server (`python -m pymodal.mcp`) for FRF / time-series collections,
SHM indicators (CFDAC, RVAC, SCI, …), and PyTorch dataset handoff. The
contract between the two MCPs is on disk:

| File                               | Producer                       | Consumer                                          |
|------------------------------------|--------------------------------|---------------------------------------------------|
| `*.med`  (MED v4.1, named groups)  | `export_mesh(format="med")`    | Code_Aster modal extraction → `pymodal.frf`        |
| `nodes.json` `{id:[x,y,z]}`        | `export_nodes_json`            | `pymodal.load_nodes_json` / `closest_node`         |
| `groups.json` `{groups, extras…}`  | `export_groups_json`           | Code_Aster command file (BC anchor names + extras) |

Defaults that match pymodal:

- **Units:** `space_units="millimeter"`. STEP exports use `GEOM.LU_MILLIMETER`,
  and the same `space_units` value is written into `groups.json`.
- **MED export:** `med_version=41`, `auto_groups=False` (only the explicitly
  inherited groups are kept — Code_Aster commands referencing `base_rails`
  etc. resolve unambiguously).
- **Group propagation:** geometry-level groups (e.g. `base_rails`,
  `top_face`) are added with `add_face_group`; meshes opt-in via
  `create_mesh(..., inherit_groups=[...])`, which emits
  `mesh.GroupOnGeom(...)` so the groups survive into the MED file.

`closest_node(nodes_json_path, x, y, z)` is also available as a tool — it
mirrors `pymodal.closest_node` and lets the model resolve user-supplied
excitation/measurement coordinates against a Salome mesh **without** needing
pymodal installed. `pymodal_handoff_summary()` reports everything the
session has scheduled and how it maps to `pymodal.frf` /
`pymodal.scenarios.build_frf_collection`.

When you actually want pymodal in the same environment, install the extra:

```bash
pip install -e ".[pymodal]"
```

## Install

```bash
pip install -e .
```

This installs the `salome-mcp` console script (and `python -m salome_mcp`).

Salome itself is **not** required to use the MCP — the server happily
generates scripts without it. If you want `build` to actually execute the
script, install Salome and either put `salome` on your `PATH` or set
`SALOME_BIN` to the absolute binary path.

## Configure your MCP client

Point the client at both servers; they're complementary.

```json
{
  "mcpServers": {
    "salome": {
      "command": "salome-mcp",
      "env": {
        "SALOME_BIN": "/opt/salome/SALOME-9.13.0/salome"
      }
    },
    "pymodal": {
      "command": "python",
      "args": ["-m", "pymodal.mcp"]
    }
  }
}
```

Drop `SALOME_BIN` if `salome` is on your `PATH`, or omit it entirely if you
only want SalomeMCP's script-generation features.

## Typical workflow (pymodal-bound)

```text
user>  Build the Los Alamos 3-storey mini benchmark and export a MED + nodes/groups JSON.

model> set_units("millimeter")
model> record_design_intent("3-storey shear-frame benchmark, base_rails BC, +Y rail.",
                            source="user_text")
model> create_box("plate_0", dx=300, dy=300, dz=10, cz=0)
model> create_box("plate_1", dx=300, dy=300, dz=10, cz=300)
model> create_box("col_NW",  dx=10, dy=10, dz=290, cx=0,   cy=0,   cz=10)
model> create_box("col_NE",  dx=10, dy=10, dz=290, cx=290, cy=0,   cz=10)
model> create_box("col_SW",  dx=10, dy=10, dz=290, cx=0,   cy=290, cz=10)
model> create_box("col_SE",  dx=10, dy=10, dz=290, cx=290, cy=290, cz=10)
model> fuse_list("building", ["plate_0","plate_1","col_NW","col_NE","col_SW","col_SE"])

model> add_face_group("base_rails", "building", near_x=150, near_y=150, near_z=0)
model> add_face_group("top_face",   "building", near_x=150, near_y=150, near_z=310)

model> create_mesh("building_mesh", "building", max_size=20, fineness="moderate",
                   inherit_groups=["base_rails", "top_face"])
model> export_mesh("building_mesh", "/work/building.med",
                   format="med", med_version=41, auto_groups=False)
model> export_nodes_json("building_mesh", "/work/nodes.json")
model> export_groups_json("building_mesh", "/work/groups.json",
                          extras={"rail_direction": "Y"})

model> pymodal_handoff_summary()   # confirm what the build will produce
model> build()                     # writes session.py and runs salome -t
```

After `build`, the pymodal MCP can take over:

```text
# pymodal MCP calls (same MCP client, second server)
pymodal_describe_collection(...)               # once you've extracted FRFs
pymodal_create_frf_collection(...)             # build the labelled HDF5
pymodal_compute_indicator("cfdac", ref, dmg)   # SHM indicators
```

## Layout

```
src/salome_mcp/
├── __init__.py            # Public surface
├── __main__.py            # `python -m salome_mcp`
├── server.py              # FastMCP server with all tools
├── session.py             # In-memory state + script renderer
├── runner.py              # Subprocess launcher for `salome -t`
├── pymodal_bridge.py      # load_nodes_json / closest_node mirroring pymodal
└── vibrational.py         # Beam / plate analytical formulas + materials DB
tests/
├── test_session.py        # Script rendering, units, groups, MED options, JSON exports
├── test_vibrational.py    # Beam/plate closed forms, inverse problem
└── test_pymodal_bridge.py # JSON layout + closest-node compatibility with pymodal
examples/
├── prompts.md             # Description / image / vibrational prompts
└── los_alamos_demo.md     # End-to-end pymodal-bound benchmark walkthrough
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

The tests cover script rendering, group propagation, MED v4.1 export
options, the JSON companion files, the pymodal bridge utilities, and the
closed-form vibrational formulas; they do **not** require Salome.

## License

MIT — see `LICENSE`.
