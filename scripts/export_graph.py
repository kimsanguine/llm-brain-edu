#!/usr/bin/env python3
"""export_graph.py — wiki/ wikilink 그래프를 D3 force-graph용 JSON으로 export.

Producer 역할: wiki/ 파일을 읽어 graph.json만 생성한다.
Consumer(habix.ai 빌드, universe.habix.ai 등)는 이 JSON을 소비한다.

노드 종류 (kind):
  - "page":  wiki/ 정제 페이지 (frontmatter title 있음)
  - "tag":   wiki 페이지가 부여한 #태그 (slug: "tag:<name>")
  - "ghost": wikilink로 참조되지만 wiki/에 페이지 없는 슬러그

엣지:
  - page → page : 본문 [[wikilink]]
  - page → tag  : 페이지가 해당 태그를 가짐
  - page → ghost: 페이지가 미정제 wikilink 참조

출력: wiki/graph.json
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

WIKI_DIR = Path(__file__).resolve().parent.parent / "wiki"
OUTPUT = WIKI_DIR / "graph.json"

META_FILES = {"graph_report.md", "distill_queue.md", "index.md"}

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:#[^\]|]*)?(?:\|[^\]]+)?\]\]")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

TAG_PREFIX = "tag:"
GHOST_PREFIX = "ghost:"


def parse_frontmatter(text: str) -> dict:
    """최소 YAML frontmatter 파서. PyYAML 의존 회피."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    fm: dict = {}
    current_list: list | None = None
    for line in m.group(1).split("\n"):
        line = line.rstrip()
        if not line:
            continue
        if line.startswith("- ") and current_list is not None:
            current_list.append(_unquote(line[2:].strip()))
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            current_list = None
            if not val:
                fm[key] = []
                current_list = fm[key]
            elif val.startswith("[") and val.endswith("]"):
                inner = val[1:-1].strip()
                fm[key] = [_unquote(i.strip()) for i in inner.split(",") if i.strip()]
            else:
                fm[key] = _unquote(val)
    return fm


def _unquote(s: str) -> str:
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("\"", "'"):
        return s[1:-1]
    return s


def extract_wikilinks(text: str) -> set[str]:
    body = FRONTMATTER_RE.sub("", text, count=1)
    return set(WIKILINK_RE.findall(body))


