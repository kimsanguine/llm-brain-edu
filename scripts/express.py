#!/usr/bin/env python3
"""
express.py — wiki/ 페이지를 읽어 창작물(블로그, 강의, 요약, 리포트) 초안을 준비한다.
실제 LLM 합성은 Claude Code가 담당하며, 이 스크립트는 관련 페이지 수집·경로 안내 역할.

사용법:
  python scripts/express.py blog "AI 에이전트 설계 패턴에 대해"
  python scripts/express.py lecture "context-first-orchestration" --slides 3
  python scripts/express.py summary --week
  python scripts/express.py summary --month
  python scripts/express.py report "habix 경쟁사 현황"
"""
import argparse
import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

import episode  # scripts/ 가 sys.path 에 있음(스크립트 직접 실행·테스트 모두)

WIKI_ROOT = Path(__file__).parent.parent
WIKI_DIR = WIKI_ROOT / "wiki"
INDEX_FILE = WIKI_ROOT / "index.md"
EXPRESS_DIR = WIKI_ROOT / "express"
RAW_BLOG_DIR = WIKI_ROOT / "raw" / "blog"

# 타입별 express/ 하위 디렉토리
TYPE_DIR = {
    "blog": EXPRESS_DIR / "blog",
    "lecture": EXPRESS_DIR / "lecture",
    "summary": EXPRESS_DIR / "summary",
    "report": EXPRESS_DIR / "report",
}


# ── 유틸리티 ────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    """토픽 문자열을 파일명 slug로 변환한다."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    return text[:60]


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def load_index() -> str:
    if not INDEX_FILE.exists():
        return ""
    return INDEX_FILE.read_text(errors="replace")


def extract_wikilinks(text: str) -> list[str]:
    """[[wikilink]] 형식의 링크명을 추출한다."""
    return re.findall(r"\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]", text)


def find_wiki_file(slug: str) -> Path | None:
    """wiki/ 전체에서 slug에 해당하는 .md 파일을 탐색한다."""
    for f in WIKI_DIR.rglob("*.md"):
        if f.stem == slug:
            return f
    return None


def keyword_score(text: str, keywords: list[str]) -> int:
    """텍스트에 키워드가 등장하는 횟수를 점수로 반환한다."""
    text_lower = text.lower()
    return sum(text_lower.count(kw.lower()) for kw in keywords)


def collect_related_pages(topic: str, max_pages: int = 5) -> list[tuple[Path, str]]:
    """
    index.md의 wikilink와 한 줄 설명을 키워드 매칭으로 순위를 매겨
    관련 wiki 페이지 파일과 내용을 반환한다.
    """
    index_text = load_index()
    keywords = [w for w in re.split(r"[\s\-/]+", topic) if len(w) > 1]

    # index.md에서 [[slug]] — 설명 줄을 파싱
    pattern = re.compile(r"\[\[([^\]]+)\]\]\s*—\s*(.+)")
    candidates: list[tuple[int, str, str]] = []  # (score, slug, desc)

    for line in index_text.splitlines():
        m = pattern.search(line)
        if not m:
            continue
        slug, desc = m.group(1).strip(), m.group(2).strip()
        score = keyword_score(slug + " " + desc, keywords)
        if score > 0:
            candidates.append((score, slug, desc))

    # 점수 내림차순 정렬, 상위 max_pages
    candidates.sort(key=lambda x: x[0], reverse=True)
    top = candidates[:max_pages]

    results: list[tuple[Path, str]] = []
    for _, slug, _ in top:
        path = find_wiki_file(slug)
        if path and path.exists():
            results.append((path, path.read_text(errors="replace")))

    return results


