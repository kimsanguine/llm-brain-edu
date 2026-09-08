"""curate.py meta-memory 점수(memory_score) 테스트 — Phase 2 / US-006 (SPEC §C4).

WHY (이 테스트들이 인코딩하는 *의도*):
  1. **재사용 우선**: 점수는 express_reuse(35)·episode_ref(25)가 access_count(10)보다
     무겁다. 가중치 숫자가 바뀌어도 "재사용된 페이지가 단지 많이 조회된 페이지보다
     높게 평가된다"는 방향성은 깨지면 안 된다.
  2. **결정성**: 동일 입력 → 동일 출력(now 주입). curate 루프가 비결정적이면 distill
     순서·rescue 판정이 흔들린다.
  3. **rescue(보존)**: inbound==0·age>ttl 인 archive 후보라도 재사용 신호가 높으면
     아카이브에서 *제외*되어 살아남아야 한다 — "재사용되나 orphan"인 페이지의 영구
     소실 방지(SPEC §C4 plug-in ②). do_purge 까지 통과해 *실제로* 안 옮겨져야 한다.
  4. **이중계산 방지**: episode_ref 는 task_type=express_* 에피소드를 제외한다(같은
     express 런이 express_reuse 와 episode_ref 를 동시에 올리는 것 차단, Codex C3).
  5. **config 견고성**: config.yaml 부재 → 기본값. 부분/타입오류/0·음수 CAP →
     해당 항만 기본값 + stderr warn, 크래시·flaky 금지.

모두 tmp_path 기반 self-contained — 사용자 wiki/·express/·episodes/ 데이터에 의존하지 않는다.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import curate  # noqa: E402


# ── 공용 fixture helpers ────────────────────────────────────────────────

def _graph_index(*nodes: dict) -> dict:
    """compute_memory_score 가 받는 사전 인덱스({slug: node}) 형태.

    node: {"id": slug, "kind": "page", "inbound": int, "betweenness": float?}
    """
    return {n["id"]: n for n in nodes}


def _fm(sources: list[str] | None = None, created: str | None = None) -> dict:
    fm: dict = {}
    if sources is not None:
        fm["sources"] = sources
    if created is not None:
        fm["created"] = created
    return fm


def _patch_module_paths(monkeypatch, tmp_path: Path, wiki: Path) -> None:
    monkeypatch.setattr(curate, "WIKI_ROOT", tmp_path)
    monkeypatch.setattr(curate, "WIKI_DIR", wiki)
    monkeypatch.setattr(curate, "SCHEMA_DIR", tmp_path / "schema")
    monkeypatch.setattr(curate, "DISTILL_QUEUE_FILE", wiki / "distill_queue.md")
    monkeypatch.setattr(curate, "WIKI_STATS_FILE", tmp_path / "wiki_stats.json")
    monkeypatch.setattr(curate, "REPORT_FILE", wiki / "curate_report.md")
    monkeypatch.setattr(curate, "LOG_FILE", tmp_path / "log.md")


def _age_page(page: Path, days: int) -> None:
    """page 의 mtime 을 days 일 과거로 설정 (lifecycle age 계산용)."""
    past = time.time() - days * 86400
    os.utime(page, (past, past))


# ── 1. 결정성 ───────────────────────────────────────────────────────────

def test_compute_memory_score_deterministic():
    """동일 입력 → 동일 출력 (3회 호출 모두 같은 float)."""
    entry = {
        "slug": "alpha",
        "access_count": 7,
        "age_days": 12,
        "express_reuse": 3,
        "episode_ref": 4,
    }
    graph = _graph_index({"id": "alpha", "kind": "page", "inbound": 5, "betweenness": 0.1})
    fm = _fm(sources=["raw/a.md", "raw/b.md"])

    s1 = curate.compute_memory_score(entry, graph, fm)
    s2 = curate.compute_memory_score(entry, graph, fm)
    s3 = curate.compute_memory_score(entry, graph, fm)
    assert s1 == s2 == s3
    assert isinstance(s1, float)
    assert 0.0 <= s1 <= 100.0


# ── 2. 재사용 우선 가중 ──────────────────────────────────────────────────

def test_reuse_outweighs_access():
    """재사용 우선(WHY): express_reuse 만 만점인 페이지 > access_count 만 만점인 페이지.

    가중치 수치(35 vs 10)가 바뀌어도 이 부등식(재사용 > 단순 조회)은 유지돼야 한다.
    """
    w = curate.MEMORY_SCORE_WEIGHTS_DEFAULT
    c = curate.MEMORY_SCORE_CAPS_DEFAULT
    cw = curate.MEMORY_SCORE_CENTRALITY_WEIGHTS_DEFAULT
    graph: dict = {}

    reuse_entry = {
        "slug": "r", "access_count": 0, "age_days": 999,
        "express_reuse": int(c["express_reuse"]), "episode_ref": 0,
    }
    access_entry = {
        "slug": "a", "access_count": int(c["access_count"]), "age_days": 999,
        "express_reuse": 0, "episode_ref": 0,
    }
    s_reuse = curate.compute_memory_score(reuse_entry, graph, _fm(),
                                          weights=w, caps=c, centrality_weights=cw)
    s_access = curate.compute_memory_score(access_entry, graph, _fm(),
                                           weights=w, caps=c, centrality_weights=cw)
    assert s_reuse > s_access, "재사용(express_reuse)이 단순 조회(access)보다 높게 평가돼야 함"


def test_episode_ref_outweighs_access():
    """episode_ref(25) 만점 > access_count(10) 만점 — 운영 재참조가 단순 조회보다 무겁다."""
    c = curate.MEMORY_SCORE_CAPS_DEFAULT
    graph: dict = {}
    ep_entry = {"slug": "e", "access_count": 0, "age_days": 999,
                "express_reuse": 0, "episode_ref": int(c["episode_ref"])}
    ac_entry = {"slug": "a", "access_count": int(c["access_count"]), "age_days": 999,
                "express_reuse": 0, "episode_ref": 0}
    assert curate.compute_memory_score(ep_entry, graph, _fm()) > \
        curate.compute_memory_score(ac_entry, graph, _fm())


# ── 3. 최근성 감쇠 ───────────────────────────────────────────────────────

def test_recency_decay_direction():
    """신선한 페이지(age<30)가 오래된 페이지(age>365)보다 recency 기여만큼 높다."""
    graph: dict = {}
    fresh = {"slug": "f", "access_count": 0, "age_days": 5,
             "express_reuse": 0, "episode_ref": 0}
    old = {"slug": "o", "access_count": 0, "age_days": 400,
           "express_reuse": 0, "episode_ref": 0}
    assert curate.compute_memory_score(fresh, graph, _fm()) > \
        curate.compute_memory_score(old, graph, _fm())


# ── 4. config 견고성 ─────────────────────────────────────────────────────

def test_config_absent_uses_defaults(monkeypatch, tmp_path):
    """config.yaml 부재 → 기본 상수 그대로 (크래시 없음)."""
    schema = tmp_path / "schema"
    schema.mkdir()
    monkeypatch.setattr(curate, "SCHEMA_DIR", schema)

    weights, caps, cw = curate._load_memory_score_config()
    assert weights == curate.MEMORY_SCORE_WEIGHTS_DEFAULT
    assert caps == curate.MEMORY_SCORE_CAPS_DEFAULT
    assert cw == curate.MEMORY_SCORE_CENTRALITY_WEIGHTS_DEFAULT


def test_config_partial_bad_types_fallback_with_warning(monkeypatch, tmp_path, capsys):
    """부분/타입오류/0·음수 CAP → 해당 항만 기본값 + stderr warn (크래시·flaky 금지).

    - weights.express_reuse: 정상 override(50) → 반영
    - weights.episode_ref: 문자열(타입오류) → 기본값 유지 + warn
    - caps.access_count: 0 (금지) → 기본값 유지 + warn
    - caps.centrality: -3 (음수) → 기본값 유지 + warn
    - 누락 키(나머지) → 기본값
    """
    schema = tmp_path / "schema"
    schema.mkdir()
    (schema / "config.yaml").write_text(
        yaml.safe_dump({
            "llm": {"engine": "cli"},  # 기존 무관 섹션 — 무시돼야 함
            "memory_score": {
                "weights": {"express_reuse": 50, "episode_ref": "오타"},
                "caps": {"access_count": 0, "centrality": -3},
            },
        }, allow_unicode=True),
        encoding="utf-8",
    )
    monkeypatch.setattr(curate, "SCHEMA_DIR", schema)

    weights, caps, cw = curate._load_memory_score_config()

    assert weights["express_reuse"] == 50.0  # 정상 override 반영
    assert weights["episode_ref"] == curate.MEMORY_SCORE_WEIGHTS_DEFAULT["episode_ref"]  # 타입오류 → 기본
    assert caps["access_count"] == curate.MEMORY_SCORE_CAPS_DEFAULT["access_count"]  # 0 → 기본
    assert caps["centrality"] == curate.MEMORY_SCORE_CAPS_DEFAULT["centrality"]  # 음수 → 기본

    err = capsys.readouterr().err
    assert "episode_ref" in err and "access_count" in err and "centrality" in err, \
        "잘못된 config 항목에 대한 stderr 경고가 누락됨 (조용한 fallback 금지)"


def test_norm_guards_nonpositive_cap():
    """0/음수 CAP 가 어쩌다 들어와도 ZeroDivisionError 없이 안전(0.0)."""
    assert curate._norm(5, 0) == 0.0
    assert curate._norm(5, -1) == 0.0
    assert curate._norm(5, 10) == 0.5
    assert curate._norm(50, 10) == 1.0  # min cap


# ── 5. express_reuse / episode_ref 인덱스 ────────────────────────────────

def test_express_reuse_counts_distinct_outputs(tmp_path):
    """express_reuse = 이 slug 를 인용한 express *산출물 수*. source 인용 + [[wikilink]] 모두.

    blog1: sources 에 alpha → +1
    blog2: 본문 [[alpha]] → +1
    report1: alpha 미인용 → 0
    → alpha == 2
    """
    ex = tmp_path / "express"
    (ex / "blog").mkdir(parents=True)
    (ex / "report").mkdir(parents=True)
    (ex / "blog" / "p1.md").write_text(
        "---\ntype: blog\nsources:\n  - wiki/concepts/alpha.md\n  - wiki/tools/beta.md\n---\n\n본문.\n",
        encoding="utf-8",
    )
    (ex / "blog" / "p2.md").write_text(
        "---\ntype: blog\nsources:\n  - wiki/tools/beta.md\n---\n\n본문 [[alpha]] 인용.\n",
        encoding="utf-8",
    )
    (ex / "report" / "r1.md").write_text(
        "---\ntype: report\nsources:\n  - wiki/tools/beta.md\n---\n\ngamma 만.\n",
        encoding="utf-8",
    )

    idx = curate.build_express_reuse_index(ex)
    assert idx.get("alpha") == 2
    assert idx.get("beta") == 3
    assert "gamma" not in idx


def test_episode_ref_excludes_express_episodes(tmp_path):
    """episode_ref 는 task_type=express_* 에피소드를 제외 (이중계산 방지)."""
    eps = tmp_path / "episodes"
    eps.mkdir()
    (eps / "2026-06.jsonl").write_text(
        # express_blog: 같은 alpha 를 읽었지만 제외돼야 함
        '{"task_type": "express_blog", "read_pages": ["wiki/concepts/alpha.md"]}\n'
        # ai_answer: alpha 1회 집계
        '{"task_type": "ai_answer", "read_pages": ["wiki/concepts/alpha.md"]}\n'
        # ingest: alpha + beta
        '{"task_type": "ingest", "read_pages": ["wiki/concepts/alpha.md", "wiki/tools/beta.md"]}\n',
        encoding="utf-8",
    )
    idx = curate.build_episode_ref_index(eps)
    assert idx.get("alpha") == 2, "express_* 제외 후 비-express 에피소드 2개만 집계"
    assert idx.get("beta") == 1


# ── 6. rescue (plug-in ②) — run_lifecycle 판정 ──────────────────────────

def _setup_lifecycle_wiki(tmp_path: Path, monkeypatch) -> Path:
    """insights 도메인(ttl 작게)에 reused-orphan + dead-orphan 두 archive 후보 구성.

    reused-orphan: express 산출물이 인용(재사용 높음) → rescue 대상.
    dead-orphan:   아무 신호 없음 → archive.
    """
    wiki = tmp_path / "wiki"
    (wiki / "insights").mkdir(parents=True)
    reused = wiki / "insights" / "reused-orphan.md"
    dead = wiki / "insights" / "dead-orphan.md"
    reused.write_text("---\ntitle: Reused\ntype: insight\ncreated: 2026-01-01\n---\n\n본문.\n", encoding="utf-8")
    dead.write_text("---\ntitle: Dead\ntype: insight\ncreated: 2026-01-01\n---\n\n본문.\n", encoding="utf-8")
    # 둘 다 오래됨(age 200일 > ttl) + inbound 0 (서로 링크 없음)
    _age_page(reused, 200)
    _age_page(dead, 200)

    # schema/sources.yaml — insights ttl 30일
    schema = tmp_path / "schema"
    schema.mkdir()
    (schema / "sources.yaml").write_text(
        yaml.safe_dump({"lifecycle": {"domains": {"insights": {"ttl_days": 30}}}}),
        encoding="utf-8",
    )

    # express/ — reused-orphan 을 인용하는 산출물 2개
    ex = tmp_path / "express" / "blog"
    ex.mkdir(parents=True)
    (ex / "b1.md").write_text(
        "---\ntype: blog\nsources:\n  - wiki/insights/reused-orphan.md\n---\n\n본문.\n",
        encoding="utf-8",
    )
    (ex / "b2.md").write_text(
        "---\ntype: blog\n---\n\n본문 [[reused-orphan]] 인용.\n",
        encoding="utf-8",
    )

    _patch_module_paths(monkeypatch, tmp_path, wiki)
    return wiki


def test_rescue_reused_orphan_excluded_from_archive(monkeypatch, tmp_path):
    """RED→GREEN: 재사용 높은 orphan 은 archive 후보에서 제외(rescued)되고,
    신호 없는 orphan 은 archive 된다."""
    _setup_lifecycle_wiki(tmp_path, monkeypatch)

    result = curate.run_lifecycle(curate.find_all_wiki_pages())

    archived = {Path(a["path"]).stem for a in result.get("archive", [])}
    rescued = {Path(r["path"]).stem for r in result.get("rescued", [])}

    assert "reused-orphan" in rescued, "재사용된 orphan 이 rescue 되지 않음 (영구 소실 위험)"
    assert "reused-orphan" not in archived, "재사용된 orphan 이 archive 후보에 남음"
    assert "dead-orphan" in archived, "신호 없는 orphan 은 archive 돼야 함 (rescue 과잉 금지)"
    assert "dead-orphan" not in rescued


def test_rescue_survives_purge_end_to_end(monkeypatch, tmp_path):
    """RED→GREEN (Rule 8, 실제 동작): rescue 된 페이지는 do_purge 까지 통과해도
    실제 파일이 archive/ 로 옮겨지지 않아야 한다. dead-orphan 은 옮겨진다."""
    wiki = _setup_lifecycle_wiki(tmp_path, monkeypatch)
    reused = wiki / "insights" / "reused-orphan.md"
    dead = wiki / "insights" / "dead-orphan.md"

    pages = curate.find_all_wiki_pages()
    audit = curate.run_audit(pages)          # orphan 섹션이 채워짐(둘 다 orphan)
    lifecycle = curate.run_lifecycle(pages)
    curate.write_report(audit, [], lifecycle)
    curate.do_purge()

    assert reused.exists(), "rescue 된 재사용 orphan 이 purge 로 archive/ 이동됨 (보존 실패)"
    moved = wiki / "archive" / "dead-orphan.md"
    assert not dead.exists() and moved.exists(), "신호 없는 orphan 은 archive/ 로 이동돼야 함"


# ── 7. plug-in ① — distill 큐 점수 정렬 + 임계 게이트 유지 ────────────────

def test_distill_tier_sorted_by_memory_score_and_gates_kept(monkeypatch, tmp_path):
    """plug-in ①: urgent tier 안에서 memory_score 내림차순 정렬.
    임계 게이트(access>=10)는 유지(backward-compat) — 둘 다 urgent 에 남는다."""
    wiki = tmp_path / "wiki"
    (wiki / "concepts").mkdir(parents=True)
    # 둘 다 access>=10 → urgent tier. reused 는 express 인용으로 점수 높음.
    reused = wiki / "concepts" / "reused-hot.md"
    plain = wiki / "concepts" / "plain-hot.md"
    reused.write_text("---\ntitle: R\ntype: concept\ncreated: 2026-06-01\naccess_count: 12\n---\n\n본문.\n", encoding="utf-8")
    plain.write_text("---\ntitle: P\ntype: concept\ncreated: 2026-06-01\naccess_count: 12\n---\n\n본문.\n", encoding="utf-8")

    ex = tmp_path / "express" / "blog"
    ex.mkdir(parents=True)
    (ex / "b1.md").write_text(
        "---\ntype: blog\nsources:\n  - wiki/concepts/reused-hot.md\n---\n\n본문.\n",
        encoding="utf-8",
    )

    (tmp_path / "schema").mkdir()
    _patch_module_paths(monkeypatch, tmp_path, wiki)

    candidates = curate.run_distill(curate.find_all_wiki_pages())
    queue = (wiki / "distill_queue.md").read_text(encoding="utf-8")

    # 임계 게이트 유지: 둘 다 urgent 후보로 큐에 존재.
    assert "reused-hot" in queue and "plain-hot" in queue
    assert any("reused-hot" in c for c in candidates)
    assert any("plain-hot" in c for c in candidates)
    # 점수 기입 확인
    assert "score=" in queue, "distill_queue 에 memory_score 가 기입돼야 함"
    # 정렬: reused-hot 라인이 plain-hot 라인보다 먼저 등장.
    assert queue.index("reused-hot") < queue.index("plain-hot"), \
        "memory_score 높은 페이지가 tier 내 먼저 정렬돼야 함"


def test_distill_config_absent_no_crash(monkeypatch, tmp_path):
    """config.yaml·express/·episodes/ 모두 부재라도 run_distill 이 옛 동작대로
    임계 분류를 수행하고 크래시하지 않는다 (backward-compat)."""
    wiki = tmp_path / "wiki"
    (wiki / "concepts").mkdir(parents=True)
    hot = wiki / "concepts" / "hot.md"
    hot.write_text("---\ntitle: H\ntype: concept\ncreated: 2026-06-01\naccess_count: 15\n---\n\n본문.\n", encoding="utf-8")
    (tmp_path / "schema").mkdir()
    _patch_module_paths(monkeypatch, tmp_path, wiki)

    candidates = curate.run_distill(curate.find_all_wiki_pages())  # 크래시 금지
    assert any("hot" in c for c in candidates)  # 임계 게이트(access>=10) 그대로 작동
