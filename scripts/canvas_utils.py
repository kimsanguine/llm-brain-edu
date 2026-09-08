"""
canvas_utils.py — Obsidian Canvas JSON 생성 유틸 (force-directed 레이아웃)

공개 API:
  build_neighborhood_canvas(graph_data, slug) -> dict | None
  build_delta_canvas(current_graph, prev_graph) -> dict | None
  compute_delta(current, prev) -> dict
  save_canvas(canvas_data, path)
"""
import json
import math
from pathlib import Path

import networkx as nx


# ── 시각 상수 ────────────────────────────────────────────────
_NODE_W = 250
_NODE_H = 60
_CENTER_W = 300        # 쿼리 중심 노드는 약간 크게
_CENTER_H = 80
_MAX_NEIGHBORS = 5
_LAYOUT_SEED = 42      # spring_layout 결정적 시드

# Obsidian Canvas color: 1=red 2=orange 3=yellow 4=green 5=cyan 6=purple
_COLOR_QUERY_CENTER = "4"   # green
_COLOR_NEW_NODE     = "3"   # yellow


def _wiki_path(node: dict) -> str:
    category = node.get("category") or "concepts"
    return f"wiki/{category}/{node['id']}.md"


def _make_file_node(node_id: str, wiki_path: str, x: int, y: int,
                    color: str | None = None,
                    w: int = _NODE_W, h: int = _NODE_H) -> dict:
    n: dict = {
        "id": node_id,
        "type": "file",
        "file": wiki_path,
        "x": x,
        "y": y,
        "width": w,
        "height": h,
    }
    if color:
        n["color"] = color
    return n


def _make_edge(edge_id: str, from_node: str, to_node: str) -> dict:
    return {
        "id": edge_id,
        "fromNode": from_node,
        "toNode": to_node,
    }


def _force_layout(node_ids: list[str],
                  edges: list[tuple[str, str]],
                  fixed_center: str | None = None) -> dict[str, tuple[int, int]]:
    """
    Force-directed 레이아웃으로 노드 좌표를 계산한다.

    kamada_kawai를 1차로 사용하고, disconnected component 등으로 실패하면
    spring_layout으로 폴백한다. fixed_center가 지정되면 결과를 평행이동해
    해당 노드가 (0,0)에 오도록 정렬한다.

    Obsidian Canvas의 y축은 화면 좌표계(위가 음수)라 networkx y를 반전한다.
    """
    G = nx.Graph()
    for nid in node_ids:
        G.add_node(nid)
    for s, t in edges:
        if s in G and t in G and s != t:
            G.add_edge(s, t)

    n = max(len(node_ids), 1)
    scale = max(500, int(260 * n ** 0.5))

    pos: dict
    try:
        if G.number_of_edges() == 0:
            raise nx.NetworkXError("no edges, fall back to spring")
        pos = nx.kamada_kawai_layout(G, scale=scale)
    except (nx.NetworkXError, nx.NetworkXException, ImportError):
        # 분리 컴포넌트 / 엣지 없음 / scipy 부재 등 — spring으로 폴백
        init_pos: dict[str, tuple[float, float]] = {}
        for i, nid in enumerate(node_ids):
            angle = 2 * math.pi * i / max(n, 1)
            init_pos[nid] = (math.cos(angle), math.sin(angle))
        pos = nx.spring_layout(
            G, k=2.0 / (n ** 0.5), iterations=200,
            pos=init_pos, seed=_LAYOUT_SEED, scale=scale,
        )

    # fixed_center가 (0,0)에 오도록 전체 평행이동
    if fixed_center and fixed_center in pos:
        cx, cy = pos[fixed_center]
        pos = {nid: (p[0] - cx, p[1] - cy) for nid, p in pos.items()}

    # Obsidian 좌표계: 위쪽이 음수 → y 반전
    return {nid: (int(p[0]), int(-p[1])) for nid, p in pos.items()}


# ── Neighborhood canvas ──────────────────────────────────────

def build_neighborhood_canvas(graph_data: dict, slug: str) -> dict | None:
    """
    slug 노드의 1-depth 네이버후드를 force-directed 레이아웃으로 그린다.

    inbound/outbound 각 최대 _MAX_NEIGHBORS개, inbound_count 내림차순.
    slug가 page 노드로 graph에 없으면 None 반환.
    """
    nodes_by_id = {n["id"]: n for n in graph_data["nodes"] if n["kind"] == "page"}
    if slug not in nodes_by_id:
        return None

    links = graph_data.get("links", [])

    inbound_ids = [
        lnk["source"] for lnk in links
        if lnk["target"] == slug and lnk["source"] in nodes_by_id
    ]
    outbound_ids = [
        lnk["target"] for lnk in links
        if lnk["source"] == slug and lnk["target"] in nodes_by_id
    ]

    def _sort_key(nid: str) -> int:
        return nodes_by_id[nid].get("inbound", 0)

    inbound_ids  = sorted(set(inbound_ids),  key=_sort_key, reverse=True)[:_MAX_NEIGHBORS]
    outbound_ids = sorted(set(outbound_ids), key=_sort_key, reverse=True)[:_MAX_NEIGHBORS]

    canvas_node_ids = [slug] + [nid for nid in inbound_ids + outbound_ids if nid != slug]
    canvas_id_set = set(canvas_node_ids)

    edges_for_layout: list[tuple[str, str]] = []
    canvas_edges: list[dict] = []
    edge_idx = 0
    for lnk in links:
        if lnk.get("kind") != "wikilink":
            continue
        s, t = lnk["source"], lnk["target"]
        if s in canvas_id_set and t in canvas_id_set:
            edges_for_layout.append((s, t))
            canvas_edges.append(_make_edge(f"e-{edge_idx}", s, t))
            edge_idx += 1

    positions = _force_layout(canvas_node_ids, edges_for_layout, fixed_center=slug)

    canvas_nodes: list[dict] = []
    for nid in canvas_node_ids:
        x, y = positions[nid]
        if nid == slug:
            canvas_nodes.append(_make_file_node(
                nid, _wiki_path(nodes_by_id[nid]),
                x, y, _COLOR_QUERY_CENTER, w=_CENTER_W, h=_CENTER_H,
            ))
        else:
            canvas_nodes.append(_make_file_node(
                nid, _wiki_path(nodes_by_id[nid]), x, y,
            ))

    return {"nodes": canvas_nodes, "edges": canvas_edges}


