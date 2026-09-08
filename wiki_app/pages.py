"""페이지 로더 — frontmatter + 본문 + graph 메타데이터."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import frontmatter


logger = logging.getLogger(__name__)


class PageNotFound(Exception):
    pass


_CATEGORIES = ("concepts", "tools", "people", "projects", "business", "lecture", "insights")


def find_page_path(slug: str, wiki_root: Path) -> Path:
    """slug에 해당하는 마크다운 파일을 카테고리 폴더에서 찾는다.

    path traversal 방어: resolved candidate가 wiki_root 밖으로 나가면
    (예: slug="../../CLAUDE") 파일이 실재해도 무시하고 계속 탐색한다.
    정당한 중첩 slug("260515_llm_wiki/prd" 등 '/' 포함)는 wiki_root 안이므로 허용된다.
    """
    root_resolved = wiki_root.resolve()
    for cat in _CATEGORIES:
        candidate = wiki_root / cat / f"{slug}.md"
        if not candidate.resolve().is_relative_to(root_resolved):
            continue
        if candidate.exists():
            return candidate
    raise PageNotFound(f"slug not found: {slug}")


def _load_graph(wiki_root: Path) -> dict:
    """graph.json을 로드하고 slug → node 매핑을 만든다."""
    graph_path = wiki_root / "graph.json"
    if not graph_path.exists():
        return {}
    graph = json.loads(graph_path.read_text())
    return {n["id"]: n for n in graph["nodes"] if n.get("kind") == "page"}


def load_page(slug: str, wiki_root: Path) -> dict:
    """페이지 데이터를 dict로 반환한다.

    frontmatter(YAML) 파싱 실패는 PageNotFound로 격리한다 — 깨진 한 페이지가
    API를 HTTP 500으로 떨어뜨리지 않고 404로 graceful 처리되도록.
    """
    path = find_page_path(slug, wiki_root)
    try:
        post = frontmatter.load(path)
    except Exception as e:
        logger.warning("frontmatter parse failed for %s (%s): %s", slug, path, e)
        raise PageNotFound(f"invalid page (frontmatter parse error): {slug}") from e
    graph_nodes = _load_graph(wiki_root)
    node = graph_nodes.get(slug, {})
    return {
        "slug": slug,
        "category": path.relative_to(wiki_root).parts[0],
        "frontmatter": post.metadata,
        "body_md": post.content,
        "inbound": node.get("inbound", 0),
        "outbound": node.get("outbound", 0),
    }
