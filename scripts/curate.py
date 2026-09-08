#!/usr/bin/env python3
"""
curate.py — wiki 감사(audit) + 압축(distill) + 수명 관리(lifecycle) + 링크 분석(graph).

사용법:
  python scripts/curate.py --all
  python scripts/curate.py --audit
  python scripts/curate.py --distill
  python scripts/curate.py --lifecycle
  python scripts/curate.py --graph
  python scripts/curate.py --reweave [--fix] [--dry-run] [--weekly-summary]
"""
import argparse
import fcntl
import json
import logging
import math
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import yaml

import episode  # 로컬 모듈 (scripts/ on sys.path) — US-002 curate 실행 episode 기록
from lib import frontmatter_utils, gates  # v0.3 reweave — 만료 판정(gates)·body 무손상 쓰기
# v0.3.1 Wave 6 — 순수 결정적 코어 배선(import만, 로직 수정 금지).
#   reconcile: 모순 후보 탐지 → contradiction_queue.md (WS-5 결정적 부분)
#   synthesis: 종합 대상 선정·shrink 가드 → reweave_queue.md synthesis 섹션 (WS-1 결정적 부분)
from lib import reconcile, synthesis
from lib import memory_score  # 점수 코어 (v0.3 선행 추출 — lib/gates.py 와 공유)
# merge-review 유사도 토큰 — lib/gates.py 와 단일 구현 공유 (중복 제거, parity 테스트 유지).
from lib.gates import _merge_token_set  # noqa: F401
# 점수 코어 re-export — 기존 공개 이름 유지(테스트·wiki_app·memory_health 무수정 호환).
# 경로 기본값을 갖는 5개 로더(_load_memory_score_config 등)는 아래 wrapper 로 노출한다
# (이 모듈 전역 WIKI_ROOT/WIKI_DIR/SCHEMA_DIR 주입 — 테스트 monkeypatch 대상이기 때문).
from lib.memory_score import (  # noqa: F401  (re-export)
    MEMORY_SCORE_WEIGHTS_DEFAULT,
    MEMORY_SCORE_CAPS_DEFAULT,
    MEMORY_SCORE_CENTRALITY_WEIGHTS_DEFAULT,
    RECENCY_FULL_DAYS,
    RECENCY_ZERO_DAYS,
    RETENTION_DECAY_FACTORS_DEFAULT,
    RESCUE_TOP_PCT_DEFAULT,
    _REASON_LABEL,
    _as_num,
    _norm,
    _recency_score,
    _merge_numeric,
    _retention_factor,
    build_centrality_index,
    _centrality_node,
    _slug_from_path,
    extract_wikilinks,
    _express_cited_slugs,
    _age_days_from_fm,
    _score_terms,
    compute_memory_score,
    memory_reason,
)

logger = logging.getLogger(__name__)

WIKI_ROOT = Path(__file__).parent.parent
WIKI_DIR = WIKI_ROOT / "wiki"
SCHEMA_DIR = WIKI_ROOT / "schema"
LOG_FILE = WIKI_ROOT / "log.md"
REPORT_FILE = WIKI_DIR / "curate_report.md"
DISTILL_QUEUE_FILE = WIKI_DIR / "distill_queue.md"
# v0.3.1 큐/스냅샷 — 파일명 상수만 두고 경로는 WIKI_DIR/WIKI_ROOT 로 **동적 결합**한다
# (REWEAVE_QUEUE_NAME 선례). 모듈 로드 시 경로를 굳히면 테스트 monkeypatch(WIKI_DIR)가
# 흘러가지 못해 실제 wiki/ 로 쓰기가 새기 때문.
CONTRADICTION_QUEUE_NAME = "contradiction_queue.md"  # WS-5 모순 후보 큐 (후보 0이면 미생성)
SYNTHESIS_SNAPSHOT_NAME = ".synthesis_snapshot.json"  # WS-1 shrink 가드 대상 한정 스냅샷(gitignored)
# 종합 큐 상한 — 조밀하게 연결된 실 wiki 는 자격 기준만으론 대부분이 종합 대상이 되어
# 우선순위 신호가 희석된다(실측: 109p 중 103p). 점수 상위 N개만 큐잉해 실용화한다.
SYNTHESIS_QUEUE_LIMIT = 15
WIKI_STATS_FILE = WIKI_ROOT / "wiki_stats.json"
# lifecycle 제외 도메인 (ttl_days: 0인 것들) + gates 관리 폴더(observing·rejected —
# 만료는 gates 가 자체 관리하므로 TTL decay 대상이 아니다. SPEC v0.3 §D 3점 방어)
LIFECYCLE_EXEMPT = {"concepts", "tools", "people", "projects", "business", "lecture",
                    "observing", "rejected"}


# ── Stats (access tracking) ────────────────────────────────────────────
#
# wiki_stats.json 갱신은 web(wiki_app.access.track)과 CLI(record_access) 두
# 프로세스가 동시에 read-modify-write할 수 있다. 무잠금이면 lost update가
# 발생하고, 한쪽이 write_text 도중일 때 다른 쪽이 json.loads하면 partial-read로
# 파싱 실패한다. 그래서 두 경로가 **같은 lockfile**을 flock으로 잡은 상태에서
# atomic replace(temp + os.replace)로 저장하는 단일 shared helper로 통합한다.
#
# lockfile은 stats 파일과 같은 디렉토리에 둔다 (stats_lock_path). web/CLI가
# stats 파일 위치를 단일 기준으로 공유하므로 lockfile도 같은 경로로 수렴한다.
# 둘이 다른 파일을 잠그면 flock 직렬화가 무의미해지기 때문이다.

_STATS_LOCKFILE_NAME = ".access.lock"


def stats_lock_path(stats_file: Path) -> Path:
    """stats_file과 동일 디렉토리의 lockfile 경로.

    web(access.py)과 CLI(여기)가 같은 stats_file을 경쟁하므로 둘 다 이 함수가
    돌려주는 단일 경로를 flock 대상으로 써야 직렬화가 성립한다.
    """
    return stats_file.parent / _STATS_LOCKFILE_NAME


def load_wiki_stats() -> dict:
    """wiki_stats.json 로드. 없으면 빈 dict 반환."""
    if WIKI_STATS_FILE.exists():
        return json.loads(WIKI_STATS_FILE.read_text())
    return {}


def _atomic_write_text(path: Path, text: str) -> None:
    """임시 파일에 쓴 뒤 os.replace로 원자적 교체.

    flock을 잡은 상태에서도 write_text는 truncate→write의 비원자적 구간이 생겨
    별도 프로세스가 그 사이 partial-read로 깨진 JSON을 읽을 수 있다. temp +
    os.replace는 reader에게 항상 old 또는 new 완전본만 보이도록 보장한다.
    """
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def write_stats_access(slug: str, stats_file: Path) -> int:
    """slug의 access_count를 1 증가시켜 stats_file에 atomic replace로 기록 (lock 없음).

    **호출자는 반드시 stats_lock_path(stats_file)에 flock을 잡은 상태여야 한다.**
    이 함수 자체는 lock을 잡지 않는다 — web(access.track)은 frontmatter 갱신과
    함께 하나의 flock 안에서 이 core를 호출하고, CLI(update_stats_access)는 lock을
    잡은 뒤 이 core를 호출한다. 동일 프로세스에서 같은 lockfile을 두 fd로 중첩
    flock하면 self-deadlock하므로 lock 획득은 단일 지점(호출자)에 둔다.

    엔트리 형태:
        {"access_count": int, "last_accessed": "YYYY-MM-DD"}
    """
    stats: dict = {}
    if stats_file.exists():
        stats = json.loads(stats_file.read_text(encoding="utf-8"))
    entry = stats.get(slug, {"access_count": 0, "last_accessed": None})
    entry["access_count"] = int(entry.get("access_count") or 0) + 1
    entry["last_accessed"] = datetime.now().strftime("%Y-%m-%d")
    stats[slug] = entry
    _atomic_write_text(
        stats_file, json.dumps(stats, ensure_ascii=False, indent=2)
    )
    return entry["access_count"]


def update_stats_access(slug: str, stats_file: Path) -> int:
    """slug의 access_count를 1 증가시켜 stats_file(wiki_stats.json)에 기록한다.

    web(access.track)과 CLI(record_access)가 공유하는 단일 helper. stats_file
    기준 같은 lockfile을 flock(LOCK_EX)으로 잡은 상태에서 read-modify-write를
    수행하고 atomic replace로 저장해 cross-process lost update / partial-read를
    막는다. 갱신된 access_count를 반환한다.
    """
    lock_path = stats_lock_path(stats_file)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        return write_stats_access(slug, stats_file)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def record_access(page_slug: str) -> None:
    """query 모드(CLI)에서 호출. page_slug의 access_count를 wiki_stats.json에 기록.

    web(access.track)과 동일한 shared helper(update_stats_access)를 써서 같은
    lockfile을 flock으로 잡은 상태에서 atomic replace한다.
    """
    new_count = update_stats_access(page_slug, WIKI_STATS_FILE)
    print(f"  [stats] {page_slug} access_count={new_count}")


# ── Frontmatter helpers ────────────────────────────────────────────────

_FM_PATTERN = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


