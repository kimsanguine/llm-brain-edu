"""검색 인덱스 + B 알고리즘 (Task 3) + C 확장 (Task 4)."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter

from wiki_app import pages


logger = logging.getLogger(__name__)


@dataclass
class _Entry:
    slug: str
    category: str
    description: str  # index.md의 한 줄 설명
    page_title: str = ""  # frontmatter title (한국어 포함)
    tags: list[str] = field(default_factory=list)
    degree: int = 0  # inbound + outbound (정렬 tiebreaker)


# index.md 라인 예: "- [[habix-profile]] — 이든(김생근) 비즈니스 프로파일..."
_INDEX_LINE_RE = re.compile(r"^\s*-\s+\[\[([^\]]+)\]\]\s*—\s*(.*)$")
# 카테고리 헤더: "## concepts/ (20개)"
_INDEX_CAT_RE = re.compile(r"^##\s+(\w+)/")


class Index:
    def __init__(self, wiki_root: Path, by_slug: dict[str, _Entry]):
        self.wiki_root = wiki_root
        self.by_slug = by_slug
        self.total_pages = len(by_slug)

    @classmethod
    def build(cls, wiki_root: Path) -> "Index":
        """index.md + 각 페이지 frontmatter + graph.json 로드."""
        by_slug: dict[str, _Entry] = {}

        # 1. index.md에서 slug + category + description
        # index.md는 wiki_root의 부모(프로젝트 루트)에 위치.
        # index.md 부재 시(아직 ingest 전 / fresh project) FileNotFoundError 로
        # 부팅이 죽지 않도록 빈 인덱스(0 페이지)로 graceful 처리한다.
        index_path = wiki_root.parent / "index.md"
        if not index_path.exists():
            logger.warning(
                "index.md not found at %s — building empty index (0 pages)",
                index_path,
            )
            return cls(wiki_root=wiki_root, by_slug=by_slug)

        root_resolved = wiki_root.resolve()
        current_cat = "concepts"
        for line in index_path.read_text().splitlines():
            mcat = _INDEX_CAT_RE.match(line)
            if mcat:
                current_cat = mcat.group(1)
                continue
            m = _INDEX_LINE_RE.match(line)
            if m:
                slug = m.group(1).strip()
                desc = m.group(2).strip()
                # path traversal 차단: slug→path 가 wiki_root 밖으로 나가는
                # 엔트리(예: `[[../../secret]]` / 절대경로형 slug)는 아예 등록하지
                # 않는다. 등록하면 index.md 의 description 만으로도 검색 결과에
                # 떠 wiki 밖 존재를 노출하고, 이후 frontmatter/본문 read 의
                # 우회로가 된다. find_page_path 와 같은 is_relative_to 경계.
                candidate = wiki_root / current_cat / f"{slug}.md"
                if not candidate.resolve().is_relative_to(root_resolved):
                    logger.warning(
                        "skip index entry — slug resolves outside wiki_root "
                        "(possible path traversal): %s",
                        slug,
                    )
                    continue
                by_slug[slug] = _Entry(slug=slug, category=current_cat, description=desc)

        # 2. 각 페이지 frontmatter에서 tags + title 채움
        for entry in by_slug.values():
            # slug→path 는 containment-checked 로만 만든다. index.md 에
            # `[[../../secret]]` 같은 traversal slug 가 들어오면
            # find_page_path 가 resolve().is_relative_to(wiki_root) 로 거르고
            # PageNotFound 를 던지므로, 그 엔트리는 frontmatter 없이 skip 된다
            # (wiki_root 밖 파일을 읽어 title/tags 로 흡수하는 경로 차단).
            try:
                md_path = pages.find_page_path(entry.slug, wiki_root)
            except pages.PageNotFound:
                logger.warning(
                    "skip page in index build — slug not found or outside wiki_root "
                    "(possible path traversal): %s",
                    entry.slug,
                )
                continue
            if md_path.exists():
                # 한 페이지의 frontmatter(YAML) 파싱 실패가 전체 인덱스 빌드를
                # 크래시시키지 않도록 격리: 깨진 페이지는 tags/title 없이 skip,
                # index.md 기반 slug/category/description 은 유지된다.
                try:
                    post = frontmatter.load(md_path)
                except Exception as e:
                    logger.warning(
                        "skip page in index build — frontmatter parse failed for %s (%s): %s",
                        entry.slug, md_path, e,
                    )
                    continue
                tags = post.metadata.get("tags") or []
                entry.tags = [str(t).lower() for t in tags]
                entry.page_title = str(post.metadata.get("title") or "")

        # 3. graph.json에서 degree
        graph_path = wiki_root / "graph.json"
        if graph_path.exists():
            graph = json.loads(graph_path.read_text())
            for n in graph["nodes"]:
                if n.get("kind") == "page" and n["id"] in by_slug:
                    by_slug[n["id"]].degree = n.get("inbound", 0) + n.get("outbound", 0)

        return cls(wiki_root=wiki_root, by_slug=by_slug)

    def search(self, query: str) -> dict:
        """B 알고리즘: 제목+desc+tags 점수 매칭."""
        q = query.strip().lower()
        if not q:
            return {"query": query, "results": [], "expanded": False, "total": 0}

        scored: list[tuple[int, str, _Entry]] = []
        for entry in self.by_slug.values():
            score = 0
            matched = []
            if q in entry.slug.lower():
                score += 3
                matched.append("title")
            if entry.page_title and q in entry.page_title.lower():
                score += 3
                matched.append("page_title")
            if any(q in t for t in entry.tags):
                score += 2
                matched.append("tags")
            if q in entry.description.lower():
                score += 1
                matched.append("desc")
            if score > 0:
                scored.append((score, "+".join(matched), entry))

        # 점수 내림차순, 동점은 degree 내림차순
        scored.sort(key=lambda x: (-x[0], -x[2].degree, x[2].slug))

        results = [
            {
                "slug": e.slug,
                "category": e.category,
                "description": e.description,
                "score": score,
                "degree": e.degree,
                "match_type": match_type,
                "snippet": None,
            }
            for score, match_type, e in scored
        ]
        # B 결과가 3개 미만이면 C 확장 발동
        if len(results) < 3:
            existing_slugs = {r["slug"] for r in results}
            expanded_results = self._body_grep(q, existing_slugs)
            if expanded_results:
                basic_total = len(results)
                results.extend(expanded_results)
                return {
                    "query": query,
                    "results": results,
                    "expanded": True,
                    "basic_total": basic_total,
                    "total": len(results),
                }

        return {"query": query, "results": results, "expanded": False, "total": len(results)}

    def _body_grep(self, q: str, exclude: set[str]) -> list[dict]:
        """본문 grep으로 추가 매칭. snippet 포함."""
        out: list[dict] = []
        for entry in self.by_slug.values():
            if entry.slug in exclude:
                continue
            # build 와 동일 trust boundary: traversal slug 의 wiki_root 밖
            # 파일을 read_text 해 snippet 으로 노출하는 우회로(/api/search)를 막는다.
            try:
                md_path = pages.find_page_path(entry.slug, self.wiki_root)
            except pages.PageNotFound:
                logger.warning(
                    "skip body grep — slug not found or outside wiki_root "
                    "(possible path traversal): %s",
                    entry.slug,
                )
                continue
            if not md_path.exists():
                continue
            text = md_path.read_text().lower()
            idx = text.find(q)
            if idx < 0:
                continue
            # 80자 snippet 추출
            start = max(0, idx - 30)
            end = min(len(text), idx + 50)
            snippet_raw = md_path.read_text()[start:end].replace("\n", " ")
            out.append({
                "slug": entry.slug,
                "category": entry.category,
                "description": entry.description,
                "score": 0,  # 본문 매칭은 점수 시스템 외
                "degree": entry.degree,
                "match_type": "body",
                "snippet": snippet_raw,
            })
        # degree 내림차순으로 일부 정렬
        out.sort(key=lambda r: -r["degree"])
        return out[:10]  # 최대 10개
