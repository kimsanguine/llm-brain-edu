"""wiki_app AI 답변 → episode 원장 배선 테스트 (Phase 1, PRD US-002).

WHY (이 테스트가 인코딩하는 의도):
  1. 양 핸들러(비스트림·스트림)는 AI 답변 1건마다 episode 를 **정확히 1개** 기록한다
     (task_type="ai_answer", 질문, 유효 slug 를 wiki/ 경로로).
  2. **fail-soft 계약(US-002 AC·FR-8):** episode.append 가 raise 해도 AI 답변
     엔드포인트는 평소 응답을 그대로 반환한다 — 500·예외 전파 금지. episode 기록
     실패가 사용자 응답을 절대 깨거나 바꾸지 않는다.

claude CLI 는 fake subprocess 로 대체하고, episode.append 는 monkeypatch 로
가로채(capture) 또는 raise 시켜 사용자 episodes/ 를 건드리지 않는다.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

import wiki_app.api as api_module
from wiki_app.api import create_app


# ---------------------------------------------------------------------------
# fake subprocess — claude CLI 없이 비스트림(communicate)·스트림(readline/wait) 모두 모사
# ---------------------------------------------------------------------------


class _Reader:
    def __init__(self, lines: list[bytes] | None = None):
        self._lines = list(lines or [])

    async def readline(self) -> bytes:
        return self._lines.pop(0) if self._lines else b""

    async def read(self) -> bytes:
        return b""


class _FakeProc:
    """비스트림·스트림 둘 다 정상(done) 경로로 끝나는 fake proc."""

    def __init__(self, *, stdout_lines: list[bytes] | None = None, returncode: int = 0):
        self.stdout = _Reader(
            stdout_lines
            if stdout_lines is not None
            else ["관련 정보 없음\n".encode()]
        )
        self.stderr = _Reader([])
        self._rc = returncode
        self.returncode = None
        self.pid = 4242

    def kill(self):  # 정상 경로에선 호출 안 됨
        pass

    async def communicate(self):
        self.returncode = 0
        return ("관련 정보 없음".encode(), b"")

    async def wait(self):
        if self.returncode is None:
            self.returncode = self._rc
        return self.returncode


def _make_wiki(tmp_path) -> Path:
    """wiki_root/concepts/alpha.md (slug="alpha") + index.md 를 갖춘 tmp 프로젝트."""
    project_root = tmp_path / "proj"
    wiki_root = project_root / "wiki"
    (wiki_root / "concepts").mkdir(parents=True)
    (wiki_root / "concepts" / "alpha.md").write_text(
        "---\ntitle: Alpha\ntags: [misc]\n---\n# Alpha\n\n본문.\n"
    )
    (project_root / "index.md").write_text("## concepts/ (1개)\n- [[alpha]] — 알파\n")
    return wiki_root


def _make_trusted_wiki(tmp_path) -> Path:
    wiki_root = _make_wiki(tmp_path)
    project_root = wiki_root.parent
    raw_bytes = b"Alpha current fact.\n"
    raw_path = project_root / "raw" / "notes" / "alpha.md"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(raw_bytes)
    (wiki_root / "concepts" / "alpha.md").write_text(
        "---\ntitle: Alpha\nsources: [raw/notes/alpha.md]\n---\n\nAlpha current fact.\n",
        encoding="utf-8",
    )
    record = {
        "claim_id": "claim:alpha-1",
        "statement": "Alpha current fact.",
        "kind": "fact",
        "raw_path": "raw/notes/alpha.md",
        "raw_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "valid_from": "2026-08-01",
        "valid_until": "2099-12-31",
        "status": "active",
        "trust": "trusted",
    }
    (project_root / "claims.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    return wiki_root


def _install_fake_claude(monkeypatch, proc: _FakeProc) -> None:
    monkeypatch.setattr(api_module.shutil, "which", lambda name: "/usr/bin/claude")

    async def fake_exec(*args, **kwargs):
        return proc

    monkeypatch.setattr(api_module.asyncio, "create_subprocess_exec", fake_exec)


# ---------------------------------------------------------------------------
# 1) capture — AI 답변 1건이 episode 를 정확히 1개, 올바른 필드로 기록
# ---------------------------------------------------------------------------


def test_non_stream_records_one_ai_answer_episode(tmp_path, monkeypatch):
    wiki_root = _make_wiki(tmp_path)
    _install_fake_claude(monkeypatch, _FakeProc())

    captured: list[dict] = []
    monkeypatch.setattr(
        api_module.episode, "append",
        lambda record, **kw: captured.append(record),
    )

    client = TestClient(create_app(wiki_root=wiki_root))
    r = client.post("/api/ai-answer",
                    json={"question": "알파란?", "context_slugs": ["alpha"]})

    assert r.status_code == 200
    assert r.json()["status"] == "abstained"

    # 정확히 1건 기록
    assert len(captured) == 1
    rec = captured[0]
    assert rec["task_type"] == "ai_answer"
    assert rec["user_goal"] == "알파란?"
    assert rec["inputs"] == {"question": "알파란?"}
    # 유효 slug 가 wiki/ 경로로
    assert rec["read_pages"] == ["wiki/alpha.md"]
    assert rec["procedures_used"] == []
    assert rec["outputs"] == {"answer_status": "abstained"}
    assert rec["status"] == "abstained"
    assert rec["notes"] == ""
    # timestamp 는 tz-aware ISO (오프셋 포함)
    assert "T" in rec["timestamp"]
    from datetime import datetime as _datetime
    assert _datetime.fromisoformat(rec["timestamp"]).tzinfo is not None


def test_stream_records_one_ai_answer_episode(tmp_path, monkeypatch):
    wiki_root = _make_wiki(tmp_path)
    _install_fake_claude(
        monkeypatch, _FakeProc(stdout_lines=["관련 정보 없음\n".encode()])
    )

    captured: list[dict] = []
    monkeypatch.setattr(
        api_module.episode, "append",
        lambda record, **kw: captured.append(record),
    )

    client = TestClient(create_app(wiki_root=wiki_root))
    with client.stream("POST", "/api/ai-answer/stream",
                       json={"question": "알파란?", "context_slugs": ["alpha"]}) as r:
        body = r.read().decode("utf-8")

    assert "event: done" in body

    assert len(captured) == 1
    rec = captured[0]
    assert rec["task_type"] == "ai_answer"
    assert rec["user_goal"] == "알파란?"
    assert rec["read_pages"] == ["wiki/alpha.md"]
    assert rec["outputs"] == {"answer_status": "abstained"}
    assert rec["status"] == "abstained"


# ---------------------------------------------------------------------------
# 2) fail-soft (CRITICAL) — episode.append 가 raise 해도 응답은 정상
# ---------------------------------------------------------------------------


def test_non_stream_episode_failure_is_fail_soft(tmp_path, monkeypatch):
    """episode.append 가 raise 해도 /api/ai-answer 는 평소 200/abstained를 반환한다.

    episode 기록 실패가 AI 답변 응답을 절대 깨거나(500) 바꾸지 않는다(US-002 AC).
    """
    wiki_root = _make_wiki(tmp_path)
    _install_fake_claude(monkeypatch, _FakeProc())

    def boom(record, **kw):
        raise RuntimeError("episode ledger down")

    monkeypatch.setattr(api_module.episode, "append", boom)

    client = TestClient(create_app(wiki_root=wiki_root))
    r = client.post("/api/ai-answer",
                    json={"question": "알파란?", "context_slugs": ["alpha"]})

    # 핵심 단언: 500 도, 예외 전파도 없이 평소 응답 그대로
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "abstained"
    assert data["answer"] == "관련 정보 없음"
    assert data["sources"] == []


def test_stream_episode_failure_is_fail_soft(tmp_path, monkeypatch):
    """episode.append 가 raise 해도 SSE 스트림은 정상적으로 done 까지 완료한다."""
    wiki_root = _make_wiki(tmp_path)
    _install_fake_claude(
        monkeypatch, _FakeProc(stdout_lines=["관련 정보 없음\n".encode()])
    )

    def boom(record, **kw):
        raise RuntimeError("episode ledger down")

    monkeypatch.setattr(api_module.episode, "append", boom)

    client = TestClient(create_app(wiki_root=wiki_root))
    with client.stream("POST", "/api/ai-answer/stream",
                       json={"question": "알파란?", "context_slugs": ["alpha"]}) as r:
        assert r.status_code == 200
        body = r.read().decode("utf-8")

    # 스트림이 error 로 깨지지 않고 정상 done 까지 도달
    assert "event: done" in body
    assert "관련 정보 없음" in body


# ---------------------------------------------------------------------------
# 3) unavailable(early-return) 경로는 finally 진입 전이라 episode 미기록
# ---------------------------------------------------------------------------


def test_non_stream_unavailable_records_no_episode(tmp_path, monkeypatch):
    """claude CLI 부재 → unavailable early-return (subprocess try 진입 전).
    finally 가 실행되지 않으므로 episode 는 기록되지 않는다."""
    wiki_root = _make_trusted_wiki(tmp_path)
    monkeypatch.setattr(api_module.shutil, "which", lambda name: None)

    captured: list[dict] = []
    monkeypatch.setattr(
        api_module.episode, "append",
        lambda record, **kw: captured.append(record),
    )

    client = TestClient(create_app(wiki_root=wiki_root))
    r = client.post("/api/ai-answer",
                    json={"question": "알파란?", "context_slugs": ["alpha"]})

    assert r.status_code == 200
    assert r.json()["status"] == "unavailable"
    assert captured == []