class FrontmatterParseError(ValueError):
    """frontmatter 블록은 있으나 YAML 파싱에 실패했거나 dict가 아닐 때 raise.

    fail-loud: 조용히 ({}, body)를 반환하면 호출부가 "frontmatter 없음"으로 오인해
    기존 필드(title·type·tags·created·sources 등)를 덮어써 영구 삭제하는
    silent data-loss가 발생한다. 그래서 파싱 실패를 명확히 신호한다.

    invalid YAML뿐 아니라 valid YAML이지만 non-dict(list/scalar 등)인 경우도
    포함한다. 호출부(ensure_distill_fields·access tracking)는 frontmatter를
    dict로 가정해 키를 대입하는데, list/scalar면 TypeError로 크래시하거나
    (access 경로처럼 예외가 삼켜지면) 카운트 누락이 발생하기 때문이다.
    """


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """(frontmatter_dict, body) 반환. frontmatter 없으면 ({}, content).

    frontmatter 블록은 존재하나 YAML이 invalid거나 dict가 아니면
    FrontmatterParseError를 raise한다 (조용한 {} 반환 금지 — 호출부의
    덮어쓰기로 인한 데이터 손실 방지). 빈 블록(safe_load → None)은 정상으로
    보고 ({}, body)를 반환한다.
    """
    m = _FM_PATTERN.match(content)
    if not m:
        return {}, content
    try:
        loaded = yaml.safe_load(m.group(1))
    except yaml.YAMLError as exc:
        raise FrontmatterParseError(str(exc)) from exc
    # 빈 블록(None)은 정상 — {}로 취급. list/scalar 등 non-dict는 fail-loud.
    if loaded is None:
        fm: dict = {}
    elif isinstance(loaded, dict):
        fm = loaded
    else:
        raise FrontmatterParseError(
            f"frontmatter는 dict여야 하나 {type(loaded).__name__}을 받음: {loaded!r}"
        )
    body = content[m.end():]
    return fm, body


def serialize_frontmatter(fm: dict, body: str) -> str:
    dumped = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False)
    return f"---\n{dumped}---{body}"


def ensure_distill_fields(page: Path) -> dict | None:
    """
    distill_level / access_count / last_accessed / last_distilled 필드가
    없으면 기본값으로 추가하고 파일을 갱신한다. 갱신된 frontmatter 반환.

    frontmatter YAML 파싱에 실패한 페이지는 절대 rewrite하지 않는다
    (skip + warning) → 원본을 그대로 보존하고 None을 반환한다.

    None 반환은 호출부(run_distill)가 "parse 실패"를 "정상 빈 frontmatter({})"와
    구별하기 위한 sentinel이다. {}를 반환하면 run_distill이 정상 빈 페이지로 보고
    wiki_stats의 access_count를 적용해 distill 후보(rewrite 대상)에 추가하는데,
    이는 fail-loud로 보호한 페이지를 다시 Claude distill 대상으로 만들어 데이터
    손실 경로를 재개방한다. parse 실패 페이지는 후보 산정에서 완전히 제외해야 한다.
    """
    content = page.read_text()
    try:
        fm, body = parse_frontmatter(content)
    except FrontmatterParseError as exc:
        logger.warning(
            "frontmatter 파싱 실패 — 원본 보존하고 건너뜀: %s (%s)",
            page, exc,
        )
        return None
    changed = False
    for field, default in [
        ("distill_level", 0),
        ("access_count", 0),
        ("last_accessed", None),
        ("last_distilled", None),
    ]:
        if field not in fm:
            fm[field] = default
            changed = True
    if changed:
        page.write_text(serialize_frontmatter(fm, body))
    return fm


# ── Memory score (US-006) — 점수 코어는 lib/memory_score.py 로 추출됨 ──
#
# v0.3 선행 리팩터(SPEC "v0.3 Quality-Driven Curation — 설계" §B): 상수·순수
# 함수는 파일 상단에서 re-export 하고, 경로 기본값이 이 모듈 전역(WIKI_ROOT/
# WIKI_DIR/SCHEMA_DIR — 테스트가 monkeypatch 하는 대상)에 묶인 로더 5개만 아래
# 얇은 위임 wrapper 로 유지한다. 동작 무변경 (점수 로직·폴백·경고 전부
# lib/memory_score.py 에 그대로).


def _load_memory_score_config(config_file: Path | None = None) -> tuple[dict, dict, dict]:
    """(weights, caps, centrality_weights) 해석 — lib/memory_score 위임.

    config_file 미지정 시 이 모듈의 SCHEMA_DIR/config.yaml 을 주입한다
    (테스트 monkeypatch(curate.SCHEMA_DIR) 호환)."""
    if config_file is None:
        config_file = SCHEMA_DIR / "config.yaml"
    return memory_score._load_memory_score_config(config_file)


def _load_retention_factors(config_file: Path | None = None) -> dict[str, float]:
    """retention→decay factor 맵 — lib/memory_score 위임 (경로 주입 wrapper)."""
    if config_file is None:
        config_file = SCHEMA_DIR / "config.yaml"
    return memory_score._load_retention_factors(config_file)


def load_graph_index(graph_path: Path | None = None) -> dict[str, dict]:
    """wiki/graph.json → centrality 인덱스 — lib/memory_score 위임 (경로 주입 wrapper)."""
    if graph_path is None:
        graph_path = WIKI_DIR / "graph.json"
    return memory_score.load_graph_index(graph_path)


def build_express_reuse_index(express_dir: Path | None = None) -> dict[str, int]:
    """express/ 재사용 인덱스 — lib/memory_score 위임 (경로 주입 wrapper)."""
    if express_dir is None:
        express_dir = WIKI_ROOT / "express"
    return memory_score.build_express_reuse_index(express_dir)


def build_episode_ref_index(episodes_dir: Path | None = None) -> dict[str, int]:
    """episodes/ 참조 인덱스 — lib/memory_score 위임 (경로 주입 wrapper)."""
    if episodes_dir is None:
        episodes_dir = WIKI_ROOT / "episodes"
    return memory_score.build_episode_ref_index(episodes_dir)


# ── Audit ─────────────────────────────────────────────────────────────

def find_all_wiki_pages() -> list[Path]:
    excluded = {
        "curate_report.md",
        "distill_queue.md",
        "graph_report.md",
        "reweave_queue.md",
        "contradiction_queue.md",  # v0.3.1 WS-5 운영 큐 — 정규 스캔에서 격리
    }
    # observing/·rejected/ 는 gates 관리 폴더(사적 판단 로그) — 정규 audit/distill/
    # lifecycle/merge-review 스캔에서 격리한다 (SPEC v0.3 §D 3점 방어 중 코드 측).
    # run_reweave 의 만료 처리만 observing/ 을 직접 스캔한다.
    excluded_dirs = {"archive", "observing", "rejected"}
    return [p for p in WIKI_DIR.rglob("*.md")
            if p.name not in excluded and not excluded_dirs & set(p.parts)]


def build_link_graph(pages: list[Path]) -> tuple[dict, dict]:
    outbound: dict[str, set[str]] = {}
    inbound: dict[str, set[str]] = defaultdict(set)
    page_names = {p.stem for p in pages}

    for page in pages:
        name = page.stem
        links = extract_wikilinks(page.read_text())
        valid = links & page_names
        outbound[name] = valid
        for target in valid:
            inbound[target].add(name)

    return outbound, dict(inbound)


def _project_pages(pages: list[Path]) -> list[gates.ExistingPage]:
    """wiki 페이지들을 gates.ExistingPage(slug·frontmatter·body) 로 투영한다.

    reconcile/synthesis 순수 코어가 요구하는 입력 형태(SPEC §A: I/O 는 호출측이 수행해
    주입). frontmatter 파싱 실패 페이지는 fail-loud 로 건너뛴다(원본 불간섭 — find_merge_
    candidates 와 동일 방침). slug=파일 stem."""
    out: list[gates.ExistingPage] = []
    for page in pages:
        try:
            fm, body = parse_frontmatter(page.read_text(encoding="utf-8"))
        except (OSError, FrontmatterParseError):
            continue
        out.append(gates.ExistingPage(slug=page.stem, frontmatter=fm, body=body))
    return out


def _latest_raw_source() -> reconcile.NewSource | None:
    """raw/ 에서 가장 최근(mtime) ingest 된 .md/.txt 를 신규 근거로 투영한다.

    reconcile.detect_contradiction_candidates 의 new_source 재료. raw/ 부재·후보 없음이면
    None(→ 모순 후보 0 → 큐 미생성, 보수적). frontmatter 파싱 실패는 frontmatter 없음으로
    간주({}, 전체 본문) — 주제 겹침 토큰이 비면 어차피 후보가 안 잡힌다(오탐 방지)."""
    raw_dir = WIKI_ROOT / "raw"
    if not raw_dir.is_dir():
        return None
    candidates = [p for p in raw_dir.rglob("*")
                  if p.is_file() and p.suffix in {".md", ".txt"}]
    if not candidates:
        return None
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    try:
        fm, body = parse_frontmatter(latest.read_text(encoding="utf-8"))
    except (OSError, FrontmatterParseError):
        try:
            fm, body = {}, latest.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    return reconcile.NewSource(
        source_ref=str(latest.relative_to(WIKI_ROOT)),
        text=body,
        frontmatter=fm if isinstance(fm, dict) else {},
    )


def _write_contradiction_queue(candidates: list, now: datetime) -> None:
    """모순 후보를 contradiction_queue.md 로 직렬화 (distill_queue.md 동일 체크박스 패턴).

    LLM 컴파일러가 `commands/curate.md` Step 에서 소비해 `schema/curate.md`
    `## Reconciliation Rules` 에 따라 `## 반론/갱신` 을 작성한다. 후보 0이면 이 함수는
    호출되지 않는다(run_audit 이 미생성 — 오탐 시 남발 방지, 보수적)."""
    ts = now.strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Contradiction Queue — {ts}\n",
        "> 이 파일은 `curate --audit`가 생성합니다. Claude Code가 읽고 "
        "`schema/curate.md`의 `## Reconciliation Rules`에 따라 해당 페이지에 "
        "`## 반론/갱신 (YYYY-MM-DD)` 3요소를 append 하세요 (자동 편집 아님 — 사람/LLM 판단).\n",
        f"\n## 모순 후보 ({len(candidates)}개)",
        "> 신호 = 상반 극 · 겹침 = 주제 토큰 교집합 · 우선순위 = 리뷰 힌트. "
        "옛 주장 삭제 금지 — `superseded_claims` 표시만.\n",
    ]
    for c in candidates:
        overlap = ", ".join(c.overlap_terms)
        lines.append(
            f"- [ ] [[{c.existing_slug}]] ↔ {c.new_source_ref} — "
            f"신호 {c.signal} · 겹침 {overlap} · 우선순위 {c.confidence_hint}"
        )
        lines.append(f'      기존 주장: "{c.existing_claim}"')
        lines.append(f'      신규 근거: "{c.new_claim}"')
    (WIKI_DIR / CONTRADICTION_QUEUE_NAME).write_text("\n".join(lines))


