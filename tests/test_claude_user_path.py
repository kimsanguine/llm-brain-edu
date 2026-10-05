"""test_claude_user_path — Claude Code 사용자 경로의 계약(2026-10-05 e2e 회귀).

각 테스트는 "이게 깨지면 Claude 사용자에게 무슨 일이 일어나는가"를 적는다.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

import compile as compile_mod  # noqa: E402
import express  # noqa: E402


# ── compile: cli 엔진은 키 없이 LIVE ──────────────────────────────────────────


def test_cli_engine_is_live_without_any_key(monkeypatch):
    """engine: cli 이고 claude 가 있으면 키 환경변수가 없어도 LIVE 다.

    깨지면: OpenAI 키가 없는 Claude 구독 사용자는 엔진을 바꿔도 영영 RULE 에 머물고,
    가짜 키를 넣어야만 LIVE 가 된다(2026-10-05 e2e 실측).
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(compile_mod.shutil, "which", lambda name: "/usr/local/bin/claude")
    live, why = compile_mod._live_check({"engine": "cli", "api_key_env": "OPENAI_API_KEY"})
    assert live and "claude CLI 감지됨" in why
    assert "OPENAI_API_KEY" not in why  # 키를 감지했다는 거짓 안내를 찍지 않는다


def test_cli_engine_without_claude_falls_back_to_rule(monkeypatch):
    """claude 명령이 없으면 RULE 이고, 이유를 말한다(조용한 실패 금지)."""
    monkeypatch.setattr(compile_mod.shutil, "which", lambda name: None)
    live, why = compile_mod._live_check({"engine": "cli"})
    assert not live and "claude CLI 없음" in why