# ── Delta canvas ────────────────────────────────────────────

def compute_delta(current: dict, prev: dict) -> dict:
    """
    두 graph_data를 비교해 delta를 반환한다.

    반환값:
      new_nodes:     prev에 없고 current에 있는 page 노드
      removed_nodes: current에 없고 prev에 있는 page 노드 (ghost 제외)
      updated_nodes: 두 그래프 모두 존재하며 inbound count가 변경된 page 노드
      new_edges:     prev에 없는 (source, target) 쌍
    """
    cur_pages = {n["id"]: n for n in current["nodes"] if n["kind"] == "page"}
    prv_pages = {n["id"]: n for n in prev["nodes"]    if n["kind"] == "page"}
    prv_ghosts = {n["id"] for n in prev["nodes"] if n["kind"] == "ghost"}

    new_nodes = [cur_pages[nid] for nid in cur_pages if nid not in prv_pages]
    removed_nodes = [
        prv_pages[nid] for nid in prv_pages
        if nid not in cur_pages and nid not in prv_ghosts
    ]
    updated_nodes = [
        cur_pages[nid] for nid in cur_pages
        if nid in prv_pages and cur_pages[nid]["inbound"] != prv_pages[nid]["inbound"]
    ]

    cur_edges = {(lnk["source"], lnk["target"]) for lnk in current.get("links", [])}
    prv_edges = {(lnk["source"], lnk["target"]) for lnk in prev.get("links", [])}
    new_edges = [{"source": s, "target": t} for s, t in cur_edges - prv_edges]

    return {
        "new_nodes":     new_nodes,
        "removed_nodes": removed_nodes,
        "updated_nodes": updated_nodes,
        "new_edges":     new_edges,
    }


def build_delta_canvas(current: dict, prev: dict) -> dict | None:
    """
    이번 ingest에서 추가된 신규 page 노드와, 그 노드들의 1-depth 이웃을
    union하여 force-directed 그래프로 그린다.

    갱신/제거 노드는 표시하지 않는다 (터미널 print_delta에서 확인).
    신규 노드가 없으면 None 반환.
    """
    delta = compute_delta(current, prev)
    new_nodes = delta["new_nodes"]
    if not new_nodes:
        return None

    cur_nodes_by_id = {n["id"]: n for n in current["nodes"] if n["kind"] == "page"}
    links = current.get("links", [])
    new_ids = {n["id"] for n in new_nodes}

    neighbor_ids: set[str] = set()
    for lnk in links:
        s, t = lnk["source"], lnk["target"]
        if s in new_ids and t in cur_nodes_by_id and t not in new_ids:
            neighbor_ids.add(t)
        if t in new_ids and s in cur_nodes_by_id and s not in new_ids:
            neighbor_ids.add(s)

    canvas_node_ids = sorted(new_ids) + sorted(neighbor_ids)
    canvas_id_set = set(canvas_node_ids)

    edges_for_layout: list[tuple[str, str]] = []
    canvas_edges: list[dict] = []
    edge_idx = 0
    for lnk in links:
        if lnk.get("kind") != "wikilink":
            continue
        s, t = lnk["source"], lnk["target"]
        if s in canvas_id_set and t in canvas_id_set:
            edges_for_layout.append((s, t))
            canvas_edges.append(_make_edge(f"e-{edge_idx}", s, t))
            edge_idx += 1

    positions = _force_layout(canvas_node_ids, edges_for_layout)

    canvas_nodes: list[dict] = []
    for nid in canvas_node_ids:
        x, y = positions[nid]
        color = _COLOR_NEW_NODE if nid in new_ids else None
        canvas_nodes.append(_make_file_node(
            nid,
            _wiki_path(cur_nodes_by_id[nid]) if nid in cur_nodes_by_id else f"wiki/{nid}.md",
            x, y, color,
        ))

    return {"nodes": canvas_nodes, "edges": canvas_edges}


# ── I/O ─────────────────────────────────────────────────────

def save_canvas(canvas_data: dict, path: Path) -> None:
    """canvas_data를 Obsidian Canvas JSON 파일로 저장한다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(canvas_data, ensure_ascii=False, indent=2))