def run_audit(pages: list[Path]) -> dict:
    _, inbound = build_link_graph(pages)
    now = datetime.now()

    orphans, stale_links = [], []

    for page in pages:
        name = page.stem
        mtime = datetime.fromtimestamp(page.stat().st_mtime)
        age_days = (now - mtime).days
        in_count = len(inbound.get(name, set()))

        if in_count == 0 and age_days > 30:
            orphans.append({
                "path": str(page.relative_to(WIKI_ROOT)),
                "age_days": age_days,
                "inbound": 0,
            })

    # Stale link 탐지
    page_names = {p.stem for p in pages}
    for page in pages:
        content = page.read_text()
        links = extract_wikilinks(content)
        missing = links - page_names
        for m in missing:
            stale_links.append({
                "source": str(page.relative_to(WIKI_ROOT)),
                "missing_target": m,
            })

    # 모순 후보 탐지 (v0.3.1 WS-5 결정적 부분) — 가장 최근 raw 근거 × 기존 페이지 대조.
    #   reconcile 순수 코어에 위임(정밀도 우선·보수적). 후보 0이면 큐 미생성(오탐 남발 방지).
    contradictions: list = []
    new_source = _latest_raw_source()
    if new_source is not None:
        contradictions = reconcile.detect_contradiction_candidates(
            new_source, _project_pages(pages))
    if contradictions:
        _write_contradiction_queue(contradictions, now)
        print(f"  [audit] 모순 후보 {len(contradictions)}개 → wiki/contradiction_queue.md 저장")

    return {"orphans": orphans, "stale_links": stale_links, "contradictions": contradictions}


# ── Merge-review (US-006, 결정적 근접 중복 표면화 — 임베딩 없음) ──────────
#
# 같은 카테고리 디렉토리 안의 페이지 쌍을 (소문자 제목 토큰 ∪ 소문자 태그) 집합의
# Jaccard 유사도로 비교해 임계 이상이면 후보로 표면화한다. **자동 병합 금지(Rule 9)** —
# write_report 의 별도 섹션에 후보만 나열하고 사람이 병합을 판단한다. 카테고리 경계는
# 넘지 않는다(카테고리 분리는 의도된 의미 구분 — 교차 카테고리 동명은 거짓양성).

MERGE_SIMILARITY_DEFAULT = 0.6


def _load_merge_threshold(config_file: Path | None = None) -> float:
    """merge-review Jaccard 임계. schema/config.yaml `merge_review.similarity_threshold`
    로 override. 부재/타입오류/범위 밖(0..1)이면 기본값 + stderr warn (조용한 오작동 금지)."""
    if config_file is None:
        config_file = SCHEMA_DIR / "config.yaml"
    if not config_file.exists():
        return MERGE_SIMILARITY_DEFAULT
    try:
        raw = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"  [merge_review] config.yaml 파싱 실패 — 기본값 사용 ({exc})", file=sys.stderr)
        return MERGE_SIMILARITY_DEFAULT
    section = raw.get("merge_review") if isinstance(raw, dict) else None
    val = section.get("similarity_threshold") if isinstance(section, dict) else None
    if val is None:
        return MERGE_SIMILARITY_DEFAULT
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        print(f"  [merge_review] similarity_threshold 타입 오류 — 기본값 {MERGE_SIMILARITY_DEFAULT} 사용",
              file=sys.stderr)
        return MERGE_SIMILARITY_DEFAULT
    if not 0.0 <= val <= 1.0:
        print(f"  [merge_review] similarity_threshold={val} 범위 밖(0..1) — 기본값 {MERGE_SIMILARITY_DEFAULT} 사용",
              file=sys.stderr)
        return MERGE_SIMILARITY_DEFAULT
    return float(val)


# _merge_token_set 은 lib/gates.py 의 동일 구현을 import 해 재사용한다 (파일 상단 참조).
# 중복 정의를 제거해 유사도 토큰 규칙의 단일 출처를 gates 로 수렴 (parity 테스트: test_gates).


def find_merge_candidates(pages: list[Path], *, threshold: float | None = None) -> list[dict]:
    """같은 카테고리 디렉토리 내 페이지 쌍의 근접 중복 후보를 결정적으로 표면화.

    유사도 = (소문자 제목 토큰 ∪ 소문자 태그) 집합의 Jaccard. threshold 이상인 쌍만
    후보. threshold 미지정 시 config(또는 기본 0.6) 로드. **카테고리(부모 디렉토리)
    경계는 넘지 않는다** — 교차 카테고리 동명은 의도된 의미 구분이라 비교 대상 아님.
    정렬: similarity 내림차순, 동점은 (a, b) slug 오름차순(결정성). **자동 병합하지
    않는다(Rule 9)** — 후보만 반환하고 사람이 병합 판단.

    반환: [{"a": slugA, "b": slugB, "similarity": float, "reason": str}] (a < b).
    """
    if threshold is None:
        threshold = _load_merge_threshold()

    by_category: dict[str, list[tuple[str, set[str]]]] = defaultdict(list)
    for page in pages:
        try:
            fm, _ = parse_frontmatter(page.read_text(encoding="utf-8"))
        except (OSError, FrontmatterParseError):
            continue  # 읽기/파싱 실패 페이지는 비교에서 제외(원본 불간섭)
        by_category[page.parent.name].append((page.stem, _merge_token_set(fm)))

    candidates: list[dict] = []
    for members in by_category.values():
        for i in range(len(members)):
            slug_i, set_i = members[i]
            for j in range(i + 1, len(members)):
                slug_j, set_j = members[j]
                union = set_i | set_j
                if not union:
                    continue  # 둘 다 토큰 없음 → 유사도 정의 불가(0으로 본다)
                sim = len(set_i & set_j) / len(union)
                if sim < threshold:
                    continue
                a, b = sorted((slug_i, slug_j))
                shared = ", ".join(sorted(set_i & set_j))
                candidates.append({
                    "a": a, "b": b,
                    "similarity": round(sim, 4),
                    "reason": f"제목·태그 유사 (공통 {len(set_i & set_j)}개: {shared})",
                })
    candidates.sort(key=lambda c: (-c["similarity"], c["a"], c["b"]))
    return candidates


# ── Distill ────────────────────────────────────────────────────────────

def run_distill(pages: list[Path]) -> list[str]:
    """
    wiki 전체를 스캔해 distill 후보를 분류하고 distill_queue.md에 저장한다.
    실제 LLM 압축은 Claude Code가 이 파일을 읽고 실행한다.

    반환값: distill 큐에 추가된 페이지 경로 목록.
    """
    now = datetime.now()
    stats = load_wiki_stats()

    # plug-in ① (US-006): tier 내 정렬용 memory_score 입력 인덱스를 1회 빌드.
    # 임계 게이트(아래 access≥10 등)는 유지 — 점수는 tier '내부 정렬'에만 쓴다.
    graph_index = load_graph_index()
    express_idx = build_express_reuse_index()
    episode_idx = build_episode_ref_index()
    ms_weights, ms_caps, ms_cw = _load_memory_score_config()
    ms_retention = _load_retention_factors()

    urgent: list[dict] = []    # access_count >= 10 AND distill_level < 3
    priority: list[dict] = []  # access_count >= 5  AND distill_level < 2
    lifecycle_via_distill: list[dict] = []  # access_count == 0 AND 90일+

    for page in pages:
        # frontmatter 필드 보장
        fm = ensure_distill_fields(page)

        # parse 실패 페이지(None)는 distill 후보 산정에서 완전히 skip한다.
        # fail-loud로 원본을 보존한 페이지를 다시 distill(rewrite) 대상으로 만들면
        # 데이터 손실 경로가 재개방되므로, urgent/priority/lifecycle 어디에도
        # 넣지 않는다 (access_count가 아무리 높아도).
        if fm is None:
            continue

        # wiki_stats.json의 access_count를 frontmatter와 동기
        slug = page.stem
        stats_entry = stats.get(slug, {})
        stats_access = stats_entry.get("access_count", 0)
        # 둘 중 큰 값을 사용 (두 소스 중 최신 반영)
        access_count = max(fm.get("access_count", 0), stats_access)

        distill_level = fm.get("distill_level", 0)
        created_raw = fm.get("created")
        if created_raw:
            try:
                created_dt = datetime.strptime(str(created_raw), "%Y-%m-%d")
                age_days = (now - created_dt).days
            except ValueError:
                age_days = 0
        else:
            mtime = datetime.fromtimestamp(page.stat().st_mtime)
            age_days = (now - mtime).days

        rel_path = str(page.relative_to(WIKI_ROOT))
        entry = {
            "path": rel_path,
            "slug": slug,
            "distill_level": distill_level,
            "access_count": access_count,
            "age_days": age_days,
            "express_reuse": express_idx.get(slug, 0),
            "episode_ref": episode_idx.get(slug, 0),
        }
        # plug-in ①: tier 내 정렬용 memory_score + 사유 (임계 게이트는 그대로 유지).
        terms = _score_terms(entry, graph_index, fm, ms_weights, ms_caps, ms_cw, now, ms_retention)
        entry["memory_score"] = round(sum(terms.values()), 4)
        entry["memory_reason"] = memory_reason(terms)

        if access_count >= 10 and distill_level < 3:
            urgent.append(entry)
        elif access_count >= 5 and distill_level < 2:
            priority.append(entry)
        elif access_count == 0 and age_days > 90:
            lifecycle_via_distill.append(entry)

    # distill_queue.md 작성
    ts = now.strftime("%Y-%m-%d %H:%M")
    lines = [f"# Distill Queue — {ts}\n",
             "> 이 파일은 `curate --distill`이 생성합니다. Claude Code가 읽고 순서대로 압축을 실행하세요.\n"]

    # plug-in ①: tier 내 정렬은 memory_score 내림차순(동점은 slug 오름차순으로 결정적).
    def _by_score(entries: list[dict]) -> list[dict]:
        return sorted(entries, key=lambda x: (-x["memory_score"], x["slug"]))

    lines.append(f"\n## 긴급 후보 (access ≥ 10, distill_level < 3) — {len(urgent)}개")
    lines.append("우선순위 1: 즉시 압축 필요 (정렬: memory_score 내림차순)\n")
    for e in _by_score(urgent):
        lines.append(
            f"- [ ] `{e['path']}` — score={e['memory_score']:.1f} ({e['memory_reason']}), "
            f"access={e['access_count']}, level={e['distill_level']}, age={e['age_days']}일"
        )

    lines.append(f"\n## 우선 후보 (access ≥ 5, distill_level < 2) — {len(priority)}개")
    lines.append("우선순위 2: 다음 사이클에 압축 (정렬: memory_score 내림차순)\n")
    for e in _by_score(priority):
        lines.append(
            f"- [ ] `{e['path']}` — score={e['memory_score']:.1f} ({e['memory_reason']}), "
            f"access={e['access_count']}, level={e['distill_level']}, age={e['age_days']}일"
        )

    lines.append(f"\n## Lifecycle 후보 (access=0, 90일+) — {len(lifecycle_via_distill)}개")
    lines.append("우선순위 3: `curate --lifecycle` 또는 삭제 검토 (정렬: memory_score 내림차순)\n")
    for e in _by_score(lifecycle_via_distill):
        lines.append(
            f"- [ ] `{e['path']}` — score={e['memory_score']:.1f} ({e['memory_reason']}), "
            f"age={e['age_days']}일, access=0"
        )

    DISTILL_QUEUE_FILE.write_text("\n".join(lines))
    total = len(urgent) + len(priority)
    print(f"  [distill] 긴급={len(urgent)}, 우선={len(priority)}, lifecycle={len(lifecycle_via_distill)} → wiki/distill_queue.md 저장")

    all_candidates = [e["path"] for e in urgent + priority]
    return all_candidates


