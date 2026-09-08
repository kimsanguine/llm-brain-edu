"""sync_raw.py Capture Filter(require_keywords·min_word_count) 계약 테스트 — v0.3.0 WS-4.

WHY (이 테스트가 인코딩하는 의도):
  1. require_keywords — 리스트 중 **하나라도** 본문에 포함되면 통과(대소문자 무시),
     하나도 없으면 raw로 미복사 + 스킵 로그.
  2. min_word_count — 공백 분리 단어 수가 미만이면 미복사 + 스킵 로그.
  3. 두 필드 모두 optional — 미설정 소스는 기존 sync와 **완전 동일** 동작.
  4. md·txt 외 형식(pdf 등)은 텍스트 판정 불가 → 필터 미적용 통과.

tmp_path self-contained: sync_raw.WIKI_ROOT를 격리하고 소스 디렉토리도 tmp에 만든다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest

import sync_raw
from sync_raw import capture_filter_reason, sync_source


@pytest.fixture
def tmp_sync(tmp_path, monkeypatch):
    """(소스 디렉토리, WIKI_ROOT) 격리 튜플을 반환한다."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    wiki_root = tmp_path / "brain"
    wiki_root.mkdir()
    monkeypatch.setattr(sync_raw, "WIKI_ROOT", wiki_root)
    monkeypatch.setattr(sync_raw, "STATE_FILE", wiki_root / ".sync_state.json")
    return src_dir, wiki_root


def _cfg(src_dir: Path, **extra) -> dict:
    return {"id": "t", "source": str(src_dir), "target": "raw/t/", **extra}


# ---------------------------------------------------------------------------
# ① min_word_count
# ---------------------------------------------------------------------------

def test_min_word_count_skips_short_file(tmp_sync, capsys):
    src_dir, wiki_root = tmp_sync
    (src_dir / "short.md").write_text("단어 셋 뿐")
    cfg = _cfg(src_dir, min_word_count=10)

    copied, skipped = sync_source(cfg, {})

    assert (copied, skipped) == (0, 1)
    assert not (wiki_root / "raw" / "t" / "short.md").exists()
    out = capsys.readouterr().out
    assert "[필터]" in out and "min_word_count" in out


def test_min_word_count_copies_long_enough_file(tmp_sync):
    src_dir, wiki_root = tmp_sync
    (src_dir / "long.md").write_text(" ".join(f"w{i}" for i in range(20)))
    cfg = _cfg(src_dir, min_word_count=10)

    copied, skipped = sync_source(cfg, {})

    assert copied == 1
    assert (wiki_root / "raw" / "t" / "long.md").exists()


# ---------------------------------------------------------------------------
# ② require_keywords — 하나라도 포함 시 통과
# ---------------------------------------------------------------------------

def test_require_keywords_skips_file_without_any_keyword(tmp_sync, capsys):
    src_dir, wiki_root = tmp_sync
    (src_dir / "offtopic.md").write_text("전혀 관련 없는 내용")
    cfg = _cfg(src_dir, require_keywords=["agent", "RAG"])

    copied, skipped = sync_source(cfg, {})

    assert (copied, skipped) == (0, 1)
    assert not (wiki_root / "raw" / "t" / "offtopic.md").exists()
    out = capsys.readouterr().out
    assert "[필터]" in out and "require_keywords" in out


def test_require_keywords_passes_if_any_one_matches(tmp_sync):
    """리스트 중 하나(RAG)만 포함돼도 통과한다."""
    src_dir, wiki_root = tmp_sync
    (src_dir / "ontopic.md").write_text("RAG 파이프라인 정리")
    cfg = _cfg(src_dir, require_keywords=["agent", "RAG"])

    copied, _ = sync_source(cfg, {})

    assert copied == 1
    assert (wiki_root / "raw" / "t" / "ontopic.md").exists()


def test_require_keywords_case_insensitive(tmp_path):
    """판정 함수 단위: 키워드 매칭은 대소문자 무시."""
    f = tmp_path / "a.md"
    f.write_text("this mentions Agent memory")
    assert capture_filter_reason(f, {"require_keywords": ["AGENT"]}) is None


# ---------------------------------------------------------------------------
# ③ 두 필드 모두 미설정 → 기존과 완전 동일 (전부 복사)
# ---------------------------------------------------------------------------

def test_no_filter_fields_behaves_exactly_as_before(tmp_sync, capsys):
    src_dir, wiki_root = tmp_sync
    (src_dir / "tiny.md").write_text("한 단어")
    (src_dir / "offtopic.md").write_text("키워드 없음")
    cfg = _cfg(src_dir)  # require_keywords·min_word_count 미설정

    copied, skipped = sync_source(cfg, {})

    assert (copied, skipped) == (2, 0)
    assert "[필터]" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# ④ 비 md/txt 형식은 필터 미적용 통과 · 복합 조건
# ---------------------------------------------------------------------------

def test_non_text_format_bypasses_filter(tmp_sync):
    """pdf 등 비텍스트 형식은 판정 불가 → 필터와 무관하게 복사된다."""
    src_dir, wiki_root = tmp_sync
    (src_dir / "doc.pdf").write_bytes(b"%PDF-1.4 fake")
    cfg = _cfg(src_dir, require_keywords=["agent"], min_word_count=100)

    copied, _ = sync_source(cfg, {})

    assert copied == 1
    assert (wiki_root / "raw" / "t" / "doc.pdf").exists()


def test_both_filters_must_pass(tmp_sync):
    """키워드는 포함하지만 단어 수 미달이면 미복사 (AND 결합)."""
    src_dir, wiki_root = tmp_sync
    (src_dir / "short-ontopic.md").write_text("agent 메모")
    cfg = _cfg(src_dir, require_keywords=["agent"], min_word_count=10)

    copied, skipped = sync_source(cfg, {})

    assert (copied, skipped) == (0, 1)


def test_txt_files_are_also_filtered(tmp_sync):
    src_dir, wiki_root = tmp_sync
    (src_dir / "note.txt").write_text("키워드 없는 텍스트")
    cfg = _cfg(src_dir, require_keywords=["agent"], extensions=["md", "txt"])

    copied, skipped = sync_source(cfg, {})

    assert (copied, skipped) == (0, 1)
