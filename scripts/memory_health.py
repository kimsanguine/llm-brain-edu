#!/usr/bin/env python3
"""memory_health.py — 메모리 건강 리포트 (PRD US-008 + v0.3 WS-3 `--fix`).

5층 메모리 OS 의 ③ "오프라인 제어(메타 기억)" 관측기. wiki(의미)·episodes(에피소드)·
procedures(절차) 를 읽어 집계 리포트를 wiki/memory_health_report.md 에 쓴다.
기본(`--report`)은 **읽기 전용** — 절대 wiki 페이지를 이동·삭제·생성·수정하지 않는다
(curate 의 distill/lifecycle/purge 와 구분되는, side-effect-free 진단 도구).

v0.3 `--fix`(opt-in)는 **자동 보강 가능분만** frontmatter 를 기계적으로 채운다:
⑴ `summary` 결손 → 본문 첫 문단 40~200자 추출 ⑵ `source_count` 결손/불일치 →
`len(sources)` 캐시 ⑶ `updated` 형식 결손 채움. 쓰기는 `lib/frontmatter_utils`
read_fm/write_fm 경유(body 무손상)·idempotent(정상 페이지 2회 실행 무변경).
**본문·근거 부족은 절대 fix 하지 않고 alert 만**(가짜 보강 금지 — 본문을 생성·요약으로
늘리지 않는다). 파싱 실패 페이지도 건드리지 않고 alert(fail-loud). `--dry-run` 은
fix 대상 목록만 출력하고 아무 파일도 변경하지 않는다.

리포트 섹션: 메모리 타입별 페이지 수 · orphan semantic · stale 절차 · 최근 에피소드
(개수 + ts/task_type/status 메타만) · top 재사용 페이지 · 저신뢰 페이지 ·
weak content(본문<800자 OR 근거<2건 OR H2<3개) · archive 후보.
`--fix` 실행 시 `fixed: N / alert: M` 요약 섹션 포함.

🔴 프라이버시(SPEC §D, Claude#1·Codex C1): episode notes/inputs/outputs/user_goal 같은
verbatim 본문은 **절대** 리포트에 넣지 않는다. 에피소드는 **집계 수치 + 메타(시각·종류·
상태)** 로만 표면화한다. 또 리포트 파일명은 okf_export.META_FILES 에 등재돼(§D 누출 봉인)
공개 OKF 번들로 export 되지 않는다.

curate.py 의 *순수* 헬퍼(compute_memory_score·build_link_graph·build_express_reuse_index·
build_episode_ref_index·load_graph_index)만 재사용한다 — WIKI_ROOT 에 묶인
run_lifecycle/ensure_distill_fields(페이지 rewrite) 는 쓰지 않는다(읽기 전용 보장).
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import curate  # noqa: E402  (순수 헬퍼만 사용 — 쓰기 함수 호출 금지)
import episode  # noqa: E402
import procedures as procedures_mod  # noqa: E402
from lib import frontmatter_utils  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WIKI_ROOT = REPO_ROOT / "wiki"
DEFAULT_EPISODES_DIR = REPO_ROOT / "episodes"
DEFAULT_PROCEDURES_DIR = REPO_ROOT / "procedures"

REPORT_FILENAME = "memory_health_report.md"
# wiki_root 직속 메타·리포트 파일 — 페이지 집계에서 제외(curate.find_all_wiki_pages 와 정합).
_SKIP_META = {"curate_report.md", "distill_queue.md", "graph_report.md",
              "reweave_queue.md", REPORT_FILENAME}
# gates 관리 폴더(사적 판단 로그) + archive — 정규 진단·fix 스캔에서 격리
# (curate.find_all_wiki_pages 의 excluded_dirs 와 정합, SPEC v0.3 §D 3점 방어).
_SKIP_DIRS = {"archive", "observing", "rejected"}
# memory_type 미선언 페이지의 기본값. wiki/ 자체가 의미 기억 층(SPEC §A)이므로 semantic.
_DEFAULT_MEMORY_TYPE = "semantic"

LOW_CONFIDENCE_THRESHOLD = 0.5
STALE_PROCEDURE_DAYS = 180
ARCHIVE_AGE_DAYS = 180
TOP_REUSED_N = 10
RECENT_EPISODE_LIMIT = 50   # 집계 대상 최근 에피소드 수
RECENT_BRIEF_N = 20         # 브리프 ref 로 나열할 최대 줄 수

# weak content 기준 (v0.3 WS-3 — 기존 orphan·confidence·stale 기준에 **추가**, 대체 아님).
# schema/curate.md Promotion Gates G-1 임계값과 동일.
WEAK_BODY_MIN_CHARS = 800
WEAK_MIN_SOURCES = 2
WEAK_MIN_H2 = 3

# --fix summary 자동 생성 길이 계약 (G-1 "summary 40~200자" 와 동일).
SUMMARY_MIN_CHARS = 40
SUMMARY_MAX_CHARS = 200

_H2_PATTERN = re.compile(r"^##\s", re.MULTILINE)


@dataclass
class _PageInfo:
    path: Path
    rel: str
    slug: str
    fm: dict
    memory_type: str
    confidence: float | None
    body: str = ""


@dataclass
class FixResult:
    """run_fix 결과 — fixed(자동 보강 적용/계획)·alerts(fix 금지, 사람 판단 필요)."""
    dry_run: bool
    fixed: list[tuple[str, list[str]]] = field(default_factory=list)   # (rel, 액션들)
    alerts: list[tuple[str, str]] = field(default_factory=list)        # (rel, 사유)


def _as_float(x) -> float | None:
    """bool/non-numeric 은 None. confidence 판정용."""
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    return None


def _age_days(fm: dict, fallback_path: Path | None, now: datetime) -> int:
    """last_verified > updated > created 순으로 age(일) 계산. 전부 부재 시 mtime fallback.

    frontmatter 날짜가 우선이라 테스트 결정성을 확보한다(now 주입). 파싱 실패/부재면
    다음 키로, 끝내 없으면 파일 mtime(없으면 0).
    """
    if isinstance(fm, dict):
        for key in ("last_verified", "updated", "created"):
            val = fm.get(key)
            if not val:
                continue
            try:
                dt = datetime.strptime(str(val)[:10], "%Y-%m-%d")
            except (ValueError, TypeError):
                continue
            return (now - dt).days
    if fallback_path is not None:
        try:
            mtime = datetime.fromtimestamp(fallback_path.stat().st_mtime)
            return (now - mtime).days
        except OSError:
            return 0
    return 0


def _collect_pages(wiki_root: Path) -> tuple[list[_PageInfo], list[tuple[str, str]]]:
    """wiki_root/**/*.md 를 읽어 _PageInfo 리스트 + 파싱오류 목록 반환(읽기 전용).

    메타·리포트 파일(루트 직속)과 archive/·observing/·rejected/ 하위는 제외한다
    (curate.find_all_wiki_pages 의 페이지 정의와 정합 — gates 관리 폴더 격리).
    frontmatter 파싱 실패는 크래시 대신 fm={} 로 폴백하고 표면화한다(Rule 8).
    """
    pages: list[_PageInfo] = []
    parse_errors: list[tuple[str, str]] = []
    for md in sorted(wiki_root.rglob("*.md")):
        rel = md.relative_to(wiki_root).as_posix()
        if md.parent == wiki_root and md.name in _SKIP_META:
            continue
        if _SKIP_DIRS & set(md.relative_to(wiki_root).parts):
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            parse_errors.append((rel, f"읽기 실패: {type(exc).__name__}"))
            continue
        try:
            fm, body = frontmatter_utils.read_fm(text)
        except frontmatter_utils.FrontmatterParseError:
            parse_errors.append((rel, "frontmatter 파싱 실패"))
            fm, body = {}, text
        if not isinstance(fm, dict):
            fm = {}
        mt = fm.get("memory_type") or _DEFAULT_MEMORY_TYPE
        pages.append(_PageInfo(
            path=md, rel=rel, slug=md.stem, fm=fm,
            memory_type=str(mt), confidence=_as_float(fm.get("confidence")),
            body=body,
        ))
    return pages, parse_errors


def _section_memory_types(pages: list[_PageInfo]) -> list[str]:
    counts = Counter(p.memory_type for p in pages)
    lines = [f"## 메모리 타입별 페이지 수 — 총 {len(pages)}개", ""]
    for mt in sorted(counts):
        lines.append(f"- {mt}: {counts[mt]}")
    return lines + [""]


def _section_orphans(pages: list[_PageInfo], inbound: dict) -> list[str]:
    orphans = [p for p in pages
               if p.memory_type == "semantic" and not inbound.get(p.slug)]
    lines = [f"## Orphan semantic 페이지 (inbound 0) — {len(orphans)}개", ""]
    for p in sorted(orphans, key=lambda x: x.rel):
        lines.append(f"- {p.slug} (`{p.rel}`)")
    return lines + [""]


def _section_stale_procedures(procedures_dir: Path, now: datetime) -> list[str]:
    stale: list[tuple[str, int]] = []
    for slug in procedures_mod.list_procedures(procedures_dir=procedures_dir):
        try:
            fm, _ = procedures_mod.read_procedure(slug, procedures_dir=procedures_dir)
        except (OSError, frontmatter_utils.FrontmatterParseError):
            continue
        age = _age_days(fm if isinstance(fm, dict) else {},
                        procedures_dir / f"{slug}.md", now)
        if age > STALE_PROCEDURE_DAYS:
            stale.append((slug, age))
    lines = [f"## Stale 절차 (>{STALE_PROCEDURE_DAYS}일 미검증) — {len(stale)}개", ""]
    for slug, age in sorted(stale, key=lambda x: (-x[1], x[0])):
        lines.append(f"- {slug} — {age}일")
    return lines + [""]


def _section_recent_episodes(episodes_dir: Path) -> list[str]:
    """최근 에피소드: 개수 + task_type/status 집계 + ts·종류·상태 브리프(본문 없음).

    🔴 user_goal/inputs/outputs/notes 같은 verbatim 본문은 절대 넣지 않는다(§D).
    """
    recent = episode.read_recent(limit=RECENT_EPISODE_LIMIT, episodes_dir=episodes_dir)
    by_type = Counter(str(r.get("task_type", "?")) for r in recent)
    by_status = Counter(str(r.get("status", "?")) for r in recent)

    lines = [f"## 최근 에피소드 — 총 {len(recent)}개 (집계·메타만, 본문 비공개)", ""]
    lines.append("### task_type별")
    for t in sorted(by_type):
        lines.append(f"- {t}: {by_type[t]}")
    lines.append("")
    lines.append("### status별")
    for s in sorted(by_status):
        lines.append(f"- {s}: {by_status[s]}")
    lines.append("")
    lines.append("### 최근 활동 (timestamp · task_type · status)")
    for r in recent[:RECENT_BRIEF_N]:
        ts = str(r.get("timestamp", ""))
        lines.append(f"- {ts} · {r.get('task_type', '?')} · {r.get('status', '?')}")
    return lines + [""]


def _section_top_reused(pages: list[_PageInfo], express_idx: dict,
                        episode_idx: dict) -> list[str]:
    reused = []
    for p in pages:
        er = int(express_idx.get(p.slug, 0))
        ep = int(episode_idx.get(p.slug, 0))
        total = er + ep
        if total > 0:
            reused.append((p.slug, er, ep, total))
    reused.sort(key=lambda x: (-x[3], x[0]))
    top = reused[:TOP_REUSED_N]
    lines = [f"## Top 재사용 페이지 — {len(top)}개", ""]
    for slug, er, ep, total in top:
        lines.append(f"- {slug} — 재사용 {total} (express {er}, episode {ep})")
    return lines + [""]


def _section_low_confidence(pages: list[_PageInfo]) -> list[str]:
    low = [(p.slug, p.confidence) for p in pages
           if p.confidence is not None and p.confidence < LOW_CONFIDENCE_THRESHOLD]
    low.sort(key=lambda x: (x[1], x[0]))
    lines = [f"## 저신뢰 페이지 (confidence < {LOW_CONFIDENCE_THRESHOLD}) — {len(low)}개", ""]
    for slug, conf in low:
        lines.append(f"- {slug} — confidence {conf}")
    return lines + [""]


def _count_sources(fm: dict) -> int:
    """frontmatter sources 건수 — list 는 len, 비어있지 않은 str 은 1, 그 외 0."""
    src = fm.get("sources") if isinstance(fm, dict) else None
    if isinstance(src, list):
        return len(src)
    if isinstance(src, str) and src.strip():
        return 1
    return 0


def _weak_content_issues(fm: dict, body: str) -> list[str]:
    """weak content 판정(v0.3 신규 기준): 본문<800자 OR 근거<2건 OR H2<3개."""
    issues: list[str] = []
    n_chars = len(body.strip())
    if n_chars < WEAK_BODY_MIN_CHARS:
        issues.append(f"본문 {n_chars}자 (<{WEAK_BODY_MIN_CHARS}자)")
    n_src = _count_sources(fm)
    if n_src < WEAK_MIN_SOURCES:
        issues.append(f"근거 {n_src}건 (<{WEAK_MIN_SOURCES}건)")
    n_h2 = len(_H2_PATTERN.findall(body))
    if n_h2 < WEAK_MIN_H2:
        issues.append(f"H2 {n_h2}개 (<{WEAK_MIN_H2}개)")
    return issues


def _section_weak_content(pages: list[_PageInfo]) -> list[str]:
    weak = [(p, _weak_content_issues(p.fm, p.body)) for p in pages]
    weak = [(p, issues) for p, issues in weak if issues]
    lines = [
        f"## Weak content 페이지 (본문<{WEAK_BODY_MIN_CHARS}자 OR "
        f"근거<{WEAK_MIN_SOURCES}건 OR H2<{WEAK_MIN_H2}개) — {len(weak)}개",
        "",
        "> 자동 보강 대상 아님 — 본문·근거 부족은 raw/ 출처 기반 사람/커맨드 판단(가짜 보강 금지).",
    ]
    for p, issues in sorted(weak, key=lambda x: x[0].rel):
        lines.append(f"- {p.slug} (`{p.rel}`) — " + "; ".join(issues))
    return lines + [""]


def _section_fix_result(fr: FixResult) -> list[str]:
    mode = "dry-run·미적용" if fr.dry_run else "적용"
    lines = [f"## Fix 결과 — fixed: {len(fr.fixed)} / alert: {len(fr.alerts)} ({mode})", ""]
    if fr.fixed:
        lines.append("### 자동 보강 (frontmatter 기계적 채움)")
        for rel, actions in fr.fixed:
            lines.append(f"- `{rel}` — " + "; ".join(actions))
        lines.append("")
    if fr.alerts:
        lines.append("### Alert (자동 보강 금지 — 사람/커맨드 판단 필요)")
        for rel, reason in fr.alerts:
            lines.append(f"- `{rel}` — {reason}")
        lines.append("")
    return lines


def _section_archive_candidates(pages: list[_PageInfo], inbound: dict, graph_index: dict,
                                express_idx: dict, episode_idx: dict,
                                now: datetime) -> list[str]:
    """archive 후보 = inbound 0 AND age>180일. memory_score 로 보존 가치 주석(낮을수록 우선)."""
    cands = []
    for p in pages:
        if inbound.get(p.slug):
            continue
        age = _age_days(p.fm, p.path, now)
        if age <= ARCHIVE_AGE_DAYS:
            continue
        entry = {
            "slug": p.slug,
            "access_count": p.fm.get("access_count", 0) if isinstance(p.fm, dict) else 0,
            "age_days": age,
            "express_reuse": express_idx.get(p.slug, 0),
            "episode_ref": episode_idx.get(p.slug, 0),
        }
        score = curate.compute_memory_score(entry, graph_index, p.fm, now=now)
        cands.append((p.slug, age, score))
    cands.sort(key=lambda x: (x[2], -x[1], x[0]))  # score 오름차순(낮을수록 archive 우선)
    lines = [f"## Archive 후보 (inbound 0 · age>{ARCHIVE_AGE_DAYS}일) — {len(cands)}개", ""]
    lines.append("> memory_score 낮을수록 재사용 가치 낮음(archive 우선). 실제 이동은 사람 결정.")
    for slug, age, score in cands:
        lines.append(f"- {slug} — {age}일, score={score:.1f}")
    return lines + [""]


# ── --fix: 자동 보강 가능분만 (v0.3 WS-3) ─────────────────────────────
def _valid_date(val) -> bool:
    """YYYY-MM-DD(접두 10자) 파싱 가능 여부 — updated 형식 결손 판정용."""
    if not val:
        return False
    try:
        datetime.strptime(str(val)[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return False
    return True


def _extract_summary(body: str) -> str | None:
    """본문 첫 문단(헤딩 제외)에서 40~200자 summary 추출. 40자 미만이면 None.

    가짜 보강 금지 — 있는 텍스트의 기계적 추출·절단만 하고, 생성·패딩하지 않는다.
    """
    para_lines: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            if para_lines:
                break  # 첫 문단 종료(빈 줄 또는 다음 헤딩)
            continue   # 문단 시작 전 헤딩·빈 줄은 건너뜀
        para_lines.append(stripped)
    text = " ".join(para_lines).strip()
    if len(text) < SUMMARY_MIN_CHARS:
        return None
    return text[:SUMMARY_MAX_CHARS]


def _plan_page_fixes(fm: dict, body: str, now: datetime) -> tuple[dict, list[str], list[str]]:
    """(새 fm, 적용 액션들, 자동 보강 불가 사유들) — 기계적 채움만 계획, body 불변.

    ⑴ summary 결손 → 본문 첫 문단 40~200자 추출 ⑵ source_count 결손/불일치 →
    len(sources) 캐시 ⑶ updated 형식 결손 → created(유효 시) 또는 now 날짜.
    액션이 없으면 fm 을 다시 쓰지 않아 idempotent(2회 실행 바이트 무변경)가 보장된다.
    """
    new_fm = dict(fm)  # 삽입 순서 보존 shallow copy — write_fm(sort_keys=False)와 정합
    actions: list[str] = []
    unfixable: list[str] = []

    if not new_fm.get("summary"):
        candidate = _extract_summary(body)
        if candidate is not None:
            new_fm["summary"] = candidate
            actions.append(f"summary 생성({len(candidate)}자)")
        else:
            unfixable.append(
                f"summary 자동 생성 불가 — 본문 첫 문단 <{SUMMARY_MIN_CHARS}자 (가짜 보강 금지)")

    sources = new_fm.get("sources")
    if isinstance(sources, list) and new_fm.get("source_count") != len(sources):
        prev = new_fm.get("source_count")
        new_fm["source_count"] = len(sources)
        actions.append(f"source_count {prev!r}→{len(sources)}")

    if not _valid_date(new_fm.get("updated")):
        created = new_fm.get("created")
        filled = str(created)[:10] if _valid_date(created) else f"{now:%Y-%m-%d}"
        new_fm["updated"] = filled
        actions.append(f"updated 채움({filled})")

    return new_fm, actions, unfixable


def run_fix(wiki_root: Path, *, dry_run: bool = False, now: datetime | None = None) -> FixResult:
    """자동 보강 가능분만 fix(opt-in). 반환: FixResult(fixed·alerts).

    - 쓰기는 frontmatter_utils.read_fm/write_fm 경유 — body 무손상.
    - 본문·근거 부족(weak content)은 절대 fix 하지 않고 alert 만(가짜 보강 금지).
    - 파싱 실패 페이지는 건드리지 않고 alert(fail-loud).
    - frontmatter 블록이 없는 페이지는 기계적 채움 대상이 아니다(블록 신설 금지).
    - dry_run=True 면 어떤 파일도 쓰지 않고 계획만 반환한다.
    """
    wiki_root = Path(wiki_root)
    if now is None:
        now = datetime.now()
    pages, parse_errors = _collect_pages(wiki_root)
    error_rels = {rel for rel, _ in parse_errors}
    result = FixResult(dry_run=dry_run)

    for rel, reason in parse_errors:
        result.alerts.append((rel, f"{reason} — fix 제외(fail-loud, 페이지 무변경)"))

    for p in pages:
        if p.rel in error_rels:
            continue  # 파싱 실패 페이지는 절대 건드리지 않는다
        issues = _weak_content_issues(p.fm, p.body)
        if issues:
            result.alerts.append((p.rel, "; ".join(issues) + " — 본문·근거 부족은 alert만"))
        if not p.fm:
            continue  # frontmatter 없음 — 기계적 채움 범위 밖
        new_fm, actions, unfixable = _plan_page_fixes(p.fm, p.body, now)
        for reason in unfixable:
            result.alerts.append((p.rel, reason))
        if actions:
            if not dry_run:
                p.path.write_text(
                    frontmatter_utils.write_fm(new_fm, p.body), encoding="utf-8")
            result.fixed.append((p.rel, actions))
    return result


def generate_report(
    wiki_root: Path,
    *,
    episodes_dir: Path | None = None,
    procedures_dir: Path | None = None,
    express_dir: Path | None = None,
    now: datetime | None = None,
    fix_result: FixResult | None = None,
) -> str:
    """집계 전용 markdown 리포트 텍스트 생성 (읽기 전용, verbatim episode 본문 금지).

    wiki_root: wiki 페이지 디렉토리(graph.json·메타파일 포함). 리포트도 이 직속에 쓰인다.
    episodes_dir/procedures_dir: wiki/ 밖 원장·절차 디렉토리(주입 가능).
    express_dir: 재사용 신호 스캔용 express 산출물 디렉토리(기본 wiki_root.parent/express).
    now: 날짜 기반 섹션(stale·archive·recency)의 결정성용 주입(기본 datetime.now()).
    fix_result: --fix/--dry-run 실행 결과 — 주어지면 `fixed: N / alert: M` 요약 섹션 포함.
    """
    wiki_root = Path(wiki_root)
    episodes_dir = Path(episodes_dir) if episodes_dir is not None else DEFAULT_EPISODES_DIR
    procedures_dir = Path(procedures_dir) if procedures_dir is not None else DEFAULT_PROCEDURES_DIR
    express_dir = Path(express_dir) if express_dir is not None else wiki_root.parent / "express"
    if now is None:
        now = datetime.now()

    pages, parse_errors = _collect_pages(wiki_root)
    _, inbound = curate.build_link_graph([p.path for p in pages])
    express_idx = curate.build_express_reuse_index(express_dir)
    episode_idx = curate.build_episode_ref_index(episodes_dir)
    graph_index = curate.load_graph_index(wiki_root / "graph.json")

    if fix_result is not None and not fix_result.dry_run:
        mode_line = ("> --fix 실행 집계 리포트(메타 기억 관측). 자동 보강 가능분의 "
                     "frontmatter만 갱신 — 페이지 이동·삭제·생성·본문 변경 없음.")
    else:
        mode_line = ("> 읽기 전용 집계 리포트(메타 기억 관측). "
                     "어떤 wiki 페이지도 이동·삭제·생성하지 않는다.")
    lines = [
        f"# Memory Health Report — {now:%Y-%m-%d %H:%M}",
        "",
        mode_line,
        "> verbatim episode 본문 없음(§D 프라이버시). okf META_FILES 제외 — 공개 번들 미포함.",
        "",
    ]
    if fix_result is not None:
        lines += _section_fix_result(fix_result)
    lines += _section_memory_types(pages)
    lines += _section_orphans(pages, inbound)
    lines += _section_stale_procedures(procedures_dir, now)
    lines += _section_recent_episodes(episodes_dir)
    lines += _section_top_reused(pages, express_idx, episode_idx)
    lines += _section_low_confidence(pages)
    lines += _section_weak_content(pages)
    lines += _section_archive_candidates(
        pages, inbound, graph_index, express_idx, episode_idx, now)

    if parse_errors:
        lines.append(f"## frontmatter 파싱 경고 — {len(parse_errors)}개")
        lines.append("")
        for rel, reason in parse_errors:
            lines.append(f"- `{rel}` — {reason}")
        lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


def write_report(
    wiki_root: Path,
    *,
    episodes_dir: Path | None = None,
    procedures_dir: Path | None = None,
    express_dir: Path | None = None,
    now: datetime | None = None,
    fix_result: FixResult | None = None,
) -> Path:
    """generate_report 결과를 wiki_root/memory_health_report.md 에 쓰고 경로 반환.

    유일한 부작용은 이 리포트 파일 쓰기뿐 — 다른 wiki 페이지는 절대 건드리지 않는다
    (페이지 쓰기는 opt-in `run_fix` 만 수행한다).
    """
    wiki_root = Path(wiki_root)
    text = generate_report(
        wiki_root, episodes_dir=episodes_dir, procedures_dir=procedures_dir,
        express_dir=express_dir, now=now, fix_result=fix_result,
    )
    report_path = wiki_root / REPORT_FILENAME
    report_path.write_text(text, encoding="utf-8")
    return report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="메모리 건강 리포트 → wiki/memory_health_report.md "
                    "(US-008; 기본 read-only, --fix 만 opt-in 페이지 보강)"
    )
    parser.add_argument(
        "--report", action="store_true",
        help="wiki/memory_health_report.md 생성(기본 동작, 읽기 전용 — 페이지 무변경)",
    )
    parser.add_argument(
        "--fix", action="store_true",
        help="자동 보강 가능분만 fix(summary·source_count·updated 기계적 채움, "
             "idempotent) 후 리포트에 fixed/alert 요약 포함. 본문·근거 부족은 alert만",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="fix 대상 목록만 출력 — 어떤 파일도 변경하지 않음(리포트 미작성)",
    )
    args = parser.parse_args(argv)

    if not DEFAULT_WIKI_ROOT.is_dir():
        print(f"[memory_health] ERROR: wiki dir not found: {DEFAULT_WIKI_ROOT}",
              file=sys.stderr)
        return 1

    if args.dry_run:
        result = run_fix(DEFAULT_WIKI_ROOT, dry_run=True)
        print(f"[memory_health] dry-run — fix 대상 {len(result.fixed)}건 / "
              f"alert {len(result.alerts)}건 (파일 무변경)")
        for rel, actions in result.fixed:
            print(f"  fix: {rel} — {'; '.join(actions)}")
        for rel, reason in result.alerts:
            print(f"  alert: {rel} — {reason}")
        return 0

    if args.fix:
        result = run_fix(DEFAULT_WIKI_ROOT, dry_run=False)
        path = write_report(DEFAULT_WIKI_ROOT, fix_result=result)
        print(f"[memory_health] fixed: {len(result.fixed)} / "
              f"alert: {len(result.alerts)} → {path}")
        return 0

    path = write_report(DEFAULT_WIKI_ROOT)
    print(f"[memory_health] → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
