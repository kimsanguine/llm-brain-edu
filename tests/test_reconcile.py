"""lib/reconcile.py 모순 후보 탐지 테스트 — v0.3.1 WS-5.

WHY (이 테스트들이 인코딩하는 *의도* — schema/curate.md "Reconciliation Rules" 단일 출처):
  1. **명확한 모순 검출**: 기존 "A는 불가" 페이지 + "A 가능" 신규 근거 →
     주제 겹침 + 상반 극 신호 → 후보 1건 (existing_slug·signal 정확).
  2. **오탐 최소(정밀도 우선)**: 무관한 주제(frontmatter 겹침 < min_overlap) →
     상반 극이 있어도 후보 0. 단순 보강(상반 신호 없음) → 후보 0. 같은 극 → 0.
  3. **주어 불일치 방지**: "A는 불가" vs "B는 가능" — 극은 반대지만 주어가 달라 False.
  4. **부정어 페어 각각**: ANTONYM_PAIRS 대표 페어(한국어·영어)가 개별 작동.
  5. **결정성**: 같은 입력 → 같은 출력 (재호출 동일). now()/random 없음.
  6. **순수성**: 파일 I/O·LLM 없음 — 전부 인메모리. claude CLI 의존 0.

frontmatter 신규 필드 상수(superseded_claims·last_reconciled)가 schema 와 일치하는지도 고정.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from lib import reconcile  # noqa: E402
from lib.gates import ExistingPage  # noqa: E402
from lib.reconcile import (  # noqa: E402
    ContradictionCandidate,
    NewSource,
    detect_contradiction_candidates,
    is_potential_contradiction,
)


# ── 헬퍼 ────────────────────────────────────────────────────────────────

def _page(slug: str, *, title: str, tags: list[str], body: str) -> ExistingPage:
    return ExistingPage(slug=slug, frontmatter={"title": title, "tags": tags}, body=body)


def _source(ref: str, *, title: str, tags: list[str], text: str) -> NewSource:
    return NewSource(source_ref=ref, text=text,
                     frontmatter={"title": title, "tags": tags})


# ── 1. 명확한 모순 → 후보 검출 ──────────────────────────────────────────

def test_clear_contradiction_detected():
    page = _page(
        "prompt-caching",
        title="프롬프트 캐싱",
        tags=["llm", "caching"],
        body="프롬프트 캐싱은 스트리밍과 동시 사용이 불가능하다.",
    )
    src = _source(
        "raw/2026/caching.md",
        title="프롬프트 캐싱 업데이트",
        tags=["llm", "caching"],
        text="이제 프롬프트 캐싱은 스트리밍과 동시 사용이 가능하다.",
    )
    out = detect_contradiction_candidates(src, [page])
    assert len(out) == 1
    c = out[0]
    assert c.existing_slug == "prompt-caching"
    assert c.new_source_ref == "raw/2026/caching.md"
    assert c.signal == "가능↔불가능"
    assert "caching" in c.overlap_terms and "llm" in c.overlap_terms
    assert "불가능" in c.existing_claim
    assert "가능" in c.new_claim
    assert c.confidence_hint in ("low", "medium")


# ── 2. 무관한 주제(겹침 없음) → 후보 0 (오탐 방지) ───────────────────────

def test_unrelated_topic_no_candidate_even_with_opposite_poles():
    # 상반 극(불가능 vs 가능)이 본문에 있어도 주제(frontmatter)가 무관하면 후보 아님.
    page = _page("baking-bread", title="빵 굽기", tags=["cooking", "bread"],
                 body="오븐 없이 빵 굽기는 불가능하다.")
    src = _source("raw/finance.md", title="세금 신고", tags=["tax", "finance"],
                  text="온라인 세금 신고가 이제 가능하다.")
    assert detect_contradiction_candidates(src, [page]) == []


# ── 3. 단순 보강(상반 신호 없음) → 후보 0 ───────────────────────────────

def test_plain_reinforcement_no_candidate():
    page = _page("rag", title="RAG 검색", tags=["rag", "llm"],
                 body="RAG 는 외부 지식을 검색해 문맥에 넣는다.")
    src = _source("raw/rag2.md", title="RAG 심화", tags=["rag", "llm"],
                  text="RAG 는 재랭킹으로 검색 품질을 높인다.")
    assert detect_contradiction_candidates(src, [page]) == []


def test_same_pole_no_candidate():
    # 둘 다 "가능" — 같은 극이면 모순 아님.
    page = _page("feature-x", title="기능 X", tags=["product", "x"],
                 body="기능 X 는 오프라인에서 사용 가능하다.")
    src = _source("raw/x.md", title="기능 X 노트", tags=["product", "x"],
                  text="기능 X 는 모바일에서도 사용 가능하다.")
    assert detect_contradiction_candidates(src, [page]) == []


# ── 4. 주어 불일치 → 모순 아님 ──────────────────────────────────────────

def test_different_subject_not_contradiction():
    # 공유 내용 토큰이 전혀 없음(레디스 vs 몽고, 서로 다른 술어) → 극이 반대여도 False.
    assert is_potential_contradiction("레디스는 불가능", "몽고는 가능") is False


def test_same_subject_opposite_poles_is_contradiction():
    assert is_potential_contradiction("동시성은 불가능하다", "동시성은 가능하다") is True


# ── 5. 부정어/반의어 페어 각각 ──────────────────────────────────────────

@pytest.mark.parametrize("a,b", [
    ("이 방법은 가능하다", "이 방법은 불가능하다"),
    ("이 방법은 가능", "이 방법은 불가"),
    ("해당 필드는 있다", "해당 필드는 없다"),
    ("배포는 성공", "배포는 실패"),
    ("이 설정은 안전", "이 설정은 위험"),
    ("this feature works", "this feature fails"),
    ("the api is supported", "the api is unsupported"),
    ("streaming is possible", "streaming is impossible"),
    ("caching can run here", "caching cannot run here"),
])
def test_antonym_pairs_each_detected(a, b):
    assert is_potential_contradiction(a, b) is True


@pytest.mark.parametrize("a,b", [
    ("이 방법은 가능하다", "이 방법은 유용하다"),   # 극 없음(반대 아님)
    ("배포는 성공", "테스트는 통과"),               # 극 하나뿐
    ("the api is supported", "the docs are updated"),
])
def test_no_opposite_signal_is_false(a, b):
    assert is_potential_contradiction(a, b) is False


# ── 6. 영어 단어 경계 — 부분문자열 오탐 방지 ─────────────────────────────

def test_ascii_pole_word_boundary_no_false_match():
    # "candidate" 안의 "can" 이 극으로 오매칭되면 안 된다.
    assert is_potential_contradiction("the candidate applies here",
                                      "the candidate cannot apply") is False
    # 실제 "can" vs "cannot" 는 잡힌다(같은 주어 candidate).
    assert is_potential_contradiction("the candidate can apply",
                                      "the candidate cannot apply") is True


# ── 7. 주제 겹침 임계 경계 ──────────────────────────────────────────────

def test_min_overlap_boundary():
    # 제목 토큰은 서로 다르게(주제하나 vs 주제둘) → 겹침은 tags 로만 = {alpha, beta} = 2.
    page = _page("pc", title="주제하나", tags=["alpha", "beta"],
                 body="동시성은 불가능하다")
    src = _source("raw/pc.md", title="주제둘", tags=["alpha", "beta"],
                  text="동시성은 가능하다")
    assert len(detect_contradiction_candidates(src, [page], min_overlap=2)) == 1
    # 같은 입력, min_overlap=3 → 겹침 부족(2 < 3) → 후보 0.
    assert detect_contradiction_candidates(src, [page], min_overlap=3) == []


def test_overlap_below_threshold_excluded():
    # 겹침 1개(alpha 만) < 2 → 제외 (제목 토큰 disjoint).
    page = _page("pc", title="주제하나", tags=["alpha"],
                 body="동시성은 불가능하다")
    src = _source("raw/pc.md", title="주제둘", tags=["alpha", "beta", "gamma"],
                  text="동시성은 가능하다")
    # 교집합 = {alpha} → len 1 < 2
    assert detect_contradiction_candidates(src, [page]) == []


# ── 8. 빈 입력 / 방어 ───────────────────────────────────────────────────

def test_empty_inputs():
    assert detect_contradiction_candidates(
        _source("raw/x.md", title="x", tags=[], text=""), []) == []
    assert is_potential_contradiction("", "") is False
    assert is_potential_contradiction("가능", "") is False
    assert is_potential_contradiction(None, "가능") is False  # type: ignore[arg-type]


def test_empty_body_no_crash():
    page = _page("p", title="프롬프트 캐싱", tags=["llm", "caching"], body="")
    src = _source("raw/x.md", title="프롬프트 캐싱", tags=["llm", "caching"],
                  text="가능하다")
    assert detect_contradiction_candidates(src, [page]) == []


# ── 9. 다중 페이지 정렬 · 결정성 ─────────────────────────────────────────

def test_multiple_pages_sorted_and_only_contradicting():
    p_hit = _page("zzz-caching", title="프롬프트 캐싱", tags=["llm", "caching"],
                  body="동시 사용 불가능")
    p_related_ok = _page("aaa-caching", title="캐싱 개요", tags=["llm", "caching"],
                         body="캐싱은 비용을 줄인다")  # 겹침 있으나 상반 신호 없음
    src = _source("raw/c.md", title="캐싱 업데이트", tags=["llm", "caching"],
                  text="이제 동시 사용 가능")
    out = detect_contradiction_candidates(src, [p_hit, p_related_ok])
    assert [c.existing_slug for c in out] == ["zzz-caching"]  # 상반 신호 있는 것만


def test_deterministic_repeated_calls():
    page = _page("pc", title="프롬프트 캐싱", tags=["llm", "caching"],
                 body="동시 사용은 불가능하다")
    src = _source("raw/pc.md", title="프롬프트 캐싱", tags=["llm", "caching"],
                  text="동시 사용은 가능하다")
    first = detect_contradiction_candidates(src, [page])
    second = detect_contradiction_candidates(src, [page])
    assert first == second  # frozen dataclass 값 동일 → 재호출 동일


# ── 10. frontmatter 상수 · 사전 형태 ────────────────────────────────────

def test_frontmatter_field_constants():
    assert reconcile.SUPERSEDED_CLAIMS_FIELD == "superseded_claims"
    assert reconcile.LAST_RECONCILED_FIELD == "last_reconciled"


def test_antonym_pairs_are_pairs():
    assert all(len(p) == 2 for p in reconcile.ANTONYM_PAIRS)
    assert ("가능", "불가능") in reconcile.ANTONYM_PAIRS


def test_candidate_is_frozen():
    c = ContradictionCandidate("s", "r", ("a",), "x↔y", "low", "e", "n")
    with pytest.raises((AttributeError, Exception)):
        c.existing_slug = "other"  # type: ignore[misc]
