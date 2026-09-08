import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from wiki_app.search import Index


@pytest.fixture(scope="module")
def index(tmp_path_factory):
    """Use synthetic pages so a public clone never needs a personal wiki."""
    tmp_path = tmp_path_factory.mktemp("search-index")
    index_body = (
        "## concepts/ (4개)\n"
        "- [[habix-profile]] — Habix profile summary\n"
        "- [[ai-pm-role]] — AI product manager role\n"
        "- [[agent-harness-pattern]] — Agent harness pattern\n"
        "- [[resnet-note]] — Computer vision note\n"
    )
    pages = {
        "concepts": {
            "habix-profile": "---\ntitle: Habix Profile\ntags: [habix]\n---\n# Habix\n",
            "ai-pm-role": "---\ntitle: AI PM Role\ntags: [ai-pm]\n---\n# PM\n",
            "agent-harness-pattern": "---\ntitle: Agent Harness\ntags: [agent]\n---\n# Agent\n",
            "resnet-note": "---\ntitle: Vision Note\ntags: [vision]\n---\nResNet body text\n",
        }
    }
    return Index.build(wiki_root=_build_wiki(tmp_path, pages, index_body))


def _build_wiki(tmp_path, pages, index_body):
    """tmp_path 안에 wiki_root + 부모의 index.md 를 만든다.

    Index.build 는 index.md 를 wiki_root.parent 에서 읽으므로 그 레이아웃을 그대로 재현.
    pages: {category: {slug: file_content}}, index_body: index.md 전문.
    반환: wiki_root Path.
    """
    project_root = tmp_path / "proj"
    wiki_root = project_root / "wiki"
    for category, slug_map in pages.items():
        cat_dir = wiki_root / category
        cat_dir.mkdir(parents=True, exist_ok=True)
        for slug, content in slug_map.items():
            (cat_dir / f"{slug}.md").write_text(content)
    (project_root / "index.md").write_text(index_body)
    return wiki_root


@pytest.mark.requires_user_wiki
def test_index_loads_all_pages(index):
    assert index.total_pages >= 40
    assert "habix-profile" in index.by_slug


def test_search_title_match(index):
    results = index.search("habix")
    slugs = [r["slug"] for r in results["results"]]
    assert "habix-profile" in slugs


def test_search_korean_description_match(tmp_path):
    # WHY: slug 은 영문이라 한국어 쿼리로 매칭 안 되지만, index.md description
    # 또는 frontmatter page_title 의 한국어는 매칭돼야 한다. 특정 작성자 slug
    # ("agent-harness-pattern") 가 아니라 "한국어 본문이 description/title 로
    # 매칭된다"는 로직을 self-contained 로 검증.
    index_body = (
        "## concepts/ (2개)\n"
        "- [[harness-pattern]] — 에이전트 하네스 설계 패턴 정리\n"
        "- [[other-topic]] — 전혀 다른 주제 설명\n"
    )
    pages = {
        "concepts": {
            "harness-pattern": (
                "---\ntitle: 에이전트 하네스 패턴\ntags: [agent, harness]\n---\n# 본문\n"
            ),
            "other-topic": (
                "---\ntitle: Other Topic\ntags: [misc]\n---\n# 본문\n"
            ),
        },
    }
    idx = Index.build(wiki_root=_build_wiki(tmp_path, pages, index_body))

    # 한국어 "에이전트" 는 영문 slug 엔 없지만 description + page_title 에 있다.
    results = idx.search("에이전트")
    slugs = [r["slug"] for r in results["results"]]
    assert "harness-pattern" in slugs
    # 한국어 매칭이 없는 페이지는 빠져야 한다 (false positive 방지).
    assert "other-topic" not in slugs
    # description(+1) + page_title(+3) 둘 다 매칭이라 점수가 desc-only(1) 보다 높다.
    hit = next(r for r in results["results"] if r["slug"] == "harness-pattern")
    assert "page_title" in hit["match_type"]


def test_search_tag_match(index):
    # ai-pm-role의 tags에 "ai-pm" 있음
    results = index.search("ai-pm")
    slugs = [r["slug"] for r in results["results"]]
    assert "ai-pm-role" in slugs


