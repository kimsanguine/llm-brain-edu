"""curate.py 데이터 손실 버그 회귀 테스트.

WHY (이 테스트가 인코딩하는 의도):
  1. invalid YAML frontmatter 페이지를 curate의 rewrite 경로(ensure_distill_fields)가
     "frontmatter 없음"으로 오인해 title·type·tags·created·sources를 영구 삭제하면 안 된다.
     parse 실패 페이지는 원본 그대로 보존(skip)되어야 한다 (CRITICAL silent data-loss).
  2. schema/sources.yaml 이 없는 fresh-clone 환경에서 lifecycle / bare curate 가
     FileNotFoundError 로 크래시하면 안 된다 (graceful skip 또는 example 폴백).

모두 tmp_path 기반 self-contained — 사용자 wiki/ 데이터에 의존하지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# scripts/ 를 import 경로에 추가 (기존 wiki_app/access.py 컨벤션과 동일).
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import curate  # noqa: E402


# invalid YAML 재현: sources 리스트 아이템의 닫는 따옴표 뒤에 텍스트가 붙어 YAML 파서가 거부한다.
# 예: - "Building a Second Brain" (Tiago Forte, 2022)
INVALID_YAML_PAGE = """---
title: Second Brain
type: concept
tags: [pkm, productivity]
created: 2026-01-01
sources:
  - "Building a Second Brain" (Tiago Forte, 2022)
---

본문 내용은 보존되어야 한다.
"""

# 원본에 존재해야 할 "사용자 작성" 필드 (distill 필드가 아닌, 손실되면 안 되는 것들).
_USER_FIELDS = ["title:", "type:", "tags:", "created:", "sources:"]


def _make_wiki(tmp_path: Path, page_body: str) -> Path:
    """tmp 안에 wiki/concepts/second-brain.md 한 장을 만들고 wiki 디렉토리를 반환."""
    wiki = tmp_path / "wiki"
    (wiki / "concepts").mkdir(parents=True)
    page = wiki / "concepts" / "second-brain.md"
    page.write_text(page_body, encoding="utf-8")
    return wiki


def _patch_module_paths(monkeypatch, tmp_path: Path, wiki: Path) -> None:
    """curate 모듈 전역 경로를 tmp 격리 경로로 치환."""
    monkeypatch.setattr(curate, "WIKI_ROOT", tmp_path)
    monkeypatch.setattr(curate, "WIKI_DIR", wiki)
    monkeypatch.setattr(curate, "SCHEMA_DIR", tmp_path / "schema")
    monkeypatch.setattr(curate, "DISTILL_QUEUE_FILE", wiki / "distill_queue.md")
    monkeypatch.setattr(curate, "WIKI_STATS_FILE", tmp_path / "wiki_stats.json")
    monkeypatch.setattr(curate, "REPORT_FILE", wiki / "curate_report.md")
    monkeypatch.setattr(curate, "LOG_FILE", tmp_path / "log.md")


def test_invalid_yaml_page_preserved_on_distill(monkeypatch, tmp_path, caplog):
    """RED→GREEN: invalid YAML 페이지에 distill rewrite 경로 실행 → 기존 필드 보존 + 경고.

    수정 전: parse_frontmatter 가 ({}, body) 를 조용히 반환 → ensure_distill_fields 가
    distill 필드 4개만 다시 써서 title/type/tags/created/sources 클로버 (5개 필드 소실).
    수정 후: parse 실패 페이지는 skip + warning, 원본 그대로 보존.
    """
    wiki = _make_wiki(tmp_path, INVALID_YAML_PAGE)
    _patch_module_paths(monkeypatch, tmp_path, wiki)

    page = wiki / "concepts" / "second-brain.md"
    before = page.read_text(encoding="utf-8")

    import logging
    with caplog.at_level(logging.WARNING):
        curate.run_distill(curate.find_all_wiki_pages())

    after = page.read_text(encoding="utf-8")

    # 핵심 단언: 사용자 필드가 하나도 소실되지 않아야 한다 (클로버 금지).
    for field in _USER_FIELDS:
        assert field in after, f"{field} 가 distill rewrite 로 소실됨 (silent data-loss)"
    assert "Building a Second Brain" in after, "sources 원문 소실됨"
    assert "본문 내용은 보존되어야 한다." in after, "본문 소실됨"

    # parse 실패 페이지는 rewrite 하지 않으므로 원본과 동일해야 한다.
    assert after == before, "parse 실패 페이지가 변형됨 — 원본 보존 위반"

    # fail-loud: 조용히 넘어가지 말고 경고를 남겨야 한다.
    assert any("second-brain" in rec.getMessage() or "second-brain" in str(rec.args)
               for rec in caplog.records), "parse 실패에 대한 경고가 없음 (fail-silent)"


# valid YAML이지만 frontmatter가 dict가 아닌 경우(C5).
# safe_load가 list/scalar를 반환하면 ensure_distill_fields가 dict로 가정해 키를
# 대입하다 TypeError로 크래시(또는 access 경로에선 예외가 삼켜져 카운트 누락)한다.
LIST_FM_PAGE = """---
- a
- b
---

