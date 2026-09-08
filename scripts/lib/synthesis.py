"""synthesis — WS-1 종합(Synthesis) 결정적 코어 (v0.3.1).

생성 규칙의 **단일 출처는 `schema/curate.md` "## Synthesis Rules" 절**이다.
이 모듈은 그 문서의 "무엇을 종합할지 선정 + 반복 신호를 계산 + 축소를 차단"하는
**결정적 부분만** 옮긴 순수 함수 묶음이다 — LLM 호출 0, 파일 I/O 0. 판정에 필요한
모든 값은 인자로 주입받는다(같은 입력 → 같은 출력). 날짜가 필요하면 인자로 주입한다
(`datetime.now()` 내부 호출 금지 — 테스트 결정성).

LLM 실행 경계 (SPEC §A): 종합 **문장 생성**(`## 인사이트 (종합)` 서술·강한 각도
서술)은 결정적으로 계산할 수 없으므로 `commands/curate.md`의 Step(Claude Code)이
수행한다. 이 모듈은 "어떤 페이지가 종합 후보이고, 어떤 raw 소스들이 교차하며, 반복
신호가 몇인가"를 **선정·계산**해 큐 재료를 반환할 뿐, 종합 문장을 절대 만들지 않는다
(Rule 5 — 판단·생성은 사람/모델, 선정·계산 규칙은 코드).

curate 배선 계약 (Wave 6 이 이 모듈을 import — 예정):
    1. `find_all_wiki_pages()` 로 페이지를 모으고, 각 페이지 fm/body 를
       `lib.gates.ExistingPage(slug, frontmatter, body)` 로 투영한다
       (sources 는 wiki frontmatter 의 `sources` 키에 있다 — Candidate 처럼 별도
       필드가 아니다).
    2. `inbound = curate.build_link_graph(pages)[1]` — inbound 인접맵을
       `link_graph` 인자로 넘긴다 (slug → 그 페이지를 가리키는 slug 집합).
    3. `targets = select_synthesis_targets(projections, inbound)` 로 종합 대상을
       결정적으로 선정 → `wiki/reweave_queue.md` 의 synthesis 섹션(체크박스 큐)에
       기입한다 (distill_queue.md 와 동일 패턴). 생성은 Step 이 소비.
    4. LLM 이 종합을 append 한 뒤 **저장 직전**, curate 는
       `guard_no_shrink(before_fm, before_body, after_fm, after_body)` 를 통과시킨다.
       `blocked=True` 면 저장을 거부하고 `WARN shrink` 를 낸다 (schema/curate.md
       "불변식 — 기존 본문·sources 삭제·단축 절대 금지"의 결정적 게이트).
    5. frontmatter 신규 필드(`angles`·`signal_count`·`synthesis_updated`)는
       `lib.frontmatter_utils` 경유로 쓴다 (파서 신설 금지, SPEC §C).

유사도·소스·길이 규칙은 `lib.gates` 의 구현을 **재사용**한다 (중복 구현 금지 —
토큰/소스/길이 규칙의 단일 출처를 gates 로 수렴).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Collection, Mapping, Sequence

# 토큰/소스/길이 규칙은 gates 의 구현을 재사용한다 (parity 는 test_gates·test_synthesis).
from lib.gates import ExistingPage, _chars, _count_sources, _merge_token_set

# ── frontmatter 신규 필드 상수 (schema/curate.md "frontmatter 사용법(Synthesis)"와 1:1) ──
FM_ANGLES = "angles"                    # 강한 각도 1~3개 (list[str])
FM_SIGNAL_COUNT = "signal_count"        # 반복 신호 카운트 (int)
FM_SYNTHESIS_UPDATED = "synthesis_updated"  # 마지막 종합 갱신일 (YYYY-MM-DD)

# ── 선정 파라미터 (schema 가 수치를 명시하지 않은 지점은 여기 문서화된 기본값) ──
# (a) "2개+ raw 소스 교차" 는 min_sources 인자로 주입(기본 2). (교차 요건 §Synthesis Rules)
# inbound 허브 임계는 schema 에 수치가 없어 여기서 기본값을 정한다 — 2개+ 페이지가
# 가리키는 노드를 "교차도 높은 허브"로 본다 (해석 지점, 보고서에 명시).
HUB_INBOUND_MIN = 2
# 반복 신호: 두 페이지가 토큰을 1개 이상 공유하면 "같은 신호가 반복"으로 센다
# (거친 결정적 프록시 — 실제 신호 판단은 LLM Step). schema 미명시 → 여기 기본값.
SIGNAL_MIN_SHARED = 1


# ── 데이터 계약 (frozen — 해시 가능·불변) ────────────────────────────────

@dataclass(frozen=True)
class SynthesisTarget:
    """종합 대상 1건 (reweave_queue.md synthesis 큐의 재료).

    slug            대상 페이지 slug.
    crossing_sources 교차하는 raw 소스 경로(frontmatter `sources`)의 순서 보존 목록.
                    len ≥ min_sources 면 (a) "2개+ raw 소스 교차" 요건 충족.
    signal_count    반복 신호 수 = 토큰을 공유하는 다른 페이지 수(count_repeat_signals).
    inbound_degree  이 페이지를 가리키는 페이지 수 (link_graph inbound).
    reason          선정 사유 (사람이 읽는 큐 라벨).
    """
    slug: str
    crossing_sources: tuple[str, ...]
    signal_count: int
    inbound_degree: int
    reason: str


@dataclass(frozen=True)
class ShrinkVerdict:
    """shrink 가드 판정 (종합 저장 전 결정적 게이트).

    blocked         True 면 저장 거부 (본문 또는 sources 가 줄었다).
    reasons         판정 상세(감사 로그용) — 통과/차단 모두 근거를 담는다.
    body_delta      after 본문 문자 수 − before 본문 문자 수 (음수면 축소).
    sources_delta   after sources 건수 − before sources 건수 (음수면 삭제).
    """
    blocked: bool
    reasons: tuple[str, ...]
    body_delta: int
    sources_delta: int


# ── 내부 헬퍼 (전부 순수) ───────────────────────────────────────────────

def _source_list(fm) -> tuple[str, ...]:
    """frontmatter `sources` → 비어있지 않은 문자열만 순서 보존한 tuple.

    gates._count_sources 와 동일한 "비어있지 않은 str 만 센다" 규칙을 목록 형태로
    반환한다 (건수는 len 으로 gates 와 일치)."""
    if not isinstance(fm, dict):
        return ()
    raw = fm.get("sources")
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(s for s in raw if isinstance(s, str) and s.strip())


def count_repeat_signals(page: ExistingPage,
                         related_pages: Sequence[ExistingPage]) -> int:
    """같은 신호(토큰)가 몇 개의 다른 페이지에서 반복되는지 결정적 카운트.

    page 의 (소문자 제목 토큰 ∪ 소문자 태그) 집합과 토큰을 `SIGNAL_MIN_SHARED` 개
    이상 공유하는 related_pages 의 **서로 다른 slug 수**를 반환한다
    (gates._merge_token_set 재사용 — 토큰 규칙 단일 출처). 자기 자신(같은 slug)은
    제외한다. 순서 무관·중복 slug 무관(집합 기반) — 같은 입력이면 항상 같은 수.

    이는 거친 결정적 프록시다 — 실제 "이게 진짜 반복 신호인가"의 판단은 LLM Step.
    """
    page_tokens = _merge_token_set(page.frontmatter)
    if not page_tokens:
        return 0
    hit_slugs: set[str] = set()
    for other in related_pages:
        if other.slug == page.slug:
            continue
        shared = page_tokens & _merge_token_set(other.frontmatter)
        if len(shared) >= SIGNAL_MIN_SHARED:
            hit_slugs.add(other.slug)
    return len(hit_slugs)


def select_synthesis_targets(pages: Sequence[ExistingPage],
                             link_graph: Mapping[str, Collection[str]],
                             *,
                             min_sources: int = 2,
                             limit: int | None = None) -> list[SynthesisTarget]:
    """종합(Synthesis) 대상을 결정적으로 선정 (schema/curate.md 단일 출처).

    선정 기준 (둘 중 하나면 대상):
      - **교차 요건**: crossing_sources(=frontmatter sources) 건수 ≥ min_sources
        (schema (a) "2개+ raw 소스 교차 인용"). 2개+면 소스를 교차해 종합할 수 있다.
      - **허브 요건**: inbound_degree ≥ HUB_INBOUND_MIN — 여러 페이지가 가리키는
        교차도 높은 허브. 종합의 레버리지가 크다.
    (signal_count 는 선정 자격에 영향을 주지 않는다 — 보고·정렬 신호일 뿐.)

    link_graph: slug → 그 페이지를 가리키는 slug 집합 (inbound 인접맵).
        Wave 6 은 `curate.build_link_graph(pages)[1]` 을 넘긴다.

    정렬(결정성): 점수 desc, 동점은 slug asc. 점수 = 교차소스수 + inbound차수 +
    반복신호수 (교차 밀도의 결정적 합 — 실제 우선순위 재판단은 LLM Step).

    limit: 상위 N개만 반환(정렬 후 슬라이스). None=전체(하위호환). 조밀하게
        연결된 실 wiki 는 자격 기준만으론 대부분이 대상이 되므로(임계 상향 효과 미미),
        우선순위 큐로 쓰려면 점수 상위 N개로 잘라 실용화한다(실측 근거).
    """
    targets: list[SynthesisTarget] = []
    for i, page in enumerate(pages):
        crossing = _source_list(page.frontmatter)
        source_count = len(crossing)
        inbound_degree = len(link_graph.get(page.slug, ()))
        related = [p for j, p in enumerate(pages) if j != i]
        signal_count = count_repeat_signals(page, related)

        source_ok = source_count >= min_sources
        hub_ok = inbound_degree >= HUB_INBOUND_MIN
        if not (source_ok or hub_ok):
            continue

        if source_ok and hub_ok:
            reason = (f"{source_count}개 raw 소스 교차(기준 ≥{min_sources}) + "
                      f"inbound 허브 {inbound_degree}개 — 종합 우선")
        elif source_ok:
            reason = f"{source_count}개 raw 소스 교차(기준 ≥{min_sources}) — 교차 종합 대상"
        else:
            reason = f"inbound 허브 {inbound_degree}개(기준 ≥{HUB_INBOUND_MIN}) — 교차도 높음"

        targets.append(SynthesisTarget(
            slug=page.slug,
            crossing_sources=crossing,
            signal_count=signal_count,
            inbound_degree=inbound_degree,
            reason=reason,
        ))

    # 점수 desc, slug asc (결정성). 점수는 필드로부터 파생 가능 → 별도 노출 안 함.
    targets.sort(key=lambda t: (
        -(len(t.crossing_sources) + t.inbound_degree + t.signal_count),
        t.slug,
    ))
    if limit is not None:
        return targets[:limit]
    return targets


def guard_no_shrink(before_fm, before_body,
                    after_fm, after_body) -> ShrinkVerdict:
    """종합 후 본문·sources 가 줄면 저장을 차단하는 결정적 게이트 (WS-1 불변식).

    schema/curate.md "불변식 — 기존 본문·sources 삭제·단축 절대 금지":
      - 본문 문자 수(gates._chars = strip 후 len) 가 줄면 blocked.
      - sources 건수(gates._count_sources) 가 줄면 blocked.
    동일·증가는 통과. 두 조건은 독립 평가돼 reasons 에 모두 담긴다(감사 로그).

    curate 는 blocked 면 저장하지 않고 `WARN shrink` 를 낸다 (append/갱신만 허용).
    """
    body_before = _chars(before_body)
    body_after = _chars(after_body)
    src_before = _count_sources(_source_list(before_fm))
    src_after = _count_sources(_source_list(after_fm))
    body_delta = body_after - body_before
    sources_delta = src_after - src_before

    reasons: list[str] = []
    body_shrunk = body_delta < 0
    sources_shrunk = sources_delta < 0

    reasons.append(
        f"본문 {body_before}자 → {body_after}자 ({body_delta:+d})"
        + (" — 축소(차단)" if body_shrunk else " — 유지/증가")
    )
    reasons.append(
        f"근거 {src_before}건 → {src_after}건 ({sources_delta:+d})"
        + (" — 삭제(차단)" if sources_shrunk else " — 유지/증가")
    )

    return ShrinkVerdict(
        blocked=body_shrunk or sources_shrunk,
        reasons=tuple(reasons),
        body_delta=body_delta,
        sources_delta=sources_delta,
    )