def test_search_score_ordering_title_first(index):
    # 제목에 "agent" 포함된 것이 description만 매칭되는 것보다 위
    results = index.search("agent")
    top_slugs = [r["slug"] for r in results["results"][:3]]
    # 슬러그에 agent 들어간 페이지가 상위 3개 안에 있어야 함
    assert any("agent" in s for s in top_slugs)


def test_search_returns_score_and_match_type(index):
    results = index.search("habix")
    first = results["results"][0]
    assert "score" in first
    assert "match_type" in first
    assert first["score"] > 0


def test_search_expands_when_fewer_than_3_results(index):
    # 매우 specific한 키워드 — B로는 적게 매칭됨
    results = index.search("ResNet")  # 본문에만 있고 description엔 없을 가능성
    # B 단계에서 0~2개 → C 확장 발동
    if results["expanded"]:
        assert results["total"] >= results.get("basic_total", 0)


def test_search_expansion_adds_snippet(index):
    # 결과 적은 쿼리에서 snippet이 채워지는지
    results = index.search("ResNet")
    if results["expanded"]:
        expanded = [r for r in results["results"] if r["snippet"]]
        if expanded:
            assert "ResNet" in expanded[0]["snippet"]


def test_search_no_expansion_when_3plus_results(index):
    # 많이 매칭되는 키워드 — 확장 안 함
    results = index.search("agent")
    if results["total"] >= 3:
        # B에서 3개 이상이면 확장 안 함 (basic_total 없음 또는 expanded=False)
        assert results["expanded"] is False


# --- 버그 4 회귀: 깨진 페이지 1개가 전체 인덱스 빌드를 크래시시키지 않는다 ---
# WHY: Index.build 는 페이지별 frontmatter.load 중 한 페이지의 invalid YAML 로
# 전체가 죽으면 안 된다. 깨진 페이지는 skip 하고 나머지는 정상 인덱싱돼야 한다.


def test_index_build_skips_broken_page_and_indexes_rest(tmp_path):
    index_body = (
        "## concepts/ (3개)\n"
        "- [[good-one]] — 정상 페이지 하나\n"
        "- [[broken-one]] — 깨진 YAML 페이지\n"
        "- [[good-two]] — 또 다른 정상 페이지\n"
    )
    pages = {
        "concepts": {
            "good-one": "---\ntitle: Good One\ntags: [alpha]\n---\n# Good One\n",
            # invalid YAML: 닫히지 않은 따옴표 + 깨진 들여쓰기
            "broken-one": "---\ntitle: \"unterminated\ntags: [a, b\n  : : :\n---\n# Broken\n",
            "good-two": "---\ntitle: Good Two\ntags: [beta]\n---\n# Good Two\n",
        },
    }
    wiki_root = _build_wiki(tmp_path, pages, index_body)

    # 빌드가 예외 없이 끝나야 한다 (크래시 격리).
    idx = Index.build(wiki_root=wiki_root)

    # 세 slug 모두 index.md 기반으로 등록은 된다 (description/category 보존).
    assert set(idx.by_slug) == {"good-one", "broken-one", "good-two"}
    # 정상 페이지는 frontmatter title/tags 가 채워진다.
    assert idx.by_slug["good-one"].page_title == "Good One"
    assert idx.by_slug["good-two"].page_title == "Good Two"
    assert "alpha" in idx.by_slug["good-one"].tags
    # 깨진 페이지는 frontmatter 메타 없이 skip — title 비고 tags 비어있음.
    assert idx.by_slug["broken-one"].page_title == ""
    assert idx.by_slug["broken-one"].tags == []
    # 정상 페이지 검색은 정상 작동.
    good_slugs = [r["slug"] for r in idx.search("Good One")["results"]]
    assert "good-one" in good_slugs


