#!/usr/bin/env python3
"""brain_context.py — 작업기억(working-memory) 팩 생성기 (PRD US-005, Phase 2).

5층 메모리 OS 의 "턴 직전 조립" 기질. 한 작업을 시작하기 전에 흩어진 메모리
(semantic wiki · episodic 원장 · procedural 절차 · 정적 가드레일)를 **결정적 순서**의
한 팩으로 모아 Claude Code 가 곧바로 읽을 수 있게 한다. 임베딩 없는 file-first 조립이라
현 저장소에서 <1s 안에 끝난다.

6 섹션(결정적 순서, 테스트 가능):
  1. 목표        — --task 원문
  2. 관련 semantic 페이지 — express.collect_related_pages 재사용 + **graph degree 동점 정렬**
  3. 최근 관련 episode    — episode.read_recent (--type 에서 task_type 파생)
  4. 후보 procedure       — procedures 로더 + topic 키워드 필터
  5. 제약                 — CLAUDE.md 가드레일 정적 주입
  6. 출처 경로            — 포함 페이지의 raw/ provenance

wiki_root/episodes_dir/procedures_dir 는 주입 가능(테스트는 tmp 픽스처 사용).
"""
from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
from pathlib import Path

import episode
import express
import procedures
from lib import frontmatter_utils

# 기본 경로 — express.WIKI_ROOT 와 동일한 저장소 루트 의미.
REPO_ROOT = express.WIKI_ROOT

# 정적 가드레일(섹션 5) — CLAUDE.md "가드레일 (절대 위반 금지)" 4항을 그대로 주입.
# raw/ 출처 없는 wiki 사실 금지가 핵심. 모델이 추측으로 채우지 않게 매 팩에 동봉한다.
CONSTRAINTS: tuple[str, ...] = (
    "raw/ 출처 없이 wiki/ 신규 생성·사실 수정 금지",
    "query 응답 중 wiki/ 편집 금지",
    "학습 데이터만으로 wiki/ 작성 금지 — 반드시 raw/ 근거 필요",
    "raw/ 파일 수정 금지 — 읽기 전용 소스",
)

# --type → episode.read_recent 의 task_type 필터 파생.
# read_recent 는 정확 일치만 하므로, 단일 task_type 으로 깔끔히 떨어지는 경우만 지정한다.
# express 는 episode 가 express_blog/lecture/... 로 분산돼 정확 일치가 불가 → None(=topic 만 필터).
# custom 도 특정 타입에 묶지 않음 → None.
TASK_TYPE_FILTER: dict[str, str | None] = {
    "query": "ai_answer",
    "express": None,
    "curate": "curate",
    "custom": None,
}

# topic → 키워드 분해(express.collect_related_pages 와 동일 규칙, 길이 1 토큰 제외).
_SPLIT = re.compile(r"[\s\-/]+")
# index.md 의 "[[slug]] — 설명" 라인 파서(express 와 동일) — degree 동점 정렬용 점수 복원에 사용.
_INDEX_LINE = re.compile(r"\[\[([^\]]+)\]\]\s*—\s*(.+)")


def _keywords(topic: str) -> list[str]:
    return [w for w in _SPLIT.split(topic) if len(w) > 1]


@contextlib.contextmanager
def _express_rooted(wiki_root: Path):
    """express 모듈 전역(WIKI_ROOT/WIKI_DIR/INDEX_FILE)을 주입 wiki_root 로 잠시 가리킨다.

    collect_related_pages 가 모듈 전역에 의존하므로(주입 파라미터 없음) 테스트에서
    tmp wiki 를 읽히려면 이 방식이 필요하다. try/finally 로 원복해 in-process 누수 방지.

    ⚠ 동시성 비안전(코드리뷰 cr-claude MED-latent): express 모듈 전역을 변이하므로
    **CLI/단일 스레드 전용**이다. brain_context 를 FastAPI/async 에서 동시 호출하면 레이스.
    웹 배선 전에는 collect_related_pages 에 경로 주입 파라미터를 추가해 이 swap 을 제거할 것.
    """
    saved = (express.WIKI_ROOT, express.WIKI_DIR, express.INDEX_FILE)
    express.WIKI_ROOT = wiki_root
    express.WIKI_DIR = wiki_root / "wiki"
    express.INDEX_FILE = wiki_root / "index.md"
    try:
        yield
    finally:
        express.WIKI_ROOT, express.WIKI_DIR, express.INDEX_FILE = saved