# ── Lifecycle ──────────────────────────────────────────────────────────

def _load_sources_config() -> dict:
    """schema/sources.yaml을 읽는다. 없으면 sources.example.yaml로 폴백,
    둘 다 없으면 빈 config로 graceful 진행 (fresh clone에서 크래시 금지)."""
    sources_file = SCHEMA_DIR / "sources.yaml"
    if not sources_file.exists():
        example = SCHEMA_DIR / "sources.example.yaml"
        if example.exists():
            print(f"  [lifecycle] sources.yaml 없음 — {example.name}로 폴백")
            sources_file = example
        else:
            print("  [lifecycle] sources.yaml/sources.example.yaml 모두 없음 — lifecycle 건너뜀")
            return {}
    return yaml.safe_load(sources_file.read_text()) or {}


def run_lifecycle(pages: list[Path]) -> dict:
    config = _load_sources_config()
    lifecycle = config.get("lifecycle", {})
    now = datetime.now()
    _, inbound = build_link_graph(pages)

    # plug-in ② (US-006): rescue 판정용 memory_score 입력 인덱스 1회 빌드.
    graph_index = load_graph_index()
    express_idx = build_express_reuse_index()
    episode_idx = build_episode_ref_index()
    ms_weights, ms_caps, ms_cw = _load_memory_score_config()
    ms_retention = _load_retention_factors()

    archive_candidates, delete_candidates = [], []

    for page in pages:
        domain = page.parent.name
        if domain in LIFECYCLE_EXEMPT:
            continue

        domains_cfg = lifecycle.get("domains", {})
        ttl = domains_cfg.get(domain, {})
        ttl_days = ttl if isinstance(ttl, int) else ttl.get("ttl_days", 0)
        if ttl_days == 0:
            continue

        mtime = datetime.fromtimestamp(page.stat().st_mtime)
        age_days = (now - mtime).days
        in_count = len(inbound.get(page.stem, set()))

        if age_days > ttl_days and in_count == 0:
            archive_candidates.append({
                "path": str(page.relative_to(WIKI_ROOT)),
                "age_days": age_days,
                "inbound": in_count,
            })
        if age_days > ttl_days * 2 and in_count <= 1:
            delete_candidates.append({
                "path": str(page.relative_to(WIKI_ROOT)),
                "age_days": age_days,
                "inbound": in_count,
            })

    # plug-in ② rescue: archive 후보(age>ttl AND inbound==0)에 memory_score 를 매겨
    # 상위 N%(상대 임계)는 archive 에서 *제외* → 보존(promote/keep-review). "재사용되나
    # inbound 0인 orphan"이 영구 소실되는 것을 막는 핵심 지점(SPEC §C4). 점수 0(=재사용
    # 신호 전무)은 보존하지 않아 정상 decay 페이지의 무한 적체를 막는다.
    rescued, archive_candidates = _rescue_split(
        archive_candidates, graph_index, express_idx, episode_idx,
        ms_weights, ms_caps, ms_cw, now, ms_retention,
    )
    rescued_paths = {r["path"] for r in rescued}
    # 보존된 페이지는 delete 후보에서도 빼준다(같은 orphan 이 delete 게이트로 다시 잡힐 수 있음).
    delete_candidates = [d for d in delete_candidates if d["path"] not in rescued_paths]

    return {"archive": archive_candidates, "delete": delete_candidates, "rescued": rescued}


def _rescue_split(candidates: list[dict], graph_index, express_idx: dict,
                  episode_idx: dict, weights: dict, caps: dict, centrality_weights: dict,
                  now: datetime, retention_factors: dict | None = None,
                  top_pct: float = RESCUE_TOP_PCT_DEFAULT,
                  ) -> tuple[list[dict], list[dict]]:
    """archive 후보를 memory_score 로 (rescued, kept_archive) 로 가른다.

    각 후보에 memory_score·memory_reason 을 주석한다. 상대 임계: score 내림차순
    상위 ceil(top_pct·N) 중 score>0 인 것만 rescue(전부 0이면 아무도 보존 안 함).
    """
    if not candidates:
        return [], []
    for c in candidates:
        page = WIKI_ROOT / c["path"]
        slug = Path(c["path"]).stem
        try:
            fm, _ = parse_frontmatter(page.read_text(encoding="utf-8"))
        except (OSError, FrontmatterParseError):
            fm = {}
        entry = {
            "slug": slug,
            "access_count": fm.get("access_count", 0) if isinstance(fm, dict) else 0,
            "age_days": c.get("age_days"),
            "express_reuse": express_idx.get(slug, 0),
            "episode_ref": episode_idx.get(slug, 0),
        }
        terms = _score_terms(entry, graph_index, fm, weights, caps, centrality_weights, now,
                             retention_factors)
        c["memory_score"] = round(sum(terms.values()), 4)
        c["memory_reason"] = memory_reason(terms)

    ordered = sorted(candidates, key=lambda x: (-x["memory_score"], x["path"]))
    k = max(1, math.ceil(top_pct * len(ordered)))
    rescued, kept = [], []
    for i, c in enumerate(ordered):
        if i < k and c["memory_score"] > 0:
            rescued.append(c)
        else:
            kept.append(c)
    return rescued, kept


# ── Reweave (v0.3.0 WS-3) — 기존 자산 오케스트레이터 (신규 엔진 아님) ────
#
# weak 판정·자동 fix 엔진 = scripts/memory_health.py 를 import 재사용하고
# (_collect_pages·_weak_content_issues·_plan_page_fixes — 중복 구현 금지),
# observing 만료 = lib/gates.evaluate_observing_expiry 판정에 따른 결정적 파일
# 이동만 수행한다. LLM 호출 0 — 판단 필요분(본문<800자·근거<2건·H2<3개)은
# wiki/reweave_queue.md 로 큐잉하고 commands/curate.md Step 3 에서 LLM 컴파일러가
# 소비한다 (SPEC v0.3 §A: 스크립트=큐, 커맨드=실행).
#
# memory_health.run_fix 를 통째로 위임하지 않는 이유: run_fix 는 wiki_root 전체를
# 돌아 observing/·rejected/(gates 관리 폴더)까지 fix/alert 하는데, 두 폴더는
# 격리 대상이고 memory_health.py 는 수정 금지 범위라 — 같은 엔진 조각을
# 격리 필터와 함께 재구동한다 (판정·fix 계획 로직은 전부 memory_health 소유).

REWEAVE_QUEUE_NAME = "reweave_queue.md"
REWEAVE_WEEKLY_WINDOW_DAYS = 28    # --weekly-summary 집계 창
REWEAVE_WEEKLY_MIN_REPEAT = 4      # N회+ 반복 weak → 통합/삭제 후보
_REWEAVE_EPISODE_SCAN_LIMIT = 400  # 28일 일간 실행 ~28건 — 여유 상한


def _is_gate_dir_rel(rel: str) -> bool:
    """wiki 상대경로가 gates 관리 폴더(observing/·rejected/) 안인가."""
    return rel.startswith("observing/") or rel.startswith("rejected/")


