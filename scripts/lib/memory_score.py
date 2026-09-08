"""memory_score — meta-memory 점수 코어 (curate.py 에서 추출, 동작 무변경).

v0.3 선행 리팩터(SPEC "v0.3 Quality-Driven Curation — 설계" §B): 다음 Wave 의
lib/gates.py 가 curate.py 와 순환 import 없이 점수 코어를 공유하기 위해
curate.py 의 점수 블록(US-006)을 이 모듈로 옮겼다. curate.py 는 기존 공개 이름을
그대로 re-export 하므로 기존 테스트·호출부는 무수정으로 동작한다.

SPEC §C4: meta-memory 점수. 재사용 신호(express_reuse·episode_ref)에 가중치
60%를 둬 "실제로 다시 쓰인" 페이지를 보존 우선한다. 사람이 튜닝하는 가중치·CAP은
DEFAULT 상수 + 선택적 schema/config.yaml override(Rule 5). config는 gitignored이고
부재/부분/오류 시 항별 기본값으로 안전 폴백한다(크래시·flaky 금지).

norm(x) = min(x / CAP, 1.0). score = Σ weight·norm(signal).

경로 기본값 주의: 이 모듈의 WIKI_ROOT/WIKI_DIR/SCHEMA_DIR 는 repo 루트 기준
정적 기본값이다. curate.py 는 자기 모듈 전역(테스트가 monkeypatch 하는 대상)을
주입하는 얇은 wrapper 로 경로-기본값 함수들을 노출한다 — 경로를 받는 함수를
직접 쓸 때는 명시 인자 주입을 권장(결정성).
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import yaml

from lib import frontmatter_utils

# scripts/lib/memory_score.py → repo 루트 (curate.py 의 WIKI_ROOT 와 동일 지점)
WIKI_ROOT = Path(__file__).parent.parent.parent
WIKI_DIR = WIKI_ROOT / "wiki"
SCHEMA_DIR = WIKI_ROOT / "schema"

MEMORY_SCORE_WEIGHTS_DEFAULT: dict[str, float] = {
    "express_reuse": 35.0,
    "episode_ref": 25.0,
    "centrality": 15.0,
    "access_count": 10.0,
    "recency": 10.0,
    "source_count": 5.0,
}
# 정규화 분모(이 값에서 norm=1.0 포화). 0/음수 금지.
MEMORY_SCORE_CAPS_DEFAULT: dict[str, float] = {
    "express_reuse": 5.0,
    "episode_ref": 10.0,
    "centrality": 20.0,
    "access_count": 20.0,
    "source_count": 5.0,
}
# centrality = w_inbound·inbound_degree + w_betweenness·betweenness.
# graph.json은 현재 betweenness 필드를 저장하지 않으므로 부재 시 0으로 본다.
MEMORY_SCORE_CENTRALITY_WEIGHTS_DEFAULT: dict[str, float] = {
    "inbound": 1.0,
    "betweenness": 10.0,
}
# recency: age <= FULL → 1.0, >= ZERO → 0.0, 그 사이 선형.
RECENCY_FULL_DAYS = 30
RECENCY_ZERO_DAYS = 365
# 감쇠(decay): retention 이 recency 감쇠율(age 스케일)을 조절한다 (SPEC §C2 retention).
# effective_age = age · factor 에 표준 recency 곡선을 적용한다:
#   durable(0.0)   → effective_age 항상 0 → recency 1.0 고정(영구기억처럼 감쇠 없음)
#   seasonal(1.0)  → 기본 감쇠(부재 페이지와 동일)
#   ephemeral(2.0) → age-to-zero 창 절반(빠른 감쇠) → distill/rescue 우선순위 빨리 하락
# 사람 튜닝 = Rule 5. schema/config.yaml `memory_score.retention_decay` 로 override,
# 부재/부분/오류는 항별 기본값 + stderr warn 으로 안전 폴백. 미지 retention 값은 1.0.
RETENTION_DECAY_FACTORS_DEFAULT: dict[str, float] = {
    "durable": 0.0,
    "seasonal": 1.0,
    "ephemeral": 2.0,
}
# rescue: archive 후보 중 memory_score 상위 비율만큼 보존(상대 임계, SPEC §C4 plug-in ②).
RESCUE_TOP_PCT_DEFAULT = 0.20

_REASON_LABEL = {
    "express_reuse": "express 재사용",
    "episode_ref": "episode 참조",
    "centrality": "그래프 중심성",
    "access_count": "조회수",
    "recency": "최근성",
    "source_count": "출처수",
}


def _as_num(x) -> float:
    """안전한 수치 변환. bool/None/비수치는 0.0."""
    if isinstance(x, bool) or x is None:
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    return 0.0


def _norm(x, cap) -> float:
    """min(x/CAP, 1.0). CAP<=0 이면 0.0 (ZeroDivision/flaky 방지 — 방어선)."""
    cap = _as_num(cap)
    if cap <= 0:
        return 0.0
    return min(_as_num(x) / cap, 1.0)


def _recency_score(age_days, decay_factor: float = 1.0) -> float:
    """age 감쇠(retention 으로 변조): effective_age = age·factor 에 표준 곡선 적용.

    <=FULL → 1.0, >=ZERO → 0.0, 그 사이 선형. decay_factor 가 창을 스케일한다 —
    0.0(durable)이면 effective_age 가 항상 0이라 1.0 고정(감쇠 없음), 2.0(ephemeral)이면
    age-to-zero 창이 절반으로 압축(빠른 감쇠). factor 생략 시 1.0 = 기존 동작(backward-compat).
    음수 factor 는 1.0 으로 폴백(방어선).
    """
    age = _as_num(age_days)
    factor = _as_num(decay_factor)
    if factor < 0:
        factor = 1.0
    effective = age * factor
    if effective <= RECENCY_FULL_DAYS:
        return 1.0
    if effective >= RECENCY_ZERO_DAYS:
        return 0.0
    span = RECENCY_ZERO_DAYS - RECENCY_FULL_DAYS
    return max(0.0, 1.0 - (effective - RECENCY_FULL_DAYS) / span)


def _merge_numeric(target: dict, override, label: str, *, allow_zero: bool) -> None:
    """override(dict)의 수치 값만 target에 병합. 타입오류·금지값은 기본값 유지 + stderr warn.

    allow_zero=False(=CAP)면 0/음수 금지, True(=weight)면 음수만 금지.
    """
    if override is None:
        return
    if not isinstance(override, dict):
        print(f"  [memory_score] config {label} 타입 오류(dict 기대) — 기본값 사용",
              file=sys.stderr)
        return
    for key, default_val in list(target.items()):
        if key not in override:
            continue
        val = override[key]
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            print(f"  [memory_score] config {label}.{key} 타입 오류 — 기본값 {default_val} 사용",
                  file=sys.stderr)
            continue
        if not allow_zero and val <= 0:
            print(f"  [memory_score] config {label}.{key}={val} (0/음수 금지) — 기본값 {default_val} 사용",
                  file=sys.stderr)
            continue
        if allow_zero and val < 0:
            print(f"  [memory_score] config {label}.{key}={val} (음수 금지) — 기본값 {default_val} 사용",
                  file=sys.stderr)
            continue
        target[key] = float(val)


def _load_memory_score_config(config_file: Path | None = None) -> tuple[dict, dict, dict]:
    """(weights, caps, centrality_weights) 해석. schema/config.yaml의 선택적
    `memory_score:` 섹션으로 override. 부재/부분/오류는 항별 기본값으로 안전 폴백."""
    weights = dict(MEMORY_SCORE_WEIGHTS_DEFAULT)
    caps = dict(MEMORY_SCORE_CAPS_DEFAULT)
    cw = dict(MEMORY_SCORE_CENTRALITY_WEIGHTS_DEFAULT)

    if config_file is None:
        config_file = SCHEMA_DIR / "config.yaml"
    if not config_file.exists():
        return weights, caps, cw
    try:
        raw = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"  [memory_score] config.yaml 파싱 실패 — 기본값 사용 ({exc})", file=sys.stderr)
        return weights, caps, cw
    section = raw.get("memory_score") if isinstance(raw, dict) else None
    if not isinstance(section, dict):
        return weights, caps, cw  # memory_score 섹션 없음 → 기본값

    _merge_numeric(weights, section.get("weights"), "weights", allow_zero=True)
    _merge_numeric(caps, section.get("caps"), "caps", allow_zero=False)
    _merge_numeric(cw, section.get("centrality_weights"), "centrality_weights", allow_zero=True)
    return weights, caps, cw


def _load_retention_factors(config_file: Path | None = None) -> dict[str, float]:
    """retention→decay factor 맵. schema/config.yaml `memory_score.retention_decay`로
    override. 부재/부분/오류는 항별 기본값으로 안전 폴백(0/양수 허용, 음수만 거부 — durable
    factor 0.0 이 유효해야 하므로 allow_zero=True)."""
    factors = dict(RETENTION_DECAY_FACTORS_DEFAULT)
    if config_file is None:
        config_file = SCHEMA_DIR / "config.yaml"
    if not config_file.exists():
        return factors
    try:
        raw = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"  [retention_decay] config.yaml 파싱 실패 — 기본값 사용 ({exc})", file=sys.stderr)
        return factors
    section = raw.get("memory_score") if isinstance(raw, dict) else None
    override = section.get("retention_decay") if isinstance(section, dict) else None
    _merge_numeric(factors, override, "retention_decay", allow_zero=True)
    return factors


def _retention_factor(fm, factors: dict) -> float:
    """페이지 frontmatter `retention` → decay factor. 부재 → 1.0(seasonal/기본).

    미지 값(맵에 없는 retention 문자열)은 1.0 으로 폴백 + stderr warn (조용한 오분류 금지)."""
    retention = fm.get("retention") if isinstance(fm, dict) else None
    if retention is None:
        return 1.0  # 부재 = 기본 감쇠(seasonal 과 동일), 경고 없음
    key = str(retention)
    if key in factors:
        return float(factors[key])
    print(f"  [retention_decay] 미지 retention 값 '{key}' — 기본 감쇠(1.0) 사용", file=sys.stderr)
    return 1.0


def build_centrality_index(graph_json) -> dict[str, dict]:
    """graph.json 원본 → {slug: node} 인덱스 (page 노드만). 1회 빌드해 재사용."""
    if not isinstance(graph_json, dict):
        return {}
    return {n["id"]: n for n in graph_json.get("nodes", [])
            if isinstance(n, dict) and n.get("kind") == "page" and "id" in n}


def load_graph_index(graph_path: Path | None = None) -> dict[str, dict]:
    """wiki/graph.json 을 읽어 centrality 인덱스 반환. 부재/오류 시 빈 dict (graceful)."""
    if graph_path is None:
        graph_path = WIKI_DIR / "graph.json"
    if not graph_path.exists():
        return {}
    try:
        return build_centrality_index(json.loads(graph_path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return {}


def _centrality_node(graph, slug: str) -> dict:
    """graph 가 원본 json({"nodes":[...]})이든 사전 인덱스({slug:node})든 노드 dict 반환."""
    if not isinstance(graph, dict):
        return {}
    nodes = graph.get("nodes")
    if isinstance(nodes, list):  # 원본 graph.json (소규모 테스트 경로)
        for n in nodes:
            if isinstance(n, dict) and n.get("id") == slug:
                return n
        return {}
    node = graph.get(slug)  # 사전 인덱스 (운영 경로)
    return node if isinstance(node, dict) else {}


def _slug_from_path(value) -> str:
    """'wiki/concepts/foo.md' / 'foo.md' / 'foo' → 'foo' (stem)."""
    if not isinstance(value, str):
        return ""
    return Path(value.strip()).stem


def extract_wikilinks(content: str) -> set[str]:
    return set(re.findall(r"\[\[([^\]|#]+?)(?:\|[^\]]*)?\]\]", content))


def build_express_reuse_index(express_dir: Path | None = None) -> dict[str, int]:
    """express/ 산출물을 스캔해 {slug: 인용한 산출물 수} 반환.

    한 산출물이 같은 slug 를 여러 번 인용해도 +1 (산출물 단위 dedup). 인용 경로:
    frontmatter `sources`/`source_pages`(파일경로 → stem) + 본문 `[[wikilink]]`.
    """
    if express_dir is None:
        express_dir = WIKI_ROOT / "express"
    express_dir = Path(express_dir)
    counts: dict[str, int] = defaultdict(int)
    if not express_dir.exists():
        return {}
    for md in sorted(express_dir.rglob("*.md")):
        try:
            content = md.read_text(encoding="utf-8")
        except OSError:
            continue
        for slug in _express_cited_slugs(content):
            counts[slug] += 1
    return dict(counts)


def _express_cited_slugs(content: str) -> set[str]:
    """한 express 산출물이 인용한 slug 집합 (산출물 단위 dedup용)."""
    try:
        fm, body = frontmatter_utils.read_fm(content)
    except frontmatter_utils.FrontmatterParseError:
        fm, body = {}, content
    slugs: set[str] = set()
    if isinstance(fm, dict):
        for key in ("source_pages", "sources"):
            vals = fm.get(key)
            if isinstance(vals, list):
                for v in vals:
                    slug = _slug_from_path(v)
                    if slug:
                        slugs.add(slug)
    slugs |= extract_wikilinks(body)
    return slugs


def build_episode_ref_index(episodes_dir: Path | None = None) -> dict[str, int]:
    """episodes/ 샤드를 스캔해 {slug: 참조 에피소드 수} 반환.

    task_type=express_* 에피소드는 제외(express_reuse 와 이중계산 방지, Codex C3).
    task_type=reweave 도 제외(v0.3 WS-3) — reweave 는 weak 페이지 목록을 read_pages 로
    기록하므로 집계하면 weak 할수록 점수가 오르는 자기 되먹임이 생긴다(express_* 와 동일 이유).
    에피소드 1건의 read_pages 안 중복 slug 는 1회만 집계(에피소드 단위 dedup).
    """
    if episodes_dir is None:
        episodes_dir = WIKI_ROOT / "episodes"
    episodes_dir = Path(episodes_dir)
    counts: dict[str, int] = defaultdict(int)
    if not episodes_dir.exists():
        return {}
    for shard in sorted(episodes_dir.glob("*.jsonl")):
        try:
            lines = shard.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            task_type = str(rec.get("task_type", ""))
            if task_type == "express" or task_type.startswith("express_"):
                continue  # express_* 제외
            if task_type == "reweave":
                continue  # reweave 제외 — weak 스캔 read_pages 자기 점수 되먹임 차단 (v0.3)
            read_pages = rec.get("read_pages", [])
            if not isinstance(read_pages, list):
                continue
            seen: set[str] = set()
            for p in read_pages:
                slug = _slug_from_path(p)
                if slug and slug not in seen:
                    seen.add(slug)
                    counts[slug] += 1
    return dict(counts)


def _age_days_from_fm(fm, now: datetime | None = None) -> int:
    """frontmatter `created` 와 now 로 age(일) 계산. created 부재/오류 시 0."""
    if now is None:
        now = datetime.now()
    created = fm.get("created") if isinstance(fm, dict) else None
    if not created:
        return 0
    try:
        created_dt = datetime.strptime(str(created), "%Y-%m-%d")
    except (ValueError, TypeError):
        return 0
    return (now - created_dt).days


def _score_terms(entry: dict, graph, fm, weights: dict, caps: dict,
                 centrality_weights: dict, now: datetime | None,
                 retention_factors: dict | None = None) -> dict[str, float]:
    """항별 가중 기여(weight·norm(signal))를 dict로 반환. compute_memory_score/이유 공용.

    retention_factors 미지정 시 기본 감쇠 맵 사용. recency 항은 페이지 `retention`
    (frontmatter)으로 감쇠율이 변조된다(durable=감쇠 없음, ephemeral=빠른 감쇠)."""
    if retention_factors is None:
        retention_factors = RETENTION_DECAY_FACTORS_DEFAULT
    slug = entry.get("slug", "")
    node = _centrality_node(graph, slug)
    inbound = _as_num(node.get("inbound", 0))
    betweenness = _as_num(node.get("betweenness", 0.0))
    centrality = (centrality_weights["inbound"] * inbound
                  + centrality_weights["betweenness"] * betweenness)

    age_days = entry.get("age_days")
    if age_days is None:
        age_days = _age_days_from_fm(fm, now)
    source_count = len(fm.get("sources") or []) if isinstance(fm, dict) else 0
    decay_factor = _retention_factor(fm, retention_factors)

    return {
        "express_reuse": weights["express_reuse"] * _norm(entry.get("express_reuse", 0), caps["express_reuse"]),
        "episode_ref": weights["episode_ref"] * _norm(entry.get("episode_ref", 0), caps["episode_ref"]),
        "centrality": weights["centrality"] * _norm(centrality, caps["centrality"]),
        "access_count": weights["access_count"] * _norm(entry.get("access_count", 0), caps["access_count"]),
        "recency": weights["recency"] * _recency_score(age_days, decay_factor),
        "source_count": weights["source_count"] * _norm(source_count, caps["source_count"]),
    }


def compute_memory_score(entry: dict, graph, fm: dict, *, weights: dict | None = None,
                         caps: dict | None = None, centrality_weights: dict | None = None,
                         now: datetime | None = None) -> float:
    """slug 1개의 meta-memory 점수(0~100, 재사용 우선·결정적). SPEC §C4.

    entry: 호출측이 채운 신호 묶음 {slug, access_count, age_days, express_reuse,
           episode_ref}. 누락 신호는 0으로 본다.
    graph: graph.json 원본 dict({"nodes":..}) 또는 사전 인덱스({slug: node}).
    fm:    페이지 frontmatter dict — source_count = len(sources).
    weights/caps/centrality_weights 미지정 시 config(또는 기본값) 1회 로드.
    now:   age_days 부재 시 recency 계산에만 사용(주입으로 결정성 보장).
    """
    if weights is None and caps is None and centrality_weights is None:
        weights, caps, centrality_weights = _load_memory_score_config()
        retention_factors = _load_retention_factors()
    else:
        weights = {**MEMORY_SCORE_WEIGHTS_DEFAULT, **(weights or {})}
        caps = {**MEMORY_SCORE_CAPS_DEFAULT, **(caps or {})}
        centrality_weights = {**MEMORY_SCORE_CENTRALITY_WEIGHTS_DEFAULT, **(centrality_weights or {})}
        retention_factors = dict(RETENTION_DECAY_FACTORS_DEFAULT)

    terms = _score_terms(entry, graph, fm, weights, caps, centrality_weights, now, retention_factors)
    return round(sum(terms.values()), 4)


def memory_reason(terms: dict[str, float]) -> str:
    """기여가 가장 큰 신호를 사람이 읽는 사유 라벨로. 전부 0이면 '신호 없음'."""
    if not terms or max(terms.values()) <= 0:
        return "신호 없음"
    top = max(terms, key=lambda k: (terms[k], k))
    return _REASON_LABEL.get(top, top)
