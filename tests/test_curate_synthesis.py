"""test_curate_synthesis.py — v0.3.1 Wave 6: curate 가 synthesis 순수 코어를 배선한다.

WHY (이 테스트가 인코딩하는 의도):
  1. run_reweave 는 select_synthesis_targets 로 2+ 소스 교차/inbound 허브 페이지를
     종합 대상으로 선정해 reweave_queue.md 의 **별도 `## 종합 대상` 섹션**에 큐잉한다
     (weak 보강 큐와 라벨로 구분 — LLM Step 이 다른 규칙으로 처리).
  2. shrink 가드: guard_no_shrink 를 **실제 호출**하는 배선 경로는 synthesis 대상
     한정 스냅샷 대비다. 이전 run 대비 본문·근거가 줄면 curate_report 에 WARN shrink
     로 표면화한다(자동 차단 아님 — 사람/LLM 검토, 정밀도 우선). distill(의도적 압축)
     오탐을 피하려 감지 범위를 synthesis 대상으로 한정했다.
  3. --dry-run 은 스냅샷·큐 어떤 파일도 쓰지 않는다.

tmp_path self-contained (claude CLI 불요).
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import curate  # noqa: E402

NOW = datetime(2026, 7, 4, 9, 0)


def _fm_block(**fields) -> str:
    lines = ["---"]
    for k, v in fields.items():
        if isinstance(v, list):
            lines.append(f"{k}: [" + ", ".join(str(x) for x in v) + "]")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def _healthy_body(marker: str = "본문") -> str:
    filler = ("검증 가능한 근거와 함께 정리한 내용 " * 20).strip()
    sections = "\n\n".join(f"## 섹션 {i}\n\n{filler}" for i in range(1, 4))
    return f"\n\n# {marker}\n\n{sections}\n"


def _page(title: str, sources: list[str], body: str | None = None,
          **fm_over) -> str:
    fm = dict(title=title, type="concept", created="2026-06-01", updated="2026-06-01",
              summary="요약 " * 15, sources=sources, source_count=len(sources))
    fm.update(fm_over)
    return _fm_block(**fm) + (body if body is not None else _healthy_body())


def _patch_paths(monkeypatch, tmp_path: Path) -> Path:
    wiki = tmp_path / "wiki"
    wiki.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(curate, "WIKI_ROOT", tmp_path)
    monkeypatch.setattr(curate, "WIKI_DIR", wiki)
    monkeypatch.setattr(curate, "DISTILL_QUEUE_FILE", wiki / "distill_queue.md")
    monkeypatch.setattr(curate, "WIKI_STATS_FILE", tmp_path / "wiki_stats.json")
    monkeypatch.setattr(curate, "REPORT_FILE", wiki / "curate_report.md")
    monkeypatch.setattr(curate, "LOG_FILE", tmp_path / "log.md")
    monkeypatch.setattr(curate.episode, "EPISODES_DIR", tmp_path / "episodes")
    return wiki


def _write(root: Path, rel: str, content: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ── 1. 종합 대상 선정 → reweave_queue.md 종합 섹션 ────────────────────────

def test_cross_source_page_queued_as_synthesis_target(monkeypatch, tmp_path):
    """2+ 소스 교차 페이지가 `## 종합 대상` 섹션에 큐잉된다."""
    wiki = _patch_paths(monkeypatch, tmp_path)
    _write(wiki, "concepts/cross.md", _page("cross", ["raw/a.md", "raw/b.md"]))
    _write(wiki, "concepts/single.md", _page("single", ["raw/a.md"]))

    result = curate.run_reweave(now=NOW)

    slugs = [t.slug for t in result["synthesis"]]
    assert "cross" in slugs           # 2 소스 교차 → 대상
    assert "single" not in slugs      # 1 소스 · 허브 아님 → 대상 아님

    queue = (wiki / "reweave_queue.md").read_text(encoding="utf-8")
    assert "## 종합 대상" in queue
    assert "- [ ] [[cross]]" in queue
    assert "소스 raw/a.md, raw/b.md" in queue


def test_inbound_hub_queued_as_synthesis_target(monkeypatch, tmp_path):
    """inbound 허브(2+ 페이지가 가리킴)는 단일 소스여도 종합 대상."""
    wiki = _patch_paths(monkeypatch, tmp_path)
    _write(wiki, "concepts/hub.md", _page("hub", ["raw/a.md"]))
    _write(wiki, "concepts/p1.md", _page("p1", ["raw/a.md"],
                                         body=_healthy_body("p1") + "\n[[hub]]\n"))
    _write(wiki, "concepts/p2.md", _page("p2", ["raw/a.md"],
                                         body=_healthy_body("p2") + "\n[[hub]]\n"))

    result = curate.run_reweave(now=NOW)

    hub = next((t for t in result["synthesis"] if t.slug == "hub"), None)
    assert hub is not None and hub.inbound_degree == 2


# ── 2. shrink 가드 — guard_no_shrink 실제 호출 배선 ───────────────────────

def test_shrink_guard_flags_body_reduction_between_runs(monkeypatch, tmp_path):
    """synthesis 대상의 본문이 run 사이에 줄면 guard_no_shrink 가 WARN shrink 로 표면화."""
    wiki = _patch_paths(monkeypatch, tmp_path)
    page = _write(wiki, "concepts/cross.md",
                  _page("cross", ["raw/a.md", "raw/b.md"]))

    # run1: 스냅샷 저장(비교 대상 없음 → 경고 0).
    r1 = curate.run_reweave(now=NOW)
    assert r1["shrink_warnings"] == []
    assert (wiki / curate.SYNTHESIS_SNAPSHOT_NAME).exists()

    # 본문을 대폭 축소(소스는 2 유지 → 여전히 synthesis 대상).
    page.write_text(_page("cross", ["raw/a.md", "raw/b.md"],
                          body="\n\n# cross\n\n짧게 줄임.\n"), encoding="utf-8")

    # run2: 이전 스냅샷 대비 축소 감지.
    r2 = curate.run_reweave(now=NOW)
    warned = [slug for slug, _ in r2["shrink_warnings"]]
    assert "cross" in warned

    curate.write_report({}, [], {}, [], reweave=r2)
    report = (wiki / "curate_report.md").read_text(encoding="utf-8")
    assert "WARN shrink" in report
    assert "[[cross]]" in report


def test_no_shrink_no_warning_idempotent(monkeypatch, tmp_path):
    """본문 불변이면 두 번째 run 에서 경고 없음 (오탐 없음)."""
    wiki = _patch_paths(monkeypatch, tmp_path)
    _write(wiki, "concepts/cross.md", _page("cross", ["raw/a.md", "raw/b.md"]))

    curate.run_reweave(now=NOW)
    r2 = curate.run_reweave(now=NOW)
    assert r2["shrink_warnings"] == []


def test_dry_run_writes_no_snapshot(monkeypatch, tmp_path):
    wiki = _patch_paths(monkeypatch, tmp_path)
    _write(wiki, "concepts/cross.md", _page("cross", ["raw/a.md", "raw/b.md"]))

    result = curate.run_reweave(dry_run=True, now=NOW)

    assert not (wiki / curate.SYNTHESIS_SNAPSHOT_NAME).exists()
    assert not (wiki / "reweave_queue.md").exists()
    # 계획(대상 선정)은 반환값엔 담긴다.
    assert [t.slug for t in result["synthesis"]] == ["cross"]


# ── 3. episode 카운트 ─────────────────────────────────────────────────

def test_reweave_episode_counts_synthesis(monkeypatch, tmp_path):
    wiki = _patch_paths(monkeypatch, tmp_path)
    _write(wiki, "concepts/cross.md", _page("cross", ["raw/a.md", "raw/b.md"]))

    result = curate.run_reweave(now=NOW)
    rec = curate._reweave_episode_record(result, fix=False, weekly_summary=False)
    assert rec["outputs"]["synthesis_targets"] == 1
    assert rec["outputs"]["shrink_warnings"] == 0
    curate.episode._validate(rec)  # 스키마 통과
