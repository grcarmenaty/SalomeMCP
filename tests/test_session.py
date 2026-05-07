from pathlib import Path

import pytest

from salome_mcp.session import GeomEntry, Session, to_var


def test_to_var_sanitises():
    assert to_var("box-1") == "box_1"
    assert to_var("3legs") == "_3legs"
    assert to_var("hello world") == "hello_world"
    with pytest.raises(ValueError):
        to_var("")
    with pytest.raises(ValueError):
        to_var("   ")


def test_add_object_appends_addToStudy():
    s = Session()
    s.add_object(
        "box1", "box", {"dx": 1, "dy": 2, "dz": 3},
        ["{var} = geompy.MakeBox(0,0,0,1,2,3)"],
    )
    code = s.objects["box1"].code
    assert "geompy.MakeBox(0,0,0,1,2,3)" in code
    assert "geompy.addToStudy(box1, 'box1')" in code


def test_duplicate_object_name_rejected():
    s = Session()
    s.add_object("a", "box", {}, ["{var} = geompy.MakeBoxDXDYDZ(1,1,1)"])
    with pytest.raises(ValueError):
        s.add_object("a", "box", {}, ["{var} = geompy.MakeBoxDXDYDZ(1,1,1)"])


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


def test_render_script_has_imports_and_objects():
    s = Session()
    s.add_object("b", "box", {}, ["{var} = geompy.MakeBoxDXDYDZ(1,1,1)"])
    s.add_note("design intent")
    text = s.render_script()
    assert "salome.salome_init()" in text
    assert "geompy = geomBuilder.New()" in text
    assert "smesh = smeshBuilder.New()" in text
    assert "design intent" in text
    assert "geompy.MakeBoxDXDYDZ" in text


def test_export_lines_emitted():
    s = Session()
    s.add_object("b", "box", {}, ["{var} = geompy.MakeBoxDXDYDZ(1,1,1)"])
    s.add_export("step", "b", "/tmp/b.step")
    s.add_export("stl", "b", "/tmp/b.stl")
    text = s.render_script()
    assert "ExportSTEP(b, '/tmp/b.step', GEOM.LU_METER)" in text
    assert "ExportSTL(b, '/tmp/b.stl', True)" in text


def test_save_load_roundtrip(tmp_path: Path):
    s = Session(workdir=tmp_path)
    s.add_object(
        "b", "box", {"dx": 1.0},
        ["{var} = geompy.MakeBoxDXDYDZ(1,1,1)"],
    )
    s.add_note("hello")
    s.add_export("step", "b", str(tmp_path / "b.step"))
    p = tmp_path / "session.json"
    s.save(p)

    loaded = Session.load(p)
    assert "b" in loaded.objects
    assert isinstance(loaded.objects["b"], GeomEntry)
    assert loaded.notes == ["hello"]
    assert loaded.exports[0]["kind"] == "step"


def test_fresh_var_resolves_collisions():
    s = Session()
    s.add_object("part-A", "box", {}, ["{var} = geompy.MakeBoxDXDYDZ(1,1,1)"])
    # different name that sanitises to the same identifier should still get
    # a unique python variable.
    var2 = s.fresh_var("part-A")
    assert var2 != s.objects["part-A"].var


def test_require_lists_existing_on_error():
    s = Session()
    s.add_object("box1", "box", {}, ["{var} = geompy.MakeBoxDXDYDZ(1,1,1)"])
    with pytest.raises(KeyError) as exc:
        s.require("missing")
    assert "box1" in str(exc.value)
