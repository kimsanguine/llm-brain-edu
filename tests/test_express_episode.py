"""express.py — episode 배선(US-002) + 재사용 frontmatter(US-007) 계약 테스트 (Phase 1).

WHY (이 테스트가 인코딩하는 의도):
  1. US-002 — save_draft 성공 직후 episode.append(record) 가 호출된다. record 의
     task_type/user_goal/read_pages/procedures_used/outputs/status/timestamp 가 계약대로다.
  2. **fail-soft (핵심)** — episode.append 가 터져도(스키마 오류든 임의 예외든) 명령은
     예외를 전파하지 않고, draft 는 여전히 디스크에 남는다(메인 경로 = fail-soft).
  3. US-007 — express 산출물 frontmatter 에 재사용 메타(output_type/published_url/
     source_pages/derived_insight/reuse_as)가 추가되고 기존 필드는 보존된다.

express 의 출력 경로·소스 수집을 monkeypatch 로 tmp_path 에 격리한다(사용자 wiki/ 무관).
episode.append 도 monkeypatch 해 실제 episodes/ 원장을 건드리지 않는다.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import episode  # noqa: E402
import express  # noqa: E402


@pytest.fixture
def tmp_express(tmp_path, monkeypatch):
    """express 의 출력/소스 경로를 tmp_path 로 격리한다."""
    root = tmp_path / "brain"
    (root / "wiki" / "concepts").mkdir(parents=True)
    express_dir = root / "express"
    monkeypatch.setattr(express, "WIKI_ROOT", root)
    monkeypatch.setattr(express, "WIKI_DIR", root / "wiki")
    monkeypatch.setattr(express, "EXPRESS_DIR", express_dir)
    monkeypatch.setattr(express, "RAW_BLOG_DIR", root / "raw" / "blog")
    monkeypatch.setattr(express, "INDEX_FILE", root / "index.md")
    monkeypatch.setattr(
        express,
        "TYPE_DIR",
        {
            "blog": express_dir / "blog",
            "lecture": express_dir / "lecture",
            "summary": express_dir / "summary",
            "report": express_dir / "report",
        },
    )
    return root


def _fake_pages(root: Path):
    """WIKI_ROOT(tmp) 하위의 결정적 wiki 페이지 2개를 반환한다."""
    p1 = root / "wiki" / "concepts" / "alpha.md"
    p2 = root / "wiki" / "concepts" / "beta.md"
    p1.write_text("# Alpha\n본문 a\n")
    p2.write_text("# Beta\n본문 b\n")
    return [(p1, p1.read_text()), (p2, p2.read_text())]


def _capture_append(monkeypatch) -> dict:
    captured: dict = {}
    monkeypatch.setattr(episode, "append", lambda record, **kw: captured.update(record=record))
    return captured


def _parse_frontmatter(text: str) -> dict:
    m = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    assert m is not None, "frontmatter 블록이 없습니다"
    return yaml.safe_load(m.group(1))


# ── US-002: 성공 시 episode 기록 ───────────────────────────────


def test_blog_records_episode_on_success(tmp_express, monkeypatch):
    pages = _fake_pages(tmp_express)
    monkeypatch.setattr(express, "collect_related_pages", lambda topic, max_pages=5: pages)
    captured = _capture_append(monkeypatch)

    express.cmd_blog("RAG 평가")

    rec = captured["record"]
    assert rec["task_type"] == "express_blog"
    assert rec["user_goal"] == "RAG 평가"
    assert rec["read_pages"] == ["wiki/concepts/alpha.md", "wiki/concepts/beta.md"]
    assert rec["procedures_used"] == ["collect_related_pages"]
    assert rec["outputs"]["source_count"] == 2
    assert rec["outputs"]["draft_path"].startswith("express/blog/")
    assert rec["status"] == "draft_ready"
    assert rec["notes"] == ""
    assert rec["inputs"]["topic"] == "RAG 평가"
    # timestamp 는 tz-aware 여야 한다(naive 면 read_recent 교차-TZ 정렬이 깨진다).
    assert datetime.fromisoformat(rec["timestamp"]).tzinfo is not None


def test_lecture_records_episode_with_slides_input(tmp_express, monkeypatch):
    pages = _fake_pages(tmp_express)
    monkeypatch.setattr(express, "collect_related_pages", lambda topic, max_pages=6: pages)
    captured = _capture_append(monkeypatch)

    express.cmd_lecture("orchestration", slides=3)

    rec = captured["record"]
    assert rec["task_type"] == "express_lecture"
    assert rec["inputs"]["slides"] == 3
    assert rec["outputs"]["source_count"] == 2
    assert rec["status"] == "draft_ready"


def test_report_records_episode(tmp_express, monkeypatch):
    pages = _fake_pages(tmp_express)
    monkeypatch.setattr(express, "collect_related_pages", lambda topic, max_pages=8: pages)
    captured = _capture_append(monkeypatch)

    express.cmd_report("경쟁사 현황")

    rec = captured["record"]
    assert rec["task_type"] == "express_report"
    assert rec["user_goal"] == "경쟁사 현황"
    assert rec["read_pages"] == ["wiki/concepts/alpha.md", "wiki/concepts/beta.md"]
    assert rec["status"] == "draft_ready"


def test_summary_records_episode(tmp_express, monkeypatch):
    pages = _fake_pages(tmp_express)
    monkeypatch.setattr(express, "collect_recent_pages", lambda days: pages)
    captured = _capture_append(monkeypatch)

    express.cmd_summary(week=True, month=False)

    rec = captured["record"]
    assert rec["task_type"] == "express_summary"
    assert rec["read_pages"] == ["wiki/concepts/alpha.md", "wiki/concepts/beta.md"]
    # summary 는 collect_recent_pages 를 사용한다(원장에 사실 그대로 기록).
    assert rec["procedures_used"] == ["collect_recent_pages"]
    assert rec["outputs"]["source_count"] == 2
    assert rec["status"] == "draft_ready"


# ── US-002: fail-soft (핵심) ───────────────────────────────────


def test_blog_fail_soft_when_episode_append_raises(tmp_express, monkeypatch):
    """episode.append 가 임의 예외로 터져도 명령은 예외를 전파하지 않고 draft 는 남는다."""
    pages = _fake_pages(tmp_express)
    monkeypatch.setattr(express, "collect_related_pages", lambda topic, max_pages=5: pages)

    def boom(record, **kw):
        raise RuntimeError("ledger down")

    monkeypatch.setattr(episode, "append", boom)

    express.cmd_blog("회복력 토픽")  # 예외 전파 없어야 한다

    drafts = list(express.TYPE_DIR["blog"].glob("*.md"))
    assert len(drafts) == 1  # draft 는 여전히 기록됨


def test_blog_fail_soft_on_schema_error(tmp_express, monkeypatch):
    """헬퍼의 EpisodeSchemaError(스키마 거부)도 명령을 깨지 않는다."""
    pages = _fake_pages(tmp_express)
    monkeypatch.setattr(express, "collect_related_pages", lambda topic, max_pages=5: pages)

    def schema_err(record, **kw):
        raise episode.EpisodeSchemaError("bad record")

    monkeypatch.setattr(episode, "append", schema_err)

    express.cmd_blog("스키마 토픽")  # 예외 전파 없어야 한다

    assert list(express.TYPE_DIR["blog"].glob("*.md"))


# ── US-007: 재사용 frontmatter ─────────────────────────────────


def test_blog_frontmatter_has_reuse_fields(tmp_express, monkeypatch):
    pages = _fake_pages(tmp_express)
    monkeypatch.setattr(express, "collect_related_pages", lambda topic, max_pages=5: pages)
    monkeypatch.setattr(episode, "append", lambda record, **kw: None)

    express.cmd_blog("재사용 토픽")

    draft = next(express.TYPE_DIR["blog"].glob("*.md")).read_text()
    fm = _parse_frontmatter(draft)

    # 신규 재사용 메타
    assert fm["output_type"] == "blog"
    assert "published_url" in fm and fm["published_url"] is None
    assert fm["source_pages"] == ["alpha", "beta"]
    assert "derived_insight" in fm and fm["derived_insight"] is None
    assert fm["reuse_as"] == []
    # 기존 필드 보존
    assert fm["type"] == "blog"
    assert fm["status"] == "draft"
    assert fm["topic"] == "재사용 토픽"


def test_lecture_frontmatter_has_reuse_fields(tmp_express, monkeypatch):
    pages = _fake_pages(tmp_express)
    monkeypatch.setattr(express, "collect_related_pages", lambda topic, max_pages=6: pages)
    monkeypatch.setattr(episode, "append", lambda record, **kw: None)

    express.cmd_lecture("강의 토픽", slides=4)

    draft = next(express.TYPE_DIR["lecture"].glob("*.md")).read_text()
    fm = _parse_frontmatter(draft)
    assert fm["output_type"] == "lecture"
    assert fm["source_pages"] == ["alpha", "beta"]
    assert fm["reuse_as"] == []
    assert fm["slides"] == 4  # 기존 필드 보존


def test_summary_frontmatter_source_pages_empty_is_valid_yaml(tmp_express, monkeypatch):
    """소스가 0개여도 source_pages 는 유효한 YAML 빈 리스트여야 한다."""
    monkeypatch.setattr(express, "collect_recent_pages", lambda days: [])
    monkeypatch.setattr(episode, "append", lambda record, **kw: None)

    express.cmd_summary(week=False, month=True)

    draft = next(express.TYPE_DIR["summary"].glob("*.md")).read_text()
    fm = _parse_frontmatter(draft)
    assert fm["output_type"] == "summary"
    assert fm["source_pages"] == []
    assert fm["reuse_as"] == []
