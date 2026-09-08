"""test_memory_health_fix.py — v0.3 WS-3: weak content 신규 기준 + --fix 계약.

WHY (이 테스트가 인코딩하는 의도):
  1. weak content 3기준(본문<800자 · 근거<2건 · H2<3개)이 **각각** 검출되고,
     리포트에 path·issues 상세로 표시된다 (기존 orphan·confidence·stale 기준에 추가).
  2. --fix 는 **자동 보강 가능분만** 채운다 — summary 결손(본문 첫 문단 40~200자 추출,
     경계 39/40/200 포함) · source_count 결손/불일치 · updated 형식 결손.
     본문·근거 부족은 절대 fix 하지 않고 alert 만 (가짜 보강 금지 — 본문 무손상).
  3. idempotent — 2회 실행 시 바이트 무변경. --dry-run 은 아무 파일도 안 바꾼다.
  4. 기본 --report(write_report) 계약 불변 — fixable 결손이 있어도 페이지 무변경(read-only).
  5. 파싱 실패 페이지는 건드리지 않고 alert (fail-loud).

tmp_path self-contained (claude CLI 불요) — 컨벤션: test_memory_health 와 동일.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import memory_health  # noqa: E402
from lib import frontmatter_utils  # noqa: E402

NOW = datetime(2026, 7, 4, 9, 0)

# 40자 이상 첫 문단 (len 50) — summary 추출 원본.
INTRO_50 = "이 페이지는 자동 요약 추출 검증용 첫 문단으로 사십 자를 확실히 넘도록 길게 작성한 문장이다."
assert len(INTRO_50) >= 40


def _write(root: Path, rel: str, content: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def _healthy_body(intro: str = INTRO_50) -> str:
    """본문 ≥800자 · H2 3개 — weak 기준에 안 걸리는 본문."""
    filler = ("검증 가능한 근거와 함께 정리한 내용 " * 20).strip()  # 문단당 ~380자
    sections = "\n\n".join(f"## 섹션 {i}\n\n{filler}" for i in range(1, 4))
    return f"\n\n# healthy\n\n{intro}\n\n{sections}\n"


def _fm_block(*, summary: str | None = None, sources: list[str] | None = None,
              source_count: int | None = None, updated: str | None = "2026-06-01") -> str:
    lines = ["---", "title: page", "type: concept", "created: 2026-06-01"]
    if updated is not None:
        lines.append(f"updated: {updated}")
    if summary is not None:
        lines.append(f"summary: {summary}")
    if sources is not None:
        lines.append("sources: [" + ", ".join(sources) + "]")
    if source_count is not None:
        lines.append(f"source_count: {source_count}")
    lines.append("---")
    return "\n".join(lines)


def _healthy_page(**fm_over) -> str:
    defaults = dict(summary="요약 " * 15, sources=["raw/a.md", "raw/b.md"], source_count=2)
    defaults.update(fm_over)
    return _fm_block(**defaults) + _healthy_body()


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _read_fm(path: Path) -> tuple[dict, str]:
    return frontmatter_utils.read_fm(path.read_text(encoding="utf-8"))


# ── 1. weak content 3기준 각각 검출 ───────────────────────────────────
def test_weak_content_three_criteria_detected(tmp_path):
    wiki = tmp_path / "wiki"
    # 전 기준 통과 → weak 아님.
    _write(wiki, "concepts/healthy.md", _healthy_page())
    # 본문<800자 (sources·H2 는 통과).
    short_body = ("\n\n# short\n\n" + INTRO_50 + "\n\n"
                  + "\n\n".join(f"## 섹션 {i}\n\n짧은 내용." for i in range(1, 4)))
    _write(wiki, "concepts/short-body.md",
           _fm_block(summary="요약 " * 15, sources=["raw/a.md", "raw/b.md"],
                     source_count=2) + short_body)
    # 근거<2건 (본문·H2 는 통과).
    _write(wiki, "concepts/few-sources.md",
           _fm_block(summary="요약 " * 15, sources=["raw/a.md"], source_count=1)
           + _healthy_body())
    # H2<3개 (본문·sources 는 통과).
    filler = ("두꺼운 본문 내용을 담은 문단 " * 40).strip()
    few_h2_body = f"\n\n# few-h2\n\n{INTRO_50}\n\n## 섹션 1\n\n{filler}\n\n## 섹션 2\n\n{filler}\n"
    _write(wiki, "concepts/few-h2.md",
           _fm_block(summary="요약 " * 15, sources=["raw/a.md", "raw/b.md"],
                     source_count=2) + few_h2_body)

    text = memory_health.generate_report(
        wiki, episodes_dir=tmp_path / "episodes", procedures_dir=tmp_path / "procedures",
        express_dir=tmp_path / "express", now=NOW)
    weak_section = text.split("## Weak content", 1)[1].split("\n## ", 1)[0]

    assert "healthy" not in weak_section
    assert "short-body" in weak_section and "본문" in weak_section
    # path·issues 상세 표시.
    assert "`concepts/short-body.md`" in weak_section
    few_src_line = next(l for l in weak_section.splitlines() if "few-sources" in l)
    assert "근거 1건" in few_src_line
    few_h2_line = next(l for l in weak_section.splitlines() if "few-h2" in l)
    assert "H2 2개" in few_h2_line
    # 각 페이지는 위반한 기준만 보고한다.
    short_line = next(l for l in weak_section.splitlines() if "short-body" in l)
    assert "근거" not in short_line and "H2" not in short_line


# ── 2. --fix: summary 결손 자동 생성 (40~200자 경계 포함) ──────────────
def test_fix_generates_summary_from_first_paragraph(tmp_path):
    wiki = tmp_path / "wiki"
    page = _write(wiki, "concepts/no-summary.md", _healthy_page(summary=None))
    _, body_before = _read_fm(page)

    result = memory_health.run_fix(wiki, now=NOW)

    fm, body_after = _read_fm(page)
    assert fm.get("summary") == INTRO_50
    assert 40 <= len(fm["summary"]) <= 200
    assert body_after == body_before, "--fix 가 body 를 손상함"
    assert any(rel == "concepts/no-summary.md" for rel, _ in result.fixed)


@pytest.mark.parametrize("para_len,expect_len", [(40, 40), (200, 200), (300, 200)])
def test_fix_summary_length_boundaries(tmp_path, para_len, expect_len):
    """첫 문단 40자(하한 경계)=그대로, 200자=그대로, 300자=200자 절단."""
    wiki = tmp_path / "wiki"
    para = "가" * para_len
    page = _write(wiki, "concepts/boundary.md",
                  _fm_block(summary=None, sources=["raw/a.md", "raw/b.md"], source_count=2)
                  + _healthy_body(intro=para))
    memory_health.run_fix(wiki, now=NOW)
    fm, _ = _read_fm(page)
    assert len(fm["summary"]) == expect_len
    assert fm["summary"] == para[:expect_len]


def test_fix_summary_below_40_not_generated(tmp_path):
    """첫 문단 39자(<40) → summary 미생성(가짜 보강 금지) + alert."""
    wiki = tmp_path / "wiki"
    para = "가" * 39
    page = _write(wiki, "concepts/tiny-para.md",
                  _fm_block(summary=None, sources=["raw/a.md", "raw/b.md"], source_count=2)
                  + _healthy_body(intro=para))
    result = memory_health.run_fix(wiki, now=NOW)
    fm, _ = _read_fm(page)
    assert "summary" not in fm
    assert any(rel == "concepts/tiny-para.md" and "summary" in reason
               for rel, reason in result.alerts)


# ── 3. --fix: source_count · updated 기계적 채움 ──────────────────────
def test_fix_source_count_missing_and_mismatch(tmp_path):
    wiki = tmp_path / "wiki"
    missing = _write(wiki, "concepts/sc-missing.md", _healthy_page(source_count=None))
    mismatch = _write(wiki, "concepts/sc-mismatch.md", _healthy_page(source_count=7))
    memory_health.run_fix(wiki, now=NOW)
    assert _read_fm(missing)[0]["source_count"] == 2
    assert _read_fm(mismatch)[0]["source_count"] == 2


def test_fix_updated_filled_from_created(tmp_path):
    wiki = tmp_path / "wiki"
    page = _write(wiki, "concepts/no-updated.md", _healthy_page(updated=None))
    memory_health.run_fix(wiki, now=NOW)
    fm, _ = _read_fm(page)
    assert str(fm["updated"])[:10] == "2026-06-01"  # created 값으로 기계적 채움


# ── 4. 본문 부족은 fix 금지 — alert 만 (가짜 보강 금지) ────────────────
def test_body_placeholder_not_fixed_only_alert(tmp_path):
    """본문 500자 placeholder — 바이트 무변경 + alert (본문 생성·요약 확장 금지)."""
    wiki = tmp_path / "wiki"
    placeholder = ("자리표시 내용 " * 63)[:500]  # 500자, H2 0개
    page = _write(wiki, "concepts/placeholder.md",
                  _fm_block(summary="요약 " * 15, sources=["raw/a.md", "raw/b.md"],
                            source_count=2) + f"\n\n# placeholder\n\n{placeholder}\n")
    before = page.read_bytes()

    result = memory_health.run_fix(wiki, now=NOW)

    assert page.read_bytes() == before, "본문 부족 페이지를 --fix 가 수정함(가짜 보강)"
    assert not any(rel == "concepts/placeholder.md" for rel, _ in result.fixed)
    alert = next(reason for rel, reason in result.alerts
                 if rel == "concepts/placeholder.md")
    assert "본문" in alert and "(<800자)" in alert and "H2 0개" in alert


# ── 5. idempotent + --dry-run ─────────────────────────────────────────
def test_fix_idempotent_second_run_no_byte_change(tmp_path):
    wiki = tmp_path / "wiki"
    _write(wiki, "concepts/all-deficits.md",
           _fm_block(summary=None, sources=["raw/a.md", "raw/b.md"],
                     source_count=None, updated=None) + _healthy_body())
    first = memory_health.run_fix(wiki, now=NOW)
    assert first.fixed, "1회차에 fix 가 있어야 idempotency 검증이 유효"
    snap = _snapshot(wiki)

    second = memory_health.run_fix(wiki, now=NOW)

    assert second.fixed == [], f"2회차에 재수정 발생: {second.fixed}"
    assert _snapshot(wiki) == snap, "2회 실행 시 바이트 변경(idempotent 위반)"


def test_healthy_page_untouched_by_fix(tmp_path):
    """정상 페이지는 --fix 1회차부터 무변경 (파일 mtime 외 바이트 동일)."""
    wiki = tmp_path / "wiki"
    page = _write(wiki, "concepts/healthy.md", _healthy_page())
    before = page.read_bytes()
    result = memory_health.run_fix(wiki, now=NOW)
    assert page.read_bytes() == before
    assert result.fixed == []


def test_dry_run_lists_targets_without_changes(tmp_path):
    wiki = tmp_path / "wiki"
    _write(wiki, "concepts/no-summary.md", _healthy_page(summary=None))
    snap = _snapshot(wiki)

    result = memory_health.run_fix(wiki, dry_run=True, now=NOW)

    assert result.dry_run is True
    assert any(rel == "concepts/no-summary.md" for rel, _ in result.fixed)
    assert _snapshot(wiki) == snap, "--dry-run 이 파일을 변경함"


# ── 6. 기본 --report 는 여전히 read-only ──────────────────────────────
def test_default_report_readonly_even_with_fixable_deficits(tmp_path):
    """fixable 결손(summary·source_count·updated)이 있어도 write_report 는 페이지 무변경."""
    wiki = tmp_path / "wiki"
    _write(wiki, "concepts/no-summary.md",
           _fm_block(summary=None, sources=["raw/a.md", "raw/b.md"],
                     source_count=None, updated=None) + _healthy_body())
    before = _snapshot(wiki)

    memory_health.write_report(
        wiki, episodes_dir=tmp_path / "episodes", procedures_dir=tmp_path / "procedures",
        express_dir=tmp_path / "express", now=NOW)

    after = _snapshot(wiki)
    assert set(after) - set(before) == {"memory_health_report.md"}
    for rel, content in before.items():
        assert after[rel] == content, f"기본 --report 가 페이지를 수정함: {rel}"


# ── 7. 파싱 실패 페이지: 무변경 + alert (fail-loud) ────────────────────
def test_parse_error_page_untouched_and_alerted(tmp_path):
    wiki = tmp_path / "wiki"
    broken = _write(wiki, "concepts/broken.md",
                    "---\ntitle: [unclosed\n---\n\n# broken\n\n본문.\n")
    before = broken.read_bytes()

    result = memory_health.run_fix(wiki, now=NOW)

    assert broken.read_bytes() == before, "파싱 실패 페이지를 --fix 가 수정함"
    assert not any(rel == "concepts/broken.md" for rel, _ in result.fixed)
    assert any(rel == "concepts/broken.md" and "파싱 실패" in reason
               for rel, reason in result.alerts)


# ── 8. --fix 리포트에 fixed/alert 요약 포함 ────────────────────────────
def test_fix_report_contains_fixed_alert_summary(tmp_path):
    wiki = tmp_path / "wiki"
    _write(wiki, "concepts/no-summary.md", _healthy_page(summary=None))   # fixed 1
    placeholder = ("자리표시 내용 " * 63)[:500]
    _write(wiki, "concepts/placeholder.md",
           _fm_block(summary="요약 " * 15, sources=["raw/a.md", "raw/b.md"],
                     source_count=2) + f"\n\n# p\n\n{placeholder}\n")     # alert 1

    result = memory_health.run_fix(wiki, now=NOW)
    path = memory_health.write_report(
        wiki, episodes_dir=tmp_path / "episodes", procedures_dir=tmp_path / "procedures",
        express_dir=tmp_path / "express", now=NOW, fix_result=result)

    text = path.read_text(encoding="utf-8")
    assert f"fixed: {len(result.fixed)} / alert: {len(result.alerts)}" in text
    assert "`concepts/no-summary.md`" in text
    assert "`concepts/placeholder.md`" in text


# ── 9. gates 관리 폴더 격리 (V1 리뷰 발견 회귀 방지) ────────────────────
# WHY: 단독 memory_health --fix 경로가 observing/·rejected/·reweave_queue.md 를
#      정규 페이지로 오집계·write 하면 gates 격리(SPEC v0.3 §D)가 우회된다.
#      curate.find_all_wiki_pages 와 동일하게 이 셋을 스캔에서 제외해야 한다.
def test_fix_skips_gates_managed_dirs_and_reweave_queue(tmp_path):
    wiki = tmp_path / "wiki"
    _write(wiki, "concepts/healthy.md", _healthy_page())
    # summary 결손 = 정상 경로였다면 fix 대상 — 격리되어 미접촉이어야 함
    obs = _write(wiki, "observing/bar.md", _healthy_page(summary=None))
    rej = _write(wiki, "rejected/baz.md", _healthy_page(summary=None))
    queue = _write(wiki, "reweave_queue.md", "- [ ] wiki/concepts/x.md\n")

    before = {p: p.read_bytes() for p in (obs, rej, queue)}
    result = memory_health.run_fix(wiki, now=NOW)

    collected = {pi.rel for pi in memory_health._collect_pages(wiki)[0]}
    assert collected == {"concepts/healthy.md"}
    for p, b in before.items():
        assert p.read_bytes() == b, f"{p} 격리 위반 — 미접촉이어야 함"
    assert all("observing/" not in f and "rejected/" not in f and "reweave_queue" not in f
               for f in result.fixed)