def main() -> int:
    if not WIKI_DIR.is_dir():
        print(f"[export_graph] ERROR: wiki dir not found: {WIKI_DIR}", file=sys.stderr)
        return 1

    # 1) wiki 페이지 수집
    pages: dict[str, dict] = {}
    raw_out_links: dict[str, set[str]] = {}
    raw_tags: dict[str, list[str]] = {}

    for md in WIKI_DIR.rglob("*.md"):
        if md.parent == WIKI_DIR and md.name in META_FILES:
            continue
        text = md.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        if not fm or "title" not in fm:
            continue

        rel = md.relative_to(WIKI_DIR)
        category = rel.parts[0] if len(rel.parts) > 1 else "root"
        # subpath slug 지원: wiki/projects/260515_llm_wiki/prd.md → "260515_llm_wiki/prd"
        # (그렇지 않으면 wikilink [[260515_llm_wiki/prd]]가 ghost로 잡힘)
        if len(rel.parts) > 2:
            slug = "/".join(list(rel.parts[1:-1]) + [md.stem])
        else:
            slug = md.stem
        domain = fm.get("domain", [])
        if isinstance(domain, str):
            domain = [domain] if domain else []
        tags = fm.get("tags", []) if isinstance(fm.get("tags"), list) else []

        pages[slug] = {
            "id": slug,
            "kind": "page",
            "title": fm.get("title", slug),
            "type": fm.get("type", "unknown"),
            "category": category,
            "domain": domain,
            "tags": tags,
        }
        raw_out_links[slug] = extract_wikilinks(text)
        raw_tags[slug] = tags

    # 2) 태그·ghost 노드 채집
    tag_nodes: dict[str, dict] = {}
    ghost_nodes: dict[str, dict] = {}

    for slug, tags in raw_tags.items():
        for t in tags:
            if not t:
                continue
            tid = f"{TAG_PREFIX}{t}"
            tag_nodes.setdefault(tid, {
                "id": tid,
                "kind": "tag",
                "title": f"#{t}",
                "type": "tag",
                "category": "tag",
                "domain": [],
                "tags": [],
            })

    def resolve_link(tgt: str) -> str | None:
        """wikilink target → 실제 페이지 slug. Obsidian 스타일 basename fallback 지원.

        예: [[prd]] 단축형 → 유일한 subpath page "260515_llm_wiki/prd" 매칭.
        모호한 매칭(2개 이상)은 ghost로 fall through.
        """
        if tgt in pages:
            return tgt
        matches = [p for p in pages if p.endswith("/" + tgt)]
        if len(matches) == 1:
            return matches[0]
        return None

    for slug, targets in raw_out_links.items():
        for tgt in targets:
            if tgt == slug:
                continue
            if resolve_link(tgt) is not None:
                continue
            gid = f"{GHOST_PREFIX}{tgt}"
            ghost_nodes.setdefault(gid, {
                "id": gid,
                "kind": "ghost",
                "title": tgt,
                "type": "ghost",
                "category": "ghost",
                "domain": [],
                "tags": [],
            })

    # 3) 엣지 빌드
    nodes_by_id: dict[str, dict] = {}
    for d in (pages, tag_nodes, ghost_nodes):
        nodes_by_id.update(d)

    inbound = {nid: 0 for nid in nodes_by_id}
    outbound = {nid: 0 for nid in nodes_by_id}
    edges: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    def add_edge(src: str, tgt: str, kind: str) -> None:
        if src == tgt or src not in nodes_by_id or tgt not in nodes_by_id:
            return
        key = (src, tgt, kind)
        if key in seen:
            return
        seen.add(key)
        edges.append({"source": src, "target": tgt, "kind": kind})
        inbound[tgt] += 1
        outbound[src] += 1

    # page → page / page → ghost (basename fallback 적용)
    for src, targets in raw_out_links.items():
        for tgt in targets:
            resolved = resolve_link(tgt)
            if resolved is not None:
                add_edge(src, resolved, "wikilink")
            else:
                add_edge(src, f"{GHOST_PREFIX}{tgt}", "ghost")

    # page → tag
    for src, tags in raw_tags.items():
        for t in tags:
            if t:
                add_edge(src, f"{TAG_PREFIX}{t}", "tag")

    # 4) 노드 메타 finalize
    for nid, meta in nodes_by_id.items():
        meta["inbound"] = inbound[nid]
        meta["outbound"] = outbound[nid]

    nodes = sorted(nodes_by_id.values(), key=lambda n: -n["inbound"])

    # 5) 통계
    kinds: dict[str, int] = {}
    types: dict[str, int] = {}
    domains: dict[str, int] = {}
    edge_kinds: dict[str, int] = {}
    for n in nodes:
        kinds[n["kind"]] = kinds.get(n["kind"], 0) + 1
        if n["kind"] == "page":
            types[n["type"]] = types.get(n["type"], 0) + 1
            for d in n["domain"]:
                if d:
                    domains[d] = domains.get(d, 0) + 1
    for e in edges:
        edge_kinds[e["kind"]] = edge_kinds.get(e["kind"], 0) + 1

    result = {
        "meta": {
            "generated": datetime.now(timezone.utc).isoformat(),
            # total_pages 는 필드명대로 실제 page kind 노드 수만 센다.
            # 전체 노드 수(page+tag+ghost)는 total_nodes 로 분리해 노출한다.
            "total_pages": kinds.get("page", 0),
            "total_nodes": len(nodes),
            "total_links": len(edges),
            "kinds": kinds,
            "types": types,
            "domains": domains,
            "edge_kinds": edge_kinds,
        },
        "nodes": nodes,
        "links": edges,
    }

    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[export_graph] {len(nodes)} nodes, {len(edges)} edges → {OUTPUT}")
    print(f"  kinds: {kinds}")
    print(f"  page types: {types}")
    print(f"  edge kinds: {edge_kinds}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
