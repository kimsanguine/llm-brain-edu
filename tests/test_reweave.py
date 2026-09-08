"""test_reweave.py — v0.3.0 WS-3: curate --reweave 통합 배선 계약.

WHY (이 테스트가 인코딩하는 의도):
  1. reweave 는 신규 엔진이 아니라 기존 자산 오케스트레이터다 — weak 판정·fix 는
     memory_health 엔진, observing 만료는 gates.evaluate_observing_expiry 판정.
  2. observing/·rejected/ 3점 방어 중 코드 측 2점 — find_all_wiki_pages 격리 +
     lifecycle TTL decay 면제. (설정 측 1점은 test_okf_security 에서 단언.)
  3. 만료 observing 페이지는 wiki/rejected/ 로 이동 + gate_status: rejected 갱신
     (frontmatter_utils 경유, body 무손상). 미만료·재등장 페이지는 무변경.
  4. --dry-run 은 어떤 파일도 변경·생성하지 않는다. --fix 는 idempotent.
  5. 판단 필요분은 reweave_queue.md 체크박스 큐로 — 자동 보강 금지(가짜 보강 금지).
  6. episode: task_type=reweave 기록은 fail-soft, build_episode_ref_index 는
     reweave 를 집계에서 제외한다(자기 점수 되먹임 차단).
  7. --weekly-summary: 28일 4회+ 반복 weak = 통합/삭제 후보. 이력 부족 시 현재
     스캔만으로 후보 + 정직 표기(크래시 금지).

tmp_path self-contained (claude CLI 불요).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import curate  # noqa: E402
from lib import frontmatter_utils, memory_score  # noqa: E402

NOW = datetime(2026, 7, 4, 9, 0)

# 40자 이상 첫 문단 — --fix summary 추출 원본 (test_memory_health_fix 와 동일 컨벤션).
INTRO_50 = "이 페이지는 reweave 자동 보강 검증용 첫 문단으로 사십 자를 확실히 넘도록 길게 작성한 문장이다."
assert len(INTRO_50) >= 40


def _write(root: Path, rel: str, content: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def _healthy_body(intro: str = INTRO_50) -> str:
    """본문 ≥800자 · H2 3개 — weak 기준에 안 걸리는 본문."""
    filler = ("검증 가능한 근거와 함께 정리한 내용 " * 20).strip()
    sections = "\n\n".join(f"## 섹션 {i}\n\n{filler}" for i in range(1, 4))
    return f"\n\n# healthy\n\n{intro}\n\n{sections}\n"


def _fm_block(**fields) -> str:
    lines = ["---"]
    for k, v in fields.items():
        if isinstance(v, list):
            lines.append(f"{k}: [" + ", ".join(str(x) for x in v) + "]")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def _healthy_page(**fm_over) -> str:
    fm = dict(title="page", type="concept", created="2026-06-01", updated="2026-06-01",
              summary="요약 " * 15, sources=["raw/a.md", "raw/b.md"], source_count=2)
    fm.update(fm_over)
    return _fm_block(**fm) + _healthy_body()


def _weak_page(**fm_over) -> str:
    """본문 <800자 · H2 0개 · 근거 1건 — 판단 필요분(자동 보강 금지)."""
    fm = dict(title="weak", type="concept", created="2026-06-01", updated="2026-06-01",
              summary="요약 " * 15, sources=["raw/a.md"], source_count=1)
    fm.update(fm_over)
    return _fm_block(**fm) + "\n\n# weak\n\n짧은 본문.\n"


def _observing_page(expires: str, recurrence: int = 1) -> str:
    fm = dict(title="obs", type="concept", created="2026-06-20", updated="2026-06-20",
              gate_status="observing", observation_expires=expires, recurrence=recurrence)
    return _fm_block(**fm) + "\n\n# obs\n\n유예 중 후보 본문.\n"


def _patch_paths(monkeypatch, tmp_path: Path) -> Path:
    """curate 모듈 전역 경로 + episode 원장을 tmp 로 격리 (test_curate_frontmatter 패턴)."""
    wiki = tmp_path / "wiki"
    wiki.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(curate, "WIKI_ROOT", tmp_path)
    monkeypatch.setattr(curate, "WIKI_DIR", wiki)
    monkeypatch.setattr(curate, "SCHEMA_DIR", tmp_path / "schema")
    monkeypatch.setattr(curate, "DISTILL_QUEUE_FILE", wiki / "distill_queue.md")
    monkeypatch.setattr(curate, "WIKI_STATS_FILE", tmp_path / "wiki_stats.json")
    monkeypatch.setattr(curate, "REPORT_FILE", wiki / "curate_report.md")
    monkeypatch.setattr(curate, "LOG_FILE", tmp_path / "log.md")
    monkeypatch.setattr(curate.episode, "EPISODES_DIR", tmp_path / "episodes")
    return wiki


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


# ── 1. 스캔 격리 (3점 방어 — 코드 측) ─────────────────────────────────

def test_find_all_wiki_pages_excludes_gate_dirs_and_queue(monkeypatch, tmp_path):
    wiki = _patch_paths(monkeypatch, tmp_path)
    _write(wiki, "concepts/normal.md", _healthy_page())
    _write(wiki, "observing/pending.md", _observing_page("2026-07-10"))
    _write(wiki, "rejected/dropped.md", _weak_page(title="dropped"))
    _write(wiki, "reweave_queue.md", "# Reweave Queue\n- [ ] `wiki/concepts/normal.md`\n")

    rels = {p.relative_to(wiki).as_posix() for p in curate.find_all_wiki_pages()}
    assert rels == {"concepts/normal.md"}


def test_lifecycle_exempts_observing_rejected(monkeypatch, tmp_path):
    """observing/·rejected/ 는 TTL decay 대상이 아니다 — 페이지가 직접 주입돼도 면제."""
    wiki = _patch_paths(monkeypatch, tmp_path)
    schema = tmp_path / "schema"
    schema.mkdir()
    (schema / "sources.yaml").write_text(
        "lifecycle:\n  domains:\n    observing: 1\n    rejected: 1\n    insights: 1\n",
        encoding="utf-8",
    )
    old = "2020-01-01"
    obs = _write(wiki, "observing/old-obs.md", _observing_page("2020-01-08"))
    rej = _write(wiki, "rejected/old-rej.md", _weak_page(title="old-rej", created=old))
    # 대조군은 memory_score 0(무신호)이어야 rescue 되지 않고 후보에 남는다.
    ins = _write(wiki, "insights/old-insight.md",
                 _weak_page(title="old-insight", created=old, sources=[], source_count=0))
    # mtime 을 과거로 밀어 age>ttl 조건을 강제한다.
    import os
    past = datetime(2020, 1, 1).timestamp()
    for p in (obs, rej, ins):
        os.utime(p, (past, past))

    result = curate.run_lifecycle([obs, rej, ins])
    listed = {c["path"] for c in result["archive"] + result["delete"]}
    assert not any("observing/" in p or "rejected/" in p for p in listed), listed
    # 대조군: 면제 아닌 도메인(insights)은 정상적으로 후보에 잡힌다.
    assert any("insights/old-insight.md" in p for p in listed)


# ── 2. observing 만료 처리 ────────────────────────────────────────────

def test_expired_observing_moved_to_rejected(monkeypatch, tmp_path):
    wiki = _patch_paths(monkeypatch, tmp_path)
    src = _write(wiki, "observing/expired.md", _observing_page("2026-07-01"))  # NOW 이전

    result = curate.run_reweave(now=NOW)

    assert not src.exists()
    dst = wiki / "rejected" / "expired.md"
    assert dst.exists()
    fm, body = frontmatter_utils.read_fm(dst.read_text(encoding="utf-8"))
    assert fm["gate_status"] == "rejected"
    assert str(fm["observation_expires"]) == "2026-07-01"  # 이력 보존 (yaml 은 date 로 파싱)
    assert "유예 중 후보 본문" in body  # body 무손상
    assert result["expired"] == [{
        "slug": "expired",
        "from": "wiki/observing/expired.md",
        "to": "wiki/rejected/expired.md",
        "reason": "insufficient_recurrence",
    }]


def test_unexpired_and_reappeared_observing_untouched(monkeypatch, tmp_path):
    wiki = _patch_paths(monkeypatch, tmp_path)
    keep1 = _write(wiki, "observing/future.md", _observing_page("2026-07-10"))
    keep2 = _write(wiki, "observing/reappeared.md",
                   _observing_page("2026-07-01", recurrence=2))
    before1, before2 = keep1.read_bytes(), keep2.read_bytes()

    result = curate.run_reweave(now=NOW)

    assert result["expired"] == []
    assert keep1.read_bytes() == before1
    assert keep2.read_bytes() == before2
    assert not (wiki / "rejected").exists()


def test_observing_missing_expires_surfaced_not_crash(monkeypatch, tmp_path):
    """gates fail-loud(ValueError)는 표면화하되 런 전체를 못 깨뜨린다 — 파일 무변경."""
    wiki = _patch_paths(monkeypatch, tmp_path)
    broken = _write(wiki, "observing/broken.md",
                    _fm_block(title="broken", type="concept", created="2026-06-20",
                              updated="2026-06-20", gate_status="observing")
                    + "\n\n본문.\n")
    before = broken.read_bytes()

    result = curate.run_reweave(now=NOW)

    assert broken.read_bytes() == before
    assert any("observing/broken.md" == rel for rel, _ in result["expiry_errors"])


# ── 3. weak 스캔·큐·fix ───────────────────────────────────────────────

def test_weak_page_queued_not_fixed(monkeypatch, tmp_path):
    """판단 필요분(본문·근거 부족)은 fix 하지 않고 큐+alert 만 (가짜 보강 금지)."""
    wiki = _patch_paths(monkeypatch, tmp_path)
    weak = _write(wiki, "concepts/thin.md", _weak_page(title="thin"))
    _write(wiki, "concepts/solid.md", _healthy_page(title="solid"))
    before = weak.read_bytes()

    result = curate.run_reweave(fix=True, now=NOW)

    assert weak.read_bytes() == before  # 본문·근거 부족 페이지 무변경
    assert [rel for rel, _ in result["weak"]] == ["concepts/thin.md"]
    queue = (wiki / "reweave_queue.md").read_text(encoding="utf-8")
    assert "- [ ] `wiki/concepts/thin.md`" in queue  # distill_queue 동일 체크박스 패턴
    assert "solid.md" not in queue


def test_gate_dirs_isolated_from_weak_scan(monkeypatch, tmp_path):
    """observing/·rejected/ 의 weak 페이지는 큐·alert·fix 어디에도 안 잡힌다."""
    wiki = _patch_paths(monkeypatch, tmp_path)
    _write(wiki, "observing/thin-obs.md", _observing_page("2026-07-10"))
    rej = _write(wiki, "rejected/thin-rej.md", _weak_page(title="thin-rej"))
    before = rej.read_bytes()

    result = curate.run_reweave(fix=True, now=NOW)

    assert result["weak"] == []
    assert result["fixed"] == []
    assert result["alerts"] == []
    assert rej.read_bytes() == before
    queue = (wiki / "reweave_queue.md").read_text(encoding="utf-8")
    assert "thin-obs" not in queue and "thin-rej" not in queue


def test_fix_applies_memory_health_engine_and_idempotent(monkeypatch, tmp_path):
    wiki = _patch_paths(monkeypatch, tmp_path)
    page = _write(wiki, "concepts/fixable.md",
                  _fm_block(title="fixable", type="concept", created="2026-06-01",
                            updated="2026-06-01", sources=["raw/a.md", "raw/b.md"])
                  + _healthy_body())

    r1 = curate.run_reweave(fix=True, now=NOW)
    assert [rel for rel, _ in r1["fixed"]] == ["concepts/fixable.md"]
    fm, body = frontmatter_utils.read_fm(page.read_text(encoding="utf-8"))
    assert fm["summary"].startswith(INTRO_50[:20])   # 본문 첫 문단 기계적 추출
    assert fm["source_count"] == 2                    # len(sources) 캐시
    assert "## 섹션 1" in body                        # body 무손상

    # idempotent — 2회째 실행은 아무 것도 다시 고치지 않는다.
    snap = _snapshot(wiki)
    r2 = curate.run_reweave(fix=True, now=NOW)
    assert r2["fixed"] == []
    snap2 = _snapshot(wiki)
    # 큐 파일은 타임스탬프 포함이라 동일 now 주입 시 동일 바이트여야 한다.
    assert snap == snap2


def test_scan_without_fix_previews_but_does_not_write(monkeypatch, tmp_path):
    """--reweave (fix 미지정): fix 가능분을 계획으로 **예고**하되 페이지는 무변경.

    (구계약은 fix 미지정 시 계획 자체를 스킵해 fixed=0 → --dry-run 단독이 fixable 을
    0 으로 잘못 보여주는 함정이 있었다. 신계약: 계획은 항상, 쓰기만 --fix 게이트.)
    """
    wiki = _patch_paths(monkeypatch, tmp_path)
    page = _write(wiki, "concepts/fixable.md",
                  _fm_block(title="fixable", type="concept", created="2026-06-01",
                            updated="2026-06-01", sources=["raw/a.md", "raw/b.md"])
                  + _healthy_body())
    before = page.read_bytes()

    result = curate.run_reweave(fix=False, now=NOW)

    assert len(result["fixed"]) == 1  # fix 가능분(summary·source_count)을 예고한다
    assert page.read_bytes() == before  # 핵심: --fix 없으면 파일 무변경
    assert (wiki / "reweave_queue.md").exists()  # 큐는 생성된다


def test_fix_dry_run_previews_same_plan_but_no_write(monkeypatch, tmp_path):
    """--fix --dry-run: --fix 와 동일한 fix 계획을 예고하되 파일은 안 쓴다(진짜 미리보기)."""
    wiki = _patch_paths(monkeypatch, tmp_path)
    page = _write(wiki, "concepts/fixable.md",
                  _fm_block(title="fixable", type="concept", created="2026-06-01",
                            updated="2026-06-01", sources=["raw/a.md", "raw/b.md"])
                  + _healthy_body())
    before = page.read_bytes()

    preview = curate.run_reweave(fix=True, dry_run=True, now=NOW)
    assert len(preview["fixed"]) == 1
    assert page.read_bytes() == before  # dry-run — 무변경

    applied = curate.run_reweave(fix=True, dry_run=False, now=NOW)
    assert len(applied["fixed"]) == 1
    assert page.read_bytes() != before  # 실제 적용 — 변경됨
    # 미리보기 계획과 실제 적용 계획이 동일해야 미리보기가 신뢰된다
    assert [a for _, a in preview["fixed"]] == [a for _, a in applied["fixed"]]


def test_dry_run_changes_nothing(monkeypatch, tmp_path):
    wiki = _patch_paths(monkeypatch, tmp_path)
    _write(wiki, "concepts/fixable.md",
           _fm_block(title="fixable", type="concept", created="2026-06-01",
                     updated="2026-06-01", sources=["raw/a.md"]) + _healthy_body())
    _write(wiki, "concepts/thin.md", _weak_page(title="thin"))
    _write(wiki, "observing/expired.md", _observing_page("2026-07-01"))
    snap = _snapshot(tmp_path)

    result = curate.run_reweave(fix=True, dry_run=True, weekly_summary=True, now=NOW)

    assert _snapshot(tmp_path) == snap  # 파일 무변경 (큐·이동·fix·episode 전부)
    # 계획은 반환값에 담긴다.
    assert [rel for rel, _ in result["fixed"]] == ["concepts/fixable.md"]
    assert result["expired"] and result["expired"][0]["slug"] == "expired"


# ── 4. 리포트 ## Reweave 섹션 ─────────────────────────────────────────

def test_report_contains_reweave_section(monkeypatch, tmp_path):
    wiki = _patch_paths(monkeypatch, tmp_path)
    _write(wiki, "concepts/thin.md", _weak_page(title="thin"))
    _write(wiki, "observing/expired.md", _observing_page("2026-07-01"))

    result = curate.run_reweave(fix=True, now=NOW)
    curate.write_report({}, [], {}, [], reweave=result)

    report = (wiki / "curate_report.md").read_text(encoding="utf-8")
    assert "## Reweave" in report
    assert f"fixed: {len(result['fixed'])} / alert: {len(result['alerts'])} / expired: 1" in report
    assert "wiki/observing/expired.md → wiki/rejected/expired.md" in report
    assert "`concepts/thin.md`" in report


# ── 5. episode 기록 (fail-soft) + 점수 되먹임 차단 ────────────────────

def test_reweave_episode_record_shape(monkeypatch, tmp_path):
    wiki = _patch_paths(monkeypatch, tmp_path)
    _write(wiki, "concepts/thin.md", _weak_page(title="thin"))
    result = curate.run_reweave(now=NOW)

    rec = curate._reweave_episode_record(result, fix=False, weekly_summary=False)
    assert rec["task_type"] == "reweave"
    assert rec["read_pages"] == ["wiki/concepts/thin.md"]
    assert rec["outputs"]["queued"] == 1
    # 스키마 검증 통과 (fail-loud 헬퍼 기준).
    curate.episode._validate(rec)


def test_record_reweave_episode_fail_soft(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)

    def boom(record, episodes_dir=None):
        raise RuntimeError("원장 쓰기 실패")

    monkeypatch.setattr(curate.episode, "append", boom)
    # 예외가 밖으로 안 새면 통과 (fail-soft).
    curate._record_reweave_episode({"weak": [], "fixed": [], "alerts": [], "expired": []},
                                   fix=False, weekly_summary=False)


def test_episode_ref_index_excludes_reweave(tmp_path):
    """build_episode_ref_index: reweave 에피소드의 read_pages 는 집계 제외."""
    episodes = tmp_path / "episodes"
    episodes.mkdir()

    def _rec(task_type):
        return {"timestamp": "2026-07-04T09:00:00+09:00", "task_type": task_type,
                "user_goal": "g", "inputs": {}, "read_pages": ["wiki/concepts/thin.md"],
                "procedures_used": [], "outputs": {}, "status": "ok", "notes": ""}

    shard = episodes / "2026-07.jsonl"
    shard.write_text(
        "\n".join(json.dumps(_rec(t), ensure_ascii=False)
                  for t in ("reweave", "reweave", "ai_answer")) + "\n",
        encoding="utf-8",
    )

    idx = memory_score.build_episode_ref_index(episodes)
    assert idx == {"thin": 1}  # ai_answer 1건만 — reweave 2건은 되먹임 차단


# ── 6. --weekly-summary ───────────────────────────────────────────────

def _reweave_episode_line(ts: str, pages: list[str]) -> str:
    return json.dumps({
        "timestamp": ts, "task_type": "reweave", "user_goal": "curate reweave",
        "inputs": {"mode": "reweave"}, "read_pages": pages, "procedures_used": [],
        "outputs": {}, "status": "ok", "notes": "",
    }, ensure_ascii=False)


def test_weekly_summary_repeat_candidates(monkeypatch, tmp_path):
    """28일 내 4회+ 반복 weak 노드가 통합/삭제 후보로 집계된다 (현재 스캔 포함)."""
    wiki = _patch_paths(monkeypatch, tmp_path)
    _write(wiki, "concepts/thin.md", _weak_page(title="thin"))

    episodes = tmp_path / "episodes"
    episodes.mkdir()
    lines = []
    for d in range(1, 4):  # 과거 3런 + 현재 스캔 1런 = 4런
        ts = (NOW - timedelta(days=d)).isoformat()
        lines.append(_reweave_episode_line(ts, ["wiki/concepts/thin.md"]))
    # 창 밖(29일 전) 런은 집계 제외 — 포함되면 one-off.md 가 후보로 오염된다.
    lines.append(_reweave_episode_line((NOW - timedelta(days=29)).isoformat(),
                                       ["wiki/concepts/one-off.md"]))
    (episodes / "2026-07.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = curate.run_reweave(weekly_summary=True, now=NOW)
    weekly = result["weekly"]
    assert weekly["insufficient_history"] is False
    assert weekly["runs"] == 4
    assert weekly["candidates"] == [("wiki/concepts/thin.md", 4)]

    curate.write_report({}, [], {}, [], reweave=result)
    report = (wiki / "curate_report.md").read_text(encoding="utf-8")
    assert "Weekly Summary" in report
    assert "`wiki/concepts/thin.md` — 4회" in report


def test_weekly_summary_insufficient_history_honest(monkeypatch, tmp_path):
    """episodes 부재 시 크래시 없이 현재 스캔 후보 + '이력 부족' 정직 표기."""
    wiki = _patch_paths(monkeypatch, tmp_path)
    _write(wiki, "concepts/thin.md", _weak_page(title="thin"))
    # episodes/ 디렉토리 자체가 없음 (fresh clone).

    result = curate.run_reweave(weekly_summary=True, now=NOW)
    weekly = result["weekly"]
    assert weekly["insufficient_history"] is True
    assert weekly["candidates"] == [("wiki/concepts/thin.md", 1)]

    curate.write_report({}, [], {}, [], reweave=result)
    report = (wiki / "curate_report.md").read_text(encoding="utf-8")
    assert "이력 부족" in report
