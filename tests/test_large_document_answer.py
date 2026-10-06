"""200쪽짜리 PDF 같은 큰 문서에서도 AI 답변이 끝까지 가는지 검증한다.

2026-10-06 e2e: 한국 AI 행동계획 PDF(근거 약 3.2MB)로 질문하면 `LLM 호출 중 오류: OSError`
(Argument list too long)가 났다. 원인은 둘이었다. 프롬프트를 명령행 인자로 보내 운영체제
한계(맥 약 1MB, 윈도우 약 32KB)를 넘겼고, 질문과 무관하게 페이지의 근거를 전부 보냈다.
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
from scripts.lib import claim_ledger
from scripts.lib.llm_client import call_llm
from wiki_app.api import create_app

FILLER_COUNT = 600
FILLER_TEXT = "배경 설명 문장입니다 " * 40          # 한 건 약 1KB, 600건이면 상한을 넘는다
RELEVANT = "미국 AI 행동계획의 세 가지 기둥은 혁신, 인프라, 국제 외교와 안보다."


def _claim(project_root: Path, number: str, statement: str, raw_path: str, trust="trusted"):
    return {
        "claim_id": f"claim:{number}",
        "statement": statement,
        "kind": "fact",
        "raw_path": raw_path,
        "raw_sha256": hashlib.sha256((project_root / raw_path).read_bytes()).hexdigest(),
        "locator": f"{raw_path}#L1-L1",
        "valid_from": "2026-08-01",
        "valid_until": "2099-12-31",
        "status": "active",
        "trust": trust,
    }


def _big_project(tmp_path: Path) -> tuple[Path, list[dict]]:
    project_root = tmp_path / "proj"
    wiki_root = project_root / "wiki"
    (wiki_root / "concepts").mkdir(parents=True)
    (project_root / "raw" / "docs").mkdir(parents=True)
    (project_root / "raw" / "clippings").mkdir(parents=True)
    (project_root / "index.md").write_text("## concepts/ (1개)\n", encoding="utf-8")
    (project_root / "raw" / "docs" / "big.md").write_text("big doc\n", encoding="utf-8")
    (project_root / "raw" / "clippings" / "web.md").write_text("web\n", encoding="utf-8")
    (wiki_root / "concepts" / "big.md").write_text(
        "---\ntitle: Big\ncreated: 2026-08-01\nupdated: 2026-08-10\n"
        "sources:\n  - raw/docs/big.md\n---\n\nbig\n",
        encoding="utf-8",
    )
    claims = [
        _claim(project_root, f"big-{i + 1}", f"{i}번 {FILLER_TEXT}", "raw/docs/big.md")
        for i in range(FILLER_COUNT)
    ]
    claims.append(_claim(project_root, "big-9999", RELEVANT, "raw/docs/big.md"))
    (project_root / "claims.jsonl").write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in claims), encoding="utf-8"
    )
    return project_root, claims


def _records(claims):
    return [claim_ledger.ClaimRecord(**c) for c in claims]


def test_over_budget_ledger_keeps_the_claims_that_match_the_question(tmp_path):
    # 근거를 앞에서부터 자르면 문서 뒷부분에 있는 답이 사라진다. 질문과 겹치는 근거가 남아야 한다.
    project_root, claims = _big_project(tmp_path)
    records = _records(claims)

    selected = claim_ledger.select_claims_for_question(
        records, "미국 AI 행동계획의 세 가지 기둥은 무엇인가요?", project_root=project_root
    )

    size = sum(
        len(json.dumps(r.to_mapping(), ensure_ascii=True, sort_keys=True, separators=(",", ":")))
        for r in selected
    )
    assert size <= claim_ledger.CONTEXT_MAX_BYTES
    assert "claim:big-9999" in {r.claim_id for r in selected}


def test_within_budget_ledger_is_sent_unchanged(tmp_path):
    # 작은 문서의 답변이 달라지면 안 된다(질문과 안 겹치는 근거도 그대로 간다).
    project_root, claims = _big_project(tmp_path)
    records = _records(claims[:5])

    selected = claim_ledger.select_claims_for_question(
        records, "전혀 다른 질문", project_root=project_root
    )

    assert [r.claim_id for r in selected] == [r.claim_id for r in records]


def test_trusted_claims_win_the_budget_over_untrusted_web_text(tmp_path):
    # 외부 웹 글이 예산을 다 먹어 정작 신뢰하는 근거가 빠지면, 답변이 거절로 끝난다.
    project_root, claims = _big_project(tmp_path)
    web = [
        _claim(project_root, f"web-{i + 1}", f"{RELEVANT} {FILLER_TEXT}", "raw/clippings/web.md", "untrusted")
        for i in range(FILLER_COUNT)
    ]
    records = _records(web + claims)

    selected = claim_ledger.select_claims_for_question(
        records, "미국 AI 행동계획의 세 가지 기둥은?", project_root=project_root
    )

    assert "claim:big-9999" in {r.claim_id for r in selected}


def test_big_page_answer_sends_a_bounded_prompt_and_keeps_citations_valid(tmp_path, monkeypatch):
    project_root, _claims = _big_project(tmp_path)
    client = TestClient(create_app(wiki_root=project_root / "wiki"))
    monkeypatch.setattr(api_module.llm_client, "load_llm_config", lambda: {"engine": "api"})
    captured = {}

    async def fake_call_llm(prompt, *, config, timeout):
        captured["prompt"] = prompt
        return "세 가지 기둥은 혁신, 인프라, 국제 외교와 안보입니다. [claim:big-9999]"

    monkeypatch.setattr(api_module.llm_client, "call_llm", fake_call_llm)

    r = client.post(
        "/api/ai-answer",
        json={"question": "미국 AI 행동계획의 세 가지 기둥은 무엇인가요?", "context_slugs": ["big"]},
    )

    data = r.json()
    assert data["status"] == "done", data
    assert len(captured["prompt"].encode("utf-8")) < 600_000      # 통째로 보내면 600KB를 넘는다
    assert json.dumps(RELEVANT)[1:-1] in captured["prompt"]           # 질문과 맞는 근거가 담겼다
    assert "claim:big-9999" in json.dumps(data, ensure_ascii=False)


@pytest.mark.skipif(os.name == "nt", reason="셸 스크립트로 claude 를 흉내 낸다")
def test_cli_engine_sends_a_multi_megabyte_prompt_without_oserror(tmp_path, monkeypatch):
    # 명령행 인자로 보내면 약 1MB(맥)에서 E2BIG 로 죽는다. 표준입력이면 크기와 무관하다.
    fake_claude = tmp_path / "claude"
    fake_claude.write_text("#!/bin/sh\nwc -c | tr -d ' '\n", encoding="utf-8")
    fake_claude.chmod(fake_claude.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    prompt = "가" * 1_200_000                                   # UTF-8 로 3.6MB

    out = asyncio.run(call_llm(prompt, config={"engine": "cli"}))

    assert out == str(len(prompt.encode("utf-8")))


def test_external_article_asked_about_is_not_crowded_out_by_a_large_trusted_document(tmp_path):
    """깨지면: 큰 PDF 와 같이 고른 상태에서 가져온 기사를 요약해 달라고 하면 기사 근거가 통째로 빠져
    "영국 계획에 관한 근거가 없다"는 엉뚱한 답이 나온다(2026-10-06 실측)."""
    project_root, claims = _big_project(tmp_path)
    article = [
        _claim(project_root, f"web-{i + 1}", f"영국 AI 기회 실행계획 핵심 제안 {i} 번째 항목", "raw/clippings/web.md", "untrusted")
        for i in range(5)
    ]
    records = _records(claims + article)

    selected = claim_ledger.select_claims_for_question(
        records, "영국 AI 기회 실행계획 핵심 제안을 요약해 줘", project_root=project_root
    )

    assert {f"claim:web-{i + 1}" for i in range(5)} <= {r.claim_id for r in selected}
