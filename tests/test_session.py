from pathlib import Path

import pytest

from salome_mcp.session import GeomEntry, GroupEntry, MeshEntry, Session, to_var


def test_to_var_sanitises():
    assert to_var("box-1") == "box_1"
    assert to_var("3legs") == "_3legs"
    assert to_var("hello world") == "hello_world"
    with pytest.raises(ValueError):
        to_var("")
    with pytest.raises(ValueError):
        to_var("   ")


def test_default_space_units_match_pymodal():
    s = Session()
    assert s.space_units == "millimeter"


def test_set_units_validates():
    s = Session()
    s.set_units("meter")
    assert s.space_units == "meter"
    with pytest.raises(ValueError):
        s.set_units("inch")


def test_add_object_appends_addToStudy():
    s = Session()
    s.add_object(
        "box1", "box", {"dx": 1, "dy": 2, "dz": 3},
        ["{var} = geompy.MakeBox(0,0,0,1,2,3)"],
    )
    code = s.objects["box1"].code
    assert "geompy.MakeBox(0,0,0,1,2,3)" in code
    assert "geompy.addToStudy(box1, 'box1')" in code


def test_duplicate_name_rejected_across_kinds():
    s = Session()
    s.add_object("a", "box", {}, ["{var} = geompy.MakeBoxDXDYDZ(1,1,1)"])
    with pytest.raises(ValueError):
        s.add_object("a", "box", {}, ["{var} = geompy.MakeBoxDXDYDZ(1,1,1)"])
    with pytest.raises(ValueError):
        s.add_group("a", "a", "FACE",
                    ["{var} = geompy.CreateGroup({parent_var}, "
                     "geompy.ShapeType[{shape_type!r}])"])


def test_add_mesh_requires_existing_geometry():
    s = Session()
    with pytest.raises(KeyError):
        s.add_mesh("m", "missing", {}, ["{var} = smesh.Mesh({geom_var})"])


def test_add_mesh_uses_geometry_var():
    s = Session()
    s.add_object("box1", "box", {}, ["{var} = geompy.MakeBoxDXDYDZ(1,1,1)"])
    s.add_mesh(
        "mesh1", "box1", {"max": 0.1},
        ["{var} = smesh.Mesh({geom_var})"],
    )
    code = s.meshes["mesh1"].code
    assert "smesh.Mesh(box1)" in code
    assert "smesh.SetName" in code


def test_render_script_has_imports_units_and_objects():
    s = Session()
    s.add_object("b", "box", {}, ["{var} = geompy.MakeBoxDXDYDZ(1,1,1)"])
    s.add_note("design intent")
    text = s.render_script()
    assert "salome.salome_init()" in text
    assert "geompy = geomBuilder.New()" in text
    assert "smesh = smeshBuilder.New()" in text
    assert "Units: millimeter" in text
    assert "import json" in text
    assert "design intent" in text
    assert "geompy.MakeBoxDXDYDZ" in text


def test_step_export_uses_session_units_default_mm():
    s = Session()
    s.add_object("b", "box", {}, ["{var} = geompy.MakeBoxDXDYDZ(1,1,1)"])
    s.add_export("step", "b", "/tmp/b.step")
    text = s.render_script()
    assert "ExportSTEP(b, '/tmp/b.step', GEOM.LU_MILLIMETER)" in text


def test_step_export_switches_to_meter():
    s = Session()
    s.set_units("meter")
    s.add_object("b", "box", {}, ["{var} = geompy.MakeBoxDXDYDZ(1,1,1)"])
    s.add_export("step", "b", "/tmp/b.step")
    text = s.render_script()
    assert "ExportSTEP(b, '/tmp/b.step', GEOM.LU_METER)" in text


def test_face_group_renders_and_attaches_to_parent():
    s = Session()
    s.add_object("plate", "box", {}, ["{var} = geompy.MakeBoxDXDYDZ(1,1,1)"])
    s.add_group(
        "base_rails", "plate", "FACE",
        [
            "_p = geompy.MakeVertex(0.5, 0.5, 0.0)",
            "_f = geompy.GetFaceNearPoint({parent_var}, _p)",
            "{var} = geompy.CreateGroup({parent_var}, "
            "geompy.ShapeType[{shape_type!r}])",
            "geompy.UnionList({var}, [_f])",
        ],
    )
    text = s.render_script()
    assert "GetFaceNearPoint(plate" in text
    assert "geompy.ShapeType['FACE']" in text
    assert "addToStudyInFather(plate, grp_base_rails, 'base_rails')" in text


