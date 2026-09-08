"""test_export_graph.py — export_graph.py 메타 카운트 검증.

WHY: graph.json 의 `meta.total_pages` 가 필드명대로 "page kind 노드 수" 만
세는지 확인한다. 과거엔 page+tag+ghost 전체 노드 수를 담아 필드명과
불일치했다(page 3개인데 total_pages 가 더 큰 값 보고). 이 테스트는 그
회귀를 막고, 전체 노드 수는 별도 키(total_nodes)로 구분되는지 검증한다.

tmp_path self-contained: 실제 wiki/ 데이터에 의존하지 않고, 임시 wiki 디렉토리에
page 3개(서로 연결) + tag + ghost 가 섞인 위키를 만들어 export 한다.
"""
import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import export_graph  # noqa: E402


PAGE_A = """---
title: Alpha
type: concept
tags: [shared-tag]
---
Alpha 는 [[beta]] 와 [[gamma]] 를 참조한다.
또한 미정제 [[nonexistent-ghost]] 도 참조한다.
"""

PAGE_B = """---
title: Beta
type: concept
tags: [shared-tag]
---
Beta 는 [[gamma]] 를 참조한다.
"""

PAGE_C = """---
title: Gamma
type: concept
tags: [solo-tag]
---
Gamma 페이지 본문.
"""


@pytest.fixture
def exported_graph(tmp_path, monkeypatch):
    """임시 wiki/ 에 page 3 + tag 2 + ghost 1 을 만들고 export → graph.json dict 반환."""
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "alpha.md").write_text(PAGE_A, encoding="utf-8")
    (wiki_dir / "beta.md").write_text(PAGE_B, encoding="utf-8")
    (wiki_dir / "gamma.md").write_text(PAGE_C, encoding="utf-8")

    output = wiki_dir / "graph.json"
    monkeypatch.setattr(export_graph, "WIKI_DIR", wiki_dir)
    monkeypatch.setattr(export_graph, "OUTPUT", output)

    rc = export_graph.main()
    assert rc == 0
    return json.loads(output.read_text(encoding="utf-8"))


def test_total_pages_counts_page_nodes_only(exported_graph):
    """total_pages 는 page kind 노드 수(3)와 정확히 일치해야 한다."""
    meta = exported_graph["meta"]
    page_nodes = [n for n in exported_graph["nodes"] if n["kind"] == "page"]
    assert len(page_nodes) == 3
    assert meta["total_pages"] == 3


def test_total_pages_excludes_tag_and_ghost(exported_graph):
    """total_pages 는 전체 노드 수(page+tag+ghost)와 달라야 한다.

    이 위키는 page 3 + tag(shared-tag, solo-tag) 2 + ghost(nonexistent-ghost) 1
    = 전체 6 노드. total_pages 가 6 을 담으면(과거 버그) 실패한다.
    """
    all_nodes = exported_graph["nodes"]
    meta = exported_graph["meta"]
    assert len(all_nodes) > meta["total_pages"]
    assert meta["total_pages"] != len(all_nodes)


def test_total_nodes_reports_full_count(exported_graph):
    """전체 노드 수는 별도 키 total_nodes 로 노출된다."""
    meta = exported_graph["meta"]
    assert meta["total_nodes"] == len(exported_graph["nodes"])
    assert meta["total_nodes"] == 6  # page 3 + tag 2 + ghost 1