# --- 잠재/MED 회귀: index.md 부재가 부팅을 크래시시키지 않는다 ---
# WHY: Index.build 는 wiki_root.parent/index.md 를 무조건 read_text() 한다.
# index.md 가 없으면 (fresh project / 아직 ingest 전) FileNotFoundError 로
# 부팅이 죽는다. 부재 시 빈 인덱스(0 페이지)로 graceful 부팅해야 한다.


def _build_wiki_without_index(tmp_path, pages):
    """tmp_path 안에 wiki_root 와 페이지만 만들고 index.md 는 만들지 않는다."""
    project_root = tmp_path / "proj"
    wiki_root = project_root / "wiki"
    for category, slug_map in pages.items():
        cat_dir = wiki_root / category
        cat_dir.mkdir(parents=True, exist_ok=True)
        for slug, content in slug_map.items():
            (cat_dir / f"{slug}.md").write_text(content)
    project_root.mkdir(parents=True, exist_ok=True)
    assert not (project_root / "index.md").exists()
    return wiki_root


def test_index_build_missing_index_md_returns_empty_index(tmp_path):
    # index.md 가 없는 wiki_root 로도 Index.build 가 예외 없이 끝나야 한다.
    pages = {"concepts": {"orphan": "---\ntitle: Orphan\n---\n# Orphan\n"}}
    wiki_root = _build_wiki_without_index(tmp_path, pages)

    idx = Index.build(wiki_root=wiki_root)  # FileNotFoundError 나면 안 됨

    # index.md 가 없으면 slug 목록을 만들 소스가 없으므로 0 페이지.
    assert idx.total_pages == 0
    assert idx.by_slug == {}


def test_index_build_missing_index_md_logs_warning(tmp_path, caplog):
    # 크래시 대신 logging 으로 부재를 표면화해야 한다 (silent 금지).
    import logging

    pages = {"concepts": {"orphan": "---\ntitle: Orphan\n---\n# Orphan\n"}}
    wiki_root = _build_wiki_without_index(tmp_path, pages)

    with caplog.at_level(logging.WARNING, logger="wiki_app.search"):
        Index.build(wiki_root=wiki_root)

    assert any(
        record.levelno >= logging.WARNING for record in caplog.records
    ), "index.md 부재가 로그로 남아야 한다"


def test_search_on_empty_index_returns_no_results(tmp_path):
    # 빈 인덱스에서 검색해도 크래시 없이 빈 결과를 돌려준다.
    wiki_root = _build_wiki_without_index(
        tmp_path, {"concepts": {"orphan": "---\ntitle: Orphan\n---\n# Orphan\n"}}
    )
    idx = Index.build(wiki_root=wiki_root)

    result = idx.search("anything")
    assert result["results"] == []
    assert result["total"] == 0


# --- 과제 2(b): C 확장(_body_grep) expanded=True 경로 강제 커버 ---
# WHY: 기존 test_search_expands_* 들은 `if results["expanded"]:` 가드로 감싸져
# 있어 실제 위키 본문에 따라 dead-path 가 된다. 여기선 제어된 본문으로
# B 단계 < 3개 + 본문에만 존재하는 토큰을 만들어 C 확장을 *반드시* 발동시킨다.


def test_search_forces_body_grep_expansion(tmp_path):
    # index.md description/title/tags 어디에도 없고 *본문에만* 있는 토큰을 쿼리하면
    # B 단계는 0개 → C(_body_grep) 확장이 발동해 expanded=True 가 돼야 한다.
    index_body = (
        "## concepts/ (2개)\n"
        "- [[hidden-body]] — 표지에는 없는 설명\n"
        "- [[unrelated]] — 완전히 무관한 주제\n"
    )
    pages = {
        "concepts": {
            # 본문에만 'quokkasaurus' 토큰 존재 (slug/title/tags/desc 어디에도 없음)
            "hidden-body": (
                "---\ntitle: 숨은 본문\ntags: [misc]\n---\n"
                "# 제목\n\n이 페이지 본문에는 quokkasaurus 라는 토큰이 들어있다.\n"
            ),
            "unrelated": (
                "---\ntitle: 무관\ntags: [misc]\n---\n# 무관\n\n전혀 다른 내용.\n"
            ),
        },
    }
    idx = Index.build(wiki_root=_build_wiki(tmp_path, pages, index_body))

    result = idx.search("quokkasaurus")

    # B 단계로는 매칭 0 → C 확장 발동
    assert result["expanded"] is True
    assert result["basic_total"] == 0
    slugs = [r["slug"] for r in result["results"]]
    assert "hidden-body" in slugs
    # 본문 매칭은 match_type="body" + snippet 채움
    hit = next(r for r in result["results"] if r["slug"] == "hidden-body")
    assert hit["match_type"] == "body"
    assert hit["snippet"] is not None
    assert "quokkasaurus" in hit["snippet"]
    # 본문에 토큰 없는 페이지는 확장 결과에도 안 들어옴.
    assert "unrelated" not in slugs


