"""Bridge utilities between SalomeMCP-produced artefacts and pymodal.

These mirror :func:`pymodal.load_nodes_json` and :func:`pymodal.closest_node`
so an agent can resolve user-supplied ``(x, y, z)`` coordinates against a
Salome mesh **without** requiring pymodal to be installed. When pymodal *is*
installed, the implementations are equivalent (same JSON layout, same
nearest-node semantics).

Companion file conventions
--------------------------
The MCP emits, alongside a ``.med`` mesh, two JSON files that pymodal's
example pipelines (``examples/los_alamos_3story``) expect:

``nodes.json``  ``{"<node_id>": [x, y, z], ...}``
``groups.json`` ``{"groups": [...], "space_units": ..., "mesh": ..., ...}``

Coordinates in ``nodes.json`` are written in the session's ``space_units``
(``millimeter`` by default, matching pymodal's convention).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Sequence


def load_nodes_json(path: str | Path) -> tuple[list[int], list[tuple[float, float, float]]]:
    """Read a ``nodes.json`` file written by SalomeMCP / pymodal's salome_build.

    Returns ``(node_ids, coords)`` sorted by node id. The JSON layout
    ``{"<node_id>": [x, y, z], ...}`` is the same one pymodal expects, so
    the returned tuple is interoperable with ``pymodal.closest_node``.
    """
    with open(path) as fp:
        raw = json.load(fp)
    items = sorted((int(k), v) for k, v in raw.items())
    ids = [n for n, _ in items]
    coords = [tuple(float(c) for c in xyz) for _, xyz in items]
    return ids, coords


def closest_node(
    point: Sequence[float],
    node_ids: Sequence[int],
    coords: Sequence[Sequence[float]],
) -> tuple[int, tuple[float, float, float]]:
    """Return ``(node_id, (x, y, z))`` of the mesh node closest to ``point``.

    Uses squared Euclidean distance; ties go to the lowest-indexed node.
    """
    if len(node_ids) == 0:
        raise ValueError("node_ids is empty.")
    px, py, pz = (float(p) for p in point)
    best_i, best_d2 = 0, math.inf
    for i, xyz in enumerate(coords):
        x, y, z = float(xyz[0]), float(xyz[1]), float(xyz[2])
        d2 = (x - px) ** 2 + (y - py) ** 2 + (z - pz) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best_i = i
    chosen = coords[best_i]
    return int(node_ids[best_i]), (float(chosen[0]), float(chosen[1]), float(chosen[2]))


def closest_node_in_file(
    nodes_json_path: str | Path,
    point: Sequence[float],
) -> dict:
    """One-shot helper: read ``nodes.json`` and return the closest-node record."""
    ids, coords = load_nodes_json(nodes_json_path)
    nid, xyz = closest_node(point, ids, coords)
    return {
        "node_id": int(nid),
        "xyz": list(xyz),
        "query_xyz": [float(p) for p in point],
        "n_nodes": len(ids),
        "nodes_json": str(Path(nodes_json_path).resolve()),
    }
