"""curate.py 메타 기억 — 중복제거(merge-review)·감쇠(retention decay) 테스트.

이미지 5층 메모리 모델이 가리키나 코드엔 비어 있던 두 메타 연산을 닫는다:

FEATURE A — merge-review (US-006 AC: curate_report에 merge-review 후보 포함)
  WHY: 같은 카테고리 안에 제목·태그가 거의 겹치는 페이지 쌍을 *결정적으로*(임베딩
  없이 Jaccard) 표면화한다. **자동 병합은 하지 않는다** — 사람이 병합 판단(Rule 9).
  방향성 의도: 유사하면 잡고(≥임계), 다르면 안 잡는다. 카테고리 경계를 넘지 않는다.

FEATURE B — retention decay (감쇠)
  WHY: frontmatter `retention`(durable|seasonal|ephemeral)을 memory_score의 recency
  감쇠율에 *실제로* 반영한다. durable=감쇠 없음(영구기억처럼 1.0 고정), ephemeral=빠른
  감쇠(age-to-zero 창 절반), seasonal/부재=기본. 가중치 수치가 바뀌어도 이 부등식
  (durable ≥ seasonal ≥ ephemeral, 같은 age에서)은 깨지면 안 된다.

모두 tmp_path 기반 self-contained — 사용자 wiki/·express/·episodes/ 데이터 비의존.
결정성: now / age_days / threshold 를 고정 주입.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import curate  # noqa: E402


# ── 공용 helpers ────────────────────────────────────────────────────────

def _page(dir_: Path, slug: str, title: str, tags: list[str]) -> Path:
    """카테고리 디렉토리 dir_ 안에 frontmatter(title·tags) 페이지를 쓴다."""
    dir_.mkdir(parents=True, exist_ok=True)
    p = dir_ / f"{slug}.md"
    fm = {"title": title, "type": "concept", "tags": tags}
    p.write_text(
        "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n본문.\n",
        encoding="utf-8",
    )
    return p


def _pairs(cands: list[dict]) -> list[tuple[str, str]]:
    return [(c["a"], c["b"]) for c in cands]


# ════════════════════════════════════════════════════════════════════════
# FEATURE A — merge-review
# ════════════════════════════════════════════════════════════════════════

def test_merge_flags_near_duplicate_same_category(tmp_path):
    """같은 카테고리에 제목·태그가 거의 겹치는 두 페이지 → 후보로 표면화.

    rag-basics: {rag, basics, guide, retrieval, llm}
    rag-deep:   {rag, basics, retrieval, llm}
      inter=4, union=5 → Jaccard 0.8 ≥ 0.6 → flagged.
    vector-db:  {vector, database, storage}  (교집합 0) → 미표면.
    """
    concepts = tmp_path / "wiki" / "concepts"
    _page(concepts, "rag-basics", "RAG Basics Guide", ["retrieval", "llm"])
    _page(concepts, "rag-deep", "RAG Basics", ["retrieval", "llm"])
    _page(concepts, "vector-db", "Vector Database", ["storage"])

    pages = sorted((tmp_path / "wiki").rglob("*.md"))
    cands = curate.find_merge_candidates(pages)

    assert _pairs(cands) == [("rag-basics", "rag-deep")], "근접 중복 쌍만 잡혀야 함"
    c = cands[0]
    assert c["similarity"] >= 0.6
    assert abs(c["similarity"] - 0.8) < 1e-9
    assert isinstance(c["reason"], str) and c["reason"], "사람이 읽을 사유 문자열 필요"
    # 비유사 페이지는 어떤 쌍에도 등장하지 않음
    assert all("vector-db" not in (c["a"], c["b"]) for c in cands)


def test_merge_dissimilar_not_flagged(tmp_path):
    """교집합이 임계 미만이면 후보 아님 (과잉표면 방지)."""
    concepts = tmp_path / "wiki" / "concepts"
    _page(concepts, "alpha", "Alpha One", ["a"])
    _page(concepts, "beta", "Beta Two", ["b"])
    pages = sorted((tmp_path / "wiki").rglob("*.md"))
    assert curate.find_merge_candidates(pages) == []


def test_merge_same_title_different_category_not_flagged(tmp_path):
    """설계 결정(문서화): 병합 후보는 **같은 카테고리 디렉토리 내부 쌍만** 비교한다.

    카테고리가 다르면 제목·태그가 동일해도 표면화하지 않는다 — 카테고리 분리는
    의도된 의미 구분(예: concepts/transformer vs people/transformer)이라 자동
    병합 후보로 묶으면 거짓양성이 된다. 교차 카테고리 중복은 범위 밖(v1).
    """
    _page(tmp_path / "wiki" / "concepts", "shared", "Shared Title", ["x", "y"])
    _page(tmp_path / "wiki" / "tools", "shared2", "Shared Title", ["x", "y"])
    pages = sorted((tmp_path / "wiki").rglob("*.md"))
    assert curate.find_merge_candidates(pages) == [], "교차 카테고리는 비교 대상 아님"


def test_merge_deterministic_order(tmp_path):
    """결정적 정렬: similarity 내림차순, 동점은 slug 오름차순.

    aaa·bbb·ccc 모두 concepts. aaa==bbb(1.0), aaa·ccc=bbb·ccc=0.75.
    기대 순서: (aaa,bbb)[1.0] → (aaa,ccc)[0.75] → (bbb,ccc)[0.75].
    """
    concepts = tmp_path / "wiki" / "concepts"
    _page(concepts, "aaa", "alpha beta", ["t1", "t2"])
    _page(concepts, "bbb", "alpha beta", ["t1", "t2"])
    _page(concepts, "ccc", "alpha beta", ["t1"])
    pages = sorted((tmp_path / "wiki").rglob("*.md"))

    cands = curate.find_merge_candidates(pages)
    assert _pairs(cands) == [("aaa", "bbb"), ("aaa", "ccc"), ("bbb", "ccc")]
    sims = [c["similarity"] for c in cands]
    assert sims == sorted(sims, reverse=True), "similarity 내림차순이어야 함"
    assert abs(cands[0]["similarity"] - 1.0) < 1e-9
    assert abs(cands[1]["similarity"] - 0.75) < 1e-9


def test_merge_threshold_injected_and_config_override(tmp_path, monkeypatch):
    """임계는 주입(threshold=) + config(schema/config.yaml) 양쪽으로 조절된다.

    0.75 쌍은 기본 임계(0.6)에선 잡히지만 0.9 임계에선 빠진다.
    """
    concepts = tmp_path / "wiki" / "concepts"
    _page(concepts, "p", "alpha beta", ["t1", "t2"])     # {alpha,beta,t1,t2}
    _page(concepts, "q", "alpha beta", ["t1"])           # {alpha,beta,t1} → 0.75
    pages = sorted((tmp_path / "wiki").rglob("*.md"))

    # 기본(0.6) → 잡힘
    schema = tmp_path / "schema"
    schema.mkdir()
    monkeypatch.setattr(curate, "SCHEMA_DIR", schema)
    assert _pairs(curate.find_merge_candidates(pages)) == [("p", "q")]

    # 주입 임계 0.9 → 0.75 < 0.9 → 안 잡힘
    assert curate.find_merge_candidates(pages, threshold=0.9) == []

    # config.yaml 의 merge_review.similarity_threshold=0.9 → 안 잡힘
    (schema / "config.yaml").write_text(
        yaml.safe_dump({"merge_review": {"similarity_threshold": 0.9}}),
        encoding="utf-8",
    )
    assert curate.find_merge_candidates(pages) == [], "config 임계 0.9 override 반영"


def test_merge_section_written_to_report(tmp_path, monkeypatch):
    """write_report 가 'Merge-review 후보' 섹션을 curate_report.md 에 쓴다 (US-006 AC).

    자동 병합 금지(Rule 9) — 섹션은 *후보 목록*만 제공한다.
    """
    wiki = tmp_path / "wiki"
    wiki.mkdir(parents=True)
    monkeypatch.setattr(curate, "WIKI_ROOT", tmp_path)
    monkeypatch.setattr(curate, "WIKI_DIR", wiki)
    monkeypatch.setattr(curate, "REPORT_FILE", wiki / "curate_report.md")
    monkeypatch.setattr(curate, "LOG_FILE", tmp_path / "log.md")

    merge = [{"a": "rag-basics", "b": "rag-deep", "similarity": 0.8,
              "reason": "공통 토큰 4개"}]
    curate.write_report({"orphans": [], "stale_links": []}, [],
                        {"archive": [], "delete": [], "rescued": []},
                        merge_candidates=merge)

    report = (wiki / "curate_report.md").read_text(encoding="utf-8")
    assert "## Merge-review 후보" in report, "merge-review 섹션 헤더 누락"
    assert "rag-basics" in report and "rag-deep" in report, "후보 쌍 미기입"
    assert "0.8" in report or "0.80" in report, "similarity 미표기"


def test_merge_report_section_present_when_empty(tmp_path, monkeypatch):
    """후보 0개라도 섹션 헤더는 항상 존재 — 리포트 계약 안정성(AC '포함')."""
    wiki = tmp_path / "wiki"
    wiki.mkdir(parents=True)
    monkeypatch.setattr(curate, "WIKI_ROOT", tmp_path)
    monkeypatch.setattr(curate, "WIKI_DIR", wiki)
    monkeypatch.setattr(curate, "REPORT_FILE", wiki / "curate_report.md")
    monkeypatch.setattr(curate, "LOG_FILE", tmp_path / "log.md")

    curate.write_report({"orphans": [], "stale_links": []}, [],
                        {"archive": [], "delete": [], "rescued": []})
    report = (wiki / "curate_report.md").read_text(encoding="utf-8")
    assert "## Merge-review 후보" in report


# ════════════════════════════════════════════════════════════════════════
# FEATURE B — retention decay (감쇠)
# ════════════════════════════════════════════════════════════════════════

_W = curate.MEMORY_SCORE_WEIGHTS_DEFAULT
_C = curate.MEMORY_SCORE_CAPS_DEFAULT
_CW = curate.MEMORY_SCORE_CENTRALITY_WEIGHTS_DEFAULT


def _score(entry: dict, fm: dict):
    """결정적·격리 점수 — 가중치 명시 주입(파일 미접근)."""
    return curate.compute_memory_score(entry, {}, fm, weights=dict(_W),
                                       caps=dict(_C), centrality_weights=dict(_CW))


def test_durable_recency_unchanged_with_age():
    """durable 페이지는 나이가 들어도 recency 기여가 변하지 않는다 (감쇠 없음)."""
    fm = {"retention": "durable"}
    base = {"slug": "d", "access_count": 0, "express_reuse": 0, "episode_ref": 0}
    young = _score({**base, "age_days": 5}, fm)
    old = _score({**base, "age_days": 4000}, fm)
    assert young == old, "durable 은 age 무관하게 recency 고정(1.0)이어야 함"


def test_ephemeral_decays_faster_than_seasonal_same_age():
    """같은 age에서 ephemeral recency < seasonal recency ≤ durable.

    age=120: seasonal eff=120 → ~0.731, ephemeral eff=240 → ~0.373.
    seasonal == 부재(둘 다 factor 1.0). durable == 1.0(최대).
    """
    base = {"slug": "x", "access_count": 0, "express_reuse": 0, "episode_ref": 0,
            "age_days": 120}
    s_durable = _score(base, {"retention": "durable"})
    s_seasonal = _score(base, {"retention": "seasonal"})
    s_absent = _score(base, {})
    s_ephemeral = _score(base, {"retention": "ephemeral"})

    assert s_ephemeral < s_seasonal < s_durable, "감쇠 순서 durable>seasonal>ephemeral 위반"
    assert s_seasonal == s_absent, "seasonal 과 retention 부재는 동일(기본 감쇠)"


def test_unknown_retention_defaults_and_warns(capsys):
    """미지 retention 값 → 기본(1.0=seasonal)으로 폴백 + stderr warn, 크래시 금지."""
    base = {"slug": "u", "access_count": 0, "express_reuse": 0, "episode_ref": 0,
            "age_days": 120}
    s_unknown = _score(base, {"retention": "forever-and-ever"})
    s_seasonal = _score(base, {"retention": "seasonal"})
    assert s_unknown == s_seasonal, "미지 값은 기본 감쇠(1.0)로 폴백해야 함"
    err = capsys.readouterr().err
    assert "retention" in err and "forever-and-ever" in err, "미지 retention 경고 누락"


def test_recency_score_helper_decay_factor():
    """_recency_score(age, factor) 단위: factor 가 age-to-zero 창을 스케일한다.

    - durable factor 0.0 → 항상 1.0 (감쇠 없음)
    - ephemeral factor 2.0 → 창 절반: age 200 → 0.0 (eff 400 ≥ 365)
    - seasonal factor 1.0 → age 200 → >0 (eff 200, 아직 살아있음)
    - 기본 인자(factor 생략) = 기존 동작(backward-compat)
    """
    assert curate._recency_score(4000, 0.0) == 1.0
    assert curate._recency_score(5, 2.0) == 1.0          # eff 10 ≤ 30
    assert curate._recency_score(200, 2.0) == 0.0        # eff 400 ≥ 365
    assert curate._recency_score(200, 1.0) > 0.0         # 절반 창 대비 아직 양수
    # backward-compat: factor 생략 시 기존 단일인자 동작
    assert curate._recency_score(5) == 1.0
    assert curate._recency_score(4000) == 0.0
    assert curate._recency_score(200, 2.0) < curate._recency_score(200, 1.0)


def test_retention_factors_config_override(tmp_path, monkeypatch, capsys):
    """retention factor 맵은 config(schema/config.yaml)로 override + 안전 폴백.

    - ephemeral: 4.0 정상 override → 반영
    - durable: 음수(-1) → 거부(기본 0.0 유지) + warn
    - seasonal: 문자열 → 거부(기본 1.0 유지) + warn
    - 부재 시 전부 기본값
    """
    schema = tmp_path / "schema"
    schema.mkdir()
    monkeypatch.setattr(curate, "SCHEMA_DIR", schema)

    # 부재 → 기본
    assert curate._load_retention_factors() == curate.RETENTION_DECAY_FACTORS_DEFAULT

    (schema / "config.yaml").write_text(
        yaml.safe_dump({"memory_score": {"retention_decay": {
            "ephemeral": 4.0, "durable": -1, "seasonal": "fast",
        }}}),
        encoding="utf-8",
    )
    factors = curate._load_retention_factors()
    assert factors["ephemeral"] == 4.0, "정상 override 반영"
    assert factors["durable"] == curate.RETENTION_DECAY_FACTORS_DEFAULT["durable"], "음수 거부"
    assert factors["seasonal"] == curate.RETENTION_DECAY_FACTORS_DEFAULT["seasonal"], "타입오류 거부"
    err = capsys.readouterr().err
    assert "durable" in err and "seasonal" in err, "잘못된 factor 경고 누락"


def test_decay_deterministic_with_fixed_now():
    """now 고정 주입 + created 기반 age 경로에서도 결정적·retention 반영.

    created 1년 전 + 고정 now. durable 은 recency 고정(반복 호출 동일),
    ephemeral 은 같은 created 에서 durable 보다 낮다.
    """
    from datetime import datetime
    now = datetime(2026, 6, 28)
    fm_durable = {"retention": "durable", "created": "2025-06-28"}
    fm_ephemeral = {"retention": "ephemeral", "created": "2025-06-28"}
    entry = {"slug": "t", "access_count": 0, "express_reuse": 0, "episode_ref": 0}

    s1 = curate.compute_memory_score(entry, {}, fm_durable, weights=dict(_W),
                                     caps=dict(_C), centrality_weights=dict(_CW), now=now)
    s2 = curate.compute_memory_score(entry, {}, fm_durable, weights=dict(_W),
                                     caps=dict(_C), centrality_weights=dict(_CW), now=now)
    s_eph = curate.compute_memory_score(entry, {}, fm_ephemeral, weights=dict(_W),
                                        caps=dict(_C), centrality_weights=dict(_CW), now=now)
    assert s1 == s2, "동일 입력·고정 now → 동일 출력"
    assert s_eph < s1, "1년 경과 시 ephemeral 이 durable 보다 낮아야 함(감쇠)"