def test_search_body_grep_expansion_supplements_basic_results(tmp_path):
    # B 단계로 1~2개만 매칭되는 쿼리에서도 C 확장이 *다른* 페이지의 본문 매칭을
    # 추가로 붙여 basic_total 보다 total 이 커지는 경로를 커버한다.
    # 토큰은 slug 어디에도 없게 해 B 매칭과 C 매칭을 서로 다른 페이지로 분리한다.
    index_body = (
        "## concepts/ (3개)\n"
        "- [[cover-hit]] — zebratoken 이 description 에 있는 표지 매칭 페이지\n"
        "- [[body-hit]] — 표지엔 토큰 없음\n"
        "- [[noise]] — 무관\n"
    )
    pages = {
        "concepts": {
            # description 에만 토큰 → B 단계 매칭 (desc score +1)
            "cover-hit": "---\ntitle: T\ntags: [misc]\n---\n# T\n\n표지 매칭 페이지.\n",
            # 본문에만 토큰 (slug/desc/title/tags 어디에도 없음) → C 확장에서만 매칭
            "body-hit": (
                "---\ntitle: B\ntags: [misc]\n---\n# B\n\n본문에 zebratoken 등장.\n"
            ),
            "noise": "---\ntitle: N\ntags: [misc]\n---\n# N\n\n무관.\n",
        },
    }
    idx = Index.build(wiki_root=_build_wiki(tmp_path, pages, index_body))

    result = idx.search("zebratoken")

    # B 단계 매칭 1개(cover-hit) < 3 → 확장 발동, body-hit 본문 매칭이 추가됨.
    assert result["expanded"] is True
    assert result["basic_total"] == 1
    assert result["total"] > result["basic_total"]
    slugs = [r["slug"] for r in result["results"]]
    assert "cover-hit" in slugs  # B 매칭 (description)
    assert "body-hit" in slugs   # C 본문 매칭 (추가)
    body_hit = next(r for r in result["results"] if r["slug"] == "body-hit")
    assert body_hit["match_type"] == "body"


# --- CRITICAL 회귀: index.md slug 의 path traversal 차단 ---
# WHY: Index.build / _body_grep 가 index.md 의 slug 를
# `wiki_root / category / f"{slug}.md"` 로 만든 뒤 containment 검사 없이
# frontmatter.load / read_text 하면, index.md 에 `[[../../secret]]` 같은
# traversal slug 가 들어갈 때 wiki_root *밖*의 파일을 읽어 검색 snippet /
# frontmatter title 로 노출한다. resolve().is_relative_to(wiki_root) 검사를
# build 와 _body_grep 양쪽에 강제해 해당 엔트리를 skip 해야 한다.
# (find_page_path 의 traversal 방어는 /api/page 만 막고 /api/search 가 우회로로 남았던 결함.)