def _process_observing_expiry(today, *, dry_run: bool) -> tuple[list[dict], list[tuple[str, str]]]:
    """wiki/observing/ 에 gates.evaluate_observing_expiry 적용 — 만료면 wiki/rejected/ 이동.

    이동은 결정적 파일 작업이라 스크립트가 수행한다 (SPEC v0.3 §A). frontmatter
    `gate_status: rejected` 갱신은 frontmatter_utils 경유(body 무손상). observing 인데
    만료일 결손 등 fail-loud(ValueError) 페이지는 파일 무변경 + errors 로 표면화한다
    (한 페이지 오류가 전체 런을 못 깨뜨린다).

    반환: (expired 이동 목록, errors 목록). dry_run=True 면 이동 없이 계획만 담는다.
    """
    observing_dir = WIKI_DIR / "observing"
    rejected_dir = WIKI_DIR / "rejected"
    expired: list[dict] = []
    errors: list[tuple[str, str]] = []
    if not observing_dir.is_dir():
        return expired, errors
    for md in sorted(observing_dir.glob("*.md")):
        rel = f"observing/{md.name}"
        try:
            fm, body = frontmatter_utils.read_fm(md.read_text(encoding="utf-8"))
        except (OSError, frontmatter_utils.FrontmatterParseError) as exc:
            errors.append((rel, f"읽기/파싱 실패 — 무변경: {exc}"))
            continue
        page = gates.ExistingPage(slug=md.stem, frontmatter=fm, body=body)
        try:
            decision = gates.evaluate_observing_expiry(page, today)
        except ValueError as exc:
            errors.append((rel, f"만료 판정 실패 — 무변경: {exc}"))
            continue
        if decision is None:
            continue  # observing 아님 / 미만료 / 재등장(G-1 재판정 대상)
        dst = rejected_dir / md.name
        if not dry_run:
            if dst.exists():
                errors.append((rel, "rejected/ 에 동명 파일 존재 — 이동 보류"))
                continue
            fm["gate_status"] = "rejected"
            rejected_dir.mkdir(parents=True, exist_ok=True)
            dst.write_text(frontmatter_utils.write_fm(fm, body), encoding="utf-8")
            md.unlink()
        expired.append({
            "slug": md.stem,
            "from": f"wiki/observing/{md.name}",
            "to": f"wiki/rejected/{md.name}",
            "reason": decision.reject_reason or "",
        })
    return expired, errors


def _write_reweave_queue(queue_path: Path, weak_entries: list[tuple[str, list[str]]],
                         now: datetime, *, body_min: int, min_sources: int,
                         min_h2: int,
                         synthesis_targets: list | None = None) -> None:
    """판단 필요분 큐 + 종합 대상 큐 — distill_queue.md 와 동일 체크박스 패턴.

    weak_entries = 보강 판단 필요분(본문·근거 부족). synthesis_targets = WS-1 종합 대상
    (2+ 소스 교차 / inbound 허브). 둘은 **다른 라벨의 별도 섹션**으로 구분한다 —
    LLM Step(commands/curate.md Step 3)이 보강과 종합을 다른 규칙으로 처리하기 때문."""
    ts = now.strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Reweave Queue — {ts}\n",
        "> 이 파일은 `curate --reweave`가 생성합니다. Claude Code가 읽고 "
        "raw/ 근거 범위 안에서만 보강을 실행하세요 (commands/curate.md Step 3).\n",
        f"\n## 판단 필요분 (본문<{body_min}자 OR 근거<{min_sources}건 OR H2<{min_h2}개) "
        f"— {len(weak_entries)}개",
        "자동 보강 금지 대상 — raw/ 출처 기반 보강만 (가짜 보강 금지)\n",
    ]
    for rel, issues in weak_entries:
        lines.append(f"- [ ] `wiki/{rel}` — {'; '.join(issues)}")

    targets = synthesis_targets or []
    lines.append(f"\n## 종합 대상 (2+ 소스 교차 / inbound 허브) — {len(targets)}개")
    lines.append(
        "> `schema/curate.md`의 `## Synthesis Rules` 적용 — `## 인사이트 (종합)` "
        "섹션 생성·갱신 + frontmatter angles/signal_count/synthesis_updated. "
        "**불변식: 기존 본문·sources 삭제·단축 금지(append/갱신만)**.\n"
    )
    for t in targets:
        crossing = ", ".join(t.crossing_sources)
        lines.append(
            f"- [ ] [[{t.slug}]] — {t.reason} · 반복신호 {t.signal_count} · 소스 {crossing}"
        )
    queue_path.write_text("\n".join(lines))


# ── synthesis shrink 스냅샷 (WS-1 shrink 가드 (a) 변형 — 대상 한정) ────────
#
# 배경: synthesis 서술은 LLM Step 이 파일에 쓴다(스크립트는 큐만 생성) — 스크립트는
# LLM 저장 순간을 가로챌 수 없다. 그래서 **synthesis 대상의 본문·sources 를 run 간
# 스냅샷**해 두고, 다음 run 에서 `synthesis.guard_no_shrink` 로 축소를 감지해
# `curate_report.md` 에 `WARN shrink` 로 표면화한다(자동 차단 아님 — 사람/LLM 검토).
# 감지 범위를 synthesis 대상으로 한정한 이유: audit 전역 스냅샷은 distill(의도적 본문
# 압축)에 매번 오탐하기 때문(distill 은 본문을 일부러 줄인다). synthesis 는 "축소 금지"가
# 불변식이므로 대상 한정 스냅샷에서만 축소가 진짜 위반 신호다.


def _load_synthesis_snapshot() -> dict:
    """이전 run 의 synthesis 대상 본문·sources 스냅샷 로드. 없으면 빈 dict."""
    snap_file = WIKI_DIR / SYNTHESIS_SNAPSHOT_NAME
    if snap_file.exists():
        try:
            data = json.loads(snap_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_synthesis_snapshot(snapshot: dict) -> None:
    """현재 synthesis 대상 스냅샷을 결정적 바이트로 저장(동일 입력 → 동일 파일)."""
    (WIKI_DIR / SYNTHESIS_SNAPSHOT_NAME).write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))


def _fm_sources_list(fm) -> list:
    """frontmatter sources 를 list 로(비-list 는 빈 list). 스냅샷·guard 입력용."""
    src = fm.get("sources") if isinstance(fm, dict) else None
    return list(src) if isinstance(src, (list, tuple)) else []


def _detect_synthesis_shrink(targets: list,
                             proj_by_slug: dict) -> tuple[list[tuple[str, tuple]], dict]:
    """이전 스냅샷 대비 synthesis 대상의 본문·근거 축소를 감지 (guard_no_shrink 배선점).

    반환: (shrink_warnings, new_snapshot). shrink_warnings = [(slug, reasons)] —
    guard 가 blocked 판정한 대상만. new_snapshot = 이번 run 대상의 {body, sources}.
    guard_no_shrink 순수 함수를 **실제 호출**하는 유일 배선 경로다.
    """
    prev = _load_synthesis_snapshot()
    warnings: list[tuple[str, tuple]] = []
    new_snapshot: dict = {}
    for t in targets:
        page = proj_by_slug.get(t.slug)
        if page is None:
            continue
        cur_sources = _fm_sources_list(page.frontmatter)
        new_snapshot[t.slug] = {"body": page.body, "sources": cur_sources}
        before = prev.get(t.slug)
        if not isinstance(before, dict):
            continue  # 이전 스냅샷 없음 — 첫 등장, 비교 대상 없음
        verdict = synthesis.guard_no_shrink(
            {"sources": before.get("sources", [])}, before.get("body", ""),
            {"sources": cur_sources}, page.body,
        )
        if verdict.blocked:
            warnings.append((t.slug, verdict.reasons))
    return warnings, new_snapshot


def _reweave_weekly_summary(now: datetime, current_weak_refs: list[str]) -> dict:
    """최근 28일 reweave 에피소드 + 현재 스캔에서 반복 weak 노드를 통합/삭제 후보로 집계.

    reweave 에피소드의 read_pages(= 그 런의 weak 목록)를 런 단위로 세고, 현재 스캔도
    1개 런으로 포함한다. fail-soft: episodes 부재/부족(집계 런 < REWEAVE_WEEKLY_MIN_REPEAT
    → 어떤 노드도 임계에 못 미침)이면 현재 스캔만으로 후보를 내고
    insufficient_history=True 로 정직 표기한다 (크래시 금지).
    """
    cutoff = now - timedelta(days=REWEAVE_WEEKLY_WINDOW_DAYS)
    runs: list[set[str]] = []
    try:
        records = episode.read_recent(task_type="reweave",
                                      limit=_REWEAVE_EPISODE_SCAN_LIMIT,
                                      episodes_dir=episode.EPISODES_DIR)
    except Exception as e:  # noqa: BLE001 — 원장 read 실패가 리포트를 못 깨뜨린다
        print(f"  [reweave] weekly: episodes 읽기 실패(무시): {e}", file=sys.stderr)
        records = []
    for rec in records:
        try:
            dt = datetime.fromisoformat(str(rec.get("timestamp", "")))
        except ValueError:
            continue
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)  # 로컬 naive 로 통일(now 와 비교)
        if dt < cutoff:
            continue
        pages = rec.get("read_pages", [])
        if isinstance(pages, list):
            runs.append({p for p in pages if isinstance(p, str) and p})
    runs.append(set(current_weak_refs))  # 현재 스캔도 1개 런으로 집계

    counts: Counter = Counter()
    for run in runs:
        counts.update(run)
    insufficient = len(runs) < REWEAVE_WEEKLY_MIN_REPEAT
    if insufficient:
        candidates = [(ref, counts[ref]) for ref in sorted(set(current_weak_refs))]
    else:
        candidates = sorted(((ref, c) for ref, c in counts.items()
                             if c >= REWEAVE_WEEKLY_MIN_REPEAT),
                            key=lambda x: (-x[1], x[0]))
    return {"candidates": candidates, "runs": len(runs),
            "insufficient_history": insufficient}


