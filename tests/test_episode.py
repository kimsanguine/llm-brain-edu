"""episode.py — append-only 에피소드 원장 계약 테스트 (Phase 0, PRD US-001).

WHY (이 테스트가 인코딩하는 의도):
  1. 헬퍼는 fail-loud — 필수 키 누락·타입오류·잘못된 timestamp 는 EpisodeSchemaError
     (조용히 깨진 레코드를 원장에 쌓지 않는다). 단, *호출측* 의 fail-soft 는 Phase 1.
  2. append-only — 기존 줄은 절대 재작성하지 않는다(운영 이력의 무결성).
  3. 월별 샤드 — timestamp 의 YYYY-MM 으로 episodes/YYYY-MM.jsonl 에 적재.
  4. read_recent — 최신순(timestamp desc) 결정적 정렬 + task_type/topic 필터.

episodes_dir 를 tmp_path 로 주입해 사용자 episodes/ 를 건드리지 않는다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import episode  # noqa: E402


def _rec(**over):
    base = dict(
        timestamp="2026-06-27T07:30:00+09:00",
        task_type="ai_answer",
        user_goal="RAG 질문",
        inputs={},
        read_pages=[],
        procedures_used=[],
        outputs={},
        status="ok",
        notes="",
    )
    base.update(over)
    return base


# ── append: 정상 ───────────────────────────────────────────────
def test_append_writes_jsonl_line_to_month_shard(tmp_path):
    episode.append(_rec(), episodes_dir=tmp_path)
    shard = tmp_path / "2026-06.jsonl"
    assert shard.exists()
    lines = shard.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["task_type"] == "ai_answer"


def test_append_is_append_only(tmp_path):
    episode.append(_rec(notes="first"), episodes_dir=tmp_path)
    episode.append(_rec(notes="second"), episodes_dir=tmp_path)
    lines = (tmp_path / "2026-06.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["notes"] == "first"  # 첫 줄 보존


def test_append_unicode_preserved(tmp_path):
    episode.append(_rec(user_goal="한국어 목표"), episodes_dir=tmp_path)
    raw = (tmp_path / "2026-06.jsonl").read_text(encoding="utf-8")
    assert "한국어 목표" in raw  # ensure_ascii=False


def test_append_derives_shard_from_timestamp_month(tmp_path):
    episode.append(_rec(timestamp="2026-07-02T10:00:00+09:00"), episodes_dir=tmp_path)
    assert (tmp_path / "2026-07.jsonl").exists()
    assert not (tmp_path / "2026-06.jsonl").exists()


# ── append: fail-loud ──────────────────────────────────────────
def test_append_missing_required_key_raises_and_writes_nothing(tmp_path):
    bad = _rec()
    del bad["status"]
    with pytest.raises(episode.EpisodeSchemaError):
        episode.append(bad, episodes_dir=tmp_path)
    assert list(tmp_path.glob("*.jsonl")) == []  # 부분 기록 0


def test_append_wrong_type_raises(tmp_path):
    with pytest.raises(episode.EpisodeSchemaError):
        episode.append(_rec(read_pages="wiki/x.md"), episodes_dir=tmp_path)  # str, list 여야


def test_append_bad_timestamp_raises(tmp_path):
    with pytest.raises(episode.EpisodeSchemaError):
        episode.append(_rec(timestamp="not-a-date"), episodes_dir=tmp_path)


# ── read_recent ────────────────────────────────────────────────
def test_read_recent_returns_timestamp_desc(tmp_path):
    episode.append(_rec(timestamp="2026-06-01T00:00:00+09:00", notes="old"), episodes_dir=tmp_path)
    episode.append(_rec(timestamp="2026-06-27T00:00:00+09:00", notes="new"), episodes_dir=tmp_path)
    got = episode.read_recent(episodes_dir=tmp_path)
    assert [r["notes"] for r in got] == ["new", "old"]  # 최신순


def test_read_recent_filters_by_task_type(tmp_path):
    episode.append(_rec(task_type="ai_answer"), episodes_dir=tmp_path)
    episode.append(_rec(task_type="express_blog"), episodes_dir=tmp_path)
    got = episode.read_recent(task_type="express_blog", episodes_dir=tmp_path)
    assert len(got) == 1 and got[0]["task_type"] == "express_blog"


def test_read_recent_filters_by_topic_keyword(tmp_path):
    episode.append(_rec(user_goal="RAG 평가 파이프라인"), episodes_dir=tmp_path)
    episode.append(_rec(user_goal="영상 자막 번역"), episodes_dir=tmp_path)
    got = episode.read_recent(topic="RAG", episodes_dir=tmp_path)
    assert len(got) == 1 and "RAG" in got[0]["user_goal"]


def test_read_recent_respects_limit(tmp_path):
    for i in range(5):
        episode.append(_rec(timestamp=f"2026-06-0{i+1}T00:00:00+09:00"), episodes_dir=tmp_path)
    assert len(episode.read_recent(limit=2, episodes_dir=tmp_path)) == 2


def test_read_recent_empty_when_no_episodes(tmp_path):
    assert episode.read_recent(episodes_dir=tmp_path) == []


# ── 2-렌즈 리뷰 반영: 정렬·직렬화·견고성 ───────────────────────
def test_read_recent_sorts_chronologically_across_timezones(tmp_path):
    # #1(HIGH): 오프셋 다른 ISO 를 문자열이 아니라 *실제 시각* 으로 정렬해야 한다.
    # A=2026-06-27T00:00+00:00(UTC) 는 B=2026-06-27T06:00+09:00(=06-26 21:00 UTC)보다 늦음.
    episode.append(_rec(timestamp="2026-06-27T00:00:00+00:00", notes="A_utc_later"), episodes_dir=tmp_path)
    episode.append(_rec(timestamp="2026-06-27T06:00:00+09:00", notes="B_kst_earlier"), episodes_dir=tmp_path)
    got = episode.read_recent(episodes_dir=tmp_path)
    assert [r["notes"] for r in got] == ["A_utc_later", "B_kst_earlier"]


def test_append_non_serializable_value_raises_episode_error(tmp_path):
    # #2(HIGH): inputs/outputs 에 직렬화 불가 값(Path 등) → bare TypeError 아니라
    # EpisodeSchemaError. Phase 1 호출자의 `except EpisodeSchemaError` fail-soft 가 작동해야
    # 메인 명령 경로가 안 깨진다. FS 부작용 0.
    with pytest.raises(episode.EpisodeSchemaError):
        episode.append(_rec(outputs={"draft_path": Path("express/blog/x.md")}), episodes_dir=tmp_path)
    assert list(tmp_path.glob("*.jsonl")) == []


def test_read_recent_skips_broken_lines(tmp_path):
    # 견고성: 깨진 JSON 줄은 skip, 정상 줄만 반환(원장 read 는 한 줄 손상에 견고).
    episode.append(_rec(notes="good"), episodes_dir=tmp_path)
    with (tmp_path / "2026-06.jsonl").open("a", encoding="utf-8") as f:
        f.write("{이건 깨진 JSON\n")
    assert [r["notes"] for r in episode.read_recent(episodes_dir=tmp_path)] == ["good"]


def test_read_recent_orders_across_shards(tmp_path):
    # 크로스 샤드: 다른 달 레코드도 최신순 통합 정렬(같은 샤드만 쓰던 커버리지 갭).
    episode.append(_rec(timestamp="2026-05-10T00:00:00+09:00", notes="may"), episodes_dir=tmp_path)
    episode.append(_rec(timestamp="2026-06-10T00:00:00+09:00", notes="jun"), episodes_dir=tmp_path)
    assert [r["notes"] for r in episode.read_recent(episodes_dir=tmp_path)] == ["jun", "may"]


def test_read_recent_limit_keeps_newest(tmp_path):
    # limit 은 정렬 *후* 적용 → 최신 N 개 생존(슬라이스-전-정렬 회귀 포착).
    for d in ("01", "02", "03"):
        episode.append(_rec(timestamp=f"2026-06-{d}T00:00:00+09:00", notes=d), episodes_dir=tmp_path)
    assert [r["notes"] for r in episode.read_recent(limit=2, episodes_dir=tmp_path)] == ["03", "02"]
