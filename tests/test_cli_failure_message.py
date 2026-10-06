"""로그인이 안 된 claude CLI 의 실패가 "인용 거부"로 둔갑하지 않고 원인 그대로 보이는지 검증한다.

2026-10-06 e2e(Codex 검증자, 격리된 환경): `claude -p` 가 "Not logged in · Please run /login" 을
표준출력에 쓰고 종료 코드 1 로 끝났는데, 이 글이 답변으로 넘어가 화면에는
`claim citation rejected: answer requires at least one valid trusted citation` 만 떴다.
"""
import asyncio
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient

import wiki_app.api as api_module
from scripts.lib.llm_client import LLMError, call_llm
from wiki_app.api import create_app

pytestmark = pytest.mark.skipif(os.name == "nt", reason="셸 스크립트로 claude 를 흉내 낸다")


def _fake_claude(tmp_path: Path, monkeypatch, *, stdout: str, code: int):
    script = tmp_path / "claude"
    script.write_text(f"#!/bin/sh\ncat > /dev/null\necho '{stdout}'\nexit {code}\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")


def test_cli_failure_surfaces_the_real_reason(tmp_path, monkeypatch):
    """깨지면: 로그인이 풀린 수강생이 "문서에 근거가 없다"는 엉뚱한 오류만 보고 원인을 못 찾는다."""
    _fake_claude(tmp_path, monkeypatch, stdout="Not logged in · Please run /login", code=1)
    with pytest.raises(LLMError, match="Not logged in"):
        asyncio.run(call_llm("q", config={"engine": "cli"}))


def test_cli_success_still_returns_the_answer(tmp_path, monkeypatch):
    _fake_claude(tmp_path, monkeypatch, stdout="정상 답변", code=0)
    assert asyncio.run(call_llm("q", config={"engine": "cli"})) == "정상 답변"


def test_answer_endpoint_shows_the_cli_failure_message(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    (project / "wiki" / "concepts").mkdir(parents=True)
    (project / "raw" / "notes").mkdir(parents=True)
    (project / "index.md").write_text("## concepts/ (1개)\n", encoding="utf-8")
    raw = project / "raw" / "notes" / "a.md"
    raw.write_text("Alpha fact.\n", encoding="utf-8")
    (project / "wiki" / "concepts" / "a.md").write_text(
        "---\ntitle: A\ncreated: 2026-08-01\nupdated: 2026-08-10\nsources:\n  - raw/notes/a.md\n---\n\nAlpha fact.\n",
        encoding="utf-8")
    claim = {"claim_id": "claim:a-1", "statement": "Alpha fact.", "kind": "fact",
             "raw_path": "raw/notes/a.md", "raw_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
             "locator": "raw/notes/a.md#L1-L1", "valid_from": "2026-08-01", "valid_until": "2099-12-31",
             "status": "active", "trust": "trusted"}
    (project / "claims.jsonl").write_text(json.dumps(claim) + "\n", encoding="utf-8")
    client = TestClient(create_app(wiki_root=project / "wiki"))
    monkeypatch.setattr(api_module.llm_client, "load_llm_config", lambda: {"engine": "cli"})
    _fake_claude(tmp_path, monkeypatch, stdout="Not logged in · Please run /login", code=1)

    data = client.post("/api/ai-answer", json={"question": "Alpha?", "context_slugs": ["a"]}).json()

    assert data["status"] == "error"
    assert "Not logged in" in data["message"]
    assert "citation" not in data["message"]