def _safe_fm(content: str) -> tuple[dict, str]:
    """frontmatter 파싱(brain_context 는 한 페이지 손상으로 팩 전체를 깨지 않는다)."""
    try:
        return frontmatter_utils.read_fm(content)
    except frontmatter_utils.FrontmatterParseError:
        return {}, content


def _normalize_sources(value) -> list[str]:
    """frontmatter sources 값을 문자열 리스트로 정규화(list/str/None 안전)."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if value:
        return [str(value)]
    return []


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _load_degrees(wiki_root: Path) -> dict[str, int]:
    """wiki/graph.json 의 page 노드 degree(inbound+outbound)를 {slug: degree} 로.

    graph.json 부재·손상 시 빈 dict(=모든 degree 0, 동점 정렬은 slug asc 로 폴백)."""
    gp = wiki_root / "wiki" / "graph.json"
    if not gp.exists():
        return {}
    try:
        data = json.loads(gp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    degrees: dict[str, int] = {}
    for node in data.get("nodes", []):
        if node.get("kind") == "page":
            degrees[node.get("id")] = int(node.get("inbound", 0)) + int(node.get("outbound", 0))
    return degrees


def _index_scores(topic: str, wiki_root: Path) -> dict[str, int]:
    """index.md 에서 {slug: keyword_score} 복원.

    collect_related_pages 는 점수를 반환하지 않으므로, degree 를 **동점에만** 적용하려면
    키워드 점수(1차 키)를 다시 구해야 한다. express.keyword_score 를 재사용해 동일 점수를 보장.
    """
    index_file = wiki_root / "index.md"
    if not index_file.exists():
        return {}
    keywords = _keywords(topic)
    scores: dict[str, int] = {}
    for line in index_file.read_text(errors="replace").splitlines():
        m = _INDEX_LINE.search(line)
        if not m:
            continue
        slug, desc = m.group(1).strip(), m.group(2).strip()
        scores[slug] = express.keyword_score(slug + " " + desc, keywords)
    return scores


def _related_pages(topic: str, max_pages: int, wiki_root: Path) -> list[dict]:
    """섹션 2 — express.collect_related_pages 재사용 + degree 동점 정렬.

    정렬 키: (키워드 점수 desc, graph degree desc, slug asc). 점수가 1차이고 degree 는
    **동점일 때만** 순서를 가른다(slug 가 최종 결정 키 = 완전 결정성).
    """
    with _express_rooted(wiki_root):
        selected = express.collect_related_pages(topic, max_pages)
    scores = _index_scores(topic, wiki_root)
    degrees = _load_degrees(wiki_root)

    def sort_key(item: tuple[Path, str]):
        slug = item[0].stem
        return (-scores.get(slug, 0), -degrees.get(slug, 0), slug)

    pages: list[dict] = []
    for path, content in sorted(selected, key=sort_key):
        fm, _ = _safe_fm(content)
        slug = path.stem
        pages.append(
            {
                "slug": slug,
                "title": str(fm.get("title", slug)),
                "path": _relpath(path, wiki_root),
                "score": scores.get(slug, 0),
                "degree": degrees.get(slug, 0),
                "sources": _normalize_sources(fm.get("sources")),
            }
        )
    return pages


def _recent_episodes(type_: str, topic: str, episodes_dir: Path, limit: int) -> list[dict]:
    """섹션 3 — episode.read_recent (--type 에서 task_type 파생, topic 필터)."""
    task_type = TASK_TYPE_FILTER.get(type_)
    records = episode.read_recent(
        task_type=task_type, topic=topic, limit=limit, episodes_dir=episodes_dir
    )
    return [
        {
            "timestamp": r.get("timestamp", ""),
            "task_type": r.get("task_type", ""),
            "user_goal": r.get("user_goal", ""),
            "status": r.get("status", ""),
        }
        for r in records
    ]


def _candidate_procedures(topic: str, procedures_dir: Path) -> list[dict]:
    """섹션 4 — procedures 로더 + topic 키워드 필터(slug/제목/본문 매칭).

    list_procedures 가 이미 정렬 반환 → 매칭 순서도 결정적. 키워드가 없으면(짧은 topic)
    전체를 후보로(graceful)."""
    keywords = [k.lower() for k in _keywords(topic)]
    out: list[dict] = []
    for slug in procedures.list_procedures(procedures_dir):
        try:
            fm, body = procedures.read_procedure(slug, procedures_dir)
        except (OSError, frontmatter_utils.FrontmatterParseError):
            continue
        title = str(fm.get("title", slug))
        hay = f"{slug} {title} {body}".lower()
        if not keywords or any(k in hay for k in keywords):
            out.append({"slug": slug, "title": title})
    return out


def build_pack(
    *,
    task: str,
    topic: str,
    type_: str = "custom",
    max_pages: int = 5,
    wiki_root: Path | None = None,
    episodes_dir: Path | None = None,
    procedures_dir: Path | None = None,
    limit: int = 5,
) -> dict:
    """6 섹션 작업기억 팩(dict)을 결정적으로 조립한다.

    경로 인자는 None 이면 모듈 기본값(저장소 루트)을 쓴다 — 테스트는 tmp 를 주입.
    """
    wiki_root = Path(wiki_root) if wiki_root is not None else REPO_ROOT
    episodes_dir = (
        Path(episodes_dir) if episodes_dir is not None else episode.EPISODES_DIR
    )
    procedures_dir = (
        Path(procedures_dir) if procedures_dir is not None else procedures.PROCEDURES_DIR
    )

    related = _related_pages(topic, max_pages, wiki_root)
    source_paths = sorted({s for p in related for s in p["sources"]})

    return {
        "goal": task,
        "topic": topic,
        "type": type_,
        "related_pages": related,
        "recent_episodes": _recent_episodes(type_, topic, episodes_dir, limit),
        "candidate_procedures": _candidate_procedures(topic, procedures_dir),
        "constraints": list(CONSTRAINTS),
        "source_paths": source_paths,
    }


# ── 렌더러 ───────────────────────────────────────────────────────────────────

def render_markdown(pack: dict) -> str:
    """팩을 결정적 마크다운으로. 같은 팩 → 동일 바이트."""
    lines: list[str] = []
    lines.append(f"# 작업기억 팩 — {pack['goal']}")
    lines.append("")
    lines.append(f"- topic: {pack['topic']}")
    lines.append(f"- type: {pack['type']}")
    lines.append("")

    lines.append("## 1. 목표")
    lines.append("")
    lines.append(pack["goal"])
    lines.append("")

    lines.append("## 2. 관련 semantic 페이지")
    lines.append("")
    if pack["related_pages"]:
        for p in pack["related_pages"]:
            lines.append(
                f"- [[{p['slug']}]] — {p['title']} "
                f"(score {p['score']}, degree {p['degree']})"
            )
            lines.append(f"  - 경로: {p['path']}")
    else:
        lines.append("(관련 페이지 없음)")
    lines.append("")

    lines.append("## 3. 최근 관련 episode")
    lines.append("")
    if pack["recent_episodes"]:
        for e in pack["recent_episodes"]:
            lines.append(
                f"- {e['timestamp']} · {e['task_type']} · {e['user_goal']} ({e['status']})"
            )
    else:
        lines.append("(최근 episode 없음)")
    lines.append("")

    lines.append("## 4. 후보 procedure")
    lines.append("")
    if pack["candidate_procedures"]:
        for c in pack["candidate_procedures"]:
            lines.append(f"- {c['slug']} — {c['title']}")
    else:
        lines.append("(후보 procedure 없음)")
    lines.append("")

    lines.append("## 5. 제약")
    lines.append("")
    for c in pack["constraints"]:
        lines.append(f"- {c}")
    lines.append("")

    lines.append("## 6. 출처 경로")
    lines.append("")
    if pack["source_paths"]:
        for s in pack["source_paths"]:
            lines.append(f"- {s}")
    else:
        lines.append("(출처 경로 없음)")
    lines.append("")

    return "\n".join(lines)


def render_json(pack: dict) -> str:
    """팩을 결정적 JSON 으로(구조 무손실, 동일 입력 → 동일 바이트)."""
    return json.dumps(pack, ensure_ascii=False, indent=2)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="작업기억 팩 생성기 — 한 작업을 위해 흩어진 메모리를 결정적으로 조립한다."
    )
    parser.add_argument("--task", required=True, help="작업 목표(섹션 1)")
    parser.add_argument("--topic", required=True, help="관련 페이지·episode·procedure 검색 토픽")
    parser.add_argument(
        "--type",
        dest="type_",
        choices=["query", "express", "curate", "custom"],
        default="custom",
        help="작업 유형(episode task_type 필터 파생, 기본: custom)",
    )
    parser.add_argument("--max-pages", type=int, default=5, help="관련 페이지 최대 수(기본: 5)")
    parser.add_argument("--json", action="store_true", help="JSON 출력(기본: 마크다운)")
    args = parser.parse_args(argv)

    pack = build_pack(
        task=args.task,
        topic=args.topic,
        type_=args.type_,
        max_pages=args.max_pages,
    )
    print(render_json(pack) if args.json else render_markdown(pack))
    return 0


if __name__ == "__main__":
    sys.exit(main())
