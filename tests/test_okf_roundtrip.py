"""test_okf_roundtrip.py — OKF 번들 라운드트립 검증 (TDD).

WHY: export 의 진짜 수락 기준은 "내부 변환이 맞다"가 아니라 "외부 OKF
consumer 가 번들을 그래프로 복원할 수 있다"이다 (contract §6 DoD, design §6).
그래서 design.md 부록의 Google minimal consumer 를 **그대로 내장**해
픽스처를 export → load_bundle 로 복원 → 노드/엣지 수가 의도와 일치하는지
확인한다. consumer 의 정규식 \\]\\((/[^)]+\\.md)\\) 가 호환성의 단일 진실이다.

핵심 불변식:
  - 페이지 노드 수 == export 한 페이지 수 (index.md/log.md 같은 메타는 제외)
  - 엣지 수 == 의도된(안 깨진) wikilink 수 (깨진 링크는 그래프에서 빠진다)

self-contained 픽스처 기반이라 requires_user_wiki 마커를 달지 않는다.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import okf_export  # noqa: E402


FIXTURE_WIKI = Path(__file__).parent / "fixtures" / "okf_wiki"

# 픽스처 의도(test_okf_export.py와 동일 ground truth):
#   business/ 제외 후 export 페이지 5개.
EXPECTED_PAGE_COUNT = 5
#   안 깨진 wikilink(business 페이지의 링크는 export 안 되므로 제외):
#   rag→vector-db, rag→llm, vector-db→rag, llm→rag, researcher→rag, embeddings→vector-db = 6
EXPECTED_EDGE_COUNT = 6


# --- design.md 부록: OKF minimal consumer (Google 공개판, 그대로 내장) ---
def load_bundle(root):
    import pathlib
    import re

    import yaml

    concepts, links = {}, []
    for path in pathlib.Path(root).rglob("*.md"):
        text = path.read_text()
        meta = {}
        if text.startswith("---"):
            _, fm, body = text.split("---", 2)
            meta = yaml.safe_load(fm) or {}
        else:
            body = text
        concepts[str(path)] = meta
        for target in set(re.findall(r"\]\((/[^)]+\.md)\)", body)):
            links.append((str(path), target))
    return concepts, links
# --- /minimal consumer ---


@pytest.fixture
def bundle(tmp_path):
    """픽스처를 export 한 뒤 minimal consumer 로 복원한 (concepts, links, out_dir, stats)."""
    out_dir = tmp_path / "okf"
    stats = okf_export.export_bundle(FIXTURE_WIKI, out_dir)
    concepts, links = load_bundle(out_dir)
    return concepts, links, out_dir, stats


def _page_nodes(concepts):
    """메타 파일(index.md/log.md)을 제외한 실제 페이지 노드.

    실제 페이지는 OKF 필수 type 필드를 갖고, 생성된 index.md/log.md 는
    frontmatter 가 없어 meta=={} 이다. 이 차이로 페이지만 골라낸다.
    """
    return {p: m for p, m in concepts.items() if m.get("type")}


def _semantic_edges(concepts, links):
    """페이지 본문에서 나온 wikilink 엣지만 추린다.

    minimal consumer 는 rglob 로 index.md(목차)·log.md 까지 읽어 그 목차 링크도
    엣지로 센다. 시맨틱 엣지(페이지→페이지 wikilink)는 *페이지 노드가 src 인*
    링크뿐이다. index/log 는 type frontmatter 가 없으므로 _page_nodes 로 거른다.
    """
    page_paths = set(_page_nodes(concepts))
    return [(src, tgt) for (src, tgt) in links if src in page_paths]


def test_roundtrip_loads_without_error(bundle):
    """consumer 가 번들을 예외 없이 로드한다 (frontmatter 가 valid YAML)."""
    concepts, links, _out, _stats = bundle
    assert concepts  # 비어있지 않음
    # 모든 페이지 frontmatter 가 dict 로 파싱됨 (safe_dump 출력이 safe_load 가능).
    for meta in _page_nodes(concepts).values():
        assert isinstance(meta, dict)


def test_node_count_equals_exported_pages(bundle):
    """페이지 노드 수 == export 한 페이지 수 (메타 파일 제외)."""
    concepts, _links, _out, stats = bundle
    page_nodes = _page_nodes(concepts)
    assert len(page_nodes) == EXPECTED_PAGE_COUNT
    assert len(page_nodes) == stats.pages_exported


def test_edge_count_equals_intended_wikilinks(bundle):
    """페이지 본문 엣지 수 == 의도된(안 깨진) wikilink 수. 깨진 링크는 제외.

    (index.md 목차 링크는 시맨틱 엣지가 아니므로 _semantic_edges 로 거른다.)
    """
    concepts, links, _out, _stats = bundle
    edges = _semantic_edges(concepts, links)
    assert len(edges) == EXPECTED_EDGE_COUNT
    # stats 의 변환 카운트와도 정합.
    assert _stats.links_converted == EXPECTED_EDGE_COUNT


def test_broken_link_absent_from_graph(bundle):
    """깨진 [[nonexistent]] 는 어떤 엣지 타깃에도 나타나지 않는다."""
    concepts, links, _out, _stats = bundle
    targets = [t for (_src, t) in _semantic_edges(concepts, links)]
    assert not any("nonexistent" in t for t in targets), targets
    # 깨진 링크는 stats.broken_links 에만 남는다.
    broken = [t for (_s, t) in _stats.broken_links]
    assert "nonexistent" in broken


def test_excluded_business_node_absent(bundle):
    """제외된 business 페이지는 복원 그래프에 노드로 존재하지 않는다."""
    concepts, _links, out_dir, _stats = bundle
    # tmp 경로명 오탐 방지: 번들 루트 기준 상대경로로 정규화해 검사.
    rels = [str(Path(p).relative_to(out_dir)) for p in concepts]
    assert not any(r.startswith("business") for r in rels), rels


def test_edge_targets_resolve_to_existing_pages(bundle):
    """모든 엣지 타깃 경로가 실제 번들 파일로 존재한다 (dangling 링크 0)."""
    _concepts, links, out_dir, _stats = bundle
    for _src, target in links:
        # target 은 "/concepts/rag.md" 형태 → 번들 루트 기준 실제 파일.
        rel = target.lstrip("/")
        assert (out_dir / rel).exists(), f"dangling 링크 타깃: {target}"