def test_openai_engine_still_needs_its_key(monkeypatch):
    """수업 기본(openai)은 지금처럼 키가 있어야만 LIVE 다(키 없는 학생의 RULE 경로 유지)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(compile_mod.shutil, "which", lambda name: "/usr/local/bin/claude")
    live, _ = compile_mod._live_check({"engine": "openai", "api_key_env": "OPENAI_API_KEY"})
    assert not live


# ── express: 빈 틀은 raw/blog 로 가지 않는다 ─────────────────────────────────


@pytest.fixture
def blog_env(tmp_path, monkeypatch):
    root = tmp_path / "brain"
    (root / "wiki" / "concepts").mkdir(parents=True)
    blog_dir = root / "express" / "blog"
    monkeypatch.setattr(express, "WIKI_ROOT", root)
    monkeypatch.setattr(express, "WIKI_DIR", root / "wiki")
    monkeypatch.setattr(express, "EXPRESS_DIR", root / "express")
    monkeypatch.setattr(express, "RAW_BLOG_DIR", root / "raw" / "blog")
    monkeypatch.setattr(express, "INDEX_FILE", root / "index.md")
    monkeypatch.setattr(express, "TYPE_DIR", {"blog": blog_dir, "lecture": root / "express" / "lecture",
                                              "summary": root / "express" / "summary",
                                              "report": root / "express" / "report"})
    monkeypatch.setattr(express, "collect_related_pages", lambda topic, max_pages=5: [])
    monkeypatch.setattr(express, "_record_express_episode", lambda *a, **k: None)
    return root


def test_blog_skeleton_is_not_copied_into_raw(blog_env):
    """blog 초안 틀을 만들 때 raw/blog/ 에는 아무것도 들어가지 않는다.

    깨지면: 다음 compile 이 "(블로그 제목 — Claude가 작성)" 이라는 빈 페이지를 위키에
    만들고, raw 는 읽기 전용이라 그 자리표시자를 고칠 길도 없다.
    """
    express.cmd_blog("RAG 평가")
    assert list((blog_env / "express" / "blog").glob("*.md"))
    assert not (blog_env / "raw" / "blog").exists() or not list((blog_env / "raw" / "blog").iterdir())


def test_publish_refuses_unwritten_draft(blog_env, capsys):
    """본문을 아직 안 쓴 틀은 publish 가 거부한다."""
    express.cmd_blog("RAG 평가")
    draft = next((blog_env / "express" / "blog").glob("*.md"))
    assert express.cmd_publish(str(draft)) == 1
    assert "본문을 쓰지 않은" in capsys.readouterr().out
    assert not (blog_env / "raw" / "blog" / draft.name).exists()


def test_publish_copies_written_draft(blog_env):
    """본문을 쓴 초안은 raw/blog/ 로 들어가 다음 compile 의 재료가 된다(피드백 루프 유지)."""
    express.cmd_blog("RAG 평가")
    draft = next((blog_env / "express" / "blog").glob("*.md"))
    draft.write_text("---\ntype: blog\n---\n\n# RAG 평가 정리\n\n본문입니다.\n", encoding="utf-8")
    assert express.cmd_publish(str(draft)) == 0
    assert (blog_env / "raw" / "blog" / draft.name).read_text(encoding="utf-8").startswith("---")


def test_publish_only_accepts_blog_drafts(blog_env, tmp_path):
    """express/blog/ 밖의 파일을 raw 로 밀어 넣는 통로가 되지 않는다."""
    other = tmp_path / "secret.md"
    other.write_text("# 다른 파일\n본문", encoding="utf-8")
    assert express.cmd_publish(str(other)) == 1


# ── 문서 계약 ───────────────────────────────────────────────────────────────


def test_claude_md_imports_agents_md():
    """CLAUDE.md 가 AGENTS.md 를 import 한다.

    깨지면: Claude Code 는 CLAUDE.md 만 자동으로 읽으므로 AGENTS.md 의 규칙(raw 수정은
    사용자 요청 시 허용, 키·개인정보 출력 금지)이 Claude 에 닿지 않는다. e2e 세 세션 모두
    AGENTS.md 를 열지 않았고, 주민번호 메모를 "지울 수 없다"고 잘못 안내했다.
    """
    lines = (ROOT / "CLAUDE.md").read_text(encoding="utf-8").splitlines()
    assert "@AGENTS.md" in [ln.strip() for ln in lines]


def test_readme_tells_claude_users_how_to_install_the_plugin():
    """README 에 플러그인 설치 명령이 있고, marketplace 이름이 manifest 와 맞는다.

    깨지면: 슬래시 명령을 쓰려는 Claude 사용자가 설치 단계에서 막힌다. 이름이 상류
    marketplace(llm-brain)와 같으면 이미 상류를 쓰는 사람은 충돌한다.
    """
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    plugin = market["plugins"][0]["name"]
    assert market["name"] != "llm-brain"
    assert f"claude plugin install {plugin}@{market['name']}" in readme
    assert "claude plugin marketplace add kimsanguine/llm-brain-edu" in readme


def test_compile_main_goes_live_with_cli_engine_and_no_key(tmp_path, monkeypatch, capsys):
    """compile.py 자체가 cli 엔진 + 키 없음에서 LIVE 경로(모델 호출)를 탄다.

    _live_check 단위 테스트와 별개로, 실제 진입점이 그 판정을 쓰는지 본다.
    """
    import types

    import ingest as ingest_mod

    for name, value in {"ROOT": tmp_path, "WIKI_DIR": tmp_path / "wiki",
                        "INDEX_FILE": tmp_path / "index.md"}.items():
        monkeypatch.setattr(compile_mod, name, value)
    raw = tmp_path / "raw" / "notes" / "2026-10-05-0900-note.md"
    raw.parent.mkdir(parents=True)
    raw.write_text("오늘 배운 것: 리랭커", encoding="utf-8")

    called = {}

    async def fake_llm(raw_file, text):
        called["yes"] = True
        return tmp_path / "wiki" / "concepts" / "reranker.md", (
            "---\ntitle: \"리랭커\"\ntype: concept\nsources:\n  - raw/notes/2026-10-05-0900-note.md\n---\n\n# 리랭커\n")

    monkeypatch.setattr(sys, "argv", ["compile.py"])
    monkeypatch.setattr(ingest_mod, "load_state", lambda: {})
    monkeypatch.setattr(ingest_mod, "save_state", lambda st: None)
    monkeypatch.setattr(ingest_mod, "find_unprocessed", lambda priority_only=False: [raw])
    monkeypatch.setattr(compile_mod, "CATEGORIES", ["concepts"])
    monkeypatch.setitem(sys.modules, "export_graph", types.SimpleNamespace(main=lambda: 0))
    monkeypatch.setattr(compile_mod.llm_client, "load_llm_config",
                        lambda *a, **k: {"engine": "cli", "api_key_env": "OPENAI_API_KEY"})
    monkeypatch.setattr(compile_mod.shutil, "which", lambda name: "/usr/local/bin/claude")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(compile_mod, "_page_by_llm", fake_llm)

    assert compile_mod.main() == 0
    out = capsys.readouterr().out
    assert called.get("yes"), "cli 엔진인데 모델을 부르지 않고 RULE 로 돌았다"
    assert "경로: LIVE" in out and "[LIVE]" in out