def test_mesh_inherits_groups_into_med():
    s = Session()
    s.add_object("b", "box", {}, ["{var} = geompy.MakeBoxDXDYDZ(1,1,1)"])
    s.add_group(
        "rails", "b", "FACE",
        [
            "_p = geompy.MakeVertex(0,0,0)",
            "_f = geompy.GetFaceNearPoint({parent_var}, _p)",
            "{var} = geompy.CreateGroup({parent_var}, "
            "geompy.ShapeType[{shape_type!r}])",
            "geompy.UnionList({var}, [_f])",
        ],
    )
    s.add_mesh(
        "m", "b", {}, ["{var} = smesh.Mesh({geom_var})"],
        inherit_groups=["rails"],
    )
    text = s.render_script()
    assert "mesh_m.GroupOnGeom(grp_rails, 'rails', SMESH.FACE)" in text


def test_mesh_rejects_group_attached_to_other_geometry():
    s = Session()
    s.add_object("a", "box", {}, ["{var} = geompy.MakeBoxDXDYDZ(1,1,1)"])
    s.add_object("b", "box", {}, ["{var} = geompy.MakeBoxDXDYDZ(2,2,2)"])
    s.add_group(
        "g", "a", "FACE",
        [
            "{var} = geompy.CreateGroup({parent_var}, "
            "geompy.ShapeType[{shape_type!r}])"
        ],
    )
    with pytest.raises(ValueError):
        s.add_mesh(
            "m", "b", {}, ["{var} = smesh.Mesh({geom_var})"],
            inherit_groups=["g"],
        )


def test_med_export_with_options_v41_no_auto_groups():
    s = Session()
    s.add_object("b", "box", {}, ["{var} = geompy.MakeBoxDXDYDZ(1,1,1)"])
    s.add_mesh("m", "b", {}, ["{var} = smesh.Mesh({geom_var})"])
    s.add_export(
        "med", "m", "/tmp/m.med",
        options={"version": 41, "auto_groups": False},
    )
    text = s.render_script()
    assert (
        "mesh_m.ExportMED('/tmp/m.med', auto_groups=False, version=41)"
        in text
    )


def test_nodes_json_export_emits_dump_lines():
    s = Session()
    s.add_object("b", "box", {}, ["{var} = geompy.MakeBoxDXDYDZ(1,1,1)"])
    s.add_mesh("m", "b", {}, ["{var} = smesh.Mesh({geom_var})"])
    s.add_export("nodes_json", "m", "/tmp/nodes.json")
    text = s.render_script()
    assert "GetNodesId" in text
    assert "GetNodeXYZ" in text
    assert "json.dump(_dump, _fp)" in text


def test_groups_json_export_includes_inherited_and_extras():
    s = Session()
    s.add_object("b", "box", {}, ["{var} = geompy.MakeBoxDXDYDZ(1,1,1)"])
    s.add_group(
        "rails", "b", "FACE",
        ["{var} = geompy.CreateGroup({parent_var}, "
         "geompy.ShapeType[{shape_type!r}])"],
    )
    s.add_mesh(
        "m", "b", {}, ["{var} = smesh.Mesh({geom_var})"],
        inherit_groups=["rails"],
    )
    s.add_export(
        "groups_json", "m", "/tmp/g.json",
        options={"extras": {"rail_direction": "Y"}},
    )
    text = s.render_script()
    assert "/tmp/g.json" in text
    assert "rails" in text
    assert "rail_direction" in text


def test_save_load_roundtrip(tmp_path: Path):
    s = Session(workdir=tmp_path)
    s.set_units("meter")
    s.add_object(
        "b", "box", {"dx": 1.0},
        ["{var} = geompy.MakeBoxDXDYDZ(1,1,1)"],
    )
    s.add_group(
        "g", "b", "FACE",
        ["{var} = geompy.CreateGroup({parent_var}, "
         "geompy.ShapeType[{shape_type!r}])"],
    )
    s.add_mesh(
        "m", "b", {"max": 0.5},
        ["{var} = smesh.Mesh({geom_var})"], inherit_groups=["g"],
    )
    s.add_note("hello")
    s.add_export(
        "med", "m", str(tmp_path / "m.med"),
        options={"version": 41, "auto_groups": False},
    )
    p = tmp_path / "session.json"
    s.save(p)

    loaded = Session.load(p)
    assert loaded.space_units == "meter"
    assert isinstance(loaded.objects["b"], GeomEntry)
    assert isinstance(loaded.groups["g"], GroupEntry)
    assert isinstance(loaded.meshes["m"], MeshEntry)
    assert loaded.meshes["m"].inherited_groups == ["g"]
    assert loaded.notes == ["hello"]
    assert loaded.exports[0]["options"]["version"] == 41


def test_fresh_var_resolves_collisions():
    s = Session()
    s.add_object("part-A", "box", {}, ["{var} = geompy.MakeBoxDXDYDZ(1,1,1)"])
    var2 = s.fresh_var("part-A")
    assert var2 != s.objects["part-A"].var


def test_require_lists_existing_on_error():
    s = Session()
    s.add_object("box1", "box", {}, ["{var} = geompy.MakeBoxDXDYDZ(1,1,1)"])
    with pytest.raises(KeyError) as exc:
        s.require("missing")
    assert "box1" in str(exc.value)
