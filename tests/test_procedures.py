"""procedures.py — 재사용 절차 메모리 로더 계약 테스트 (Phase 3, PRD US-004).

WHY (이 테스트가 인코딩하는 의도):
  1. list_procedures — procedures_dir 의 .md 파일 slug 를 결정적(정렬)으로 나열.
  2. read_procedure — frontmatter_utils 로 (fm, body) 파싱, memory_type 보존.
  3. 절차 파일은 memory_type: procedural 을 선언(§C2) — episodic/semantic 과 구분되는
     "어떻게 하는가" 기질. 이 라벨이 brain_context 의 후보 procedure 필터와 OKF strip
     모드의 근거다.
  4. repo 에 *실제 커밋되는* 예시 절차(procedures/)가 전부 파싱되고 procedural 을
     선언한다 — 예시가 깨지면 loader 계약의 산 증인이 사라진다.

procedures_dir 를 tmp_path 로 주입해 격리한다(컨벤션: episode_test 와 동일).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import procedures  # noqa: E402

_REAL_PROCEDURES_DIR = _REPO_ROOT / "procedures"
_EXPECTED_EXAMPLE_SLUGS = {"ingest", "curate", "express-blog", "okf-export-safety"}


def _write(dir_: Path, slug: str, *, memory_type: str = "procedural", body: str = "1. 첫 스텝\n") -> None:
    text = f"---\ntitle: {slug} 절차\nmemory_type: {memory_type}\ntags:\n  - {slug}\n---\n{body}"
    (dir_ / f"{slug}.md").write_text(text, encoding="utf-8")


# ── list_procedures ────────────────────────────────────────────
def test_list_procedures_returns_present_slugs(tmp_path):
    _write(tmp_path, "alpha")
    _write(tmp_path, "beta")
    assert procedures.list_procedures(procedures_dir=tmp_path) == ["alpha", "beta"]


def test_list_procedures_is_sorted_deterministic(tmp_path):
    for slug in ("zeta", "alpha", "mu"):
        _write(tmp_path, slug)
    assert procedures.list_procedures(procedures_dir=tmp_path) == ["alpha", "mu", "zeta"]


def test_list_procedures_ignores_non_md(tmp_path):
    _write(tmp_path, "real")
    (tmp_path / "notes.txt").write_text("not a procedure", encoding="utf-8")
    assert procedures.list_procedures(procedures_dir=tmp_path) == ["real"]


def test_list_procedures_empty_when_dir_absent(tmp_path):
    assert procedures.list_procedures(procedures_dir=tmp_path / "nope") == []


# ── read_procedure ─────────────────────────────────────────────
def test_read_procedure_returns_fm_and_body(tmp_path):
    _write(tmp_path, "ingest", body="1. scripts/ingest.py 실행\n2. index.md 갱신\n")
    fm, body = procedures.read_procedure("ingest", procedures_dir=tmp_path)
    assert fm["memory_type"] == "procedural"
    assert fm["title"] == "ingest 절차"
    assert "scripts/ingest.py" in body


def test_read_procedure_missing_slug_raises(tmp_path):
    # fail-loud — 부재 절차에 조용한 빈 반환 금지(호출측이 오타를 알아채야 한다).
    with pytest.raises(FileNotFoundError):
        procedures.read_procedure("does-not-exist", procedures_dir=tmp_path)


def test_read_procedure_preserves_unicode_body(tmp_path):
    _write(tmp_path, "curate", body="1. 감사 → 압축 → 수명 관리\n")
    _, body = procedures.read_procedure("curate", procedures_dir=tmp_path)
    assert "감사 → 압축 → 수명 관리" in body


# ── 실제 커밋되는 예시 절차 (git-tracked, OKF-excluded) ─────────
def test_real_examples_present():
    got = set(procedures.list_procedures(procedures_dir=_REAL_PROCEDURES_DIR))
    assert _EXPECTED_EXAMPLE_SLUGS <= got, f"누락된 예시 절차: {_EXPECTED_EXAMPLE_SLUGS - got}"


def test_real_examples_all_parse_and_declare_procedural():
    for slug in procedures.list_procedures(procedures_dir=_REAL_PROCEDURES_DIR):
        fm, body = procedures.read_procedure(slug, procedures_dir=_REAL_PROCEDURES_DIR)
        assert fm.get("memory_type") == "procedural", f"{slug}: memory_type != procedural"
        assert fm.get("title"), f"{slug}: title 누락"
        assert fm.get("tags"), f"{slug}: tags 누락"
        assert body.strip(), f"{slug}: 본문(워크플로우 스텝) 누락"
