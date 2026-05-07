"""Tests for the pymodal-compatible bridge utilities.

These verify that ``nodes.json`` files written by SalomeMCP are consumable
with the same semantics pymodal uses (sorted by node id, JSON layout
``{"<node_id>": [x, y, z], ...}``, nearest-node selection by squared
Euclidean distance).
"""
import json
from pathlib import Path

import pytest

from salome_mcp.pymodal_bridge import (
    closest_node,
    closest_node_in_file,
    load_nodes_json,
)


def _write_nodes(path: Path, nodes: dict[int, tuple[float, float, float]]) -> Path:
    path.write_text(json.dumps({str(k): list(v) for k, v in nodes.items()}))
    return path


def test_load_nodes_json_sorted_by_id(tmp_path: Path):
    p = _write_nodes(tmp_path / "n.json", {3: (0, 0, 0), 1: (1, 0, 0), 2: (0, 1, 0)})
    ids, coords = load_nodes_json(p)
    assert ids == [1, 2, 3]
    assert coords[0] == (1.0, 0.0, 0.0)


def test_closest_node_picks_nearest():
    ids = [10, 11, 12]
    coords = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    nid, xyz = closest_node((0.9, 0.05, 0.0), ids, coords)
    assert nid == 11
    assert xyz == (1.0, 0.0, 0.0)


def test_closest_node_ties_take_lowest_index():
    ids = [4, 5]
    coords = [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)]
    nid, _ = closest_node((1.0, 1.0, 1.0), ids, coords)
    assert nid == 4


def test_closest_node_in_file_one_shot(tmp_path: Path):
    p = _write_nodes(tmp_path / "n.json", {1: (0, 0, 0), 2: (10, 0, 0)})
    out = closest_node_in_file(p, (8.0, 0.0, 0.0))
    assert out["node_id"] == 2
    assert out["xyz"] == [10.0, 0.0, 0.0]
    assert out["n_nodes"] == 2
    assert Path(out["nodes_json"]).name == "n.json"


def test_closest_node_empty_raises():
    with pytest.raises(ValueError):
        closest_node((0, 0, 0), [], [])


def test_compatible_with_pymodal_layout(tmp_path: Path):
    """The JSON layout matches what pymodal.scenarios.load_nodes_json reads."""
    nodes = {1: (0.0, 0.0, 0.0), 7: (1.5, 2.5, 3.5), 4: (-1.0, 0.0, 1.0)}
    p = _write_nodes(tmp_path / "compat.json", nodes)
    raw = json.loads(p.read_text())
    # Same shape as pymodal expects: dict keyed by stringified node id.
    assert all(isinstance(k, str) for k in raw)
    assert all(isinstance(v, list) and len(v) == 3 for v in raw.values())
    ids, coords = load_nodes_json(p)
    assert ids == [1, 4, 7]
    assert coords[2] == (1.5, 2.5, 3.5)
