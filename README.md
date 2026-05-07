# SalomeMCP

A [Model Context Protocol](https://modelcontextprotocol.io) server that lets a
language model build [Salome](https://www.salome-platform.org) structures from
**descriptions, pictures, and vibrational features**. The model interprets the
input and issues geometry / mesh tool calls; SalomeMCP records each call, then
renders a runnable `salome -t` script (and, if Salome is installed, executes
it).

## What the model can do through this MCP

| Capability             | Tools                                                                                    |
|------------------------|------------------------------------------------------------------------------------------|
| Describe & remember intent | `record_design_intent` (text, image, vibrational tag — preserved as script comments) |
| Build primitive solids | `create_box`, `create_cylinder`, `create_sphere`, `create_cone`, `create_torus`         |
| Sketch & sweep         | `create_polygon_face`, `create_circle_face`, `extrude`, `revolve`                       |
| Combine                | `boolean` (fuse / cut / common / section)                                                |
| Transform              | `translate`, `rotate`, `mirror`, `scale`                                                 |
| Pattern                | `linear_pattern`, `circular_pattern`                                                     |
| Soften edges           | `fillet_all_edges`, `chamfer_all_edges`                                                  |
| Import / export        | `import_step`, `export_step`, `export_brep`, `export_stl`                                |
| Mesh                   | `create_mesh` (NETGEN 1D-2D-3D), `export_mesh` (.med / .unv / .stl)                      |
| Vibrational design     | `cantilever_beam_modes`, `beam_length_for_target_frequency`, `plate_modes`, `list_materials`, `list_beam_end_conditions` |
| Session control        | `set_workdir`, `list_objects`, `get_object_info`, `get_session_script`, `clear_session`, `save_session`, `load_session`, `check_salome`, `build` |

All lengths are interpreted in **metres** and the generated script uses
`GEOM.LU_METER` for STEP export.

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

`claude_desktop_config.json` (or any other MCP-aware client):

```json
{
  "mcpServers": {
    "salome": {
      "command": "salome-mcp",
      "env": {
        "SALOME_BIN": "/opt/salome/SALOME-9.13.0/salome"
      }
    }
  }
}
```

Drop `SALOME_BIN` if `salome` is on your `PATH`, or omit it entirely if you
only want the script-generation features.

## Typical workflow

```text
user>  Build me a tuning fork that resonates at 440 Hz, made of aluminium.
model> record_design_intent("440 Hz tuning fork, aluminium 6061",
                            source="vibrational")
model> beam_length_for_target_frequency(target_hz=440, width=0.005,
                                        thickness=0.005,
                                        material="aluminum_6061",
                                        end_condition="cantilever", mode=1)
       -> {"length_m": 0.087..., ...}
model> create_box("tine_a", dx=0.005, dy=0.005, dz=0.087, cx=0.0,  cy=0.0, cz=0.0)
model> create_box("tine_b", dx=0.005, dy=0.005, dz=0.087, cx=0.012, cy=0.0, cz=0.0)
model> create_box("base",   dx=0.017, dy=0.005, dz=0.020, cx=0.0,  cy=0.0, cz=-0.020)
model> boolean("fork", "fuse", "tine_a", "tine_b")
model> boolean("fork_full", "fuse", "fork", "base")
model> fillet_all_edges("fork_smooth", "fork_full", radius=0.001)
model> create_mesh("fork_mesh", "fork_smooth", max_size=0.002)
model> export_step("fork_smooth", "/tmp/fork.step")
model> export_mesh("fork_mesh", "/tmp/fork.med", format="med")
model> build()
```

`build` writes `<workdir>/session.py` and runs Salome on it. Without Salome
installed, the script is still written and its path returned.

## Layout

```
src/salome_mcp/
├── __init__.py        # Public surface
├── __main__.py        # `python -m salome_mcp`
├── server.py          # FastMCP server with all tools
├── session.py         # In-memory state + script renderer
├── runner.py          # Subprocess launcher for `salome -t`
└── vibrational.py     # Beam / plate analytical formulas + materials DB
tests/
├── test_session.py
└── test_vibrational.py
examples/
└── prompts.md         # End-to-end prompts the model can resolve via the MCP
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

The tests cover script rendering, name handling, JSON round-tripping, and
the vibrational closed forms; they do **not** require Salome.

## License

MIT — see `LICENSE`.
