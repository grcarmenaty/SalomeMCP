"""In-memory session state for SalomeMCP.

Each tool call records a ``GeomEntry``, ``GroupEntry``, or ``MeshEntry`` that
carries the fragment of Salome Python it should emit. ``render_script()``
stitches everything together into a runnable ``salome -t`` script that
produces artefacts compatible with the
`pymodal <https://github.com/grcarmenaty/pymodal>`_ pipeline (MED mesh with
named groups, companion ``nodes.json`` and ``groups.json``).
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal, Optional

_SAFE = re.compile(r"[^A-Za-z0-9_]")

SpaceUnits = Literal["millimeter", "meter"]
ShapeType = Literal["FACE", "EDGE", "VERTEX", "SOLID"]

_GEOM_LU = {"millimeter": "GEOM.LU_MILLIMETER", "meter": "GEOM.LU_METER"}
_SMESH_TYPE = {
    "FACE":   "SMESH.FACE",
    "EDGE":   "SMESH.EDGE",
    "VERTEX": "SMESH.NODE",
    "SOLID":  "SMESH.VOLUME",
}


def to_var(name: str) -> str:
    """Turn a user-facing name into a safe Python identifier."""
    if not name or not name.strip():
        raise ValueError("Object name must be a non-empty string.")
    var = _SAFE.sub("_", name.strip())
    if var[0].isdigit():
        var = "_" + var
    return var


@dataclass
class GeomEntry:
    name: str
    var: str
    kind: str
    params: dict[str, Any]
    code: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GroupEntry:
    """A named sub-shape (face / edge / vertex / solid) attached to a parent."""
    name: str
    var: str
    parent: str
    shape_type: ShapeType
    code: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MeshEntry:
    name: str
    var: str
    geometry: str
    inherited_groups: list[str]
    params: dict[str, Any]
    code: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Session:
    workdir: Path = field(default_factory=lambda: Path.cwd() / ".salome_mcp")
    space_units: SpaceUnits = "millimeter"
    objects: dict[str, GeomEntry] = field(default_factory=dict)
    groups: dict[str, GroupEntry] = field(default_factory=dict)
    meshes: dict[str, MeshEntry] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    exports: list[dict[str, Any]] = field(default_factory=list)

    # ----- bookkeeping -----
    def reset(self) -> None:
        self.objects.clear()
        self.groups.clear()
        self.meshes.clear()
        self.notes.clear()
        self.exports.clear()

    def require(self, name: str) -> GeomEntry:
        if name not in self.objects:
            existing = ", ".join(sorted(self.objects)) or "(none)"
            raise KeyError(f"Object '{name}' not found. Existing: {existing}")
        return self.objects[name]

    def fresh_var(self, base: str) -> str:
        var = to_var(base)
        used = (
            {e.var for e in self.objects.values()}
            | {g.var for g in self.groups.values()}
            | {m.var for m in self.meshes.values()}
        )
        if var not in used:
            return var
        i = 1
        while f"{var}_{i}" in used:
            i += 1
        return f"{var}_{i}"

    def _check_unique_name(self, name: str) -> None:
        if name in self.objects:
            raise ValueError(f"Name '{name}' is already used by a geometry.")
        if name in self.groups:
            raise ValueError(f"Name '{name}' is already used by a group.")
        if name in self.meshes:
            raise ValueError(f"Name '{name}' is already used by a mesh.")

    def set_units(self, units: SpaceUnits) -> None:
        if units not in ("millimeter", "meter"):
            raise ValueError(f"Unknown units '{units}'. Use 'millimeter' or 'meter'.")
        self.space_units = units

    # ----- mutations -----
    def add_object(
        self,
        name: str,
        kind: str,
        params: dict[str, Any],
        code_lines: Iterable[str],
    ) -> GeomEntry:
        self._check_unique_name(name)
        var = self.fresh_var(name)
        rendered = [ln.replace("{var}", var) for ln in code_lines]
        rendered.append(f"geompy.addToStudy({var}, {name!r})")
        entry = GeomEntry(
            name=name, var=var, kind=kind,
            params=params, code="\n".join(rendered),
        )
        self.objects[name] = entry
        return entry

    def add_group(
        self,
        name: str,
        parent: str,
        shape_type: ShapeType,
        code_lines: Iterable[str],
        params: Optional[dict[str, Any]] = None,
    ) -> GroupEntry:
        self._check_unique_name(name)
        if parent not in self.objects:
            raise KeyError(
                f"Parent geometry '{parent}' not found. "
                f"Existing: {sorted(self.objects) or '(none)'}"
            )
        if shape_type not in {"FACE", "EDGE", "VERTEX", "SOLID"}:
            raise ValueError(
                f"shape_type must be FACE/EDGE/VERTEX/SOLID, got {shape_type!r}."
            )
        var = self.fresh_var(f"grp_{name}")
        parent_var = self.objects[parent].var
        rendered = []
        for ln in code_lines:
            rendered.append(
                ln.replace("{var}", var)
                  .replace("{parent_var}", parent_var)
                  .replace("{shape_type!r}", repr(shape_type))
                  .replace("{shape_type}", shape_type)
            )
        rendered.append(
            f"geompy.addToStudyInFather({parent_var}, {var}, {name!r})"
        )
        entry = GroupEntry(
            name=name, var=var, parent=parent,
            shape_type=shape_type, code="\n".join(rendered),
        )
        self.groups[name] = entry
        return entry

    def add_mesh(
        self,
        name: str,
        geometry: str,
        params: dict[str, Any],
        code_lines: Iterable[str],
        inherit_groups: Optional[Iterable[str]] = None,
    ) -> MeshEntry:
        self._check_unique_name(name)
        if geometry not in self.objects:
            raise KeyError(f"Geometry '{geometry}' does not exist.")
        inherit = list(inherit_groups or [])
        for gname in inherit:
            if gname not in self.groups:
                raise KeyError(f"Group '{gname}' does not exist.")
            g = self.groups[gname]
            if g.parent != geometry:
                raise ValueError(
                    f"Group '{gname}' is attached to '{g.parent}', "
                    f"not '{geometry}'; cannot inherit it on this mesh."
                )
        var = self.fresh_var(f"mesh_{name}")
        geom_var = self.objects[geometry].var
        rendered = []
        for ln in code_lines:
            rendered.append(
                ln.replace("{var}", var).replace("{geom_var}", geom_var)
            )
        for gname in inherit:
            g = self.groups[gname]
            smesh_t = _SMESH_TYPE[g.shape_type]
            rendered.append(
                f"{var}.GroupOnGeom({g.var}, {g.name!r}, {smesh_t})"
            )
        rendered.append(f"smesh.SetName({var}.GetMesh(), {name!r})")
        entry = MeshEntry(
            name=name, var=var, geometry=geometry,
            inherited_groups=inherit, params=params,
            code="\n".join(rendered),
        )
        self.meshes[name] = entry
        return entry

    def add_note(self, text: str) -> None:
        self.notes.append(text.replace("\n", " ").strip())

    def add_export(
        self,
        kind: str,
        source: str,
        path: str,
        options: Optional[dict[str, Any]] = None,
    ) -> None:
        self.exports.append(
            {"kind": kind, "source": source, "path": path,
             "options": dict(options or {})}
        )

    # ----- rendering -----
    def render_script(self) -> str:
        L: list[str] = []
        L.append("# Generated by SalomeMCP")
        L.append(f"# Units: {self.space_units}")
        L.append("# Run with:  salome -t this_script.py")
        L.append("import json, math, os, sys")
        L.append("import salome")
        L.append("salome.salome_init()")
        L.append("import GEOM")
        L.append("from salome.geom import geomBuilder")
        L.append("geompy = geomBuilder.New()")
        L.append("import SMESH")
        L.append("from salome.smesh import smeshBuilder")
        L.append("smesh = smeshBuilder.New()")
        L.append("")
        L.append("# Reference geometry")
        L.append("O  = geompy.MakeVertex(0, 0, 0)")
        L.append("OX = geompy.MakeVectorDXDYDZ(1, 0, 0)")
        L.append("OY = geompy.MakeVectorDXDYDZ(0, 1, 0)")
        L.append("OZ = geompy.MakeVectorDXDYDZ(0, 0, 1)")
        L.append("")

        if self.notes:
            L.append("# --- Design intent ---")
            for n in self.notes:
                L.append(f"# {n}")
            L.append("")

        if self.objects:
            L.append("# --- Geometry ---")
            for entry in self.objects.values():
                L.append(f"# {entry.kind}: {entry.name}")
                L.append(entry.code)
                L.append("")

        if self.groups:
            L.append("# --- Sub-shape groups (BC anchors / named features) ---")
            for entry in self.groups.values():
                L.append(f"# {entry.shape_type} group '{entry.name}' on {entry.parent}")
                L.append(entry.code)
                L.append("")

        if self.meshes:
            L.append("# --- Meshes ---")
            for entry in self.meshes.values():
                L.append(f"# mesh on {entry.geometry}"
                         + (f" inheriting {entry.inherited_groups}"
                            if entry.inherited_groups else ""))
                L.append(entry.code)
                L.append("")

        if self.exports:
            L.append("# --- Exports ---")
            for exp in self.exports:
                kind = exp["kind"]
                src = exp["source"]
                path = exp["path"]
                opts = exp.get("options", {}) or {}
                if kind == "step":
                    var = self.objects[src].var
                    unit = opts.get("space_units", self.space_units)
                    lu_e = _GEOM_LU[unit]
                    L.append(f"geompy.ExportSTEP({var}, {path!r}, {lu_e})")
                elif kind == "brep":
                    var = self.objects[src].var
                    L.append(f"geompy.ExportBREP({var}, {path!r})")
                elif kind == "stl":
                    var = self.objects[src].var
                    L.append(f"geompy.ExportSTL({var}, {path!r}, True)")
                elif kind == "med":
                    var = self.meshes[src].var
                    version = int(opts.get("version", 41))
                    auto = bool(opts.get("auto_groups", False))
                    L.append(
                        f"{var}.ExportMED({path!r}, "
                        f"auto_groups={auto}, version={version})"
                    )
                elif kind == "unv":
                    var = self.meshes[src].var
                    L.append(f"{var}.ExportUNV({path!r})")
                elif kind == "stl_mesh":
                    var = self.meshes[src].var
                    L.append(f"{var}.ExportSTL({path!r}, True)")
                elif kind == "nodes_json":
                    var = self.meshes[src].var
                    L.append(f"_ids = {var}.GetNodesId()")
                    L.append(
                        f"_dump = {{int(_n): list({var}.GetNodeXYZ(_n)) "
                        f"for _n in _ids}}"
                    )
                    L.append(f"with open({path!r}, 'w') as _fp:")
                    L.append(f"    json.dump(_dump, _fp)")
                    L.append(
                        f"print('nodes.json: %d nodes -> {path}' % len(_dump))"
                    )
                elif kind == "groups_json":
                    mesh = self.meshes[src]
                    group_names = list(opts.get("groups") or mesh.inherited_groups)
                    extras = dict(opts.get("extras") or {})
                    payload: dict[str, Any] = {
                        "groups": group_names,
                        "space_units": self.space_units,
                        "mesh": mesh.name,
                        "geometry": mesh.geometry,
                    }
                    payload.update(extras)
                    L.append(
                        f"with open({path!r}, 'w') as _fp:"
                    )
                    L.append(
                        f"    json.dump({json.dumps(payload)}, _fp, indent=2)"
                    )
                else:
                    L.append(f"# unknown export kind: {kind}")
            L.append("")

        L.append("if salome.sg.hasDesktop():")
        L.append("    salome.sg.updateObjBrowser()")
        L.append("")
        return "\n".join(L)

    # ----- persistence -----
    def to_dict(self) -> dict[str, Any]:
        return {
            "workdir": str(self.workdir),
            "space_units": self.space_units,
            "objects": {n: e.to_dict() for n, e in self.objects.items()},
            "groups":  {n: e.to_dict() for n, e in self.groups.items()},
            "meshes":  {n: e.to_dict() for n, e in self.meshes.items()},
            "notes":   list(self.notes),
            "exports": list(self.exports),
        }

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: Path) -> "Session":
        data = json.loads(Path(path).read_text())
        s = cls(
            workdir=Path(data.get("workdir", ".")),
            space_units=data.get("space_units", "millimeter"),
        )
        for n, d in data.get("objects", {}).items():
            s.objects[n] = GeomEntry(**d)
        for n, d in data.get("groups", {}).items():
            s.groups[n] = GroupEntry(**d)
        for n, d in data.get("meshes", {}).items():
            s.meshes[n] = MeshEntry(**d)
        s.notes = list(data.get("notes", []))
        s.exports = list(data.get("exports", []))
        return s