def run_reweave(*, fix: bool = False, dry_run: bool = False,
                weekly_summary: bool = False, now: datetime | None = None) -> dict:
    """weak 스캔(+옵션 자동 fix) + reweave_queue 생성 + observing 만료 처리 (v0.3 WS-3).

    - weak 판정·fix 계획 = memory_health 엔진 import 재사용. observing/·rejected/·
      reweave_queue.md 는 스캔에서 격리한다.
    - fix=True 일 때만 자동 보강 가능분(summary·source_count·updated — idempotent)을
      적용한다. 본문·근거 부족(판단 필요분)은 fix 하지 않고 alert + 큐잉만(가짜 보강 금지).
    - dry_run=True 면 어떤 파일도 변경·생성하지 않는다 (fix·이동·큐 전부 계획만).
    - weekly_summary=True 면 최근 28일 reweave 에피소드 누적 weak 후보를 집계한다.

    반환: {"fixed", "alerts", "weak", "expired", "expiry_errors", "weekly", "dry_run"}.
    """
    import memory_health  # 지연 import — memory_health 가 curate 를 import 하므로 순환 회피

    if now is None:
        now = datetime.now()

    # 1) observing 만료 처리 — 먼저 수행해 만료 페이지가 rejected/(격리 대상)로 빠지게.
    expired, expiry_errors = _process_observing_expiry(now.date(), dry_run=dry_run)

    # 2) weak 스캔 + (--fix) 자동 보강 — memory_health 엔진 + gates 폴더 격리 필터.
    pages, parse_errors = memory_health._collect_pages(WIKI_DIR)
    fixed: list[tuple[str, list[str]]] = []
    alerts: list[tuple[str, str]] = []
    weak_entries: list[tuple[str, list[str]]] = []

    for rel, reason in parse_errors:
        if _is_gate_dir_rel(rel) or rel == REWEAVE_QUEUE_NAME:
            continue
        alerts.append((rel, f"{reason} — fix 제외(fail-loud, 페이지 무변경)"))
    error_rels = {rel for rel, _ in parse_errors}

    for p in pages:
        if _is_gate_dir_rel(p.rel) or p.rel == REWEAVE_QUEUE_NAME or p.rel in error_rels:
            continue
        issues = memory_health._weak_content_issues(p.fm, p.body)
        if issues:
            weak_entries.append((p.rel, issues))
            alerts.append((p.rel, "; ".join(issues) + " — 본문·근거 부족은 alert만(판단 필요분)"))
        if not p.fm:
            continue  # frontmatter 블록 없는 페이지는 채움 범위 밖
        # 계획은 항상 세운다(fix 여부 무관) — dry-run/스캔에서도 "fix 가능분"을 예고.
        # 실제 쓰기는 --fix 이고 dry-run 이 아닐 때만(applied). 그래야 --dry-run 단독이
        # fixed 를 0 으로 잘못 보여주지 않는다(미리보기 계약).
        new_fm, actions, unfixable = memory_health._plan_page_fixes(p.fm, p.body, now)
        for reason in unfixable:
            alerts.append((p.rel, reason))
        if actions:
            if fix and not dry_run:
                p.path.write_text(frontmatter_utils.write_fm(new_fm, p.body), encoding="utf-8")
            fixed.append((p.rel, actions))

    weak_entries.sort(key=lambda x: x[0])
    alerts.sort(key=lambda x: (x[0], x[1]))

    # 2b) 종합 대상 선정 (WS-1 결정적 부분) — synthesis 순수 코어에 위임.
    #     find_all_wiki_pages 투영(gate 폴더·큐 제외)에서 2+ 소스 교차/inbound 허브를 선정.
    #     동시에 이전 run 대비 synthesis 대상 축소를 guard_no_shrink 로 감지(shrink 가드 배선).
    syn_pages = find_all_wiki_pages()
    projections = _project_pages(syn_pages)
    _, syn_inbound = build_link_graph(syn_pages)
    synthesis_targets = synthesis.select_synthesis_targets(
        projections, syn_inbound, limit=SYNTHESIS_QUEUE_LIMIT)
    proj_by_slug = {p.slug: p for p in projections}
    shrink_warnings, new_snapshot = _detect_synthesis_shrink(synthesis_targets, proj_by_slug)

    # 3) 판단 필요분 + 종합 대상 큐 — LLM 컴파일러(commands/curate.md Step 3)가 소비.
    if not dry_run:
        _write_reweave_queue(WIKI_DIR / REWEAVE_QUEUE_NAME, weak_entries, now,
                             body_min=memory_health.WEAK_BODY_MIN_CHARS,
                             min_sources=memory_health.WEAK_MIN_SOURCES,
                             min_h2=memory_health.WEAK_MIN_H2,
                             synthesis_targets=synthesis_targets)
        _save_synthesis_snapshot(new_snapshot)

    # 4) --weekly-summary: 4주 누적 반복 weak → 통합/삭제 후보.
    weekly = None
    if weekly_summary:
        weekly = _reweave_weekly_summary(now, [f"wiki/{rel}" for rel, _ in weak_entries])

    # fixed 는 항상 "fix 가능분" 계획 수 — 실제 적용은 --fix 이고 dry-run 아닐 때만.
    applied = fix and not dry_run
    label = "fixed" if applied else "fixable"
    if applied:
        tag = ""
    elif dry_run:
        tag = " (dry-run — 파일 무변경)"
    else:
        tag = " (--fix 미지정 — 파일 무변경, --fix 로 적용)"
    print(f"  [reweave] {label}={len(fixed)}, alert={len(alerts)}, "
          f"expired={len(expired)}, 큐={len(weak_entries)}개, "
          f"종합={len(synthesis_targets)}개, shrink경고={len(shrink_warnings)}개{tag}")
    if not applied:
        for rel, actions in fixed:
            print(f"    fix 계획: {rel} — {'; '.join(actions)}")
        for e in expired:
            print(f"    만료 계획: {e['from']} → {e['to']} ({e['reason']})")

    return {"fixed": fixed, "alerts": alerts, "weak": weak_entries,
            "expired": expired, "expiry_errors": expiry_errors,
            "weekly": weekly, "synthesis": synthesis_targets,
            "shrink_warnings": shrink_warnings, "dry_run": dry_run}


# ── Report ─────────────────────────────────────────────────────────────

