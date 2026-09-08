"""lib/synthesis.py WS-1 종합 결정적 코어 테스트 — v0.3.1.

WHY (이 테스트들이 인코딩하는 *의도* — schema/curate.md "## Synthesis Rules" 단일 출처):
  1. **교차 소스 경계**: raw 소스 1개 = 미선정 / 2개 = 선정 (요건 (a)
     "2개+ raw 소스 교차"). min_sources 인자가 경계를 정확히 가른다.
  2. **inbound 허브**: 소스가 부족해도 교차도 높은 허브면 선정.
  3. **signal_count 결정성**: 같은 입력 → 같은 수. 토큰 공유 페이지 수를 센다.
  4. **shrink 가드**: 본문 −1자 또는 sources −1건이면 blocked, 동일·증가는 pass
     (불변식 "본문·근거 단축/삭제 금지"의 결정적 게이트).
  5. **정렬 결정성**: 점수 desc, 동점은 slug asc.
  6. **빈 입력**: 안전하게 빈 결과.

전부 인메모리 데이터 — claude CLI·실 wiki·파일 I/O 의존 없음.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from lib.gates import ExistingPage  # noqa: E402
from lib.synthesis import (  # noqa: E402
    FM_ANGLES,
    FM_SIGNAL_COUNT,
    FM_SYNTHESIS_UPDATED,
    ShrinkVerdict,
    SynthesisTarget,
    count_repeat_signals,
    guard_no_shrink,
    select_synthesis_targets,
)


def _page(slug: str, *, sources=None, title=None, tags=None, body: str = "") -> ExistingPage:
    fm = {
        "title": title if title is not None else slug.replace("-", " "),
        "tags": tags if tags is not None else [],
    }
    if sources is not None:
        fm["sources"] = sources
    return ExistingPage(slug=slug, frontmatter=fm, body=body)


# ── 1. 교차 소스 경계 (1개=미선정 / 2개=선정) ────────────────────────────

def test_single_source_not_selected():
    """raw 소스 1개 + 허브 아님 → 종합 대상 아님 (교차 요건 미달)."""
    pages = [_page("a", sources=["raw/x.md"])]
    targets = select_synthesis_targets(pages, {}, min_sources=2)
    assert targets == []


def test_two_sources_selected():
    """raw 소스 2개 → 교차 요건 충족 → 선정. crossing_sources 순서 보존."""
    pages = [_page("a", sources=["raw/x.md", "raw/y.md"])]
    targets = select_synthesis_targets(pages, {}, min_sources=2)
    assert len(targets) == 1
    t = targets[0]
    assert t.slug == "a"
    assert t.crossing_sources == ("raw/x.md", "raw/y.md")
    assert "교차" in t.reason


def test_min_sources_param_shifts_boundary():
    """min_sources=3 이면 2개 소스는 미달(경계는 인자로 결정)."""
    pages = [_page("a", sources=["raw/x.md", "raw/y.md"])]
    assert select_synthesis_targets(pages, {}, min_sources=3) == []
    pages3 = [_page("a", sources=["raw/x.md", "raw/y.md", "raw/z.md"])]
    assert len(select_synthesis_targets(pages3, {}, min_sources=3)) == 1


def test_empty_string_sources_not_counted():
    """빈/공백 소스 문자열은 건수에서 제외 (gates._count_sources 규칙 일치)."""
    pages = [_page("a", sources=["raw/x.md", "  ", ""])]
    assert select_synthesis_targets(pages, {}, min_sources=2) == []


# ── 2. inbound 허브 선정 ─────────────────────────────────────────────────

def test_inbound_hub_selected_without_sources():
    """소스 부족해도 inbound 2개면 허브로 선정."""
    pages = [_page("hub", sources=["raw/x.md"])]
    link_graph = {"hub": {"p1", "p2"}}
    targets = select_synthesis_targets(pages, link_graph, min_sources=2)
    assert len(targets) == 1
    assert targets[0].inbound_degree == 2
    assert "허브" in targets[0].reason


def test_single_inbound_not_hub():
    """inbound 1개 + 소스 1개 → 허브도 교차도 아님 → 미선정."""
    pages = [_page("a", sources=["raw/x.md"])]
    assert select_synthesis_targets(pages, {"a": {"p1"}}, min_sources=2) == []


# ── 3. signal_count 결정성 ───────────────────────────────────────────────

def test_signal_count_counts_token_sharing_pages():
    """토큰(태그) 공유 페이지 수를 센다. 자기 자신 제외."""
    page = _page("main", tags=["llm", "caching"])
    related = [
        _page("r1", tags=["llm"]),          # 공유(llm)
        _page("r2", tags=["caching"]),      # 공유(caching)
        _page("r3", tags=["unrelated"]),    # 미공유
        _page("main", tags=["llm"]),        # 같은 slug → 제외
    ]
    assert count_repeat_signals(page, related) == 2


def test_signal_count_deterministic_order_independent():
    """순서를 바꿔도 같은 수 (집합 기반 결정성)."""
    page = _page("main", tags=["a", "b"])
    r = [_page("x", tags=["a"]), _page("y", tags=["b"]), _page("z", tags=["c"])]
    first = count_repeat_signals(page, r)
    assert first == count_repeat_signals(page, list(reversed(r)))
    assert first == 2


def test_signal_count_empty_related_is_zero():
    assert count_repeat_signals(_page("main", tags=["a"]), []) == 0


def test_signal_count_no_tokens_is_zero():
    """제목·태그 토큰이 없으면 0 (비교 불가)."""
    page = ExistingPage(slug="main", frontmatter={"title": "", "tags": []})
    assert count_repeat_signals(page, [_page("x", tags=["a"])]) == 0


# ── 4. shrink 가드 ───────────────────────────────────────────────────────

def test_shrink_guard_body_minus_one_blocked():
    """본문 −1자 → blocked."""
    v = guard_no_shrink({}, "x" * 100, {}, "x" * 99)
    assert isinstance(v, ShrinkVerdict)
    assert v.blocked is True
    assert v.body_delta == -1


def test_shrink_guard_sources_minus_one_blocked():
    """sources −1건 → blocked (본문은 동일)."""
    before = {"sources": ["raw/a.md", "raw/b.md"]}
    after = {"sources": ["raw/a.md"]}
    v = guard_no_shrink(before, "body", after, "body")
    assert v.blocked is True
    assert v.sources_delta == -1


def test_shrink_guard_equal_passes():
    """본문·sources 동일 → 통과."""
    fm = {"sources": ["raw/a.md"]}
    v = guard_no_shrink(fm, "same body", fm, "same body")
    assert v.blocked is False
    assert v.body_delta == 0
    assert v.sources_delta == 0


def test_shrink_guard_growth_passes():
    """본문·sources 증가(append) → 통과 (종합의 정상 경로)."""
    before = {"sources": ["raw/a.md"]}
    after = {"sources": ["raw/a.md", "raw/b.md"]}
    v = guard_no_shrink(before, "body", after, "body\n## 인사이트 (종합)\n...")
    assert v.blocked is False
    assert v.body_delta > 0
    assert v.sources_delta == 1


def test_shrink_guard_uses_stripped_length():
    """길이 = strip 후 len (gates._chars 일치) — 후행 공백만 변해도 축소 아님."""
    v = guard_no_shrink({}, "abc\n\n", {}, "abc")
    assert v.blocked is False
    assert v.body_delta == 0


# ── 5. 정렬 결정성 (점수 desc, 동점 slug asc) ────────────────────────────

def test_sort_by_score_desc():
    """교차소스+inbound+신호 합이 큰 페이지가 앞."""
    pages = [
        _page("low", sources=["raw/a.md", "raw/b.md"]),                    # score 2
        _page("high", sources=["raw/a.md", "raw/b.md", "raw/c.md"]),       # score 3+
    ]
    targets = select_synthesis_targets(pages, {}, min_sources=2)
    assert [t.slug for t in targets] == ["high", "low"]


def test_sort_tiebreak_slug_asc():
    """동점(같은 점수)이면 slug 오름차순."""
    # 둘 다 소스 2개·inbound 0·신호 0 → 점수 동일. slug asc: 'apple' < 'banana'.
    pages = [
        _page("banana", sources=["raw/x.md", "raw/y.md"], tags=["z1"]),
        _page("apple", sources=["raw/p.md", "raw/q.md"], tags=["z2"]),
    ]
    targets = select_synthesis_targets(pages, {}, min_sources=2)
    assert [t.slug for t in targets] == ["apple", "banana"]


# ── 6. 빈 입력 ───────────────────────────────────────────────────────────

def test_empty_pages():
    assert select_synthesis_targets([], {}, min_sources=2) == []


def test_empty_guard_bodies():
    """빈 본문·sources 부재 → 축소 없음 → 통과."""
    v = guard_no_shrink({}, "", {}, "")
    assert v.blocked is False
    assert v.body_delta == 0
    assert v.sources_delta == 0


# ── 7. frontmatter 상수 (schema/curate.md 와 일치) ───────────────────────

def test_frontmatter_field_constants():
    assert FM_ANGLES == "angles"
    assert FM_SIGNAL_COUNT == "signal_count"
    assert FM_SYNTHESIS_UPDATED == "synthesis_updated"


def test_target_is_frozen():
    """SynthesisTarget 는 frozen (불변)."""
    import dataclasses
    t = SynthesisTarget("a", ("raw/x.md",), 0, 0, "r")
    try:
        t.slug = "b"  # type: ignore[misc]
        assert False, "frozen dataclass 인데 변경 허용됨"
    except dataclasses.FrozenInstanceError:
        pass


# ── limit(top-N 큐 상한) — 조밀 wiki 실용화 (실데이터 관측 후 추가) ──
def test_select_synthesis_targets_limit_returns_top_n():
    """limit=N 이면 점수 상위 N개만. 정렬(점수 desc·slug asc)은 유지."""
    from lib.gates import ExistingPage
    pages = [
        ExistingPage(slug=f"p{i:02d}",
                     frontmatter={"sources": [f"raw/{j}.md" for j in range(i + 2)]},
                     body="x")
        for i in range(10)
    ]
    graph = {p.slug: () for p in pages}
    full = select_synthesis_targets(pages, graph, min_sources=2)
    top3 = select_synthesis_targets(pages, graph, min_sources=2, limit=3)
    assert len(top3) == 3
    assert top3 == full[:3]  # 상위 3개 = 전체 정렬의 앞 3개
    # limit=None(기본) 하위호환: 전체 반환
    assert select_synthesis_targets(pages, graph, min_sources=2, limit=None) == full


def test_select_synthesis_targets_limit_larger_than_pool():
    """limit 이 대상 수보다 크면 있는 만큼만(에러 없음)."""
    from lib.gates import ExistingPage
    pages = [ExistingPage(slug="a", frontmatter={"sources": ["raw/1.md", "raw/2.md"]}, body="x")]
    got = select_synthesis_targets(pages, {"a": ()}, min_sources=2, limit=99)
    assert len(got) == 1
