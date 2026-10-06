"""2026-10-06 튜토리얼 e2e(Codex 두 축)에서 드러난 제품 쪽 관찰 3건의 회귀 테스트.

1. curate 가 git 이 추적하는 log.md 를 매번 고쳐 `git status` 가 더러워지고 `git pull` 이 막힌다.
2. curate --reweave 보고서가 아무것도 고치지 않았는데 "fixed: 27 / 자동 보강"이라고 적는다.
3. express 가 "소재 테스트" 주제에 "김테스트" 라는 낱말 속 "테스트" 때문에 무관한 메모를 근거로 고른다.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import curate  # noqa: E402
import express  # noqa: E402

REWEAVE = {"fixed": [("concepts/a.md", ["summary 생성(200자)"])], "alerts": [], "expired": [],
           "expiry_errors": [], "weak": [], "weekly": None, "synthesis": [], "shrink_warnings": []}


@pytest.fixture
def report_paths(tmp_path, monkeypatch):
    (tmp_path / "wiki").mkdir()
    monkeypatch.setattr(curate, "REPORT_FILE", tmp_path / "wiki" / "curate_report.md")
    monkeypatch.setattr(curate, "LOG_FILE", tmp_path / "log.md")
    return tmp_path


# ── 1. 실행 기록은 git 이 추적하지 않는다 ────────────────────────────────────────


def test_run_log_is_not_tracked_by_git():
    """깨지면: curate 를 한 번만 돌려도 추적 파일이 바뀌어, 나중에 `git pull` 이 충돌로 멈춘다."""
    tracked = subprocess.run(["git", "ls-files", "log.md"], cwd=ROOT, capture_output=True, text=True).stdout
    ignored = subprocess.run(["git", "check-ignore", "log.md"], cwd=ROOT, capture_output=True, text=True).stdout
    assert tracked.strip() == ""
    assert ignored.strip() == "log.md"


def test_curate_creates_the_log_with_a_header_and_appends(report_paths):
    """log.md 가 없는 새 설치에서도 첫 실행이 오류 없이 머리글과 함께 기록을 만든다."""
    curate.write_report({}, [], {}, [])
    curate.write_report({}, [], {}, [])
    log = (report_paths / "log.md").read_text(encoding="utf-8")
    assert log.startswith("# LLM Wiki — 실행 로그")
    assert log.count("[curate]") == 2


# ── 2. reweave 보고서는 계획과 실제 적용을 구분한다 ────────────────────────────────


def test_reweave_report_says_fixable_when_nothing_was_applied(report_paths):
    """깨지면: --fix 없이 돌렸는데 보고서만 읽은 사람이 27개 페이지가 고쳐진 줄 안다."""
    curate.write_report({}, [], {}, [], reweave={**REWEAVE, "applied": False})
    text = (report_paths / "wiki" / "curate_report.md").read_text(encoding="utf-8")
    assert "fixable: 1" in text and "fixed: 1" not in text
    assert "아무 페이지도 바꾸지 않았습니다" in text
    assert "자동 보강 (" not in text
    assert "reweave: fixable 1" in (report_paths / "log.md").read_text(encoding="utf-8")


def test_reweave_report_says_fixed_when_it_was_applied(report_paths):
    curate.write_report({}, [], {}, [], reweave={**REWEAVE, "applied": True})
    text = (report_paths / "wiki" / "curate_report.md").read_text(encoding="utf-8")
    assert "fixed: 1" in text and "자동 보강 (1개)" in text
    assert "reweave: fixed 1" in (report_paths / "log.md").read_text(encoding="utf-8")


# ── 3. express 는 낱말 속에 든 글자로 관련 페이지를 고르지 않는다 ─────────────────────


@pytest.mark.parametrize("text, keywords, expected", [
    ("신규 입사자 김테스트 주민번호 안내", ["테스트"], 0),            # 사람 이름 속 "테스트"
    ("소재를 바꾸는 A/B 테스트", ["소재", "테스트"], 2),            # 조사가 붙어도, 앞에 공백이 있으면 센다
    ("recommendation engine", ["engine"], 1),
    ("reengine tools", ["engine"], 0),
])
def test_keyword_score_counts_only_word_starts(text, keywords, expected):
    assert express.keyword_score(text, keywords) == expected


def test_express_does_not_pick_a_page_only_because_a_name_contains_the_topic_word(tmp_path, monkeypatch):
    """깨지면: "소재 테스트" 초안에 신입 입사자 개인정보 메모가 근거로 들어와 본문 작성자가 오용할 위험이 생긴다."""
    wiki = tmp_path / "wiki" / "concepts"
    wiki.mkdir(parents=True)
    for slug in ("campaign", "newhire"):
        (wiki / f"{slug}.md").write_text(f"# {slug}\n", encoding="utf-8")
    monkeypatch.setattr(express, "load_index", lambda: (
        "- [[campaign]] — 소재 B가 A보다 전환 1.4배인 테스트 결과\n"
        "- [[newhire]] — 신규 입사자 김테스트 첫 출근 안내\n"))
    monkeypatch.setattr(express, "find_wiki_file", lambda slug: wiki / f"{slug}.md")
    got = [p.stem for p, _ in express.collect_related_pages("소재 테스트")]
    assert got == ["campaign"]