def write_report(audit: dict, distilled: list, lifecycle: dict,
                 merge_candidates: list | None = None,
                 reweave: dict | None = None) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"# Curate Report — {now}\n"]

    lines.append("## Audit 결과")
    orphans = audit.get("orphans", [])
    lines.append(f"### Orphan 페이지 ({len(orphans)}개)")
    for o in orphans:
        lines.append(f"- {o['path']} — {o['age_days']}일 경과, inbound 0")

    stale = audit.get("stale_links", [])
    lines.append(f"\n### Stale 링크 ({len(stale)}개)")
    for s in stale:
        lines.append(f"- {s['source']} → [[{s['missing_target']}]] (페이지 없음)")

    # 모순 후보 (v0.3.1 WS-5) — reconcile 가 표면화한 후보 카운트. 화해 서술은 LLM Step.
    contradictions = audit.get("contradictions", [])
    lines.append(f"\n### 모순 후보 ({len(contradictions)}개)")
    for c in contradictions:
        lines.append(
            f"- [[{c.existing_slug}]] ↔ {c.new_source_ref} — "
            f"신호 {c.signal} · 우선순위 {c.confidence_hint}"
        )
    if contradictions:
        lines.append(
            "\n> 상세 큐: `wiki/contradiction_queue.md` — 화해 서술은 "
            "`commands/curate.md` Step(`## 반론/갱신`)."
        )

    # Merge-review (US-006): 같은 카테고리 내 근접 중복 쌍. **자동 병합 금지(Rule 9)** —
    # 후보 목록만 제공해 사람이 병합 판단. do_purge 가 스캔하는 'Lifecycle 후보' 섹션과
    # 분리(별도 top-level 섹션) + `- wiki/..md` 형식이 아니라 purge 정규식에도 안 잡힌다.
    merge = merge_candidates or []
    lines.append("\n## Merge-review 후보 (유사 페이지 — 사람이 병합 판단)")
    lines.append("> 같은 카테고리 내 제목·태그 Jaccard 유사 쌍. **자동 병합하지 않음** — 사람이 검토 후 병합.")
    lines.append(f"### 후보 쌍 ({len(merge)}개)")
    for m in merge:
        lines.append(
            f"- [[{m['a']}]] ↔ [[{m['b']}]] — similarity {m['similarity']:.2f} ({m.get('reason', '')})"
        )

    lines.append(f"\n## Distill 결과")
    lines.append(f"- 큐에 추가된 페이지: {len(distilled)}개")
    for d in distilled:
        lines.append(f"  - {d}")
    if distilled:
        lines.append("\n> 상세 큐: `wiki/distill_queue.md`")

    lines.append("\n## Lifecycle 후보 (사용자 확인 필요)")
    archive = lifecycle.get("archive", [])
    lines.append(f"### Archive 후보 ({len(archive)}개)")
    for a in archive:
        lines.append(
            f"- {a['path']} — {a['age_days']}일 경과, inbound {a['inbound']}"
            + _score_suffix(a)
        )

    delete = lifecycle.get("delete", [])
    lines.append(f"\n### Delete 후보 ({len(delete)}개)")
    for d in delete:
        lines.append(f"- {d['path']} — {d['age_days']}일 경과, inbound {d['inbound']}")
    if delete:
        lines.append("\n> 삭제 실행: `python scripts/curate.py --purge`")

    # plug-in ② rescue: 보존된 페이지는 Lifecycle 섹션 *밖*(별도 ## 섹션)에 기록한다.
    # do_purge 는 'Lifecycle 후보' 섹션만 스캔하므로 여기 둬야 purge 에 안 잡힌다.
    rescued = lifecycle.get("rescued", [])
    lines.append(f"\n## Rescued — 재사용 보존 ({len(rescued)}개)")
    lines.append("> archive 후보였으나 memory_score 상위라 보존됨 (promote/keep-review).")
    for r in rescued:
        lines.append(
            f"- {r['path']} — {r['age_days']}일 경과, inbound {r['inbound']}"
            + _score_suffix(r)
        )

    # v0.3 Reweave (WS-3): --reweave 실행 시에만 섹션 추가.
    if reweave is not None:
        r_fixed = reweave.get("fixed", [])
        r_alerts = reweave.get("alerts", [])
        r_expired = reweave.get("expired", [])
        r_errors = reweave.get("expiry_errors", [])
        lines.append("\n## Reweave")
        lines.append(f"fixed: {len(r_fixed)} / alert: {len(r_alerts)} / expired: {len(r_expired)}")
        lines.append(f"\n### 자동 보강 ({len(r_fixed)}개)")
        for rel, actions in r_fixed:
            lines.append(f"- `{rel}` — {'; '.join(actions)}")
        lines.append(f"\n### Alert — 판단 필요분 ({len(r_alerts)}개)")
        lines.append("> 본문·근거 부족은 자동 보강 금지 — 상세 큐: `wiki/reweave_queue.md`")
        for rel, reason in r_alerts:
            lines.append(f"- `{rel}` — {reason}")
        lines.append(f"\n### Observing 만료 → rejected/ ({len(r_expired)}개)")
        for e in r_expired:
            lines.append(f"- {e['slug']} — {e['from']} → {e['to']} ({e['reason']})")
        if r_errors:
            lines.append(f"\n### Observing 처리 경고 ({len(r_errors)}개)")
            for rel, reason in r_errors:
                lines.append(f"- `{rel}` — {reason}")
        # 종합 대상 (v0.3.1 WS-1) — 상세 큐는 reweave_queue.md `## 종합 대상`.
        r_synthesis = reweave.get("synthesis", [])
        lines.append(f"\n### 종합 대상 ({len(r_synthesis)}개)")
        lines.append("> 2+ 소스 교차 / inbound 허브 — 상세 큐: `wiki/reweave_queue.md` (`## 종합 대상`)")
        # WARN shrink (WS-1 불변식) — 이전 run 대비 synthesis 대상 축소 감지(자동 차단 아님).
        r_shrink = reweave.get("shrink_warnings", [])
        lines.append(f"\n### WARN shrink — 종합 대상 축소 감지 ({len(r_shrink)}개)")
        if r_shrink:
            lines.append(
                "> 이전 run 대비 본문·근거가 줄었다 — synthesis 불변식(축소 금지) "
                "위반 가능. 사람/LLM 검토 필수."
            )
        for slug, reasons in r_shrink:
            lines.append(f"- [[{slug}]] — {'; '.join(reasons)}")
        weekly = reweave.get("weekly")
        if weekly is not None:
            cands = weekly.get("candidates", [])
            lines.append(
                f"\n### Weekly Summary — 통합/삭제 후보 ({len(cands)}개, "
                f"최근 {REWEAVE_WEEKLY_WINDOW_DAYS}일 {weekly.get('runs', 0)}런)"
            )
            if weekly.get("insufficient_history"):
                lines.append(
                    f"> ⚠ 이력 부족 (집계 런 < {REWEAVE_WEEKLY_MIN_REPEAT}) — "
                    "현재 스캔만으로 후보 표기. 실제 이동·삭제는 사용자 승인 필수."
                )
            else:
                lines.append(
                    f"> {REWEAVE_WEEKLY_MIN_REPEAT}회+ 반복 weak 노드. "
                    "실제 이동·삭제는 사용자 승인 필수."
                )
            for ref, cnt in cands:
                lines.append(f"- `{ref}` — {cnt}회")

    REPORT_FILE.write_text("\n".join(lines))
    print(f"\n[curate] 리포트 저장: wiki/curate_report.md")

    log_entry = (
        f"\n## {now} [curate]\n"
        f"- orphan: {len(orphans)}개\n"
        f"- stale_links: {len(stale)}개\n"
        f"- distill 큐: {len(distilled)}개\n"
        f"- merge-review 후보: {len(merge)}개\n"
        f"- archive 후보: {len(archive)}개\n"
        f"- rescued(보존): {len(rescued)}개\n"
    )
    if reweave is not None:
        log_entry += (
            f"- reweave: fixed {len(reweave.get('fixed', []))} / "
            f"alert {len(reweave.get('alerts', []))} / "
            f"expired {len(reweave.get('expired', []))}\n"
        )
    LOG_FILE.open("a").write(log_entry)


def _score_suffix(item: dict) -> str:
    """리포트 라인에 붙일 memory_score 주석(있을 때만)."""
    if "memory_score" not in item:
        return ""
    reason = item.get("memory_reason", "")
    return f", score={item['memory_score']:.1f} ({reason})"


# ── Graph Health ──────────────────────────────────────────────────────

def graph_health() -> None:
    """
    wiki/graph.json을 읽어 그래프 건강 지표를 출력한다.
    - pages, wikilink edges, avg degree, components, diameter, avg shortest
    - low-degree (≤2) 페이지 수, ghost 수
    - 카테고리별 내부/외부 연결 응집도
    - Betweenness Centrality TOP 5
    """
    import json
    import networkx as nx
    from collections import defaultdict, Counter

    graph_path = WIKI_ROOT / "wiki" / "graph.json"
    if not graph_path.exists():
        print("[health] graph.json 없음 — export_graph 먼저 실행")
        return

    g = json.loads(graph_path.read_text())
    pages = {n["id"]: n for n in g["nodes"] if n["kind"] == "page"}
    ghosts = [n for n in g["nodes"] if n["kind"] == "ghost"]

    G = nx.Graph()
    for p in pages:
        G.add_node(p)
    for l in g["links"]:
        if l["kind"] == "wikilink" and l["source"] in pages and l["target"] in pages:
            G.add_edge(l["source"], l["target"])

    n_pages = G.number_of_nodes()
    n_edges = G.number_of_edges()
    avg_degree = (2 * n_edges / n_pages) if n_pages > 0 else 0
    low_degree = sum(1 for _, d in G.degree() if d <= 2)
    components = nx.number_connected_components(G)

    # 연결 그래프의 지름 / 평균 최단거리 (가장 큰 컴포넌트 기준)
    largest_cc = max(nx.connected_components(G), key=len)
    sub = G.subgraph(largest_cc)
    diameter = nx.diameter(sub)
    avg_shortest = nx.average_shortest_path_length(sub)

    today = datetime.now().strftime("%Y-%m-%d")
    print(f"[health] {today}")
    print(f"  pages           = {n_pages}")
    print(f"  wikilink edges  = {n_edges}")
    print(f"  avg degree      = {avg_degree:.2f}")
    print(f"  components      = {components}")
    print(f"  diameter        = {diameter}")
    print(f"  avg shortest    = {avg_shortest:.2f}")
    print(f"  low-degree (≤2) = {low_degree}개")
    print(f"  ghost           = {len(ghosts)}개")

    # 카테고리별 응집도
    print(f"\n[health] 카테고리별 응집도")
    cat_nodes: dict[str, list[str]] = defaultdict(list)
    for pid, pdata in pages.items():
        cat = pdata.get("category", "기타")
        cat_nodes[cat].append(pid)

    cat_node_set: dict[str, set[str]] = {c: set(ns) for c, ns in cat_nodes.items()}
    for cat in sorted(cat_nodes.keys()):
        members = cat_node_set[cat]
        internal = 0
        external = 0
        for u, v in G.edges():
            u_in = u in members
            v_in = v in members
            if u_in and v_in:
                internal += 1
            elif u_in or v_in:
                external += 1
        total = internal + external
        ratio = int(internal / total * 100) if total > 0 else 0
        print(f"  {cat:<12} {len(members):>2}p  internal={internal} external={external}  내부={ratio}%")

    # Betweenness Centrality TOP 5
    print(f"\n[health] Betweenness centrality TOP 5")
    bc = nx.betweenness_centrality(G, normalized=True)
    top5 = sorted(bc.items(), key=lambda x: x[1], reverse=True)[:5]
    for slug, score in top5:
        print(f"  {slug:<40} BC={score:.4f}")


# ── Suggest Bridges ────────────────────────────────────────────────────

def suggest_bridges(n: int) -> None:
    """
    betweenness centrality + structural hole 기반으로 missing link N개를 추천한다.
    - 같은 카테고리 페이지 쌍은 제외
    - 두 페이지 사이 hop이 2 이상 (직접 연결 안 됨)
    - inbound 합 + betweenness 합 기준으로 상위 N개 선정
    """
    import json
    import networkx as nx
    from itertools import combinations

    graph_path = WIKI_ROOT / "wiki" / "graph.json"
    if not graph_path.exists():
        print("[suggest-bridges] graph.json 없음 — export_graph 먼저 실행")
        return

    g = json.loads(graph_path.read_text())
    pages = {n["id"]: n for n in g["nodes"] if n["kind"] == "page"}

    G = nx.Graph()
    for p in pages:
        G.add_node(p)
    for l in g["links"]:
        if l["kind"] == "wikilink" and l["source"] in pages and l["target"] in pages:
            G.add_edge(l["source"], l["target"])

    bc = nx.betweenness_centrality(G, normalized=True)

    # 연결된 페이지 쌍만 대상으로 경로 계산 (가장 큰 컴포넌트)
    largest_cc = max(nx.connected_components(G), key=len)
    sub = G.subgraph(largest_cc)
    sub_pages = list(largest_cc)

    candidates = []
    for a, b in combinations(sub_pages, 2):
        # 같은 카테고리 제외
        if pages[a].get("category") == pages[b].get("category"):
            continue
        # 이미 직접 연결된 쌍 제외
        if sub.has_edge(a, b):
            continue
        # hop distance 계산
        try:
            hop = nx.shortest_path_length(sub, a, b)
        except nx.NetworkXNoPath:
            continue
        if hop < 2:
            continue

        inbound_a = pages[a].get("inbound", 0)
        inbound_b = pages[b].get("inbound", 0)
        hub_score = inbound_a + inbound_b
        bc_score = bc.get(a, 0) + bc.get(b, 0)
        # 정렬 기준: hub_score 우선, bc_score 보조
        candidates.append((a, b, hop, hub_score, bc_score))

    # hub_score 내림차순, bc_score 내림차순 정렬
    candidates.sort(key=lambda x: (x[3], x[4]), reverse=True)
    top = candidates[:n]

    print(f"[suggest-bridges] 추천 missing link {len(top)}개")
    for i, (a, b, hop, hub_score, bc_score) in enumerate(top, 1):
        print(f"  {i}. [[{a}]] ↔ [[{b}]]  hop={hop}, hub-score={hub_score}")