def _build_wiki_with_external_secret(tmp_path):
    """wiki_root + 그 *밖*의 secret 파일 + traversal slug 를 가리키는 index.md.

    레이아웃:
      tmp_path/proj/wiki/concepts/legit.md   (정상 페이지)
      tmp_path/proj/secret.md                (wiki_root 밖, 유출되면 안 되는 비밀)
    index.md 의 한 엔트리 slug 가 `../../secret` 라서 category 를 거쳐도
    `wiki/concepts/../../secret.md` → `tmp_path/proj/secret.md` 로 빠져나간다.
    """
    project_root = tmp_path / "proj"
    wiki_root = project_root / "wiki"
    cat_dir = wiki_root / "concepts"
    cat_dir.mkdir(parents=True, exist_ok=True)
    (cat_dir / "legit.md").write_text(
        "---\ntitle: 정상 페이지\ntags: [ok]\n---\n# 정상\n\n본문에 publictoken 토큰.\n"
    )
    # wiki_root 밖의 비밀 파일. frontmatter title + 본문 token 둘 다 유출 표지로 사용.
    (project_root / "secret.md").write_text(
        "---\ntitle: TOP_SECRET_TITLE\n---\n# 비밀\n\nleaked_secret_token 절대노출금지.\n"
    )
    # slug `../../secret` 는 category(concepts) 를 거쳐도 proj/secret.md 로 빠져나간다.
    index_body = (
        "## concepts/ (2개)\n"
        "- [[legit]] — 정상 페이지 설명\n"
        "- [[../../secret]] — leaked_secret_token 표지에도 심어둔 traversal 엔트리\n"
    )
    (project_root / "index.md").write_text(index_body)
    return wiki_root


def test_index_build_does_not_read_external_file_via_traversal_slug(tmp_path):
    # Index.build 가 traversal slug 의 wiki_root 밖 frontmatter 를 읽어
    # page_title 로 흡수하면 안 된다. 그 엔트리는 skip (등록되더라도 메타 비어있음).
    wiki_root = _build_wiki_with_external_secret(tmp_path)

    idx = Index.build(wiki_root=wiki_root)

    # 어떤 엔트리도 wiki_root 밖 secret.md 의 frontmatter title 을 흡수하면 안 된다.
    for entry in idx.by_slug.values():
        assert entry.page_title != "TOP_SECRET_TITLE", (
            f"traversal slug {entry.slug!r} 가 wiki 밖 secret frontmatter 를 읽었다"
        )


def test_search_does_not_expose_external_secret_via_traversal_slug(tmp_path):
    # /api/search 우회로 차단: 본문 grep(_body_grep) 이 traversal slug 의
    # wiki_root 밖 파일을 read_text 해 snippet 으로 노출하면 안 된다.
    wiki_root = _build_wiki_with_external_secret(tmp_path)
    idx = Index.build(wiki_root=wiki_root)

    # secret.md 본문에만 있는 토큰으로 검색 → traversal slug 가 살아있으면
    # _body_grep 이 wiki 밖 파일을 읽어 snippet 으로 leaked_secret_token 을 노출한다.
    result = idx.search("leaked_secret_token")

    # query 에코는 검사 대상이 아니다 — 실제 노출은 results(snippet/description/
    # title) 에서만 일어난다. results 만 직렬화해 secret 표지를 검사한다.
    serialized_results = json.dumps(result["results"], ensure_ascii=False)
    assert "leaked_secret_token" not in serialized_results, (
        "검색 결과가 wiki_root 밖 secret 본문을 노출했다 (path traversal)"
    )
    assert "TOP_SECRET_TITLE" not in serialized_results, (
        "검색 결과가 wiki_root 밖 secret frontmatter 를 노출했다"
    )
    # traversal slug 자체가 결과로 떠서도 안 된다 (등록 단계에서 skip 돼야 함).
    slugs = [r["slug"] for r in result["results"]]
    assert "../../secret" not in slugs


def test_search_still_works_on_legit_slug_with_traversal_entry_present(tmp_path):
    # traversal 방어가 정상 slug 검색까지 죽이면 안 된다 (false negative 방지).
    wiki_root = _build_wiki_with_external_secret(tmp_path)
    idx = Index.build(wiki_root=wiki_root)

    # 정상 페이지는 index.md description + 본문 grep 모두 정상 작동해야 한다.
    desc_result = idx.search("정상")
    assert "legit" in [r["slug"] for r in desc_result["results"]]

    body_result = idx.search("publictoken")
    assert "legit" in [r["slug"] for r in body_result["results"]]
