import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
from canvas_utils import (
    build_neighborhood_canvas,
    save_canvas,
    compute_delta,
    build_delta_canvas,
)


# ── Neighborhood canvas ────────────────────────────────────────────────

def test_neighborhood_center_node_color(graph_stub):
    """중앙 노드는 color='4' (green)."""
    canvas = build_neighborhood_canvas(graph_stub, "alpha")
    nodes_by_id = {n["id"]: n for n in canvas["nodes"]}
    assert nodes_by_id["alpha"]["color"] == "4"


def test_neighborhood_center_fixed_at_origin(graph_stub):
    """중앙 노드는 (0,0)에 고정되어야 한다 (spring layout fixed)."""
    canvas = build_neighborhood_canvas(graph_stub, "alpha")
    center = next(n for n in canvas["nodes"] if n["id"] == "alpha")
    assert center["x"] == 0
    assert center["y"] == 0


def test_neighborhood_includes_inbound_outbound(graph_stub):
    """inbound, outbound 노드가 모두 canvas에 포함되어야 한다."""
    canvas = build_neighborhood_canvas(graph_stub, "alpha")
    ids = {n["id"] for n in canvas["nodes"]}
    # beta, gamma → alpha (inbound)
    assert "beta" in ids
    assert "gamma" in ids


def test_neighborhood_edges_present(graph_stub):
    """wikilink 엣지가 모두 표시되어야 한다."""
    canvas = build_neighborhood_canvas(graph_stub, "alpha")
    pairs = {(e["fromNode"], e["toNode"]) for e in canvas["edges"]}
    assert ("beta", "alpha") in pairs
    assert ("alpha", "gamma") in pairs


def test_neighborhood_max_5_inbound(graph_stub):
    """inbound 노드가 5개를 초과하면 상위 5개만 포함."""
    for i in range(6):
        node_id = f"in{i}"
        graph_stub["nodes"].append({
            "id": node_id, "kind": "page", "title": node_id,
            "type": "concept", "category": "concepts", "domain": [], "tags": [],
            "inbound": i, "outbound": 0,
        })
        graph_stub["links"].append({"source": node_id, "target": "alpha", "kind": "wikilink"})
    canvas = build_neighborhood_canvas(graph_stub, "alpha")
    inbound_in_canvas = [n["id"] for n in canvas["nodes"] if n["id"].startswith("in")]
    assert len(inbound_in_canvas) <= 5


def test_save_canvas(graph_stub, tmp_path):
    canvas = build_neighborhood_canvas(graph_stub, "alpha")
    out = tmp_path / "test.canvas"
    save_canvas(canvas, out)
    loaded = json.loads(out.read_text())
    assert "nodes" in loaded
    assert "edges" in loaded


def test_neighborhood_missing_slug(graph_stub):
    assert build_neighborhood_canvas(graph_stub, "nonexistent-slug") is None


def test_neighborhood_tag_nodes_excluded(graph_stub):
    """tag 노드는 center로 지정할 수 없어야 한다."""
    assert build_neighborhood_canvas(graph_stub, "delta-tag") is None


def test_neighborhood_layout_is_deterministic(graph_stub):
    """같은 입력은 같은 좌표를 생성해야 한다 (seed 고정)."""
    c1 = build_neighborhood_canvas(graph_stub, "alpha")
    c2 = build_neighborhood_canvas(graph_stub, "alpha")
    coords1 = {n["id"]: (n["x"], n["y"]) for n in c1["nodes"]}
    coords2 = {n["id"]: (n["x"], n["y"]) for n in c2["nodes"]}
    assert coords1 == coords2


# ── compute_delta ─────────────────────────────────────────────────────

def test_compute_delta_new_nodes(graph_stub):
    prev = {"nodes": [], "links": []}
    delta = compute_delta(graph_stub, prev)
    new_ids = {n["id"] for n in delta["new_nodes"]}
    assert "alpha" in new_ids
    assert "beta" in new_ids


def test_compute_delta_removed_nodes(graph_stub):
    prev = json.loads(json.dumps(graph_stub))
    prev["nodes"].append({
        "id": "old-page", "kind": "page", "title": "Old",
        "type": "concept", "category": "concepts", "domain": [], "tags": [],
        "inbound": 0, "outbound": 0,
    })
    delta = compute_delta(graph_stub, prev)
    assert "old-page" in {n["id"] for n in delta["removed_nodes"]}


def test_compute_delta_excludes_ghost_from_removed(graph_stub):
    prev = json.loads(json.dumps(graph_stub))
    prev["nodes"].append({
        "id": "ghost-1", "kind": "ghost", "title": "Ghost",
        "type": None, "category": None, "domain": [], "tags": [],
        "inbound": 0, "outbound": 0,
    })
    delta = compute_delta(graph_stub, prev)
    assert "ghost-1" not in {n["id"] for n in delta["removed_nodes"]}


