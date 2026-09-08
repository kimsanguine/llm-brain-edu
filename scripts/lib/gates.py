"""gates — Promotion Gates G-1~G-4 결정적 판정 코어 (v0.3.0 WS-2).

판정 기준의 **단일 출처는 `schema/curate.md` "Promotion Gates (G-1~G-4)" 절**이다.
이 모듈은 그 문서의 임계값·라우팅 규칙을 코드로 옮긴 순수 판정기다 — LLM 호출 0,
파일 I/O 0. 판정에 필요한 모든 값은 인자로 주입받는다(같은 입력 → 같은 출력).
날짜도 `today` 인자로 주입한다 — `datetime.now()` 내부 호출 금지(테스트 결정성).

LLM 실행 경계 (SPEC §A): "잠재가치(G-4)"·"low_value(G-3)" 같은 가치 *판단*은
결정적으로 계산할 수 없으므로 컴파일러(Claude)/사람이 내린 판단을 Candidate 의
불리언 필드로 **입력**받는다(Rule 5 — 판단은 사람/모델, 판정 규칙은 코드).
이 모듈 자체는 입력이 같으면 항상 같은 Decision 을 낸다.

Candidate 계약 (판정 입력 — Wave 3 에서 curate.py 가 조립):
    slug            생성 예정 페이지 slug (소문자-하이픈).
    body            본문 마크다운 (frontmatter 제외). 유사도 ≥0.75 로 G-2 강화
                    라우팅될 때는 이 본문이 기존 페이지에 append 될 **추가분**으로
                    본다 (강화 후 본문 = 기존 body + candidate body).
    frontmatter     생성 예정 frontmatter dict. `summary`(40~200자) 포함.
                    필수 필드는 REQUIRED_FRONTMATTER_FIELDS 참조 — `sources` 는
                    frontmatter 가 아니라 Candidate.sources 로 판정한다(승격 시
                    호출측이 frontmatter 에 기록하는 값과 동일 원천).
    recurrence      7일 윈도 내 관측된 반복 횟수 (N).
    sources         근거 raw/ 경로 목록. 비어있지 않은 문자열만 건수로 센다.
    potential_value G-4 잠재가치 판단 (주입). 반복 1회 + True → observing.
    low_value       G-3 low_value 판단 (주입). True → 형식 기준과 무관하게 기각.
    new_examples    G-2 전용: 기존 페이지에 추가되는 사례 건수.
    new_angle       G-2 전용: 새 각도 서술 텍스트 (≥200자 기준).

판정 우선순위 (결정성 — 복수 사유 동시 발생 시 하나로 분류):
    1. low_value 플래그          → rejected(low_value)  — "형식 기준과 무관"이므로 최우선
    2. 기존 최대 유사도 ≥0.75    → G-2 판정: 통과 → enriched(target_slug) /
                                   미달 → rejected(duplicate_existing)
    3. 반복 <2회                 → 반복 1회+잠재가치 → observing(만료일 today+7) /
                                   그 외 → rejected(insufficient_recurrence)
    4. 본문·H2·근거 미달         → rejected(insufficient_content)
    5. frontmatter·summary 결손  → rejected(frontmatter_invalid)
    6. 전부 통과                 → created
    (3~5 순서는 schema/curate.md G-3 표의 사유 나열 순서를 따른다.)

관측 만료 (G-4): `evaluate_observing_expiry(page, today)` — observing 페이지가
`observation_expires` **경과 후**(당일 미포함)에도 재등장(반복 ≥2) 없으면
rejected(insufficient_recurrence). 만료 관리는 gates 가 자체 수행한다
(lifecycle TTL decay 와 분리, SPEC §D).

유사도: `_merge_token_set`(소문자 title `\\w` 토큰 ∪ 소문자 tags) 집합의 Jaccard.
`curate._merge_token_set` 과 **동일 로직·동일 함수명** — lib→curate import 는
Wave 3 에서 순환을 만들므로 여기 재구현했고, **curate._merge_token_set 대체 예정**
(Wave 3 에서 curate.py 가 `from lib.gates import _merge_token_set` 으로 재사용해
중복 제거). curate 의 merge-review 는 카테고리 경계를 넘지 않는다 — 호출측이
existing_pages 를 같은 카테고리로 사전 필터해 넘기는 것을 권장한다.

길이 정의 (경계값 결정성): 본문/새 각도/summary 문자 수 = `len(text.strip())`.
H2 개수 = `^## ` (정확히 # 2개 + 공백) 로 시작하는 줄 수.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Sequence

# ── 임계값 (schema/curate.md G-1~G-4 표와 1:1) ──────────────────────────
MIN_RECURRENCE = 2            # 반복 ≥2회 (7일 내)
MIN_BODY_CHARS = 800          # 본문 ≥800자
MIN_H2_SECTIONS = 3           # H2 섹션 ≥3개
MIN_SOURCES = 2               # 근거 ≥2건
SUMMARY_MIN_CHARS = 40        # summary 40~200자
SUMMARY_MAX_CHARS = 200
SIMILARITY_ROUTE_THRESHOLD = 0.75  # 유사도 ≥0.75 → G-2 강화 라우팅
MIN_NEW_EXAMPLES = 1          # G-2: 추가 사례 ≥1건
MIN_NEW_ANGLE_CHARS = 200     # G-2: OR 새 각도 ≥200자
OBSERVATION_DAYS = 7          # G-4: 7일 유예

# wiki frontmatter 기본 계약(CLAUDE.md) 중 컴파일러가 채워야 하는 의미 필드.
# distill_level·access_count 는 시스템 기본값(0)이라 결손을 기각 사유로 보지 않고,
# sources 는 Candidate.sources 로, summary 는 별도 길이 기준으로 판정한다.
REQUIRED_FRONTMATTER_FIELDS = ("title", "type", "tags", "created", "updated")

GATE_STATUSES = ("created", "enriched", "observing", "rejected")
REJECT_REASONS = (
    "low_value",
    "insufficient_recurrence",
    "insufficient_content",
    "duplicate_existing",
    "frontmatter_invalid",
)

_MERGE_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_H2_RE = re.compile(r"^## ", re.MULTILINE)


# ── 데이터 계약 ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Candidate:
    """승격 판정 입력. 필드 의미는 모듈 docstring "Candidate 계약" 참조."""
    slug: str
    body: str
    frontmatter: dict
    recurrence: int
    sources: Sequence[str]
    potential_value: bool = False
    low_value: bool = False
    new_examples: int = 0
    new_angle: str = ""


@dataclass(frozen=True)
class ExistingPage:
    """기존 wiki 페이지의 판정용 투영 (I/O 는 호출측이 수행해 주입).

    frontmatter: title·tags 가 유사도 토큰이 된다. observing 페이지는
    gate_status·observation_expires·recurrence 를 포함해야 만료 판정 가능.
    body: G-2 "강화 후 본문 ≥800자" 판정에 쓰인다.
    """
    slug: str
    frontmatter: dict
    body: str = ""


@dataclass(frozen=True)
class Decision:
    """게이트 판정 결과.

    gate_status: created | enriched | observing | rejected
    reasons: 기준별 통과/미달 상세 (전 기준 평가 결과를 담는다 — 감사 로그용)
    reject_reason: gate_status == rejected 일 때만 (REJECT_REASONS 중 하나)
    target_slug: gate_status == enriched 일 때만 — 강화 대상 기존 페이지
    observation_expires: gate_status == observing 일 때만 — YYYY-MM-DD 문자열
    """
    gate_status: str
    reasons: tuple[str, ...] = field(default_factory=tuple)
    reject_reason: str | None = None
    target_slug: str | None = None
    observation_expires: str | None = None


# ── 유사도 (curate._merge_token_set 대체 예정 — Wave 3 에서 curate 가 재사용) ──

def _merge_token_set(fm) -> set[str]:
    """페이지 비교 단위 = (소문자 제목 토큰 ∪ 소문자 태그) 집합. \\w 토큰화로 한국어 포함.

    curate._merge_token_set 과 동일 로직·동일 함수명 — **curate._merge_token_set
    대체 예정** (Wave 3 에서 curate.py 가 이 구현을 import 해 중복 제거).
    """
    tokens: set[str] = set()
    if not isinstance(fm, dict):
        return tokens
    title = fm.get("title")
    if isinstance(title, str):
        tokens |= {t.lower() for t in _MERGE_TOKEN_RE.findall(title)}
    tags = fm.get("tags")
    if isinstance(tags, list):
        for t in tags:
            if isinstance(t, str) and t.strip():
                tokens.add(t.strip().lower())
    return tokens


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard 유사도. 합집합 공집합(둘 다 토큰 없음)은 유사도 정의 불가 → 0.0
    (curate.find_merge_candidates 의 '0으로 본다' 처리와 동일)."""
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _best_match(candidate_fm: dict,
                existing_pages: Sequence[ExistingPage]) -> tuple[float, ExistingPage | None]:
    """기존 페이지 중 최대 유사도 매치. 동점은 slug 오름차순 첫 항목(결정성)."""
    cand_tokens = _merge_token_set(candidate_fm)
    best_sim = 0.0
    best_page: ExistingPage | None = None
    for page in sorted(existing_pages, key=lambda p: p.slug):
        sim = _jaccard(cand_tokens, _merge_token_set(page.frontmatter))
        if sim > best_sim:
            best_sim, best_page = sim, page
    return best_sim, best_page


