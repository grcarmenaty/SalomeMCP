"""SalomeMCP server: a FastMCP server exposing Salome geometry/mesh tools.

Each tool records an operation in an in-memory ``Session``. The session can
be rendered to a Salome Python script and (optionally) executed via
``salome -t``. This lets a model translate user input — text descriptions,
its own image interpretation, or vibrational targets — into Salome
structures one tool call at a time.

The output is interoperable with the
`pymodal <https://github.com/grcarmenaty/pymodal>`_ MCP: meshes can carry
named groups, ``ExportMED`` writes MED v4.1 files with those groups, and
companion ``nodes.json`` / ``groups.json`` files match the format
``pymodal.load_nodes_json`` and pymodal's example pipelines expect.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from mcp.server.fastmcp import FastMCP

from salome_mcp.pymodal_bridge import closest_node_in_file
from salome_mcp.runner import find_salome, run_script
from salome_mcp.session import Session
from salome_mcp.vibrational import (
    BETA_L,
    MATERIALS,
    beam_length_for_frequency,
    beam_modes,
    plate_modes_simply_supported,
)

mcp = FastMCP("salome-mcp")
SESSION = Session()

Axis = Literal["X", "Y", "Z"]
SignedAxis = Literal["X", "Y", "Z", "-X", "-Y", "-Z"]
Plane = Literal["XY", "XZ", "YZ"]
ShapeKind = Literal["FACE", "EDGE", "VERTEX", "SOLID"]
SpaceUnits = Literal["millimeter", "meter"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _summary() -> str:
    parts = [f"workdir: {SESSION.workdir}",
             f"space_units: {SESSION.space_units}"]
    parts.append(f"objects ({len(SESSION.objects)}):")
    parts.extend(
        [f"  - {n} ({e.kind})" for n, e in SESSION.objects.items()]
        or ["  (none)"]
    )
    parts.append(f"groups ({len(SESSION.groups)}):")
    parts.extend(
        [f"  - {n} [{e.shape_type}] on {e.parent}"
         for n, e in SESSION.groups.items()]
        or ["  (none)"]
    )
    parts.append(f"meshes ({len(SESSION.meshes)}):")
    parts.extend(
        [f"  - {n} on {e.geometry}"
         + (f"  inherits={e.inherited_groups}" if e.inherited_groups else "")
         for n, e in SESSION.meshes.items()]
        or ["  (none)"]
    )
    if SESSION.exports:
        parts.append(f"exports ({len(SESSION.exports)}):")
        parts.extend(
            [f"  - {e['kind']}: {e['source']} -> {e['path']}"
             for e in SESSION.exports]
        )
    if SESSION.notes:
        parts.append(f"notes: {len(SESSION.notes)}")
    return "\n".join(parts)


def _axis_pair(axis: Axis, cx: float, cy: float, cz: float) -> list[str]:
    """Build a Salome axis vector from (cx,cy,cz) along the chosen axis."""
    dx = 1 if axis == "X" else 0
    dy = 1 if axis == "Y" else 0
    dz = 1 if axis == "Z" else 0
    return [
        f"_p1 = geompy.MakeVertex({cx}, {cy}, {cz})",
        f"_p2 = geompy.MakeVertex({cx + dx}, {cy + dy}, {cz + dz})",
        "_axis = geompy.MakeVector(_p1, _p2)",
    ]


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

@mcp.tool()
def set_workdir(path: str) -> str:
    """Set the working directory used for generated scripts and exports."""
    p = Path(path).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    SESSION.workdir = p
    return f"Workdir set to {p}"


@mcp.tool()
def set_units(units: SpaceUnits) -> str:
    """Set the session's spatial unit (``millimeter`` or ``meter``).

    Affects STEP export's length unit and the ``space_units`` field written
    into the companion ``nodes.json`` / ``groups.json`` files. The default
    is ``millimeter`` to match pymodal's convention.
    """
    SESSION.set_units(units)
    return f"space_units = {SESSION.space_units}"


@mcp.tool()
def list_objects() -> str:
    """List geometry objects, groups, meshes, and pending exports."""
    return _summary()


@mcp.tool()
def get_object_info(name: str) -> str:
    """Return the kind, parameters, and generated code for a session entry."""
    if name in SESSION.objects:
        e = SESSION.objects[name]
        return json.dumps(
            {"kind": e.kind, "params": e.params, "var": e.var, "code": e.code},
            indent=2,
        )
    if name in SESSION.groups:
        g = SESSION.groups[name]
        return json.dumps(
            {"kind": "group", "shape_type": g.shape_type,
             "parent": g.parent, "var": g.var, "code": g.code},
            indent=2,
        )
    if name in SESSION.meshes:
        m = SESSION.meshes[name]
        return json.dumps(
            {"kind": "mesh", "geometry": m.geometry,
             "inherited_groups": m.inherited_groups,
             "params": m.params, "var": m.var, "code": m.code},
            indent=2,
        )
    return f"No object, group, or mesh named '{name}'."


@mcp.tool()
def clear_session() -> str:
    """Remove all geometry, groups, meshes, notes, and exports."""
    SESSION.reset()
    return "Session cleared."


@mcp.tool()
def get_session_script() -> str:
    """Return the full Salome Python script for the current session."""
    return SESSION.render_script()


@mcp.tool()
def save_session(path: str) -> str:
    """Persist session state (objects, groups, meshes, notes, exports) to JSON."""
    target = Path(path).expanduser().resolve()
    SESSION.save(target)
    return f"Session saved to {target}"


@mcp.tool()
def load_session(path: str) -> str:
    """Replace the current session with state loaded from JSON at ``path``."""
    global SESSION
    SESSION = Session.load(Path(path).expanduser().resolve())
    return _summary()


# ---------------------------------------------------------------------------
# Build / execute
# ---------------------------------------------------------------------------

@mcp.tool()
def check_salome() -> str:
    """Report whether a Salome binary is available."""
    bin_path = find_salome()
    if bin_path:
        return f"Salome binary: {bin_path}"
    return "Salome not found. Set $SALOME_BIN or add `salome` to PATH."


@mcp.tool()
def build(salome_bin: Optional[str] = None, timeout: int = 600) -> str:
    """Write the session script and execute it via ``salome -t``.

    Pass ``salome_bin`` to override the binary path (otherwise ``$SALOME_BIN``
    or ``salome`` on ``PATH`` is used). Returns exit code, script path, and
    truncated stdout/stderr. If Salome is not installed the script is still
    written and its path returned.
    """
    SESSION.workdir.mkdir(parents=True, exist_ok=True)
    script_path = SESSION.workdir / "session.py"
    script_path.write_text(SESSION.render_script())
    try:
        result = run_script(script_path, salome_bin=salome_bin, timeout=timeout)
    except RuntimeError as exc:
        return f"Salome not invoked: {exc}\nScript written to {script_path}"
    status = "OK" if result.returncode == 0 else "FAILED"
    return (
        f"[{status}] {result.binary} -t {script_path}\n"
        f"exit={result.returncode}\n"
        f"--- stdout (tail) ---\n{result.stdout[-4000:]}\n"
        f"--- stderr (tail) ---\n{result.stderr[-2000:]}"
    )


# ---------------------------------------------------------------------------
# Primitive solids (axis-aligned by default)
# ---------------------------------------------------------------------------

@mcp.tool()
def create_box(
    name: str,
    dx: float,
    dy: float,
    dz: float,
    cx: float = 0.0,
    cy: float = 0.0,
    cz: float = 0.0,
) -> str:
    """Axis-aligned box of size (dx, dy, dz) with the near corner at (cx,cy,cz).

    Lengths are in the session's ``space_units`` (default millimetre).
    """
    code = [
        f"{{var}} = geompy.MakeBox({cx}, {cy}, {cz}, "
        f"{cx + dx}, {cy + dy}, {cz + dz})"
    ]
    SESSION.add_object(
        name=name, kind="box",
        params={"dx": dx, "dy": dy, "dz": dz, "origin": [cx, cy, cz]},
        code_lines=code,
    )
    return f"Created box '{name}' size=({dx},{dy},{dz}) at ({cx},{cy},{cz})"


@mcp.tool()
def create_cylinder(
    name: str,
    radius: float,
    height: float,
    cx: float = 0.0,
    cy: float = 0.0,
    cz: float = 0.0,
    axis: Axis = "Z",
) -> str:
    """Cylinder of given radius/height with base center at (cx,cy,cz) along an axis."""
    axis_vec = {"X": "OX", "Y": "OY", "Z": "OZ"}[axis]
    code = [
        f"_p = geompy.MakeVertex({cx}, {cy}, {cz})",
        f"{{var}} = geompy.MakeCylinder(_p, {axis_vec}, {radius}, {height})",
    ]
    SESSION.add_object(
        name=name, kind="cylinder",
        params={"radius": radius, "height": height, "axis": axis,
                "base": [cx, cy, cz]},
        code_lines=code,
    )
    return f"Created cylinder '{name}' r={radius} h={height} axis={axis}"


@mcp.tool()
def create_sphere(
    name: str,
    radius: float,
    cx: float = 0.0,
    cy: float = 0.0,
    cz: float = 0.0,
) -> str:
    """Sphere of given radius centered at (cx, cy, cz)."""
    code = [f"{{var}} = geompy.MakeSphere({cx}, {cy}, {cz}, {radius})"]
    SESSION.add_object(
        name=name, kind="sphere",
        params={"radius": radius, "center": [cx, cy, cz]},
        code_lines=code,
    )
    return f"Created sphere '{name}' r={radius}"


@mcp.tool()
def create_cone(
    name: str,
    base_radius: float,
    top_radius: float,
    height: float,
    cx: float = 0.0,
    cy: float = 0.0,
    cz: float = 0.0,
    axis: Axis = "Z",
) -> str:
    """Cone or frustum with given base/top radii and height."""
    axis_vec = {"X": "OX", "Y": "OY", "Z": "OZ"}[axis]
    code = [
        f"_p = geompy.MakeVertex({cx}, {cy}, {cz})",
        f"{{var}} = geompy.MakeCone(_p, {axis_vec}, "
        f"{base_radius}, {top_radius}, {height})",
    ]
    SESSION.add_object(
        name=name, kind="cone",
        params={"base_radius": base_radius, "top_radius": top_radius,
                "height": height, "axis": axis, "base": [cx, cy, cz]},
        code_lines=code,
    )
    return f"Created cone '{name}' r1={base_radius} r2={top_radius} h={height}"


@mcp.tool()
def create_torus(
    name: str,
    major_radius: float,
    minor_radius: float,
    cx: float = 0.0,
    cy: float = 0.0,
    cz: float = 0.0,
    axis: Axis = "Z",
) -> str:
    """Torus with the given major/minor radii."""
    axis_vec = {"X": "OX", "Y": "OY", "Z": "OZ"}[axis]
    code = [
        f"_p = geompy.MakeVertex({cx}, {cy}, {cz})",
        f"{{var}} = geompy.MakeTorus(_p, {axis_vec}, "
        f"{major_radius}, {minor_radius})",
    ]
    SESSION.add_object(
        name=name, kind="torus",
        params={"major_radius": major_radius, "minor_radius": minor_radius,
                "axis": axis, "center": [cx, cy, cz]},
        code_lines=code,
    )
    return f"Created torus '{name}' R={major_radius} r={minor_radius}"


# ---------------------------------------------------------------------------
# Sketch-based geometry
# ---------------------------------------------------------------------------

@mcp.tool()
def create_polygon_face(
    name: str,
    points: list[list[float]],
    plane: Plane = "XY",
) -> str:
    """Closed planar polygon face from 2D points laid out on the chosen plane."""
    if len(points) < 3:
        raise ValueError("Polygon needs at least 3 points.")
    map_3d = {
        "XY": lambda u, v: (u, v, 0.0),
        "XZ": lambda u, v: (u, 0.0, v),
        "YZ": lambda u, v: (0.0, u, v),
    }[plane]
    code: list[str] = ["_pts = []"]
    for pair in points:
        if len(pair) != 2:
            raise ValueError("Each point must be a [u, v] pair.")
        x, y, z = map_3d(*pair)
        code.append(f"_pts.append(geompy.MakeVertex({x}, {y}, {z}))")
    code.append(
        "_edges = [geompy.MakeEdge(_pts[i], _pts[(i+1) % len(_pts)]) "
        "for i in range(len(_pts))]"
    )
    code.append("_wire = geompy.MakeWire(_edges, 1e-7)")
    code.append("{var} = geompy.MakeFaceWires([_wire], 1)")
    SESSION.add_object(
        name=name, kind="polygon_face",
        params={"points": points, "plane": plane},
        code_lines=code,
    )
    return f"Created polygon face '{name}' with {len(points)} points on {plane}"


@mcp.tool()
def create_circle_face(
    name: str,
    radius: float,
    cx: float = 0.0,
    cy: float = 0.0,
    cz: float = 0.0,
    axis: Axis = "Z",
) -> str:
    """Planar disk (face bounded by a circle) of given radius."""
    axis_vec = {"X": "OX", "Y": "OY", "Z": "OZ"}[axis]
    code = [
        f"_p = geompy.MakeVertex({cx}, {cy}, {cz})",
        f"_c = geompy.MakeCircle(_p, {axis_vec}, {radius})",
        "_w = geompy.MakeWire([_c], 1e-7)",
        "{var} = geompy.MakeFaceWires([_w], 1)",
    ]
    SESSION.add_object(
        name=name, kind="circle_face",
        params={"radius": radius, "center": [cx, cy, cz], "axis": axis},
        code_lines=code,
    )
    return f"Created circle face '{name}' r={radius}"


@mcp.tool()
def extrude(
    name: str,
    profile: str,
    height: float,
    direction: SignedAxis = "Z",
) -> str:
    """Extrude an existing face/wire into a 3D solid along an axis direction."""
    src = SESSION.require(profile)
    sign = -1.0 if direction.startswith("-") else 1.0
    base = direction.lstrip("-")
    dx = sign if base == "X" else 0.0
    dy = sign if base == "Y" else 0.0
    dz = sign if base == "Z" else 0.0
    code = [
        f"_v = geompy.MakeVectorDXDYDZ({dx}, {dy}, {dz})",
        f"{{var}} = geompy.MakePrismVecH({src.var}, _v, {height})",
    ]
    SESSION.add_object(
        name=name, kind="extrude",
        params={"profile": profile, "height": height, "direction": direction},
        code_lines=code,
    )
    return f"Extruded '{profile}' -> '{name}' along {direction} by {height}"


@mcp.tool()
def revolve(
    name: str,
    profile: str,
    axis: Axis = "Z",
    angle_deg: float = 360.0,
    cx: float = 0.0,
    cy: float = 0.0,
    cz: float = 0.0,
) -> str:
    """Revolve a profile face/wire around an axis through (cx, cy, cz)."""
    src = SESSION.require(profile)
    code = _axis_pair(axis, cx, cy, cz)
    code.append(
        f"{{var}} = geompy.MakeRevolution({src.var}, _axis, "
        f"{angle_deg} * math.pi / 180.0)"
    )
    SESSION.add_object(
        name=name, kind="revolve",
        params={"profile": profile, "axis": axis, "angle_deg": angle_deg,
                "center": [cx, cy, cz]},
        code_lines=code,
    )
    return f"Revolved '{profile}' -> '{name}' about {axis} by {angle_deg} deg"


# ---------------------------------------------------------------------------
# Boolean
# ---------------------------------------------------------------------------

@mcp.tool()
def boolean(
    name: str,
    operation: Literal["fuse", "cut", "common", "section"],
    a: str,
    b: str,
) -> str:
    """Boolean of two solids: ``fuse``, ``cut`` (a − b), ``common``, ``section``."""
    A = SESSION.require(a)
    B = SESSION.require(b)
    fn = {
        "fuse": "MakeFuse",
        "cut": "MakeCut",
        "common": "MakeCommon",
        "section": "MakeSection",
    }[operation]
    code = [f"{{var}} = geompy.{fn}({A.var}, {B.var})"]
    SESSION.add_object(
        name=name, kind=f"boolean.{operation}",
        params={"operation": operation, "a": a, "b": b},
        code_lines=code,
    )
    return f"{operation}({a}, {b}) -> '{name}'"


@mcp.tool()
def fuse_list(
    name: str,
    objects: list[str],
    check_self_intersection: bool = False,
    remove_extra_edges: bool = True,
) -> str:
    """Fuse many solids into one in a single robust call (``MakeFuseList``).

    Preferred over chained pairwise ``fuse`` calls when assembling many
    parts (plates + columns + screws). Useful for building meshable
    welded assemblies for downstream pymodal FRF extraction.
    """
    if len(objects) < 2:
        raise ValueError("fuse_list needs at least 2 objects.")
    vars_ = [SESSION.require(o).var for o in objects]
    args = ", ".join(vars_)
    code = [
        f"{{var}} = geompy.MakeFuseList(["
        f"{args}], "
        f"checkSelfInte={bool(check_self_intersection)}, "
        f"rmExtraEdges={bool(remove_extra_edges)})"
    ]
    SESSION.add_object(
        name=name, kind="fuse_list",
        params={"objects": list(objects),
                "check_self_intersection": bool(check_self_intersection),
                "remove_extra_edges": bool(remove_extra_edges)},
        code_lines=code,
    )
    return f"Fused {len(objects)} objects -> '{name}'"


@mcp.tool()
def cut_list(name: str, main: str, tools: list[str]) -> str:
    """Subtract a list of solids from ``main`` (``MakeCutList``)."""
    if not tools:
        raise ValueError("cut_list needs at least one tool object.")
    M = SESSION.require(main)
    tool_vars = [SESSION.require(t).var for t in tools]
    code = [
        f"{{var}} = geompy.MakeCutList({M.var}, [{', '.join(tool_vars)}], False)"
    ]
    SESSION.add_object(
        name=name, kind="cut_list",
        params={"main": main, "tools": list(tools)},
        code_lines=code,
    )
    return f"Cut {len(tools)} tools from '{main}' -> '{name}'"


@mcp.tool()
def common_list(name: str, objects: list[str]) -> str:
    """Intersection of many solids in one call (``MakeCommonList``)."""
    if len(objects) < 2:
        raise ValueError("common_list needs at least 2 objects.")
    vars_ = [SESSION.require(o).var for o in objects]
    code = [
        f"{{var}} = geompy.MakeCommonList([{', '.join(vars_)}], False)"
    ]
    SESSION.add_object(
        name=name, kind="common_list",
        params={"objects": list(objects)},
        code_lines=code,
    )
    return f"Common of {len(objects)} objects -> '{name}'"


# ---------------------------------------------------------------------------
# Sub-shape groups (boundary conditions for Code_Aster downstream)
# ---------------------------------------------------------------------------

@mcp.tool()
def add_face_group(
    name: str,
    geometry: str,
    near_x: float,
    near_y: float,
    near_z: float,
) -> str:
    """Tag a single face of ``geometry`` as a named group, located by spatial probe.

    The face closest to ``(near_x, near_y, near_z)`` is selected
    (``geompy.GetFaceNearPoint``) and added as a FACE-type group. When a
    mesh on the same geometry passes ``inherit_groups=[name]`` to
    :func:`create_mesh`, the group is propagated to the MED export.
    Standard pymodal pipelines (e.g. the Los Alamos benchmark) use such
    groups to anchor Code_Aster boundary conditions like
    ``base_rails``.
    """
    code = [
        f"_p = geompy.MakeVertex({near_x}, {near_y}, {near_z})",
        "_f = geompy.GetFaceNearPoint({parent_var}, _p)",
        "{var} = geompy.CreateGroup({parent_var}, "
        "geompy.ShapeType[{shape_type!r}])",
        "geompy.UnionList({var}, [_f])",
    ]
    SESSION.add_group(name=name, parent=geometry, shape_type="FACE",
                      code_lines=code,
                      params={"near_point": [near_x, near_y, near_z]})
    return f"Created FACE group '{name}' on '{geometry}'"


@mcp.tool()
def add_edge_group(
    name: str,
    geometry: str,
    near_x: float,
    near_y: float,
    near_z: float,
) -> str:
    """Tag a single edge of ``geometry`` as a named group, located by spatial probe."""
    code = [
        f"_p = geompy.MakeVertex({near_x}, {near_y}, {near_z})",
        "_e = geompy.GetEdgeNearPoint({parent_var}, _p)",
        "{var} = geompy.CreateGroup({parent_var}, "
        "geompy.ShapeType[{shape_type!r}])",
        "geompy.UnionList({var}, [_e])",
    ]
    SESSION.add_group(name=name, parent=geometry, shape_type="EDGE",
                      code_lines=code,
                      params={"near_point": [near_x, near_y, near_z]})
    return f"Created EDGE group '{name}' on '{geometry}'"


@mcp.tool()
def add_vertex_group(
    name: str,
    geometry: str,
    x: float,
    y: float,
    z: float,
) -> str:
    """Tag a vertex of ``geometry`` as a named group (closest existing vertex)."""
    code = [
        f"_p = geompy.MakeVertex({x}, {y}, {z})",
        "_v = geompy.GetVertexNearPoint({parent_var}, _p)",
        "{var} = geompy.CreateGroup({parent_var}, "
        "geompy.ShapeType[{shape_type!r}])",
        "geompy.UnionList({var}, [_v])",
    ]
    SESSION.add_group(name=name, parent=geometry, shape_type="VERTEX",
                      code_lines=code,
                      params={"point": [x, y, z]})
    return f"Created VERTEX group '{name}' on '{geometry}'"


# ---------------------------------------------------------------------------
# Transforms (return new copies)
# ---------------------------------------------------------------------------

@mcp.tool()
def translate(
    name: str,
    source: str,
    dx: float = 0.0,
    dy: float = 0.0,
    dz: float = 0.0,
) -> str:
    """Translated copy of ``source`` by (dx, dy, dz)."""
    src = SESSION.require(source)
    code = [f"{{var}} = geompy.MakeTranslation({src.var}, {dx}, {dy}, {dz})"]
    SESSION.add_object(
        name=name, kind="translate",
        params={"source": source, "delta": [dx, dy, dz]},
        code_lines=code,
    )
    return f"Translated '{source}' -> '{name}' by ({dx},{dy},{dz})"


@mcp.tool()
def rotate(
    name: str,
    source: str,
    axis: Axis = "Z",
    angle_deg: float = 90.0,
    cx: float = 0.0,
    cy: float = 0.0,
    cz: float = 0.0,
) -> str:
    """Rotated copy of ``source`` about an axis through (cx, cy, cz)."""
    src = SESSION.require(source)
    code = _axis_pair(axis, cx, cy, cz)
    code.append(
        f"{{var}} = geompy.MakeRotation({src.var}, _axis, "
        f"{angle_deg} * math.pi / 180.0)"
    )
    SESSION.add_object(
        name=name, kind="rotate",
        params={"source": source, "axis": axis, "angle_deg": angle_deg,
                "center": [cx, cy, cz]},
        code_lines=code,
    )
    return f"Rotated '{source}' -> '{name}' by {angle_deg} deg about {axis}"


@mcp.tool()
def mirror(
    name: str,
    source: str,
    plane: Plane = "XY",
) -> str:
    """Mirrored copy of ``source`` across the global XY/XZ/YZ plane."""
    src = SESSION.require(source)
    nx, ny, nz = {"XY": (0, 0, 1), "XZ": (0, 1, 0), "YZ": (1, 0, 0)}[plane]
    code = [
        f"_n = geompy.MakeVectorDXDYDZ({nx}, {ny}, {nz})",
        "_pl = geompy.MakePlane(O, _n, 1.0)",
        f"{{var}} = geompy.MakeMirrorByPlane({src.var}, _pl)",
    ]
    SESSION.add_object(
        name=name, kind="mirror",
        params={"source": source, "plane": plane},
        code_lines=code,
    )
    return f"Mirrored '{source}' -> '{name}' across {plane}"


@mcp.tool()
def scale(
    name: str,
    source: str,
    factor: float,
    cx: float = 0.0,
    cy: float = 0.0,
    cz: float = 0.0,
) -> str:
    """Uniformly scaled copy of ``source`` about (cx, cy, cz)."""
    src = SESSION.require(source)
    code = [
        f"_c = geompy.MakeVertex({cx}, {cy}, {cz})",
        f"{{var}} = geompy.MakeScaleTransform({src.var}, _c, {factor})",
    ]
    SESSION.add_object(
        name=name, kind="scale",
        params={"source": source, "factor": factor, "center": [cx, cy, cz]},
        code_lines=code,
    )
    return f"Scaled '{source}' -> '{name}' by {factor}"


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

@mcp.tool()
def linear_pattern(
    name: str,
    source: str,
    direction: Axis,
    count: int,
    spacing: float,
) -> str:
    """Linear array of ``source`` along an axis."""
    if count < 2:
        raise ValueError("count must be >= 2.")
    src = SESSION.require(source)
    axis_vec = {"X": "OX", "Y": "OY", "Z": "OZ"}[direction]
    code = [
        f"{{var}} = geompy.MakeMultiTranslation1D({src.var}, "
        f"{axis_vec}, {spacing}, {count})"
    ]
    SESSION.add_object(
        name=name, kind="linear_pattern",
        params={"source": source, "direction": direction,
                "count": count, "spacing": spacing},
        code_lines=code,
    )
    return f"Linear pattern of '{source}' x{count} step={spacing} on {direction} -> '{name}'"


@mcp.tool()
def circular_pattern(
    name: str,
    source: str,
    axis: Axis,
    count: int,
    total_angle_deg: float = 360.0,
) -> str:
    """Circular array of ``source`` about an axis through the origin."""
    if count < 2:
        raise ValueError("count must be >= 2.")
    src = SESSION.require(source)
    axis_vec = {"X": "OX", "Y": "OY", "Z": "OZ"}[axis]
    step = total_angle_deg / (count if total_angle_deg == 360.0 else max(count - 1, 1))
    code = [
        f"{{var}} = geompy.MultiRotate1DByStep({src.var}, {axis_vec}, "
        f"{step} * math.pi / 180.0, {count})"
    ]
    SESSION.add_object(
        name=name, kind="circular_pattern",
        params={"source": source, "axis": axis,
                "count": count, "total_angle_deg": total_angle_deg},
        code_lines=code,
    )
    return f"Circular pattern of '{source}' x{count} on {axis} -> '{name}'"


# ---------------------------------------------------------------------------
# Edge modifications
# ---------------------------------------------------------------------------

@mcp.tool()
def fillet_all_edges(name: str, source: str, radius: float) -> str:
    """Fillet every edge of ``source`` with constant radius."""
    if radius <= 0:
        raise ValueError("radius must be positive.")
    src = SESSION.require(source)
    code = [f"{{var}} = geompy.MakeFilletAll({src.var}, {radius})"]
    SESSION.add_object(
        name=name, kind="fillet",
        params={"source": source, "radius": radius},
        code_lines=code,
    )
    return f"Filleted '{source}' (r={radius}) -> '{name}'"


@mcp.tool()
def chamfer_all_edges(name: str, source: str, distance: float) -> str:
    """Chamfer every edge of ``source`` by a uniform distance."""
    if distance <= 0:
        raise ValueError("distance must be positive.")
    src = SESSION.require(source)
    code = [f"{{var}} = geompy.MakeChamferAll({src.var}, {distance})"]
    SESSION.add_object(
        name=name, kind="chamfer",
        params={"source": source, "distance": distance},
        code_lines=code,
    )
    return f"Chamfered '{source}' (d={distance}) -> '{name}'"


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

@mcp.tool()
def import_step(name: str, file_path: str) -> str:
    """Import a STEP file as a new geometry object."""
    p = str(Path(file_path).expanduser().resolve())
    code = [f"{{var}} = geompy.ImportSTEP({p!r}, False, True)"]
    SESSION.add_object(
        name=name, kind="import_step",
        params={"file_path": p},
        code_lines=code,
    )
    return f"Imported STEP '{p}' as '{name}'"


@mcp.tool()
def export_step(source: str, file_path: str) -> str:
    """Schedule a STEP export of ``source`` (uses the session's space_units)."""
    SESSION.require(source)
    p = str(Path(file_path).expanduser().resolve())
    SESSION.add_export("step", source, p)
    return f"Scheduled STEP export: {source} -> {p}"


@mcp.tool()
def export_brep(source: str, file_path: str) -> str:
    """Schedule a BREP export of ``source``."""
    SESSION.require(source)
    p = str(Path(file_path).expanduser().resolve())
    SESSION.add_export("brep", source, p)
    return f"Scheduled BREP export: {source} -> {p}"


@mcp.tool()
def export_stl(source: str, file_path: str) -> str:
    """Schedule a binary STL export of geometry ``source``."""
    SESSION.require(source)
    p = str(Path(file_path).expanduser().resolve())
    SESSION.add_export("stl", source, p)
    return f"Scheduled STL export: {source} -> {p}"


# ---------------------------------------------------------------------------
# Meshing
# ---------------------------------------------------------------------------

@mcp.tool()
def create_mesh(
    name: str,
    geometry: str,
    max_size: float,
    min_size: Optional[float] = None,
    fineness: Literal[
        "very_coarse", "coarse", "moderate", "fine", "very_fine"
    ] = "moderate",
    second_order: bool = False,
    inherit_groups: Optional[list[str]] = None,
) -> str:
    """Tetrahedral NETGEN 1D-2D-3D mesh on a solid geometry.

    ``inherit_groups`` is a list of geometry-group names (created via
    :func:`add_face_group` / :func:`add_edge_group` / :func:`add_vertex_group`)
    that will be propagated onto the mesh with ``mesh.GroupOnGeom`` so they
    survive into MED export — required for downstream pymodal /
    Code_Aster boundary-condition setup.
    """
    SESSION.require(geometry)
    fineness_idx = {
        "very_coarse": 0, "coarse": 1, "moderate": 2,
        "fine": 3, "very_fine": 4,
    }[fineness]
    min_s = min_size if min_size is not None else max_size / 10.0
    code = [
        "{var} = smesh.Mesh({geom_var})",
        "_algo = {var}.Tetrahedron(algo=smeshBuilder.NETGEN_1D2D3D)",
        "_params = _algo.Parameters()",
        f"_params.SetMaxSize({max_size})",
        f"_params.SetMinSize({min_s})",
        f"_params.SetFineness({fineness_idx})",
        f"_params.SetSecondOrder({second_order})",
        f"_params.SetOptimize(1)",
        f"_params.SetQuadAllowed(0)",
        "_ok = {var}.Compute()",
        "if not _ok:",
        "    raise RuntimeError('NETGEN failed to mesh ' + repr({geom_var}))",
    ]
    SESSION.add_mesh(
        name=name, geometry=geometry,
        params={"max_size": max_size, "min_size": min_s,
                "fineness": fineness, "second_order": second_order},
        code_lines=code,
        inherit_groups=inherit_groups,
    )
    inh = list(inherit_groups or [])
    suffix = f", groups inherited: {inh}" if inh else ""
    return (f"Mesh '{name}' on '{geometry}' "
            f"(max={max_size}, min={min_s}, fineness={fineness}){suffix}")


@mcp.tool()
def export_mesh(
    source: str,
    file_path: str,
    format: Literal["med", "unv", "stl"] = "med",
    med_version: int = 41,
    auto_groups: bool = False,
) -> str:
    """Schedule a mesh export.

    For MED format, ``med_version=41`` (MED v4.1) and ``auto_groups=False``
    match what pymodal's example pipelines (e.g. the Los Alamos benchmark)
    request. ``auto_groups=False`` keeps only the explicitly inherited
    geometry groups in the file, so Code_Aster commands referencing
    ``base_rails`` etc. resolve unambiguously.
    """
    if source not in SESSION.meshes:
        raise KeyError(f"Mesh '{source}' not found.")
    p = str(Path(file_path).expanduser().resolve())
    if format == "med":
        SESSION.add_export(
            "med", source, p,
            options={"version": int(med_version),
                     "auto_groups": bool(auto_groups)},
        )
        return (f"Scheduled MED export (v{med_version}, "
                f"auto_groups={auto_groups}): {source} -> {p}")
    kind = {"unv": "unv", "stl": "stl_mesh"}[format]
    SESSION.add_export(kind, source, p)
    return f"Scheduled {format.upper()} mesh export: {source} -> {p}"


@mcp.tool()
def export_nodes_json(mesh: str, file_path: str) -> str:
    """Schedule a pymodal-compatible ``nodes.json`` dump for ``mesh``.

    The generated script writes ``{"<node_id>": [x, y, z], ...}`` to
    ``file_path`` after meshing — the exact layout
    ``pymodal.load_nodes_json`` and :func:`closest_node` expect.
    Coordinates are in the session's ``space_units``.
    """
    if mesh not in SESSION.meshes:
        raise KeyError(f"Mesh '{mesh}' not found.")
    p = str(Path(file_path).expanduser().resolve())
    SESSION.add_export("nodes_json", mesh, p)
    return f"Scheduled nodes.json export: {mesh} -> {p}"


@mcp.tool()
def export_groups_json(
    mesh: str,
    file_path: str,
    extras: Optional[dict] = None,
) -> str:
    """Schedule a pymodal-compatible ``groups.json`` dump for ``mesh``.

    The file lists the named groups carried by the MED export plus any
    extra free-form keys (e.g. ``rail_direction``) the downstream
    Code_Aster setup needs. Pymodal's example pipelines read this file
    when wiring boundary conditions.
    """
    if mesh not in SESSION.meshes:
        raise KeyError(f"Mesh '{mesh}' not found.")
    p = str(Path(file_path).expanduser().resolve())
    SESSION.add_export(
        "groups_json", mesh, p,
        options={"extras": dict(extras or {})},
    )
    return f"Scheduled groups.json export: {mesh} -> {p}"


# ---------------------------------------------------------------------------
# pymodal interop helpers (read-only, no Salome required)
# ---------------------------------------------------------------------------

@mcp.tool()
def closest_node(
    nodes_json_path: str,
    x: float,
    y: float,
    z: float,
) -> str:
    """Return the mesh node closest to ``(x, y, z)`` from a ``nodes.json`` file.

    Equivalent to ``pymodal.closest_node`` after ``pymodal.load_nodes_json``.
    Use this to map user-supplied excitation/measurement coordinates to mesh
    nodes when wiring up an FRF extraction pipeline.
    """
    out = closest_node_in_file(Path(nodes_json_path).expanduser().resolve(),
                               (x, y, z))
    return json.dumps(out, indent=2)


@mcp.tool()
def pymodal_handoff_summary() -> str:
    """Describe the artefacts SalomeMCP has scheduled for the pymodal pipeline.

    Lists the MED meshes, named groups carried into them, the companion
    ``nodes.json`` / ``groups.json`` files, and the geometry coordinate
    system (``space_units``). Useful to confirm the produced files are
    consumable by ``pymodal.frf`` / ``pymodal.load_nodes_json`` /
    ``pymodal.scenarios.build_frf_collection`` before running ``build``.
    """
    med_exports = [e for e in SESSION.exports if e["kind"] == "med"]
    nodes_exports = [e for e in SESSION.exports if e["kind"] == "nodes_json"]
    groups_exports = [e for e in SESSION.exports if e["kind"] == "groups_json"]
    out: dict = {
        "space_units": SESSION.space_units,
        "med_meshes": [
            {
                "mesh": e["source"],
                "path": e["path"],
                "version": e.get("options", {}).get("version", 41),
                "auto_groups": e.get("options", {}).get("auto_groups", False),
                "inherited_groups": SESSION.meshes[e["source"]].inherited_groups,
            }
            for e in med_exports
        ],
        "nodes_json": [{"mesh": e["source"], "path": e["path"]}
                       for e in nodes_exports],
        "groups_json": [
            {"mesh": e["source"], "path": e["path"],
             "extras": e.get("options", {}).get("extras", {})}
            for e in groups_exports
        ],
        "downstream": {
            "pymodal.load_nodes_json": (
                "consumes nodes.json -> (ids, coords) for closest_node()"
            ),
            "pymodal.frf": (
                "expects measurements_units like "
                "'millimeter / second ** 2 / newton' (accelerance) "
                "and space_units matching this session"
            ),
            "Code_Aster": (
                "uses MED group names (e.g. 'base_rails') as boundary anchors"
            ),
        },
    }
    return json.dumps(out, indent=2)


# ---------------------------------------------------------------------------
# Vibrational helpers
# ---------------------------------------------------------------------------

@mcp.tool()
def list_materials() -> str:
    """Return common engineering materials with E (Pa), nu, rho (kg/m^3)."""
    return json.dumps(MATERIALS, indent=2)


@mcp.tool()
def list_beam_end_conditions() -> str:
    """Return supported beam end conditions for vibrational analysis."""
    return json.dumps(list(BETA_L), indent=2)


@mcp.tool()
def cantilever_beam_modes(
    length: float,
    width: float,
    thickness: float,
    material: str = "structural_steel",
    end_condition: Literal[
        "cantilever", "fixed-fixed", "simply-supported", "free-free"
    ] = "cantilever",
    n_modes: int = 5,
) -> str:
    """First ``n_modes`` bending frequencies (Hz) of a slender prismatic beam.

    Inputs are in **SI metres** (independent of session ``space_units``).
    Use ``list_materials`` for available material keys.
    """
    if material not in MATERIALS:
        raise ValueError(
            f"Unknown material '{material}'. Use list_materials for options."
        )
    m = MATERIALS[material]
    out = beam_modes(
        length, width, thickness, m["E"], m["rho"],
        end_condition=end_condition, n_modes=n_modes,
    )
    return json.dumps(
        {
            "material": material,
            "end_condition": out.end_condition,
            "bending_axis": out.bending_axis,
            "second_moment_m4": out.second_moment_m4,
            "frequencies_hz": [round(f, 4) for f in out.frequencies_hz],
        },
        indent=2,
    )


@mcp.tool()
def beam_length_for_target_frequency(
    target_hz: float,
    width: float,
    thickness: float,
    material: str = "structural_steel",
    end_condition: Literal[
        "cantilever", "fixed-fixed", "simply-supported", "free-free"
    ] = "cantilever",
    mode: int = 1,
) -> str:
    """Beam length (SI metres) that puts the n-th bending mode at ``target_hz``."""
    if material not in MATERIALS:
        raise ValueError(f"Unknown material '{material}'.")
    m = MATERIALS[material]
    L = beam_length_for_frequency(
        target_hz, width, thickness, m["E"], m["rho"],
        mode=mode, end_condition=end_condition,
    )
    return json.dumps(
        {
            "length_m": round(L, 6),
            "target_hz": target_hz,
            "mode": mode,
            "end_condition": end_condition,
            "material": material,
            "width_m": width,
            "thickness_m": thickness,
        },
        indent=2,
    )


@mcp.tool()
def plate_modes(
    a: float,
    b: float,
    h: float,
    material: str = "structural_steel",
    m_max: int = 3,
    n_max: int = 3,
) -> str:
    """Natural frequencies (Hz) of a thin simply-supported rectangular plate."""
    if material not in MATERIALS:
        raise ValueError(f"Unknown material '{material}'.")
    M = MATERIALS[material]
    out = plate_modes_simply_supported(
        a, b, h, M["E"], M["nu"], M["rho"], m_max=m_max, n_max=n_max,
    )
    return json.dumps(
        {
            "material": material,
            "boundary": out.boundary,
            "flexural_rigidity": out.flexural_rigidity,
            "modes": [
                {"m": m, "n": n, "f_hz": round(f, 4)}
                for (m, n, f) in out.modes
            ],
        },
        indent=2,
    )


# ---------------------------------------------------------------------------
# Design intent (descriptions, image interpretations, vibrational targets)
# ---------------------------------------------------------------------------

@mcp.tool()
def record_design_intent(
    description: str,
    source: Literal["user_text", "image", "vibrational", "other"] = "user_text",
) -> str:
    """Record a free-text description of design intent.

    Use this whenever the model has just interpreted a user-supplied image,
    natural-language description, or vibrational target. The note is rendered
    as a comment in the generated Salome script for traceability.
    """
    SESSION.add_note(f"[{source}] {description}")
    return f"Recorded {source} intent ({len(description)} chars)."


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
