"""test_memory_health.py — memory_health 읽기전용 건강 리포트 계약 (Phase 3, PRD US-008).

WHY (이 테스트가 인코딩하는 의도):
  1. 리포트 생성 — 픽스처 wiki/episodes/procedures 에서 기대 섹션·집계 수치를 내는가.
  2. 읽기 전용 — 리포트 자신을 제외하고 wiki 페이지 파일을 단 하나도 이동·삭제·생성하지
     않는다(메타 기억은 의미 기억을 관측만 한다, SPEC §A).
  3. 프라이버시(§D) — episode notes/inputs 의 verbatim 본문 문자열이 리포트에 새지 않는다.
     리포트는 **집계 수치 + 메타(ts/task_type/status)만** 담는다.
  4. OKF 누출 봉인(§D, Claude#1·Codex C1) — memory_health_report.md 가 okf_export.META_FILES
     에 들어가 공개 번들 export 에서 구조적으로 제외된다.

wiki_root/episodes_dir/procedures_dir 를 tmp_path 로 주입해 사용자 데이터를 건드리지 않는다
(컨벤션: test_episode·test_procedures 와 동일).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import memory_health  # noqa: E402
import okf_export  # noqa: E402

SECRET = "SECRET_TOKEN_XYZ_9f3a"  # episode notes/inputs 에만 등장 — 리포트에 새면 안 됨.
NOW = datetime(2026, 6, 27, 9, 0)


def _page(slug: str, *, memory_type: str | None = "semantic", confidence=None,
          created: str = "2026-06-01", body: str = "본문.") -> str:
    fm = ["---", f"title: {slug}", "type: concept"]
    if memory_type is not None:
        fm.append(f"memory_type: {memory_type}")
    if confidence is not None:
        fm.append(f"confidence: {confidence}")
    fm.append(f"created: {created}")
    fm.append("---")
    return "\n".join(fm) + f"\n\n# {slug}\n\n{body}\n"


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


@pytest.fixture
def fixture_dirs(tmp_path):
    """self-contained wiki/episodes/procedures/express 트리 주입."""
    wiki = tmp_path / "wiki"
    episodes = tmp_path / "episodes"
    procedures = tmp_path / "procedures"
    express = tmp_path / "express"

    # ── wiki 페이지 ──
    # rag: semantic, confidence 높음, 다른 페이지가 링크 → inbound 있음(orphan 아님).
    _write(wiki, "concepts/rag.md", _page("rag", confidence=0.9, created="2026-06-01"))
    # vector-db: memory_type 필드 부재 → 기본 semantic, rag 를 링크(rag inbound 부여).
    _write(wiki, "concepts/vector-db.md",
           _page("vector-db", memory_type=None, created="2026-06-01",
                 body="[[rag]] 를 참조한다."))
    # orphan-old: semantic, inbound 0, 오래됨(>180일) → orphan + archive 후보.
    _write(wiki, "concepts/orphan-old.md",
           _page("orphan-old", created="2024-06-01"))
    # lowconf: semantic, confidence 0.3 < 0.5 → 저신뢰, 최근(archive 아님).
    _write(wiki, "concepts/lowconf.md",
           _page("lowconf", confidence=0.3, created="2026-06-01"))
    # meta/dashboard: memory_type meta.
    _write(wiki, "meta/dashboard.md",
           _page("dashboard", memory_type="meta", created="2026-06-01"))
    # 리포트가 자기 자신을 페이지로 세지 않는지 확인용 메타 파일.
    _write(wiki, "curate_report.md", "# Curate Report\n\n메타.\n")

    # ── episodes (월별 샤드) — SECRET 은 notes/inputs 에만 ──
    recs = [
        {"timestamp": "2026-06-26T10:00:00+09:00", "task_type": "ai_answer",
         "user_goal": "RAG 질문", "inputs": {"q": SECRET}, "read_pages": ["wiki/concepts/rag.md"],
         "procedures_used": [], "outputs": {}, "status": "ok", "notes": f"메모 {SECRET}"},
        {"timestamp": "2026-06-25T10:00:00+09:00", "task_type": "express_blog",
         "user_goal": "블로그", "inputs": {}, "read_pages": ["wiki/concepts/rag.md"],
         "procedures_used": [], "outputs": {}, "status": "draft_ready", "notes": ""},
        {"timestamp": "2026-06-24T10:00:00+09:00", "task_type": "ingest_url",
         "user_goal": "수집", "inputs": {}, "read_pages": [],
         "procedures_used": [], "outputs": {}, "status": "ok", "notes": ""},
    ]
    episodes.mkdir(parents=True, exist_ok=True)
    (episodes / "2026-06.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n",
        encoding="utf-8",
    )

    # ── procedures ──
    procedures.mkdir(parents=True, exist_ok=True)
    (procedures / "stale-proc.md").write_text(
        "---\ntitle: stale\nmemory_type: procedural\ncreated: 2024-01-01\n---\n1. step\n",
        encoding="utf-8")
    (procedures / "fresh-proc.md").write_text(
        "---\ntitle: fresh\nmemory_type: procedural\ncreated: 2026-06-20\n---\n1. step\n",
        encoding="utf-8")

    # ── express (재사용 신호: rag 인용) ──
    _write(express, "blog/post.md",
           "---\ntitle: post\n---\n\n[[rag]] 기반 글.\n")

    return wiki, episodes, procedures, express


def _gen(fixture_dirs):
    wiki, episodes, procedures, express = fixture_dirs
    return memory_health.generate_report(
        wiki, episodes_dir=episodes, procedures_dir=procedures,
        express_dir=express, now=NOW,
    )


# ── 1. 리포트 생성: 섹션·집계 ─────────────────────────────────────────
def test_report_has_expected_sections(fixture_dirs):
    text = _gen(fixture_dirs)
    for heading in ("메모리 타입", "Orphan", "Stale 절차", "최근 에피소드",
                    "Top 재사용", "저신뢰", "Weak content", "Archive 후보"):
        assert heading in text, f"섹션 누락: {heading}"


def test_memory_type_counts(fixture_dirs):
    text = _gen(fixture_dirs)
    # semantic 4 (rag, vector-db, orphan-old, lowconf), meta 1. curate_report.md 는 미집계.
    assert "semantic: 4" in text
    assert "meta: 1" in text


def test_orphan_semantic_pages(fixture_dirs):
    text = _gen(fixture_dirs)
    assert "orphan-old" in text
    # rag 는 inbound(vector-db→rag) 있으므로 orphan 으로 잡히지 않는다 — orphan 섹션 한정 확인.
    orphan_section = text.split("## Orphan", 1)[1].split("\n## ", 1)[0]
    assert "orphan-old" in orphan_section
    assert "rag" not in orphan_section.replace("orphan-old", "")


def test_stale_procedures(fixture_dirs):
    text = _gen(fixture_dirs)
    stale_section = text.split("Stale 절차", 1)[1].split("\n## ", 1)[0]
    assert "stale-proc" in stale_section
    assert "fresh-proc" not in stale_section


def test_recent_episode_count(fixture_dirs):
    text = _gen(fixture_dirs)
    recent_section = text.split("최근 에피소드", 1)[1].split("\n## ", 1)[0]
    # 3개 에피소드 집계 + task_type/status 메타.
    assert "3" in recent_section
    assert "ai_answer" in recent_section
    assert "ingest_url" in recent_section


def test_top_reused_pages(fixture_dirs):
    text = _gen(fixture_dirs)
    reused_section = text.split("Top 재사용", 1)[1].split("\n## ", 1)[0]
    # rag: express 인용 1 + 비-express episode_ref 1 = 재사용 신호 보유.
    assert "rag" in reused_section


def test_low_confidence_pages(fixture_dirs):
    text = _gen(fixture_dirs)
    low_section = text.split("저신뢰", 1)[1].split("\n## ", 1)[0]
    assert "lowconf" in low_section
    # confidence 0.9 의 rag 는 저신뢰 섹션에 없다.
    assert "rag" not in low_section


def test_archive_candidates(fixture_dirs):
    text = _gen(fixture_dirs)
    arch_section = text.split("Archive 후보", 1)[1]
    assert "orphan-old" in arch_section
    # 최근 페이지는 archive 후보 아님.
    assert "lowconf" not in arch_section


# ── 2. 읽기 전용 — 리포트만 생성, 다른 wiki 파일 불변 ──────────────────
def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_read_only_only_report_written(fixture_dirs):
    wiki, episodes, procedures, express = fixture_dirs
    before = _snapshot(wiki)
    path = memory_health.write_report(
        wiki, episodes_dir=episodes, procedures_dir=procedures,
        express_dir=express, now=NOW,
    )
    after = _snapshot(wiki)

    # 리포트는 wiki_root 직속에 쓰인다.
    assert path == wiki / "memory_health_report.md"
    assert path.exists()
    # 신규 파일은 리포트 하나뿐.
    added = set(after) - set(before)
    assert added == {"memory_health_report.md"}, f"리포트 외 신규 파일: {added}"
    # 삭제된 파일 없음.
    assert set(before) - set(after) == set()
    # 기존 파일 내용 불변(이동·rewrite 없음).
    for rel, content in before.items():
        assert after[rel] == content, f"기존 파일 변경됨: {rel}"


def test_read_only_external_dirs_untouched(fixture_dirs):
    wiki, episodes, procedures, express = fixture_dirs
    ep_before = _snapshot(episodes)
    pr_before = _snapshot(procedures)
    memory_health.write_report(
        wiki, episodes_dir=episodes, procedures_dir=procedures,
        express_dir=express, now=NOW,
    )
    assert _snapshot(episodes) == ep_before, "episodes/ 가 변경됨(읽기 전용 위반)"
    assert _snapshot(procedures) == pr_before, "procedures/ 가 변경됨(읽기 전용 위반)"


# ── 3. 프라이버시(§D): verbatim episode 본문 비공개 ───────────────────
def test_secret_not_in_report(fixture_dirs):
    text = _gen(fixture_dirs)
    assert SECRET not in text, "episode notes/inputs 의 verbatim 문자열이 리포트에 누출됨(§D 위반)"


def test_written_report_has_no_secret(fixture_dirs):
    wiki, episodes, procedures, express = fixture_dirs
    path = memory_health.write_report(
        wiki, episodes_dir=episodes, procedures_dir=procedures,
        express_dir=express, now=NOW,
    )
    assert SECRET not in path.read_text(encoding="utf-8")


# ── 4. OKF 누출 봉인(§D) ──────────────────────────────────────────────
def test_report_in_okf_meta_files():
    """memory_health_report.md 가 okf META_FILES 에 등재 → 공개 번들 export 제외."""
    assert "memory_health_report.md" in okf_export.META_FILES


def test_report_skipped_by_okf_export(tmp_path):
    """wiki/ 직속 memory_health_report.md 는 okf export 결과·skip 노이즈에 안 잡혀야."""
    wiki = tmp_path / "wiki"
    _write(wiki, "memory_health_report.md", "# Memory Health\n\n집계 본문(frontmatter 없음).\n")
    _write(wiki, "concepts/a.md", "---\ntitle: A\ntype: concept\n---\n\n본문.\n")
    stats = okf_export.export_bundle(wiki, tmp_path / "okf", dry_run=True)
    # title 부재 skip 노이즈로도 안 잡혀야(META_FILES 라 enumeration 단계에서 제외).
    assert not any("memory_health_report" in rel for rel, _ in stats.skipped), stats.skipped
    # export 페이지에도 없어야.
    assert stats.pages_exported == 1