# ── 내부 헬퍼 (전부 순수) ───────────────────────────────────────────────

def _chars(text) -> int:
    """길이 판정 문자 수 = strip 후 len. 비문자열은 0."""
    if not isinstance(text, str):
        return 0
    return len(text.strip())


def _count_h2(body: str) -> int:
    return len(_H2_RE.findall(body)) if isinstance(body, str) else 0


def _count_sources(sources) -> int:
    if not isinstance(sources, (list, tuple)):
        return 0
    return sum(1 for s in sources if isinstance(s, str) and s.strip())


def _parse_date(value, *, label: str) -> date:
    """date/datetime/'YYYY-MM-DD' 문자열 → date. 그 외는 fail-loud(Rule 8)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError(f"{label}: 날짜 형식 오류 {value!r} (YYYY-MM-DD 필요)") from exc
    raise ValueError(f"{label}: date 또는 'YYYY-MM-DD' 문자열 필요, got {type(value).__name__}")


def _missing_frontmatter_fields(fm: dict) -> list[str]:
    """필수 필드 결손 목록. 값이 None/공백 문자열/빈 리스트면 결손으로 본다."""
    missing = []
    for key in REQUIRED_FRONTMATTER_FIELDS:
        val = fm.get(key) if isinstance(fm, dict) else None
        if val is None:
            missing.append(key)
        elif isinstance(val, str) and not val.strip():
            missing.append(key)
        elif isinstance(val, (list, tuple)) and not val:
            missing.append(key)
    return missing


# ── 공개 API ────────────────────────────────────────────────────────────

def evaluate_promotion(candidate: Candidate,
                       existing_pages: Sequence[ExistingPage],
                       *,
                       today) -> Decision:
    """Promotion Gates G-1~G-4 판정 (schema/curate.md 단일 출처).

    today: date 또는 'YYYY-MM-DD' — observing 만료일(today+7) 계산에만 사용.
    반환 Decision 의 우선순위·필드 의미는 모듈 docstring 참조.
    """
    today_d = _parse_date(today, label="today")
    reasons: list[str] = []

    # 전 기준 선평가 (분류는 아래 우선순위, reasons 는 전체 감사 로그)
    similarity, target = _best_match(candidate.frontmatter, existing_pages)
    body_chars = _chars(candidate.body)
    h2_count = _count_h2(candidate.body)
    source_count = _count_sources(candidate.sources)
    missing_fm = _missing_frontmatter_fields(candidate.frontmatter)
    summary_chars = _chars(candidate.frontmatter.get("summary")
                           if isinstance(candidate.frontmatter, dict) else None)
    summary_ok = SUMMARY_MIN_CHARS <= summary_chars <= SUMMARY_MAX_CHARS

    recurrence_ok = candidate.recurrence >= MIN_RECURRENCE
    body_ok = body_chars >= MIN_BODY_CHARS
    h2_ok = h2_count >= MIN_H2_SECTIONS
    sources_ok = source_count >= MIN_SOURCES
    fm_ok = not missing_fm
    sim_ok = similarity < SIMILARITY_ROUTE_THRESHOLD

    def _mark(ok: bool) -> str:
        return "통과" if ok else "미달"

    reasons.append(f"반복 {candidate.recurrence}회/기준 ≥{MIN_RECURRENCE}회(7일) — {_mark(recurrence_ok)}")
    reasons.append(f"본문 {body_chars}자/기준 ≥{MIN_BODY_CHARS}자 — {_mark(body_ok)}")
    reasons.append(f"H2 {h2_count}개/기준 ≥{MIN_H2_SECTIONS}개 — {_mark(h2_ok)}")
    reasons.append(f"근거 {source_count}건/기준 ≥{MIN_SOURCES}건 — {_mark(sources_ok)}")
    reasons.append("frontmatter 필수 필드 완비 — 통과" if fm_ok
                   else f"frontmatter 결손: {', '.join(missing_fm)} — 미달")
    reasons.append(f"summary {summary_chars}자/기준 {SUMMARY_MIN_CHARS}~{SUMMARY_MAX_CHARS}자 — {_mark(summary_ok)}")
    reasons.append(
        f"기존 최대 유사도 {similarity:.4f}/기준 <{SIMILARITY_ROUTE_THRESHOLD}"
        + (f" (최근접: {target.slug})" if target else "")
        + f" — {_mark(sim_ok)}"
    )

    # 1. low_value — 정보 가치 자체가 낮음 (형식 기준과 무관, 최우선)
    if candidate.low_value:
        reasons.append("low_value 판단 주입 — 정보 가치 낮음 (형식 기준과 무관)")
        return Decision("rejected", tuple(reasons), reject_reason="low_value")

    # 2. 유사도 ≥0.75 → duplicate_existing 이 아니라 G-2 강화 라우팅
    if not sim_ok:
        assert target is not None  # similarity > 0 이므로 매치 존재
        angle_chars = _chars(candidate.new_angle)
        g2_content_ok = (candidate.new_examples >= MIN_NEW_EXAMPLES
                         or angle_chars >= MIN_NEW_ANGLE_CHARS)
        enriched_chars = _chars(target.body) + body_chars
        g2_body_ok = enriched_chars >= MIN_BODY_CHARS
        reasons.append(
            f"G-2 추가 사례 {candidate.new_examples}건(기준 ≥{MIN_NEW_EXAMPLES}) OR "
            f"새 각도 {angle_chars}자(기준 ≥{MIN_NEW_ANGLE_CHARS}) — {_mark(g2_content_ok)}"
        )
        reasons.append(f"G-2 강화 후 본문 {enriched_chars}자/기준 ≥{MIN_BODY_CHARS}자 — {_mark(g2_body_ok)}")
        if g2_content_ok and g2_body_ok:
            reasons.append(f"유사도 ≥{SIMILARITY_ROUTE_THRESHOLD} — 기존 [[{target.slug}]] 강화(G-2) 라우팅")
            return Decision("enriched", tuple(reasons), target_slug=target.slug)
        reasons.append(f"유사도 ≥{SIMILARITY_ROUTE_THRESHOLD}인데 강화(G-2) 가치도 없음 — 기각")
        return Decision("rejected", tuple(reasons), reject_reason="duplicate_existing")

    # 3. 반복 미달 → G-4 유예 또는 기각
    if not recurrence_ok:
        if candidate.recurrence == 1 and candidate.potential_value:
            expires = (today_d + timedelta(days=OBSERVATION_DAYS)).isoformat()
            reasons.append(f"반복 1회 + 잠재가치 — observing {OBSERVATION_DAYS}일 유예 (만료 {expires})")
            return Decision("observing", tuple(reasons), observation_expires=expires)
        reasons.append("반복 기준 미달 + 유예 가치 없음 — 기각")
        return Decision("rejected", tuple(reasons), reject_reason="insufficient_recurrence")

    # 4. 본문·H2·근거 미달
    if not (body_ok and h2_ok and sources_ok):
        return Decision("rejected", tuple(reasons), reject_reason="insufficient_content")

    # 5. frontmatter·summary 결손
    if not (fm_ok and summary_ok):
        return Decision("rejected", tuple(reasons), reject_reason="frontmatter_invalid")

    # 6. G-1 전부 충족
    reasons.append("G-1 7개 기준 전부 충족 — 신규 생성")
    return Decision("created", tuple(reasons))


def evaluate_observing_expiry(page: ExistingPage, today) -> Decision | None:
    """G-4 만료 판정 — observing 페이지 전용, 그 외/미만료/재등장은 None.

    schema/curate.md G-4: 재등장(반복 ≥2) 없이 `observation_expires` **경과**
    (당일 미포함, today > expires) → G-3 `insufficient_recurrence` 기각.
    재등장(반복 ≥2)한 페이지는 만료 기각 대상이 아니다 — G-1 재판정은
    `evaluate_promotion` 으로 별도 수행한다(이 함수는 None 반환).

    observing 인데 observation_expires 가 없거나 형식 오류면 ValueError
    (조용한 미만료 처리 금지 — Rule 8 fail-loud).
    """
    fm = page.frontmatter if isinstance(page.frontmatter, dict) else {}
    if fm.get("gate_status") != "observing":
        return None

    today_d = _parse_date(today, label="today")
    expires_raw = fm.get("observation_expires")
    if expires_raw is None:
        raise ValueError(f"observing 페이지 {page.slug!r}에 observation_expires 없음")
    expires_d = _parse_date(expires_raw, label=f"{page.slug}.observation_expires")

    recurrence = fm.get("recurrence")
    if isinstance(recurrence, bool) or not isinstance(recurrence, int):
        recurrence = 1  # observing 진입 조건이 반복 1회 — 결손 시 보수적 기본값
    if recurrence >= MIN_RECURRENCE:
        return None  # 재등장 — 만료 기각 아님, G-1 재판정 대상

    if today_d <= expires_d:
        return None  # 만료 전/당일 — 유예 유지

    return Decision(
        "rejected",
        (
            f"observing 만료: {expires_d.isoformat()} 경과 (today {today_d.isoformat()})",
            f"재등장 없음: 반복 {recurrence}회 < {MIN_RECURRENCE}회",
        ),
        reject_reason="insufficient_recurrence",
    )
