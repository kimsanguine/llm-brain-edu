"""lib/gates.py Promotion Gates G-1~G-4 판정 테스트 — v0.3.0 WS-2.

WHY (이 테스트들이 인코딩하는 *의도* — schema/curate.md 가 단일 출처):
  1. **G-1 경계값**: 본문 799/800 · 근거 1/2 · H2 2/3 · 반복 1/2 ·
     summary 39/40/200/201 · 유사도 0.74/0.75 — 임계 "이상/미만"이 문서와
     한 치도 어긋나면 안 된다.
  2. **유사도 ≥0.75 = duplicate_existing 이 아니라 G-2 강화 라우팅**
     (enriched + target_slug). G-2 미달일 때만 duplicate_existing.
  3. **G-4**: 반복 1회 + 잠재가치 → observing + 만료일(today+7).
     만료 판정은 "경과"(당일 미포함) + 재등장 없음일 때만 기각.
  4. **결정성**: 같은 입력 → 같은 Decision. 날짜는 today 주입(now() 금지).
  5. **curate 동일성**: _merge_token_set 은 curate._merge_token_set 과
     동일 동작 (Wave 3 에서 curate 가 gates 구현을 재사용해 중복 제거 예정).

전부 인메모리 데이터 — claude CLI·실 wiki 의존 없음.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import curate  # noqa: E402
from lib import gates  # noqa: E402
from lib.gates import (  # noqa: E402
    Candidate,
    Decision,
    ExistingPage,
    evaluate_observing_expiry,
    evaluate_promotion,
)

TODAY = date(2026, 7, 4)


def _body(n: int, h2: int = 3) -> str:
    """strip 후 정확히 n자·H2 h2개인 본문. '## X\\n' 5자 × h2 + 패딩."""
    heads = "".join(f"## {chr(65 + i)}\n" for i in range(h2))
    assert n >= len(heads)
    return heads + "x" * (n - len(heads))


def _fm(**overrides) -> dict:
    fm = {
        "title": "프롬프트 캐싱",
        "type": "concept",
        "tags": ["llm", "caching"],
        "created": "2026-07-01",
        "updated": "2026-07-04",
        "summary": "가" * 100,
    }
    fm.update(overrides)
    return fm


def _candidate(**overrides) -> Candidate:
    kwargs = dict(
        slug="prompt-caching",
        body=_body(1000),
        frontmatter=_fm(),
        recurrence=2,
        sources=["raw/til/2026-07-01.md", "raw/til/2026-07-03.md"],
    )
    kwargs.update(overrides)
    return Candidate(**kwargs)


def _tag_page(slug: str, tags: list[str], body: str = "") -> ExistingPage:
    """title 무토큰(공백) — tags 만으로 토큰 집합을 정밀 제어."""
    return ExistingPage(slug=slug, frontmatter={"title": " ", "tags": tags}, body=body)


def _tag_fm(tokens_n: int, **overrides) -> dict:
    """유사도 정밀 제어용 candidate frontmatter — 토큰 = {t0..t_{n-1}} 정확히 n개
    (title 't0' + tags t1..t_{n-1}; title 은 필수 필드라 비워둘 수 없음)."""
    return _fm(title="t0", tags=[f"t{i}" for i in range(1, tokens_n)], **overrides)


# ── G-1 전부 충족 → created ─────────────────────────────────────────────

def test_g1_all_pass_created():
    d = evaluate_promotion(_candidate(), [], today=TODAY)
    assert d.gate_status == "created"
    assert d.reject_reason is None
    assert d.target_slug is None
    assert d.observation_expires is None
    assert any("전부 충족" in r for r in d.reasons)


def test_deterministic_same_input_same_output():
    existing = [_tag_page("a-page", ["llm", "caching"], body=_body(900))]
    d1 = evaluate_promotion(_candidate(), existing, today="2026-07-04")
    d2 = evaluate_promotion(_candidate(), existing, today=TODAY)
    assert d1 == d2  # str/date today 동등 + 재호출 무변동


# ── 본문 799/800자 경계 ─────────────────────────────────────────────────

def test_body_799_rejected_insufficient_content():
    d = evaluate_promotion(_candidate(body=_body(799)), [], today=TODAY)
    assert d.gate_status == "rejected"
    assert d.reject_reason == "insufficient_content"
    assert any("본문 799자" in r and "미달" in r for r in d.reasons)


def test_body_800_created():
    d = evaluate_promotion(_candidate(body=_body(800)), [], today=TODAY)
    assert d.gate_status == "created"


# ── 근거 1/2건 경계 ─────────────────────────────────────────────────────

def test_sources_1_rejected():
    d = evaluate_promotion(_candidate(sources=["raw/a.md"]), [], today=TODAY)
    assert d.gate_status == "rejected"
    assert d.reject_reason == "insufficient_content"


def test_sources_2_created():
    d = evaluate_promotion(_candidate(sources=["raw/a.md", "raw/b.md"]), [], today=TODAY)
    assert d.gate_status == "created"


def test_sources_empty_strings_not_counted():
    d = evaluate_promotion(_candidate(sources=["raw/a.md", "  "]), [], today=TODAY)
    assert d.reject_reason == "insufficient_content"


# ── H2 2/3개 경계 ───────────────────────────────────────────────────────

def test_h2_2_rejected():
    d = evaluate_promotion(_candidate(body=_body(1000, h2=2)), [], today=TODAY)
    assert d.gate_status == "rejected"
    assert d.reject_reason == "insufficient_content"
    assert any("H2 2개" in r and "미달" in r for r in d.reasons)


def test_h2_3_created():
    d = evaluate_promotion(_candidate(body=_body(1000, h2=3)), [], today=TODAY)
    assert d.gate_status == "created"


def test_h3_not_counted_as_h2():
    body = _body(1000, h2=2) + "\n### sub\n#### deep"
    d = evaluate_promotion(_candidate(body=body), [], today=TODAY)
    assert d.reject_reason == "insufficient_content"


# ── summary 39/40/200/201자 경계 ────────────────────────────────────────

@pytest.mark.parametrize("n,status", [(39, "rejected"), (40, "created"),
                                      (200, "created"), (201, "rejected")])
def test_summary_boundaries(n, status):
    d = evaluate_promotion(
        _candidate(frontmatter=_fm(summary="가" * n)), [], today=TODAY)
    assert d.gate_status == status
    if status == "rejected":
        assert d.reject_reason == "frontmatter_invalid"


def test_summary_missing_rejected_frontmatter_invalid():
    fm = _fm()
    del fm["summary"]
    d = evaluate_promotion(_candidate(frontmatter=fm), [], today=TODAY)
    assert d.reject_reason == "frontmatter_invalid"


# ── frontmatter 필수 필드 1개 결손 ──────────────────────────────────────

@pytest.mark.parametrize("missing", ["title", "type", "tags", "created", "updated"])
def test_frontmatter_one_missing_field_rejected(missing):
    fm = _fm()
    del fm[missing]
    d = evaluate_promotion(_candidate(frontmatter=fm), [], today=TODAY)
    assert d.gate_status == "rejected"
    assert d.reject_reason == "frontmatter_invalid"
    assert any(missing in r and "결손" in r for r in d.reasons)


def test_frontmatter_empty_value_counts_as_missing():
    d = evaluate_promotion(_candidate(frontmatter=_fm(tags=[])), [], today=TODAY)
    assert d.reject_reason == "frontmatter_invalid"


# ── 반복 1/2회 경계 + G-4 observing ─────────────────────────────────────

def test_recurrence_2_created():
    d = evaluate_promotion(_candidate(recurrence=2), [], today=TODAY)
    assert d.gate_status == "created"


def test_recurrence_1_no_potential_rejected_insufficient_recurrence():
    d = evaluate_promotion(_candidate(recurrence=1), [], today=TODAY)
    assert d.gate_status == "rejected"
    assert d.reject_reason == "insufficient_recurrence"


def test_recurrence_1_with_potential_observing_expires_today_plus_7():
    d = evaluate_promotion(_candidate(recurrence=1, potential_value=True),
                           [], today=TODAY)
    assert d.gate_status == "observing"
    assert d.observation_expires == "2026-07-11"  # today+7, YYYY-MM-DD 문자열
    assert d.reject_reason is None


def test_recurrence_0_with_potential_still_rejected():
    # schema: G-4 는 "반복 1회" 전용 — 0회는 잠재가치가 있어도 기각
    d = evaluate_promotion(_candidate(recurrence=0, potential_value=True),
                           [], today=TODAY)
    assert d.reject_reason == "insufficient_recurrence"


def test_recurrence_precedes_content_classification():
    # 반복 1회 + 본문 미달 동시 → schema G-3 표 순서상 insufficient_recurrence
    d = evaluate_promotion(_candidate(recurrence=1, body=_body(100)), [], today=TODAY)
    assert d.reject_reason == "insufficient_recurrence"


def test_content_precedes_frontmatter_classification():
    fm = _fm()
    del fm["title"]
    d = evaluate_promotion(_candidate(body=_body(100), frontmatter=fm), [], today=TODAY)
    assert d.reject_reason == "insufficient_content"


# ── 유사도 0.74/0.75 경계 ───────────────────────────────────────────────

def _sim_setup(shared: int, total: int, target_body: str = ""):
    """cand 토큰 total개 ⊇ 기존 페이지 토큰 shared개 → J = shared/total."""
    cand = _candidate(frontmatter=_tag_fm(total))
    page = _tag_page("existing-node", [f"t{i}" for i in range(shared)], body=target_body)
    return cand, [page]


def test_similarity_0_74_created():
    cand, pages = _sim_setup(37, 50)  # 37/50 = 0.74 < 0.75
    d = evaluate_promotion(cand, pages, today=TODAY)
    assert d.gate_status == "created"
    assert any("0.7400" in r for r in d.reasons)


def test_similarity_0_75_routes_to_enrichment_not_duplicate():
    cand, pages = _sim_setup(36, 48, target_body=_body(1000))  # 36/48 = 0.75
    cand = Candidate(**{**cand.__dict__, "new_examples": 1})
    d = evaluate_promotion(cand, pages, today=TODAY)
    assert d.gate_status == "enriched"
    assert d.target_slug == "existing-node"
    assert d.reject_reason is None


def test_similarity_tie_breaks_by_slug_ascending():
    shared_tags = ["t0", "t1", "t2"]
    cand = _candidate(frontmatter=_tag_fm(4), new_examples=1)  # 토큰 t0..t3
    pages = [_tag_page("b-node", shared_tags, body=_body(1000)),
             _tag_page("a-node", shared_tags, body=_body(1000))]  # 둘 다 3/4 = 0.75
    d = evaluate_promotion(cand, pages, today=TODAY)
    assert d.gate_status == "enriched"
    assert d.target_slug == "a-node"


# ── G-2 기존 강화: 새 각도 199/200자 · 사례 · 강화 후 본문 ──────────────

def test_g2_new_angle_199_rejected_duplicate_existing():
    cand, pages = _sim_setup(3, 4, target_body=_body(1000))  # 0.75
    cand = Candidate(**{**cand.__dict__, "new_examples": 0, "new_angle": "각" * 199})
    d = evaluate_promotion(cand, pages, today=TODAY)
    assert d.gate_status == "rejected"
    assert d.reject_reason == "duplicate_existing"
    assert d.target_slug is None


def test_g2_new_angle_200_enriched():
    cand, pages = _sim_setup(3, 4, target_body=_body(1000))
    cand = Candidate(**{**cand.__dict__, "new_examples": 0, "new_angle": "각" * 200})
    d = evaluate_promotion(cand, pages, today=TODAY)
    assert d.gate_status == "enriched"
    assert d.target_slug == "existing-node"


def test_g2_one_example_suffices():
    cand, pages = _sim_setup(3, 4, target_body=_body(1000))
    cand = Candidate(**{**cand.__dict__, "new_examples": 1, "new_angle": ""})
    d = evaluate_promotion(cand, pages, today=TODAY)
    assert d.gate_status == "enriched"


def test_g2_post_enrichment_body_below_800_rejected():
    # 기존 300자 + 추가분 400자 = 700 < 800 → 강화 가치 있어도 유지 기준 미달
    cand, pages = _sim_setup(3, 4, target_body=_body(300, h2=3))
    cand = Candidate(**{**cand.__dict__, "body": _body(400), "new_examples": 1})
    d = evaluate_promotion(cand, pages, today=TODAY)
    assert d.reject_reason == "duplicate_existing"


def test_g2_post_enrichment_body_exactly_800_enriched():
    cand, pages = _sim_setup(3, 4, target_body=_body(400, h2=3))
    cand = Candidate(**{**cand.__dict__, "body": _body(400), "new_examples": 1})
    d = evaluate_promotion(cand, pages, today=TODAY)
    assert d.gate_status == "enriched"


# ── low_value (형식 기준과 무관, 최우선) ────────────────────────────────

def test_low_value_rejected_even_if_all_criteria_pass():
    d = evaluate_promotion(_candidate(low_value=True), [], today=TODAY)
    assert d.gate_status == "rejected"
    assert d.reject_reason == "low_value"


def test_low_value_precedes_duplicate_routing():
    cand, pages = _sim_setup(3, 4, target_body=_body(1000))
    cand = Candidate(**{**cand.__dict__, "low_value": True, "new_examples": 1})
    d = evaluate_promotion(cand, pages, today=TODAY)
    assert d.reject_reason == "low_value"


# ── G-4 만료: evaluate_observing_expiry ────────────────────────────────

def _observing_page(expires: str = "2026-07-11", recurrence: int = 1,
                    gate_status: str = "observing") -> ExistingPage:
    return ExistingPage(
        slug="obs-node",
        frontmatter={"title": "관찰 노드", "gate_status": gate_status,
                     "observation_expires": expires, "recurrence": recurrence},
    )


def test_expiry_before_date_none():
    assert evaluate_observing_expiry(_observing_page(), date(2026, 7, 10)) is None


def test_expiry_on_date_none():
    # "경과" = 당일 미포함 — 만료 당일은 아직 유예 유지
    assert evaluate_observing_expiry(_observing_page(), date(2026, 7, 11)) is None


def test_expiry_after_date_rejected_insufficient_recurrence():
    d = evaluate_observing_expiry(_observing_page(), date(2026, 7, 12))
    assert isinstance(d, Decision)
    assert d.gate_status == "rejected"
    assert d.reject_reason == "insufficient_recurrence"


def test_expiry_reappeared_recurrence_2_none():
    # 재등장(반복 ≥2) → 만료 기각 아님 (G-1 재판정은 evaluate_promotion 별도)
    assert evaluate_observing_expiry(
        _observing_page(recurrence=2), date(2026, 7, 20)) is None


def test_expiry_non_observing_page_none():
    assert evaluate_observing_expiry(
        _observing_page(gate_status="created"), date(2026, 7, 20)) is None


def test_expiry_missing_expires_fails_loud():
    page = ExistingPage(slug="broken", frontmatter={"gate_status": "observing"})
    with pytest.raises(ValueError):
        evaluate_observing_expiry(page, date(2026, 7, 20))


def test_expiry_accepts_str_today():
    d = evaluate_observing_expiry(_observing_page(), "2026-07-12")
    assert d is not None and d.reject_reason == "insufficient_recurrence"


# ── curate._merge_token_set 동일성 (Wave 3 대체 예정 계약) ──────────────

@pytest.mark.parametrize("fm", [
    {"title": "Prompt Caching 전략", "tags": ["LLM", "  caching  ", "비용"]},
    {"title": "한국어-제목_underscore도", "tags": []},
    {"title": None, "tags": ["a", 3, "", "B"]},
    {"tags": "not-a-list"},
    "not-a-dict",
    {},
])
def test_merge_token_set_identical_to_curate(fm):
    assert gates._merge_token_set(fm) == curate._merge_token_set(fm)


def test_thresholds_match_schema_curate_md():
    # schema/curate.md G-1 표와 상수 1:1 (문서=단일 출처의 드리프트 카나리)
    assert gates.MIN_RECURRENCE == 2
    assert gates.MIN_BODY_CHARS == 800
    assert gates.MIN_H2_SECTIONS == 3
    assert gates.MIN_SOURCES == 2
    assert (gates.SUMMARY_MIN_CHARS, gates.SUMMARY_MAX_CHARS) == (40, 200)
    assert gates.SIMILARITY_ROUTE_THRESHOLD == 0.75
    assert gates.MIN_NEW_ANGLE_CHARS == 200
    assert gates.OBSERVATION_DAYS == 7