본문 내용은 보존되어야 한다.
"""

SCALAR_FM_PAGE = """---
just a bare string
---

본문 내용은 보존되어야 한다.
"""


@pytest.mark.parametrize(
    "page_body, marker",
    [
        (LIST_FM_PAGE, "- a"),       # list frontmatter
        (SCALAR_FM_PAGE, "just a bare string"),  # scalar frontmatter
    ],
)
def test_nondict_yaml_page_preserved_on_distill(monkeypatch, tmp_path, caplog, page_body, marker):
    """RED→GREEN: valid YAML이지만 non-dict(list/scalar) frontmatter 페이지에
    distill rewrite 경로 실행 → 크래시/클로버 없이 원본 보존 + 경고.

    수정 전: parse_frontmatter가 list/scalar를 그대로 반환 → ensure_distill_fields가
    `fm[field] = default` 에서 TypeError로 크래시(run_distill 전체 중단).
    수정 후: non-dict는 FrontmatterParseError로 분류되어 skip + warning, 원본 보존.
    """
    wiki = _make_wiki(tmp_path, page_body)
    _patch_module_paths(monkeypatch, tmp_path, wiki)

    page = wiki / "concepts" / "second-brain.md"
    before = page.read_text(encoding="utf-8")

    import logging
    with caplog.at_level(logging.WARNING):
        # 크래시하지 않아야 한다 (TypeError 전파 금지).
        curate.run_distill(curate.find_all_wiki_pages())

    after = page.read_text(encoding="utf-8")

    # 원본 내용(frontmatter + 본문) 보존 — 클로버 금지.
    assert marker in after, "non-dict frontmatter 원문이 소실됨 (클로버)"
    assert "본문 내용은 보존되어야 한다." in after, "본문 소실됨"
    assert after == before, "parse 실패 페이지가 변형됨 — 원본 보존 위반"

    # fail-loud: 조용히 넘어가지 말고 경고를 남겨야 한다.
    assert any("second-brain" in rec.getMessage() or "second-brain" in str(rec.args)
               for rec in caplog.records), "non-dict frontmatter 경고가 없음 (fail-silent)"


def test_parse_failed_page_excluded_from_distill_queue(monkeypatch, tmp_path):
    """RED→GREEN (C5): parse 실패 페이지는 access_count가 아무리 높아도 distill
    후보/큐에 들어가면 안 된다.

    WHY: ensure_distill_fields가 parse 실패 시 {}를 반환하면 run_distill이 이를
    "정상 빈 frontmatter"로 보고 wiki_stats.json의 access_count(>=10)를 적용해
    urgent 후보에 추가한다. 그러면 fail-loud로 보호한 페이지가 다시 Claude distill
    대상(rewrite)이 되어 데이터 손실 경로가 재개방된다. parse 실패 페이지는 완전히
    skip되어야 한다.

    수정 전: distill_queue.md에 second-brain 등장 + run_distill 반환에 포함.
    수정 후: 큐/반환 모두에서 제외.
    """
    wiki = _make_wiki(tmp_path, INVALID_YAML_PAGE)
    _patch_module_paths(monkeypatch, tmp_path, wiki)

    # wiki_stats.json에 access_count=10을 심어 urgent 후보 조건을 만족시킨다.
    (tmp_path / "wiki_stats.json").write_text(
        '{"second-brain": {"access_count": 10, "last_accessed": "2026-01-01"}}',
        encoding="utf-8",
    )

    candidates = curate.run_distill(curate.find_all_wiki_pages())

    # 반환된 후보 목록에 parse 실패 페이지가 없어야 한다.
    assert not any("second-brain" in c for c in candidates), (
        "parse 실패 페이지가 distill 후보로 재유입됨 (데이터 손실 경로 재개방)"
    )

    # distill_queue.md에도 등장하면 안 된다.
    queue_text = (wiki / "distill_queue.md").read_text(encoding="utf-8")
    assert "second-brain" not in queue_text, (
        "parse 실패 페이지가 distill_queue.md에 등장 (Claude distill 대상)"
    )


def test_nondict_page_excluded_from_distill_queue(monkeypatch, tmp_path):
    """RED→GREEN (C5): non-dict(list) frontmatter 페이지도 access_count 높아도 큐 제외."""
    wiki = _make_wiki(tmp_path, LIST_FM_PAGE)
    _patch_module_paths(monkeypatch, tmp_path, wiki)

    (tmp_path / "wiki_stats.json").write_text(
        '{"second-brain": {"access_count": 99, "last_accessed": "2026-01-01"}}',
        encoding="utf-8",
    )

    candidates = curate.run_distill(curate.find_all_wiki_pages())

    assert not any("second-brain" in c for c in candidates)
    queue_text = (wiki / "distill_queue.md").read_text(encoding="utf-8")
    assert "second-brain" not in queue_text


def test_empty_block_frontmatter_is_normal(monkeypatch, tmp_path):
    """회귀 방지: 내용 없는 frontmatter 블록(`---\\n\\n---`)은 safe_load → None →
    정상 {}로 취급되어 distill 필드가 추가되고, 본문이 보존되어야 한다.

    빈 블록은 데이터 손실 위험이 없으므로 FrontmatterParseError로 막지 않는다.
    """
    empty_block_page = "---\n\n---\n\n본문.\n"
    wiki = _make_wiki(tmp_path, empty_block_page)
    _patch_module_paths(monkeypatch, tmp_path, wiki)

    page = wiki / "concepts" / "second-brain.md"
    curate.run_distill(curate.find_all_wiki_pages())
    after = page.read_text(encoding="utf-8")

    assert "distill_level:" in after  # 정상 페이지로 처리되어 distill 필드 추가
    assert "본문." in after  # 본문 보존


def test_no_frontmatter_block_unchanged(monkeypatch, tmp_path):
    """회귀 방지: frontmatter 블록 자체가 없는 페이지는 ({}, content)로 처리되어
    distill 필드가 추가되며(빈 dict 기반), 본문은 보존된다."""
    no_fm_page = "프론트매터 없는 본문만 있는 페이지.\n"
    wiki = _make_wiki(tmp_path, no_fm_page)
    _patch_module_paths(monkeypatch, tmp_path, wiki)

    page = wiki / "concepts" / "second-brain.md"
    curate.run_distill(curate.find_all_wiki_pages())
    after = page.read_text(encoding="utf-8")

    assert "프론트매터 없는 본문만 있는 페이지." in after  # 본문 보존


def test_valid_yaml_page_still_gets_distill_fields(monkeypatch, tmp_path):
    """대조군: 정상 YAML 페이지는 distill 필드가 정상 추가되어야 한다 (기존 기능 회귀 방지)."""
    valid_page = (
        "---\n"
        "title: Valid Page\n"
        "type: concept\n"
        "tags: [a, b]\n"
        "created: 2026-01-01\n"
        "---\n\n"
        "본문.\n"
    )
    wiki = _make_wiki(tmp_path, valid_page)
    _patch_module_paths(monkeypatch, tmp_path, wiki)

    page = wiki / "concepts" / "second-brain.md"
    curate.run_distill(curate.find_all_wiki_pages())
    after = page.read_text(encoding="utf-8")

    assert "title:" in after and "Valid Page" in after  # 기존 필드 유지
    assert "distill_level:" in after  # distill 필드 추가됨
    assert "access_count:" in after


def test_lifecycle_no_sources_yaml_does_not_crash(monkeypatch, tmp_path):
    """RED→GREEN: schema/sources.yaml 없는 환경에서 run_lifecycle 크래시 안 함.

    수정 전: (SCHEMA_DIR / "sources.yaml").read_text() 가 FileNotFoundError.
    수정 후: 없으면 graceful (example 폴백 또는 빈 config 로 skip).
    """
    valid_page = (
        "---\ntitle: P\ntype: insight\ncreated: 2026-01-01\n---\n\n본문.\n"
    )
    wiki = tmp_path / "wiki"
    (wiki / "insights").mkdir(parents=True)
    (wiki / "insights" / "p.md").write_text(valid_page, encoding="utf-8")
    schema = tmp_path / "schema"
    schema.mkdir()  # sources.yaml 도 sources.example.yaml 도 없는 fresh clone 상태

    _patch_module_paths(monkeypatch, tmp_path, wiki)

    # 크래시하지 않고 dict 를 반환해야 한다.
    result = curate.run_lifecycle(curate.find_all_wiki_pages())
    assert isinstance(result, dict)
    assert "archive" in result and "delete" in result


def test_bare_curate_no_sources_yaml_does_not_crash(monkeypatch, tmp_path):
    """RED→GREEN: 인자 없는 bare curate(=run_all) 가 sources.yaml 없어도 크래시 안 함."""
    valid_page = (
        "---\ntitle: P\ntype: insight\ncreated: 2026-01-01\n---\n\n본문.\n"
    )
    wiki = tmp_path / "wiki"
    (wiki / "insights").mkdir(parents=True)
    (wiki / "insights" / "p.md").write_text(valid_page, encoding="utf-8")
    (tmp_path / "schema").mkdir()

    _patch_module_paths(monkeypatch, tmp_path, wiki)
    monkeypatch.setattr(sys, "argv", ["curate.py"])  # bare = run_all

    # main() 이 FileNotFoundError 로 죽지 않아야 한다.
    curate.main()
