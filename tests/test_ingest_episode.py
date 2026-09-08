"""ingest.py — staging episode 배선(US-002) 계약 테스트 (Phase 1).

WHY (이 테스트가 인코딩하는 의도):
  1. URL/파일/노트 저장 성공 직후 main() 이 episode.append(record) 를 호출한다.
     status="pending_wiki_compilation"(아직 wiki 컴파일 전 staging) 이고
     task_type 은 ingest_url|ingest_file|ingest_note 로 분기, outputs.saved_path 가
     저장 경로(raw/...) 다.
  2. **fail-soft** — episode.append 가 터져도 ingest 명령은 예외를 전파하지 않고
     기존 종료 코드 계약(미처리=exit 1)을 그대로 탄다. 저장물은 남는다.

WIKI_ROOT/RAW_DIR/STATE_FILE 를 tmp_path 로 격리하고 episode.append 를 monkeypatch 해
실제 episodes/ 원장과 사용자 raw/ 를 건드리지 않는다. 네트워크 회피 위해 note/file 분기로 검증.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import episode  # noqa: E402
import ingest  # noqa: E402


@pytest.fixture
def tmp_raw(tmp_path, monkeypatch):
    wiki_root = tmp_path / "brain"
    raw_dir = wiki_root / "raw"
    raw_dir.mkdir(parents=True)
    monkeypatch.setattr(ingest, "WIKI_ROOT", wiki_root)
    monkeypatch.setattr(ingest, "RAW_DIR", raw_dir)
    monkeypatch.setattr(ingest, "STATE_FILE", wiki_root / ".ingest_state.json")
    return wiki_root


def _capture_append(monkeypatch) -> dict:
    captured: dict = {}
    monkeypatch.setattr(episode, "append", lambda record, **kw: captured.update(record=record))
    return captured


def test_ingest_note_records_pending_episode(tmp_raw, monkeypatch):
    captured = _capture_append(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["ingest.py", "--note", "RAG 메모", "--resonance", "high"])

    with pytest.raises(SystemExit):  # 미처리 노트 존재 → 종료 코드 1
        ingest.main()

    rec = captured["record"]
    assert rec["task_type"] == "ingest_note"
    assert rec["status"] == "pending_wiki_compilation"
    assert rec["inputs"]["source"] == "RAG 메모"
    assert rec["inputs"]["resonance"] == "high"
    assert rec["read_pages"] == []
    assert rec["procedures_used"] == []
    assert rec["outputs"]["saved_path"].startswith("raw/notes/")
    assert rec["notes"] == ""
    assert datetime.fromisoformat(rec["timestamp"]).tzinfo is not None


def test_ingest_file_records_pending_episode(tmp_raw, monkeypatch):
    src = tmp_raw / "paper.md"
    src.write_text("# 논문\n내용\n")
    captured = _capture_append(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["ingest.py", "--file", str(src)])

    with pytest.raises(SystemExit):
        ingest.main()

    rec = captured["record"]
    assert rec["task_type"] == "ingest_file"
    assert rec["status"] == "pending_wiki_compilation"
    assert rec["inputs"]["source"] == str(src)
    assert rec["inputs"]["resonance"] is None  # --resonance 미지정 → null
    assert rec["outputs"]["saved_path"].startswith("raw/docs/")


def test_ingest_note_fail_soft_when_append_raises(tmp_raw, monkeypatch):
    """episode.append 가 터져도 ingest 는 예외 전파 없이 종료 코드 계약을 탄다."""

    def boom(record, **kw):
        raise RuntimeError("ledger down")

    monkeypatch.setattr(episode, "append", boom)
    monkeypatch.setattr(sys, "argv", ["ingest.py", "--note", "회복 메모"])

    # RuntimeError 가 아니라 SystemExit(정상 종료 경로)가 떠야 fail-soft 성립.
    with pytest.raises(SystemExit) as exc:
        ingest.main()
    assert exc.value.code == 1  # 미처리 노트 존재

    # 노트는 여전히 저장돼 있어야 한다.
    notes = list((tmp_raw / "raw" / "notes").glob("*.md"))
    assert len(notes) == 1