# ── Purge ──────────────────────────────────────────────────────────────

def _lifecycle_section(content: str) -> str:
    """'## Lifecycle 후보' 섹션 텍스트만 추출(Archive·Delete 하위 포함).

    do_purge 의 `- wiki/..md` 매치 범위를 이 섹션으로 좁힌다 — audit Orphan·Distill·
    Rescued 섹션의 경로를 purge 가 잘못 이동시키지 않게 한다(rescue 보존의 실효성 확보).
    """
    out: list[str] = []
    in_section = False
    for line in content.splitlines():
        if line.startswith("## Lifecycle 후보"):
            in_section = True
            continue
        if in_section and line.startswith("## "):  # 다음 top-level 섹션에서 종료
            break
        if in_section:
            out.append(line)
    return "\n".join(out)


def do_purge() -> None:
    """curate_report.md의 'Lifecycle 후보' 섹션 경로를 wiki/archive/로 이동.

    Orphan·Distill·Rescued 섹션은 대상에서 제외한다(과잉 이동·rescue 무력화 방지).
    """
    if not REPORT_FILE.exists():
        print("[purge] curate_report.md 없음. curate --lifecycle 먼저 실행.")
        return
    content = _lifecycle_section(REPORT_FILE.read_text())
    archive_dir = WIKI_DIR / "archive"
    archive_dir.mkdir(exist_ok=True)
    moved = 0
    for match in re.finditer(r"- (wiki/\S+\.md)", content):
        src = WIKI_ROOT / match.group(1)
        if src.exists():
            dst = archive_dir / src.name
            src.rename(dst)
            print(f"  [archive] {match.group(1)}")
            moved += 1
    print(f"[purge] {moved}개 파일 archive/로 이동")


def _curate_episode_record(mode: str, audit: dict, distilled: list, lifecycle: dict,
                           *, now: datetime | None = None) -> dict:
    """curate 실행 요약을 episode 레코드(C1 스키마)로 만든다. (US-002)"""
    ts = (now or datetime.now().astimezone()).isoformat()
    return {
        "timestamp": ts,
        "task_type": "curate",
        "user_goal": f"curate {mode}",
        "inputs": {"mode": mode},
        "read_pages": [],
        "procedures_used": [],
        "outputs": {
            "orphans": len(audit.get("orphans", [])),
            "stale_links": len(audit.get("stale_links", [])),
            "contradictions": len(audit.get("contradictions", [])),
            "distill_queued": len(distilled),
            "archive_candidates": len(lifecycle.get("archive", [])),
            "delete_candidates": len(lifecycle.get("delete", [])),
            "rescued": len(lifecycle.get("rescued", [])),
        },
        "status": "ok",
        "notes": "",
    }


def _record_curate_episode(mode: str, audit: dict, distilled: list, lifecycle: dict) -> None:
    """fail-soft: episode 기록 실패가 curate 메인 경로를 못 깨뜨린다 (US-002 AC)."""
    try:
        episode.append(_curate_episode_record(mode, audit, distilled, lifecycle))
    except (episode.EpisodeSchemaError, Exception) as e:  # noqa: B014 — 명시적 fail-soft
        print(f"[curate] episode 기록 실패(무시): {e}", file=sys.stderr)


def _reweave_episode_record(result: dict, *, fix: bool, weekly_summary: bool,
                            now: datetime | None = None) -> dict:
    """reweave 실행 요약을 episode 레코드(C1 스키마)로 만든다 (v0.3 WS-3).

    read_pages = 이번 런의 weak 페이지 목록 — --weekly-summary 4주 누적 집계의 입력.
    memory_score.build_episode_ref_index 는 task_type=reweave 를 제외하므로
    (express_* 제외와 같은 이유) 이 read_pages 가 자기 점수 되먹임을 만들지 않는다.
    """
    ts = (now or datetime.now().astimezone()).isoformat()
    return {
        "timestamp": ts,
        "task_type": "reweave",
        "user_goal": "curate reweave",
        "inputs": {"mode": "reweave", "fix": fix, "weekly_summary": weekly_summary},
        "read_pages": [f"wiki/{rel}" for rel, _ in result.get("weak", [])],
        "procedures_used": [],
        "outputs": {
            "fixed": len(result.get("fixed", [])),
            "alerts": len(result.get("alerts", [])),
            "expired": len(result.get("expired", [])),
            "queued": len(result.get("weak", [])),
            "synthesis_targets": len(result.get("synthesis", [])),
            "shrink_warnings": len(result.get("shrink_warnings", [])),
        },
        "status": "ok",
        "notes": "",
    }


def _record_reweave_episode(result: dict, *, fix: bool, weekly_summary: bool) -> None:
    """fail-soft (US-002 패턴): episode 기록 실패가 reweave 경로를 못 깨뜨린다."""
    try:
        # episodes_dir 를 호출 시점 모듈 속성으로 주입 — 테스트가 episode.EPISODES_DIR
        # 를 monkeypatch 해 원장을 격리할 수 있게 한다(기본값 바인딩 회피).
        episode.append(_reweave_episode_record(result, fix=fix, weekly_summary=weekly_summary),
                       episodes_dir=episode.EPISODES_DIR)
    except (episode.EpisodeSchemaError, Exception) as e:  # noqa: B014 — 명시적 fail-soft
        print(f"[curate] reweave episode 기록 실패(무시): {e}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM wiki curate")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--distill", action="store_true")
    parser.add_argument("--lifecycle", action="store_true")
    parser.add_argument("--purge", action="store_true", help="archive 후보 실제 이동")
    parser.add_argument("--record-access", metavar="PAGE_SLUG", help="access_count 기록 (query 모드용)")
    parser.add_argument("--health", action="store_true",
                        help="graph health 지표 출력 (avg degree, components, BC top, low-degree count)")
    parser.add_argument("--suggest-bridges", type=int, default=0, metavar="N",
                        help="betweenness/structural-hole 기반 missing link 추천 N개")
    parser.add_argument("--reweave", action="store_true",
                        help="weak 스캔·reweave_queue 생성·observing 만료 처리 (v0.3 WS-3, 매일)")
    parser.add_argument("--fix", action="store_true",
                        help="--reweave 조합: 자동 보강 가능분(summary·source_count·updated) 즉시 적용")
    parser.add_argument("--dry-run", action="store_true",
                        help="--reweave 조합: 아무 파일도 변경하지 않고 계획만 출력")
    parser.add_argument("--weekly-summary", action="store_true",
                        help="--reweave 조합: 최근 28일 반복 weak 통합/삭제 후보 리포트 (일요일)")
    args = parser.parse_args()

    if args.purge:
        do_purge()
        return

    if args.record_access:
        record_access(args.record_access)
        return

    if args.health:
        graph_health()
        return

    if args.suggest_bridges > 0:
        suggest_bridges(args.suggest_bridges)
        return

    if args.dry_run and not args.reweave:
        print("[curate] --dry-run 은 --reweave 전용 플래그 — 무시", file=sys.stderr)

    # --reweave --dry-run: 파일 무변경 계약 — 계획만 출력하고 종료한다.
    # (다른 모드와 조합하지 않는다 — run_distill 등은 큐 파일을 쓰므로 dry-run 과 양립 불가.)
    if args.reweave and args.dry_run:
        run_reweave(fix=args.fix, dry_run=True, weekly_summary=args.weekly_summary)
        return

    run_all = args.all or not any([args.audit, args.distill, args.lifecycle, args.reweave])
    pages = find_all_wiki_pages()
    print(f"[curate] {datetime.now().strftime('%Y-%m-%d %H:%M')} — {len(pages)}개 페이지 분석")

    audit_result = run_audit(pages) if (run_all or args.audit) else {}
    distilled = run_distill(pages) if (run_all or args.distill) else []
    lifecycle_result = run_lifecycle(pages) if (run_all or args.lifecycle) else {}
    # merge-review 는 audit 류 분석(근접 중복 표면화)이라 audit 게이트와 함께 돈다.
    merge_candidates = find_merge_candidates(pages) if (run_all or args.audit) else []

    reweave_result = run_reweave(fix=args.fix,
                                 weekly_summary=args.weekly_summary) if args.reweave else None

    write_report(audit_result, distilled, lifecycle_result, merge_candidates,
                 reweave=reweave_result)

    if run_all or args.audit or args.distill or args.lifecycle:
        mode = "all" if run_all else "+".join(
            m for m, on in [("audit", args.audit), ("distill", args.distill), ("lifecycle", args.lifecycle)] if on
        )
        _record_curate_episode(mode, audit_result, distilled, lifecycle_result)
    if reweave_result is not None:
        _record_reweave_episode(reweave_result, fix=args.fix,
                                weekly_summary=args.weekly_summary)


if __name__ == "__main__":
    main()