def collect_recent_pages(days: int) -> list[tuple[Path, str]]:
    """
    wiki/insights/ 와 wiki/concepts/ 에서 최근 N일 이내 수정된 파일을 반환한다.
    수정일 정보가 없으면 updated: frontmatter를 파싱해 대체한다.
    """
    cutoff = datetime.now() - timedelta(days=days)
    results: list[tuple[Path, str]] = []

    target_dirs = [WIKI_DIR / "insights", WIKI_DIR / "concepts", WIKI_DIR / "projects"]
    date_pattern = re.compile(r"^updated:\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE)

    for d in target_dirs:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.md")):
            content = f.read_text(errors="replace")
            # frontmatter updated 우선, 없으면 mtime
            m = date_pattern.search(content)
            if m:
                try:
                    file_date = datetime.strptime(m.group(1), "%Y-%m-%d")
                except ValueError:
                    file_date = datetime.fromtimestamp(f.stat().st_mtime)
            else:
                file_date = datetime.fromtimestamp(f.stat().st_mtime)

            if file_date >= cutoff:
                results.append((f, content))

    return results


def build_context_block(pages: list[tuple[Path, str]]) -> str:
    """수집한 페이지를 Claude Code가 읽기 쉬운 컨텍스트 블록으로 묶는다."""
    if not pages:
        return "(관련 wiki 페이지를 찾지 못했습니다. 토픽을 달리 표현해 보세요.)"
    parts = []
    for path, content in pages:
        rel = path.relative_to(WIKI_ROOT)
        parts.append(f"### {rel}\n\n{content.strip()}")
    return "\n\n---\n\n".join(parts)


def save_draft(output_path: Path, content: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content)
    print(f"[express] 저장: {output_path.relative_to(WIKI_ROOT)}")


def _reuse_meta_block(output_type: str, pages: list[tuple[Path, str]]) -> str:
    """US-007 재사용 메타 frontmatter 블록을 (닫는 newline 없이) 만든다.

    source_pages 는 페이지 slug(파일 stem)의 기계 판독 가능한 YAML 리스트.
    소스가 0개면 `source_pages: []`(유효한 빈 리스트). 나머지는 생성 시점 기본값.
    """
    slugs = [p.stem for p, _ in pages]
    if slugs:
        source_pages = "source_pages:\n" + "\n".join(f"  - {s}" for s in slugs)
    else:
        source_pages = "source_pages: []"
    return (
        f"output_type: {output_type}\n"
        f"published_url: null\n"
        f"{source_pages}\n"
        f"derived_insight: null\n"
        f"reuse_as: []"
    )


def _record_express_episode(
    task_type: str,
    user_goal: str,
    inputs: dict,
    pages: list[tuple[Path, str]],
    out_path: Path,
    procedure: str,
) -> None:
    """save_draft 성공 직후 에피소드 원장에 기록한다(US-002).

    **fail-soft**: 헬퍼는 fail-loud(EpisodeSchemaError) 지만, 메인 명령 경로가
    원장 실패로 깨지면 안 되므로 여기서 try/except 로 감싸 warn+continue 한다.
    timestamp 는 tz-aware(astimezone) — naive 면 read_recent 의 교차-TZ 정렬이 깨진다.
    """
    try:
        record = {
            "timestamp": datetime.now().astimezone().isoformat(),
            "task_type": task_type,
            "user_goal": user_goal,
            "inputs": inputs,
            "read_pages": [str(p.relative_to(WIKI_ROOT)) for p, _ in pages],
            "procedures_used": [procedure],
            "outputs": {
                "draft_path": str(out_path.relative_to(WIKI_ROOT)),
                "source_count": len(pages),
            },
            "status": "draft_ready",
            "notes": "",
        }
        episode.append(record)
    except (episode.EpisodeSchemaError, Exception) as e:  # noqa: B014 — 명시적 fail-soft
        print(f"[express] episode 기록 실패(무시): {e}", file=sys.stderr)


# ── 서브커맨드 핸들러 ────────────────────────────────────────────────────────

def cmd_blog(topic: str) -> None:
    """블로그 포스트 초안 컨텍스트를 준비한다."""
    pages = collect_related_pages(topic, max_pages=5)
    context = build_context_block(pages)
    date_str = today_str()
    slug = slugify(topic)
    filename = f"{date_str}-{slug}.md"

    draft = f"""---
type: blog
topic: {topic}
created: {date_str}
status: draft
{_reuse_meta_block("blog", pages)}
sources:
{chr(10).join(f'  - {p.relative_to(WIKI_ROOT)}' for p, _ in pages) or '  - (없음)'}
---

# (블로그 제목 — Claude가 작성)

> **합성 대기 중** — 아래 컨텍스트를 바탕으로 Claude Code가 본문을 작성합니다.

<!-- CONTEXT_START -->
{context}
<!-- CONTEXT_END -->
"""

    out_path = TYPE_DIR["blog"] / filename
    save_draft(out_path, draft)

    # raw/blog/에도 복사 (ingest 피드백 루프)
    RAW_BLOG_DIR.mkdir(parents=True, exist_ok=True)
    raw_dst = RAW_BLOG_DIR / filename
    shutil.copy2(out_path, raw_dst)
    print(f"[express] 복사 (raw/blog/): {raw_dst.relative_to(WIKI_ROOT)}")

    _record_express_episode(
        "express_blog", topic, {"topic": topic}, pages, out_path, "collect_related_pages"
    )
    _print_synthesis_hint("blog", topic, out_path, pages)


def cmd_lecture(topic: str, slides: int) -> None:
    """강의 슬라이드 초안 컨텍스트를 준비한다."""
    pages = collect_related_pages(topic, max_pages=6)
    context = build_context_block(pages)
    date_str = today_str()
    slug = slugify(topic)
    filename = f"{date_str}-{slug}.md"

    draft = f"""---
type: lecture
topic: {topic}
slides: {slides}
created: {date_str}
status: draft
{_reuse_meta_block("lecture", pages)}
sources:
{chr(10).join(f'  - {p.relative_to(WIKI_ROOT)}' for p, _ in pages) or '  - (없음)'}
---

# (강의 제목 — Claude가 작성)

> **합성 대기 중** — {slides}장 슬라이드 구성으로 작성 예정.

<!-- CONTEXT_START -->
{context}
<!-- CONTEXT_END -->
"""

    out_path = TYPE_DIR["lecture"] / filename
    save_draft(out_path, draft)
    _record_express_episode(
        "express_lecture",
        topic,
        {"topic": topic, "slides": slides},
        pages,
        out_path,
        "collect_related_pages",
    )
    _print_synthesis_hint("lecture", topic, out_path, pages, extra=f"슬라이드 {slides}장 구성")


def cmd_summary(week: bool, month: bool) -> None:
    """주간/월간 요약 컨텍스트를 준비한다."""
    if week:
        days, label = 7, "weekly"
    else:
        days, label = 30, "monthly"

    pages = collect_recent_pages(days)
    context = build_context_block(pages)
    date_str = today_str()
    filename = f"{date_str}-{label}-summary.md"

    draft = f"""---
type: summary
period: {label}
created: {date_str}
status: draft
{_reuse_meta_block("summary", pages)}
page_count: {len(pages)}
sources:
{chr(10).join(f'  - {p.relative_to(WIKI_ROOT)}' for p, _ in pages) or '  - (없음)'}
---

# {date_str} {label.capitalize()} Summary

> **합성 대기 중** — 최근 {days}일({len(pages)}개 페이지) 기반 요약.

<!-- CONTEXT_START -->
{context}
<!-- CONTEXT_END -->
"""

    out_path = TYPE_DIR["summary"] / filename
    save_draft(out_path, draft)
    _record_express_episode(
        "express_summary",
        f"{label} summary",
        {"period": label, "days": days},
        pages,
        out_path,
        "collect_recent_pages",
    )
    _print_synthesis_hint("summary", f"{label} ({days}일)", out_path, pages)


def cmd_report(topic: str) -> None:
    """심층 리포트 컨텍스트를 준비한다. 관련 페이지를 더 넓게 수집한다."""
    pages = collect_related_pages(topic, max_pages=8)
    context = build_context_block(pages)
    date_str = today_str()
    slug = slugify(topic)
    filename = f"{date_str}-{slug}.md"

    draft = f"""---
type: report
topic: {topic}
created: {date_str}
status: draft
{_reuse_meta_block("report", pages)}
sources:
{chr(10).join(f'  - {p.relative_to(WIKI_ROOT)}' for p, _ in pages) or '  - (없음)'}
---

# (리포트 제목 — Claude가 작성)

> **합성 대기 중** — 아래 컨텍스트를 바탕으로 심층 분석 리포트를 작성합니다.

<!-- CONTEXT_START -->
{context}
<!-- CONTEXT_END -->
"""

    out_path = TYPE_DIR["report"] / filename
    save_draft(out_path, draft)
    _record_express_episode(
        "express_report", topic, {"topic": topic}, pages, out_path, "collect_related_pages"
    )
    _print_synthesis_hint("report", topic, out_path, pages)


def _print_synthesis_hint(
    output_type: str,
    topic: str,
    out_path: Path,
    pages: list[tuple[Path, str]],
    extra: str = "",
) -> None:
    """Claude Code가 실제 합성할 때 사용할 프롬프트 힌트를 출력한다."""
    page_list = "\n".join(f"  - {p.relative_to(WIKI_ROOT)}" for p, _ in pages) or "  (없음)"
    extra_note = f"\n  추가 조건: {extra}" if extra else ""

    print()
    print("=" * 60)
    print(f"[express] 합성 프롬프트 힌트 ({output_type})")
    print("=" * 60)
    print(f"  파일: {out_path.relative_to(WIKI_ROOT)}")
    print(f"  토픽: {topic}{extra_note}")
    print(f"  참조 페이지 ({len(pages)}개):")
    print(page_list)
    print()
    print("  Claude에게 붙여넣을 합성 지시:")
    print(f'  >> "{out_path.relative_to(WIKI_ROOT)}" 파일의 CONTEXT_START~END 사이 내용을')
    print(f'     바탕으로 "{topic}"에 관한 {output_type}을 작성해주세요.')
    if output_type == "blog":
        print("     - 독자: AI/기술 관심 한국어 독자")
        print("     - 길이: 800-1200자 내외")
        print("     - 구조: 도입 → 핵심 인사이트 2-3개 → 실천 제안 → 마무리")
    elif output_type == "lecture":
        print("     - 각 슬라이드: 제목 + 핵심 포인트 3개 이내")
        print("     - 마지막 슬라이드: Q&A 또는 실습 과제")
    elif output_type == "summary":
        print("     - 섹션: 핵심 인사이트 / 반복 패턴 / 다음 액션")
    elif output_type == "report":
        print("     - 섹션: 현황 / 주요 발견 / 시사점 / 권고사항")
    print("=" * 60)


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="wiki/ 페이지를 읽어 창작물 초안 컨텍스트를 준비한다."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # blog
    p_blog = sub.add_parser("blog", help="블로그 포스트 초안")
    p_blog.add_argument("topic", help="블로그 토픽")

    # lecture
    p_lecture = sub.add_parser("lecture", help="강의 슬라이드 초안")
    p_lecture.add_argument("topic", help="강의 토픽 또는 wiki slug")
    p_lecture.add_argument("--slides", type=int, default=5, help="슬라이드 수 (기본: 5)")

    # summary
    p_summary = sub.add_parser("summary", help="주간/월간 요약")
    grp = p_summary.add_mutually_exclusive_group(required=True)
    grp.add_argument("--week", action="store_true", help="주간 요약 (최근 7일)")
    grp.add_argument("--month", action="store_true", help="월간 요약 (최근 30일)")

    # report
    p_report = sub.add_parser("report", help="심층 리포트")
    p_report.add_argument("topic", help="리포트 토픽")

    args = parser.parse_args()

    if args.cmd == "blog":
        cmd_blog(args.topic)
    elif args.cmd == "lecture":
        cmd_lecture(args.topic, args.slides)
    elif args.cmd == "summary":
        cmd_summary(args.week, args.month)
    elif args.cmd == "report":
        cmd_report(args.topic)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
