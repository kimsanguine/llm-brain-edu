import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from wiki_app.pages import load_page, find_page_path, PageNotFound


def test_load_known_page_returns_frontmatter_and_body(tmp_path):
    # WHY: load_page 는 frontmatter(메타) 와 body_md(본문) 를 분리해 반환하고,
    # 카테고리 폴더명을 category 로 노출해야 한다. 특정 slug/본문 텍스트가 아니라
    # 이 분리·매핑 계약을 검증 — 작성자 실제 wiki 부재(fresh clone/CI)에도 통과.
    wiki_root = tmp_path / "wiki"
    (wiki_root / "business").mkdir(parents=True)
    (wiki_root / "business" / "sample-profile.md").write_text(
        "---\n"
        "title: 샘플 프로파일\n"
        "tags: [sample, profile]\n"
        "---\n"
        "# 본문 제목\n\n본문 단락.\n"
    )

    page = load_page("sample-profile", wiki_root=wiki_root)

    assert page["slug"] == "sample-profile"
    assert page["category"] == "business"  # 카테고리 폴더명이 그대로 매핑
    assert page["frontmatter"]["title"] == "샘플 프로파일"
    assert "sample" in page["frontmatter"]["tags"]  # 메타 분리 반환
    # body_md 는 frontmatter 블록을 제외한 본문만 — 메타 키가 섞여선 안 됨
    assert page["body_md"].startswith("# 본문 제목")
    assert "title:" not in page["body_md"]


def test_load_page_includes_graph_metadata(tmp_path):
    # WHY: load_page 는 graph.json 의 inbound/outbound degree 를 페이지 dict 에
    # 합쳐 반환한다. 특정 작성자 slug 가 아니라 "graph 메타가 정수로 병합된다"는
    # 계약을 self-contained 로 검증.
    import json
    wiki_root = tmp_path / "wiki"
    (wiki_root / "concepts").mkdir(parents=True)
    (wiki_root / "concepts" / "node-a.md").write_text("---\ntitle: A\n---\n# A\n")
    (wiki_root / "graph.json").write_text(json.dumps({
        "nodes": [{"id": "node-a", "kind": "page", "inbound": 3, "outbound": 2}],
        "links": [],
    }))

    page = load_page("node-a", wiki_root=wiki_root)

    assert isinstance(page["inbound"], int)
    assert isinstance(page["outbound"], int)
    assert page["inbound"] == 3
    assert page["outbound"] == 2


def test_load_missing_page_raises(tmp_path):
    wiki_root = tmp_path / "wiki"
    (wiki_root / "concepts").mkdir(parents=True)
    with pytest.raises(PageNotFound):
        load_page("nonexistent-slug", wiki_root=wiki_root)


def test_find_page_path_searches_all_categories(tmp_path):
    # WHY: find_page_path 는 카테고리 폴더들을 순회해 slug 를 찾고, 발견한 파일의
    # 부모 폴더명이 그 카테고리여야 한다. 특정 slug 가 아니라 탐색 로직을 검증.
    wiki_root = tmp_path / "wiki"
    (wiki_root / "people").mkdir(parents=True)
    (wiki_root / "people" / "some-person.md").write_text("---\ntitle: P\n---\n# P\n")

    p = find_page_path("some-person", wiki_root=wiki_root)
    assert p.name == "some-person.md"
    assert p.parent.name == "people"


# --- path traversal 회귀 (Codex [high]): wiki_root 밖 파일 접근 차단 ---
# 이 테스트들은 사용자 wiki 데이터에 의존하지 않도록 tmp_path 로 격리된
# wiki 구조를 직접 만든다. (conftest 의 wiki-dependent skip 은 파일명 기준이라
# 사용자 wiki 부재 시 skip 될 수 있으나, 테스트 자체는 자기완결적이다.)


@pytest.fixture
def isolated_wiki(tmp_path):
    """wiki_root 와 그 바깥에 secret 파일을 둔 격리 구조."""
    wiki_root = tmp_path / "wiki"
    (wiki_root / "concepts").mkdir(parents=True)
    (wiki_root / "concepts" / "real-page.md").write_text(
        "---\ntitle: Real\n---\n# Real\n"
    )
    # 정당한 중첩 페이지 (slug 에 '/' 포함) — 허용되어야 함
    (wiki_root / "projects" / "260515_llm_wiki").mkdir(parents=True)
    (wiki_root / "projects" / "260515_llm_wiki" / "prd.md").write_text(
        "---\ntitle: PRD\n---\n# PRD\n"
    )
    # wiki_root 밖(부모) 의 비밀 파일 — traversal 로 도달 시도 대상
    (tmp_path / "CLAUDE.md").write_text("# SECRET outside wiki\n")
    return wiki_root