def test_compute_delta_updated_nodes(graph_stub):
    prev = json.loads(json.dumps(graph_stub))
    for n in prev["nodes"]:
        if n["id"] == "alpha":
            n["inbound"] = 0
    delta = compute_delta(graph_stub, prev)
    assert "alpha" in {n["id"] for n in delta["updated_nodes"]}


def test_compute_delta_new_edges(graph_stub):
    prev = {"nodes": list(graph_stub["nodes"]), "links": []}
    delta = compute_delta(graph_stub, prev)
    assert len(delta["new_edges"]) == len(graph_stub["links"])


# ── Delta canvas ──────────────────────────────────────────────────────

def test_build_delta_canvas_returns_none_when_no_new_nodes(graph_stub):
    """신규 노드 없으면 None (갱신만 있어도 None)."""
    same = json.loads(json.dumps(graph_stub))
    assert build_delta_canvas(graph_stub, same) is None

    prev_with_updated_only = json.loads(json.dumps(graph_stub))
    for n in prev_with_updated_only["nodes"]:
        if n["id"] == "alpha":
            n["inbound"] = 0
    assert build_delta_canvas(graph_stub, prev_with_updated_only) is None


def test_build_delta_canvas_new_node_color(graph_stub):
    """신규 노드 color='3' (yellow)."""
    prev = {"nodes": [], "links": []}
    canvas = build_delta_canvas(graph_stub, prev)
    assert canvas is not None
    new_node = next(n for n in canvas["nodes"] if n["id"] == "alpha")
    assert new_node["color"] == "3"


def test_build_delta_canvas_excludes_updated_nodes(graph_stub):
    """갱신 노드는 신규 자격(color='3')으로 들어가지 않아야 한다."""
    prev = {
        "nodes": [
            {"id": "alpha", "kind": "page", "title": "Alpha", "type": "concept",
             "category": "concepts", "domain": [], "tags": [], "inbound": 0, "outbound": 0},
            {"id": "beta",  "kind": "page", "title": "Beta",  "type": "concept",
             "category": "concepts", "domain": [], "tags": [], "inbound": 1, "outbound": 0},
        ],
        "links": [],
    }
    canvas = build_delta_canvas(graph_stub, prev)
    assert canvas is not None
    canvas_ids = {n["id"] for n in canvas["nodes"]}
    assert "gamma" in canvas_ids  # 신규
    if "alpha" in canvas_ids:
        alpha_node = next(n for n in canvas["nodes"] if n["id"] == "alpha")
        assert alpha_node.get("color") != "3"


def test_build_delta_canvas_neighbor_dedup(graph_stub):
    """같은 노드가 여러 신규의 이웃이어도 한 번만 표시."""
    prev = {
        "nodes": [
            {"id": "gamma", "kind": "page", "title": "Gamma", "type": "concept",
             "category": "concepts", "domain": [], "tags": [], "inbound": 0, "outbound": 0},
        ],
        "links": [],
    }
    canvas = build_delta_canvas(graph_stub, prev)
    assert canvas is not None
    gamma_nodes = [n for n in canvas["nodes"] if n["id"] == "gamma"]
    assert len(gamma_nodes) == 1


def test_build_delta_canvas_includes_internal_edges(graph_stub):
    """신규-신규 엣지도 포함되어야 한다."""
    prev = {
        "nodes": [
            {"id": "gamma", "kind": "page", "title": "Gamma", "type": "concept",
             "category": "concepts", "domain": [], "tags": [], "inbound": 0, "outbound": 0},
        ],
        "links": [],
    }
    canvas = build_delta_canvas(graph_stub, prev)
    assert canvas is not None
    edge_pairs = {(e["fromNode"], e["toNode"]) for e in canvas["edges"]}
    assert ("beta", "alpha") in edge_pairs
    assert ("alpha", "gamma") in edge_pairs
    assert ("gamma", "alpha") in edge_pairs


def test_build_delta_canvas_layout_is_deterministic(graph_stub):
    """같은 입력은 같은 좌표를 생성해야 한다."""
    prev = {"nodes": [], "links": []}
    c1 = build_delta_canvas(graph_stub, prev)
    c2 = build_delta_canvas(graph_stub, prev)
    coords1 = {n["id"]: (n["x"], n["y"]) for n in c1["nodes"]}
    coords2 = {n["id"]: (n["x"], n["y"]) for n in c2["nodes"]}
    assert coords1 == coords2
