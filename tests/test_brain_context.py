"""brain_context.py — 작업기억 팩 생성기 계약 테스트 (Phase 2, PRD US-005).

WHY (이 테스트가 인코딩하는 의도):
  1. 6 섹션을 **항상** 결정적 순서로 만든다 — 빈 wiki 여도 모든 섹션이 존재(graceful).
  2. 관련 semantic 페이지는 express.collect_related_pages 재사용 + **graph degree
     동점 정렬**(키워드 점수 동률이면 degree desc, 그다음 slug asc) — US-005 요구.
  3. 최근 episode / 후보 procedure 는 각각 episode·procedures 로더로 채운다.
  4. 같은 입력 → 동일 출력 바이트(결정성). --json 은 동일 구조.

wiki_root/episodes_dir/procedures_dir 를 tmp_path 로 주입해 사용자 데이터를 건드리지 않는다.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import brain_context  # noqa: E402
import episode  # noqa: E402


# ── 픽스처 헬퍼 ──────────────────────────────────────────────────────────────

EM = "—"  # em dash — express index 파서가 기대하는 구분자


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _page(title: str, sources: list[str]) -> str:
    src = "\n".join(f"  - {s}" for s in sources)
    return f"---\ntitle: {title}\nmemory_type: semantic\nsources:\n{src}\n---\n\n본문\n"


def _build_wiki(root: Path) -> None:
    """alpha·beta 두 페이지(동일 키워드 점수) + degree 차이가 있는 graph.json."""
    # index.md — 두 줄 다 "agent orchestration" 키워드를 동일하게 포함(점수 동률)
    _write(
        root / "index.md",
        f"- [[alpha]] {EM} agent orchestration pattern\n"
        f"- [[beta]] {EM} agent orchestration pattern\n",
    )
    _write(root / "wiki" / "concepts" / "alpha.md", _page("Alpha 페이지", ["raw/a.md"]))
    _write(root / "wiki" / "concepts" / "beta.md", _page("Beta 페이지", ["raw/b.md"]))
    # degree(alpha)=1, degree(beta)=5 → 동점 정렬에서 beta 가 앞
    graph = {
        "nodes": [
            {"id": "alpha", "kind": "page", "inbound": 1, "outbound": 0},
            {"id": "beta", "kind": "page", "inbound": 3, "outbound": 2},
        ],
        "links": [],
    }
    _write(root / "wiki" / "graph.json", json.dumps(graph))


def _pack(root: Path, **over):
    kwargs = dict(
        task="에이전트 작업기억 설계",
        topic="agent orchestration",
        type_="custom",
        max_pages=5,
        wiki_root=root,
        episodes_dir=root / "episodes",
        procedures_dir=root / "procedures",
    )
    kwargs.update(over)
    return brain_context.build_pack(**kwargs)


# ── 1. 빈 wiki 여도 6 섹션 graceful ───────────────────────────────────────────

def test_empty_wiki_produces_all_sections(tmp_path):
    pack = _pack(tmp_path)
    for key in (
        "goal",
        "related_pages",
        "recent_episodes",
        "candidate_procedures",
        "constraints",
        "source_paths",
    ):
        assert key in pack, f"섹션 누락: {key}"
    assert pack["goal"] == "에이전트 작업기억 설계"
    assert pack["related_pages"] == []
    assert pack["recent_episodes"] == []
    assert pack["candidate_procedures"] == []
    assert pack["source_paths"] == []
    # 제약은 빈 wiki 여도 정적 주입 → 항상 존재
    assert pack["constraints"], "제약(가드레일)은 항상 존재해야 한다"
    # 렌더도 깨지지 않고 6 섹션 헤더를 낸다
    md = brain_context.render_markdown(pack)
    for n in range(1, 7):
        assert f"## {n}." in md


# ── 2. 매칭 wiki 페이지가 섹션 2 + 출처가 섹션 6 ──────────────────────────────

def test_matching_pages_and_sources(tmp_path):
    _build_wiki(tmp_path)
    pack = _pack(tmp_path)
    slugs = [p["slug"] for p in pack["related_pages"]]
    assert "alpha" in slugs and "beta" in slugs
    # 출처(raw/ provenance)가 섹션 6 에 집계
    assert pack["source_paths"] == ["raw/a.md", "raw/b.md"]


# ── 3. 최근 episode 가 섹션 3 (task_type 파생 필터) ───────────────────────────

def test_recent_episodes_appear(tmp_path):
    _build_wiki(tmp_path)
    ep_dir = tmp_path / "episodes"
    rec = dict(
        timestamp="2026-06-27T07:30:00+09:00",
        task_type="ai_answer",
        user_goal="agent orchestration 질문",
        inputs={"topic": "agent orchestration"},
        read_pages=["wiki/concepts/alpha.md"],
        procedures_used=[],
        outputs={},
        status="ok",
        notes="",
    )
    episode.append(rec, episodes_dir=ep_dir)
    # --type query → task_type=ai_answer 로 파생 필터
    pack = _pack(tmp_path, type_="query")
    assert len(pack["recent_episodes"]) == 1
    assert pack["recent_episodes"][0]["task_type"] == "ai_answer"
    assert "agent orchestration" in pack["recent_episodes"][0]["user_goal"]


def test_episode_type_filter_excludes_other_task_types(tmp_path):
    """--type query 는 ai_answer 만 통과시키고 ingest 등은 거른다(파생 필터 검증)."""
    _build_wiki(tmp_path)
    ep_dir = tmp_path / "episodes"
    for tt in ("ai_answer", "ingest"):
        episode.append(
            dict(
                timestamp="2026-06-27T07:30:00+09:00",
                task_type=tt,
                user_goal="agent orchestration 작업",
                inputs={},
                read_pages=[],
                procedures_used=[],
                outputs={},
                status="ok",
                notes="",
            ),
            episodes_dir=ep_dir,
        )
    pack = _pack(tmp_path, type_="query")
    types = {e["task_type"] for e in pack["recent_episodes"]}
    assert types == {"ai_answer"}


# ── 4. 후보 procedure 가 섹션 4 (topic 키워드 필터) ───────────────────────────

def test_candidate_procedures_filtered(tmp_path):
    _build_wiki(tmp_path)
    proc_dir = tmp_path / "procedures"
    _write(
        proc_dir / "agent-setup.md",
        "---\ntitle: agent 셋업 절차\nmemory_type: procedural\n---\n\n절차 본문\n",
    )
    _write(
        proc_dir / "billing.md",
        "---\ntitle: 결제 절차\nmemory_type: procedural\n---\n\n무관 본문\n",
    )
    pack = _pack(tmp_path)
    cand_slugs = [c["slug"] for c in pack["candidate_procedures"]]
    assert "agent-setup" in cand_slugs
    assert "billing" not in cand_slugs  # topic 키워드 미매칭 → 제외


# ── 5. 결정적 순서 (동점 degree 정렬 + 동일 바이트) ───────────────────────────

def test_degree_tiebreaker_and_determinism(tmp_path):
    _build_wiki(tmp_path)
    pack = _pack(tmp_path)
    # 동일 키워드 점수 → degree desc 동점 정렬: beta(5) 가 alpha(1) 보다 앞
    order = [p["slug"] for p in pack["related_pages"]]
    assert order == ["beta", "alpha"], f"degree 동점 정렬 실패: {order}"
    # 같은 입력 → 동일 출력 바이트
    md1 = brain_context.render_markdown(_pack(tmp_path))
    md2 = brain_context.render_markdown(_pack(tmp_path))
    assert md1 == md2
    js1 = brain_context.render_json(_pack(tmp_path))
    js2 = brain_context.render_json(_pack(tmp_path))
    assert js1 == js2


# ── 6. --json 은 동일 구조 ────────────────────────────────────────────────────

def test_json_same_structure(tmp_path):
    _build_wiki(tmp_path)
    pack = _pack(tmp_path)
    parsed = json.loads(brain_context.render_json(pack))
    assert parsed == pack  # JSON 직렬화가 dict 구조를 무손실 반영


# ── 7. CLI 스모크 (argparse 배선 + exit 0) ────────────────────────────────────

def test_cli_smoke():
    script = _REPO_ROOT / "scripts" / "brain_context.py"
    out = subprocess.run(
        [sys.executable, str(script), "--task", "테스트 목표", "--topic", "agent"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 0, out.stderr
    assert "## 1." in out.stdout
    assert "## 5." in out.stdout  # 제약 섹션은 데이터 없어도 항상 출력