@pytest.mark.parametrize(
    "evil_slug",
    [
        "../../CLAUDE",          # 리포 루트 CLAUDE.md 노출 재현 케이스
        "../CLAUDE",             # 한 단계 상위
        "../../../etc/passwd",   # 시스템 파일
        "/etc/passwd",           # 선행 '/' 절대경로
    ],
)
def test_find_page_path_rejects_traversal(isolated_wiki, evil_slug):
    # wiki_root 밖으로 나가는 slug 는 파일이 실재해도 PageNotFound 여야 한다.
    with pytest.raises(PageNotFound):
        find_page_path(evil_slug, wiki_root=isolated_wiki)


def test_find_page_path_allows_legit_single_slug(isolated_wiki):
    p = find_page_path("real-page", wiki_root=isolated_wiki)
    assert p.name == "real-page.md"
    assert p.parent.name == "concepts"


def test_find_page_path_allows_legit_nested_slug(isolated_wiki):
    # slug 에 '/' 가 있어도 wiki_root 안이면 허용 — "'/' 있으면 거부"는 틀린 fix.
    p = find_page_path("260515_llm_wiki/prd", wiki_root=isolated_wiki)
    assert p.name == "prd.md"
    assert p.parent.name == "260515_llm_wiki"


# --- 버그 3 회귀: invalid YAML frontmatter 페이지가 HTTP 500 대신 graceful 처리 ---
# WHY: frontmatter.load 가 깨진 YAML 에서 예외를 던지면 API 가 500 으로 떨어진다.
# load_page 는 이를 PageNotFound 로 격리해야 하고, /api/page 는 404 로 응답해야 한다.


@pytest.fixture
def wiki_with_broken_page(tmp_path):
    """정상 페이지 1 + invalid YAML frontmatter 페이지 1 을 둔 격리 wiki.

    create_app/Index.build 가 wiki_root.parent/index.md 를 읽으므로 그 레이아웃을
    재현 — 부모에 index.md 를 둬 API 엔드투엔드 테스트도 self-contained 하게 한다.
    """
    project_root = tmp_path / "proj"
    wiki_root = project_root / "wiki"
    (wiki_root / "concepts").mkdir(parents=True)
    (wiki_root / "concepts" / "good.md").write_text(
        "---\ntitle: Good\ntags: [ok]\n---\n# Good\n"
    )
    # 닫히지 않은 따옴표 + 잘못된 들여쓰기로 YAML 파서를 깨뜨린다.
    (wiki_root / "concepts" / "broken.md").write_text(
        "---\n"
        "title: \"unterminated\n"
        "tags: [a, b\n"
        "  bad-indent: : :\n"
        "---\n"
        "# Broken body\n"
    )
    (project_root / "index.md").write_text(
        "## concepts/ (2개)\n"
        "- [[good]] — 정상 페이지\n"
        "- [[broken]] — 깨진 YAML 페이지\n"
    )
    return wiki_root


def test_load_page_invalid_yaml_raises_page_not_found(wiki_with_broken_page):
    # 깨진 YAML 은 예외를 그대로 전파하는 대신 PageNotFound 로 변환돼야 한다.
    with pytest.raises(PageNotFound):
        load_page("broken", wiki_root=wiki_with_broken_page)


def test_load_page_good_page_still_loads_alongside_broken(wiki_with_broken_page):
    # 깨진 페이지 존재가 정상 페이지 로드를 방해하지 않는다.
    page = load_page("good", wiki_root=wiki_with_broken_page)
    assert page["slug"] == "good"
    assert page["frontmatter"]["title"] == "Good"


def test_api_page_invalid_yaml_returns_404_not_500(wiki_with_broken_page):
    # 엔드투엔드: /api/page/{slug} 가 깨진 페이지에 500 이 아니라 404 를 준다.
    from fastapi.testclient import TestClient
    from wiki_app.api import create_app

    client = TestClient(create_app(wiki_root=wiki_with_broken_page))
    resp = client.get("/api/page/broken")
    assert resp.status_code == 404  # NOT 500
