"""reconcile — 모순 후보 탐지 결정적 코어 (v0.3.1 WS-5).

이 모듈은 **모순 *후보* 탐지(결정적)만** 한다 — "이 신규 근거가 기존 페이지의 어떤
주장과 충돌 *가능성*이 있다"를 보수적으로 표면화하는 순수 함수다. 실제 화해 문장
작성(`## 반론/갱신` 서술·`superseded_claims` 판단)은 **LLM 컴파일러의 몫**이며
`commands/curate.md` Step / `schema/curate.md` "Reconciliation Rules" 가 단일 출처다
(SPEC §A LLM 실행 경계: 결정적 후보 탐지 → contradiction_queue.md / 화해 서술 → 커맨드 Step).

핵심 원칙 — **정밀도 우선(precision-first), 오탐 최소**:
    WS-5 Q3 "반론 섹션 남발 위험" 때문에 임계를 보수적으로 잡는다. 확신이 없으면
    후보에서 제외한다. 재현율(빠짐 없이 잡기)보다 정밀도(잘못 잡지 않기)를 택한다.
    두 페이지가 주제상 무관하면(토큰 교집합 < min_overlap) 반의어 신호가 있어도
    후보가 아니다 — 무관한 페이지 오탐 방지.

계약 (순수·결정적·보수적):
    - LLM 호출 0, 파일 I/O 0, random/now() 판정 0. 같은 입력 → 항상 같은 출력.
    - 어느 주장이 "옳은지"는 판단하지 않는다 (그것은 raw/ 근거를 읽는 LLM/사람의 몫).
      이 모듈은 "상반 신호가 있으니 사람이/LLM이 화해를 검토하라"만 표면화한다.
    - 반의어/부정 사전(ANTONYM_PAIRS)은 모듈 상수 — 확장 가능. 한국어+영어 기본 페어.

Wave 6 배선 계약 (curate → contradiction_queue.md):
    `detect_contradiction_candidates(...)` 가 반환한 `list[ContradictionCandidate]` 를
    curate 가 `wiki/contradiction_queue.md` 로 직렬화한다 (distill_queue.md·reweave_queue.md
    와 동일 체크박스 패턴). 각 후보는 큐 1줄이 된다, 예:

        - [ ] [[{existing_slug}]] ↔ {new_source_ref} — 신호 {signal} · 겹침 {overlap_terms}
              기존 주장: "{existing_claim}"  /  신규 근거: "{new_claim}"

    이후 `commands/curate.md` 의 LLM Step 이 이 큐를 소비해 해당 페이지에
    `## 반론/갱신 (YYYY-MM-DD)` 3요소(기존 주장·반례 근거·현재 판단)를 append 하고,
    frontmatter `superseded_claims`·`last_reconciled` 를 갱신한다 (schema/curate.md).
    후보의 `existing_claim`·`new_claim` 발췌는 LLM Step 이 3요소 중 앞 둘("기존 주장"·
    "반례 근거")을 채우는 재료다 — 자동 편집은 하지 않는다(Rule 9: 화해는 사람/LLM 판단).

입력 형태:
    new_source     : NewSource — 신규 근거(raw/ 원천). source_ref·text·frontmatter.
    existing_pages : Sequence[gates.ExistingPage] — 기존 wiki 페이지 투영
                     (slug·frontmatter·body). I/O 는 호출측이 수행해 주입.
                     gates.ExistingPage 를 재사용해 curate 가 이미 조립하는 투영을 그대로 넘긴다.

주제 겹침 토큰: `lib.gates._merge_token_set`(소문자 title \\w 토큰 ∪ 소문자 tags) 재사용 —
유사도 토큰 규칙의 단일 출처를 gates 로 수렴(중복 정의 금지).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from lib.gates import _merge_token_set  # 주제 겹침 토큰 — 단일 출처(gates) 재사용

# ── frontmatter 신규 필드 상수 (schema/curate.md "Reconciliation" 절 일치) ──
# 옛 주장은 본문에 남기고 여기에 "대체됨" 표시만 한다(삭제 금지). last_reconciled 는
# 화해 서술을 append 한 날짜. 두 필드 다 optional — 화해가 일어난 페이지에만 존재.
SUPERSEDED_CLAIMS_FIELD = "superseded_claims"
LAST_RECONCILED_FIELD = "last_reconciled"

# ── 탐지 임계 (보수적 기본값) ────────────────────────────────────────────
# 두 페이지가 "같은 주제"라고 볼 최소 frontmatter 토큰 교집합 수. 미만이면 무관 →
# 반의어 신호가 있어도 후보 제외(오탐 방지). 경계는 "이상"(>=): 정확히 이 값이면 포함.
DEFAULT_MIN_OVERLAP = 2

# 발췌(claim) 최대 길이 — 큐 가독성용 절단(경계 결정적).
_CLAIM_MAX_CHARS = 200

# ── 반의어/부정 사전 (모듈 상수 — 확장 가능) ─────────────────────────────
# 각 항목은 (긍정 극, 부정/반대 극). "부정"은 종종 긍정을 부분문자열로 포함하므로
# (예: "불가능" ⊃ "가능") 매칭 시 긴 극을 먼저 소비해 오매칭을 막는다(_extract_poles).
# 한국어(부분문자열 매칭 — 어절 경계 없음) + 영어(단어 경계 \\b 매칭 — 부분문자열 오탐 방지).
# 보수적으로 단일 음절·과빈출 극(예: "참"/"거짓")은 제외했다(정밀도 우선).
ANTONYM_PAIRS: tuple[tuple[str, str], ...] = (
    # 한국어
    ("가능", "불가능"),
    ("가능", "불가"),
    ("있다", "없다"),
    ("있음", "없음"),
    ("된다", "안된다"),
    ("됨", "안됨"),
    ("한다", "않는다"),
    ("맞다", "틀리다"),
    ("안전", "위험"),
    ("허용", "금지"),
    ("지원", "미지원"),
    ("증가", "감소"),
    ("상승", "하락"),
    ("성공", "실패"),
    ("필요", "불필요"),
    # 영어 (단어 경계 매칭 — "not" 은 부정 극이 결합된 형태 cannot·impossible 등으로 표현)
    ("can", "cannot"),
    ("possible", "impossible"),
    ("true", "false"),
    ("supported", "unsupported"),
    ("enabled", "disabled"),
    ("allowed", "forbidden"),
    ("works", "fails"),
    ("increase", "decrease"),
    ("valid", "invalid"),
)

# 주제 판정에서 무시할 영어 기능어(주어 토큰으로 세지 않음 — 오탐 방지).
_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "and", "or", "it", "its", "this", "that", "these", "those",
    "in", "on", "for", "with", "as", "at", "by", "we", "you", "they", "i",
    "do", "does", "did", "has", "have", "had", "will", "would", "should",
    "but", "not", "no", "if", "than", "then", "so", "such",
})

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
# 주장 분할: 개행 + 문장 종결/구두점 경계.
_CLAIM_SPLIT_RE = re.compile(r"[\n\.!?。！？;]+")

# 극 매칭 준비 — 한국어(비-ascii) 극은 긴 것부터 소비, ascii 극은 단어 경계.
_ALL_POLES: tuple[str, ...] = tuple({p for pair in ANTONYM_PAIRS for p in pair})
_KOREAN_POLES_DESC: tuple[str, ...] = tuple(
    sorted((p for p in _ALL_POLES if not p.isascii()), key=len, reverse=True)
)
_ASCII_POLES: tuple[str, ...] = tuple(p for p in _ALL_POLES if p.isascii())


@dataclass(frozen=True)
class NewSource:
    """신규 근거 투영 (raw/ 원천). I/O 는 호출측이 수행해 주입.

    source_ref  : raw/ 경로 또는 근거 식별자 (큐/후보에 그대로 기록).
    text        : 근거 본문 (frontmatter 제외). 주장 분할·상반 신호 탐지 대상.
    frontmatter : title·tags 로 주제 겹침을 판정 (없으면 겹침 0 → 후보 없음).
    """
    source_ref: str
    text: str
    frontmatter: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ContradictionCandidate:
    """모순 *후보* (자동 확정 아님 — 사람/LLM 화해 검토용).

    existing_slug   : 충돌 가능성이 있는 기존 페이지 slug.
    new_source_ref  : 상반 신호를 준 신규 근거 (NewSource.source_ref).
    overlap_terms   : 주제 겹침 근거 (frontmatter 토큰 교집합, 정렬 튜플).
    signal          : 상반 신호 "긍정극↔부정극" (예: "가능↔불가능") — 왜 후보인지.
    confidence_hint : 리뷰 우선순위 힌트("low"|"medium") — 주제 겹침·신호 수 기반.
                      결정적 라벨일 뿐, 어느 쪽이 옳은지·자동 조치는 함의하지 않는다.
    existing_claim  : 기존 본문에서 상반 신호가 잡힌 문장 발췌(절단됨). 화해 3요소
                      "기존 주장" 재료.
    new_claim       : 신규 근거에서 상반 신호가 잡힌 문장 발췌(절단됨). "반례 근거" 재료.
    """
    existing_slug: str
    new_source_ref: str
    overlap_terms: tuple[str, ...]
    signal: str
    confidence_hint: str
    existing_claim: str
    new_claim: str


# ── 내부 헬퍼 (전부 순수·결정적) ────────────────────────────────────────

def _tokens(text: str) -> set[str]:
    """소문자 \\w 토큰 집합. 비문자열은 공집합."""
    if not isinstance(text, str):
        return set()
    return {t.lower() for t in _TOKEN_RE.findall(text)}


def _extract_poles(claim: str) -> set[str]:
    """주장에 등장한 극(pole) 집합. 한국어는 긴 극부터 소비(부분문자열 오탐 차단),
    영어는 단어 경계(\\b) 매칭 — "can" 이 "candidate"·"cannot" 안에서 오매칭되지 않게."""
    if not isinstance(claim, str):
        return set()
    low = claim.lower()
    found: set[str] = set()
    remaining = low
    for pole in _KOREAN_POLES_DESC:      # 긴 극 먼저: "불가능" 소비 후 "가능" 재매칭 차단
        if pole in remaining:
            found.add(pole)
            remaining = remaining.replace(pole, " ")
    for pole in _ASCII_POLES:
        if re.search(rf"\b{re.escape(pole)}\b", low):
            found.add(pole)
    return found


def _opposing_pair(poles_a: set[str], poles_b: set[str]) -> tuple[str, str] | None:
    """두 극 집합에서 상반 페어 하나를 찾는다(양방향). 없으면 None.
    결정성: ANTONYM_PAIRS 정의 순서로 첫 매치 반환."""
    for pos, neg in ANTONYM_PAIRS:
        if (pos in poles_a and neg in poles_b) or (neg in poles_a and pos in poles_b):
            return (pos, neg)
    return None


def _token_has_pole(token: str) -> bool:
    """토큰이 극(주제가 아니라 극성 단어)을 담고 있나 — 주어 토큰 집계에서 제외용."""
    if token in _ASCII_POLES:
        return True
    return any(pole in token for pole in _KOREAN_POLES_DESC)


def _subject_tokens(claim: str) -> set[str]:
    """주장의 '주제' 토큰 = 극·기능어를 뺀 나머지. 두 주장이 같은 대상을 말하는지 판정용."""
    out: set[str] = set()
    for t in _tokens(claim):
        if t in _STOPWORDS or _token_has_pole(t):
            continue
        out.add(t)
    return out


def is_potential_contradiction(claim_a: str, claim_b: str) -> bool:
    """두 문장이 상반될 *가능성*이 있는지 결정적으로 판정 (보수적 — 확실치 않으면 False).

    참 조건 (둘 다 충족):
      1. 상반 극 페어 존재 — 한 문장이 긍정 극, 다른 문장이 그 반대 극(ANTONYM_PAIRS).
      2. 공통 주어 존재 — 두 문장이 같은 대상을 말한다(극·기능어 뺀 토큰 교집합 ≥1).
         "A는 불가" vs "B는 가능" 처럼 주어가 다르면 극이 반대여도 False (오탐 방지).

    같은 극(둘 다 "가능")·극 없음(단순 보강)·주어 불일치는 전부 False.
    """
    if not isinstance(claim_a, str) or not isinstance(claim_b, str):
        return False
    if not claim_a.strip() or not claim_b.strip():
        return False
    pair = _opposing_pair(_extract_poles(claim_a), _extract_poles(claim_b))
    if pair is None:
        return False
    if not (_subject_tokens(claim_a) & _subject_tokens(claim_b)):
        return False
    return True


def _split_claims(text: str) -> list[str]:
    """본문/근거를 주장 후보 문장 리스트로 분할 (개행·문장 종결 경계). 결정적 순서 유지.
    마크다운 헤딩 마커(#)·리스트 마커(-,*)는 앞부분만 벗겨 문장 텍스트를 남긴다."""
    if not isinstance(text, str):
        return []
    claims: list[str] = []
    for raw in _CLAIM_SPLIT_RE.split(text):
        s = raw.strip().lstrip("#-*> \t").strip()
        if s:
            claims.append(s)
    return claims


def _truncate(claim: str) -> str:
    """발췌 절단 (큐 가독성) — 경계 결정적."""
    s = claim.strip()
    return s if len(s) <= _CLAIM_MAX_CHARS else s[:_CLAIM_MAX_CHARS].rstrip() + "…"


def _confidence_hint(overlap_count: int, match_count: int, min_overlap: int) -> str:
    """리뷰 우선순위 힌트 — 결정적. 주제 겹침이 임계 초과 + 상반 신호 복수면 medium,
    아니면 low. 정밀도 우선이라 상한을 medium 으로 둔다(자동 확정 아님을 라벨로 강제)."""
    if overlap_count > min_overlap and match_count > 1:
        return "medium"
    return "low"


# ── 공개 API ────────────────────────────────────────────────────────────

def detect_contradiction_candidates(
    new_source: NewSource,
    existing_pages: Sequence,
    *,
    min_overlap: int = DEFAULT_MIN_OVERLAP,
) -> list[ContradictionCandidate]:
    """신규 근거와 기존 페이지 주장 사이의 모순 *후보* 를 보수적으로 탐지.

    절차 (페이지별, existing_slug 오름차순 — 결정성):
      1. 주제 겹침: new_source.frontmatter ∩ page.frontmatter 토큰 교집합.
         len < min_overlap → 무관 페이지, 건너뜀(오탐 방지). ≥ min_overlap 만 진행.
      2. 상반 신호: page.body 주장 × new_source.text 주장 전조합을 is_potential_contradiction
         으로 검사. 첫 매치(결정적 순서)로 후보 1건을 만든다. 매치 총수는 confidence_hint 에 반영.
      3. 후보 없으면 그 페이지는 결과에서 빠진다(빈 리스트 가능 — 정상).

    반환: existing_slug 오름차순 정렬된 list[ContradictionCandidate] (페이지당 최대 1건).
    파일·LLM 접촉 0. 실제 화해 서술은 호출측 LLM Step 의 몫(모듈 docstring 배선 계약 참조).
    """
    new_fm = new_source.frontmatter if isinstance(new_source.frontmatter, dict) else {}
    new_tokens = _merge_token_set(new_fm)
    new_claims = _split_claims(new_source.text)

    candidates: list[ContradictionCandidate] = []
    for page in sorted(existing_pages, key=lambda p: p.slug):
        page_fm = page.frontmatter if isinstance(page.frontmatter, dict) else {}
        overlap = new_tokens & _merge_token_set(page_fm)
        if len(overlap) < min_overlap:
            continue  # 주제 무관 — 후보 아님 (정밀도 우선)

        first: tuple[str, str, tuple[str, str]] | None = None
        match_count = 0
        for ec in _split_claims(page.body):
            for nc in new_claims:
                if is_potential_contradiction(ec, nc):
                    match_count += 1
                    if first is None:
                        pair = _opposing_pair(_extract_poles(ec), _extract_poles(nc))
                        first = (ec, nc, pair)  # type: ignore[assignment]
        if first is None:
            continue  # 겹침은 있으나 상반 신호 없음 — 단순 보강, 후보 아님

        ec, nc, pair = first
        candidates.append(ContradictionCandidate(
            existing_slug=page.slug,
            new_source_ref=new_source.source_ref,
            overlap_terms=tuple(sorted(overlap)),
            signal=f"{pair[0]}↔{pair[1]}",
            confidence_hint=_confidence_hint(len(overlap), match_count, min_overlap),
            existing_claim=_truncate(ec),
            new_claim=_truncate(nc),
        ))
    return candidates
