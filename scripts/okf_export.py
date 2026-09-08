#!/usr/bin/env python3
"""okf_export.py — wiki/ (내부 슈퍼셋) → OKF v0.1 호환 번들 okf/ 투영 (Phase 1).

llm-brain의 export 포트. 내부 포맷은 바꾸지 않고 경계에서만 변환한다.
- frontmatter: OKF 예약 필드(type,title,description,resource,tags,timestamp)로 매핑,
  나머지 내부 필드는 x-llmbrain-* 네임스페이스로 보존 (--strip-internal이면 제거).
- 본문 wikilink: [[X]] → [X](/<rel>) (번들 루트 기준 절대경로). 깨진 링크는 텍스트화.
- description: 규칙 기반 추출 (LLM 호출 없음 — 결정적 변환).
- exclude: 경로 글롭(기본 business/**, canvas/**) + domain 라벨 + slug.

가드레일: raw/·wiki/는 읽기 전용. 출력은 out_dir(기본 okf/)에만.
파서 함수는 scripts/export_graph.py에서 import (수정 없음).

설계와 계약의 공개 기준: SPEC.md 및 schema/okf.md
"""
from __future__ import annotations

import argparse
import datetime
import fnmatch
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# scripts/export_graph.py에서 파서 함수만 import (계약 §0). export_graph는 수정 없음.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_graph import (  # noqa: E402
    FRONTMATTER_RE,
    WIKILINK_RE,
    parse_frontmatter,
)
from export_graph import META_FILES as _EG_META_FILES  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

# 최상위 메타 파일은 export 대상에서 제외 (계약 §3). export_graph의 집합을 재사용해 drift를
# 줄이고, okf 운영 산출물 curate_report.md를 추가(미등재 시 "title 부재"로 skip되는 노이즈).
# memory_health_report.md 도 추가(SPEC §D 누출 봉인): episode 집계 = 격리한 사적 운영맥락의
# 파생이라 공개 OKF 번들에 절대 새면 안 된다(Claude#1·Codex C1, Phase 3 US-008 동반).
META_FILES = _EG_META_FILES | {"curate_report.md", "memory_health_report.md"}

SHARE_MANIFEST = "share-manifest.json"
SHARE_SENTINEL = ".okf-share-bundle"
CANONICAL_SHARE_APPROVAL = "I_ACKNOWLEDGE_SHARE_READY_EXPORT"
KNOWN_SHARE_SCOPES = {"private", "shared"}
KNOWN_SHARE_CLASSIFICATIONS = {
    "business",
    "concept",
    "insight",
    "lecture",
    "person",
    "project",
    "tool",
}

# OKF 예약 필드 순서 (계약 §4). x-llmbrain 보존에서 제외할 소스 키 집합도 여기서 파생.
RESERVED_ORDER = ["type", "title", "description", "resource", "tags", "timestamp"]
# x-llmbrain-* 보존에서 빼는 소스 fm 키 (예약 필드의 소스). updated는 timestamp로 흡수됨.
PRESERVE_SKIP = {"type", "title", "description", "resource", "tags", "updated"}

# 본문에서 마크다운/wikilink 마크업 제거용 (description 추출 시).
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")  # [텍스트](url) → 텍스트
_INLINE_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]")
_MD_MARKUP_RE = re.compile(r"[*_`#>]+")
# description 추출 시 건너뛸 라인: 표 행(`|`로 시작)·수평선(---/***/___).
# 표 구분행은 `| --- |`처럼 `---`를 품어 OKF consumer의 text.split("---")를 깨뜨린다.
_TABLE_ROW_RE = re.compile(r"^\s*\|")
_HRULE_RE = re.compile(r"^\s*([-*_])\1{2,}\s*$")
# ASCII 다이어그램·박스드로잉·화살표 — description으로 부적합(P1: architecture.md·video-pipeline 등).
_DIAGRAM_RE = re.compile(r"[─│┌┐└┘├┤┬┴┼━┃▶◀▲▼➤▸→←↓↑↔⇒]|──▶|\[소스\]")
# 번호 목록 항목(`1. ` `2) `) — 요약이 아니고 다음 번호의 마침표에서 잘림(P1).
_NUMLIST_RE = re.compile(r"^\s*\d+[.)]\s")
# 수식 라인(=, 그리스/첨자 포함) — description으로 부적합(P1: deep-learning 'y = σ(...)').
_FORMULA_RE = re.compile(r"=.*[σΣπΠμλθα-ω₀-₉∑∫√≈≤≥]|[σΣπΠμλθ].*=")
# 영문 약어/이니셜 — 첫 문장 추출이 여기서 잘리면 안 됨(P1: 'Carlos E.').
_ABBREV = {"e.g", "i.e", "etc", "vs", "inc", "ltd", "co", "dr", "mr", "ms", "al", "fig", "no"}


def _is_skippable_desc_line(s: str) -> bool:
    """description 본문 추출에서 제외할 라인(표·수평선·다이어그램·번호목록·bullet·수식)인지."""
    s2 = s.strip()
    return bool(
        _TABLE_ROW_RE.match(s2)
        or _HRULE_RE.match(s2)
        or _DIAGRAM_RE.search(s2)
        or _NUMLIST_RE.match(s2)   # 번호 목록 항목
        or _FORMULA_RE.search(s2)  # 수식
        or s2.startswith("- ")     # bullet 항목은 요약이 아님
        or s2.startswith("* ")
    )


def _clean_description(text: str) -> str:
    """description 최종 정리: 표 파이프·'---'·다이어그램 제거, 공백 축약, 품질 필터.

    OKF consumer는 frontmatter를 text.split('---')로 자르므로 값에 '---'가 남으면 안 된다.
    추출 시 표/다이어그램 스킵에 더한 2차 정리. 품질 미달(버전 문자열만·너무 짧음·글자
    없음)이면 빈 문자열을 반환(잘못된 description보다 없는 게 낫다, P1).
    """
    text = text.replace("|", " ")
    text = re.sub(r"-{3,}", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if _DIAGRAM_RE.search(text) or _FORMULA_RE.search(text):
        return ""
    # 버전 문자열만(예: 'openai-agents=0.14.0.') 또는 글자 없는 경우 → 무의미
    if re.fullmatch(r"[\w.\-=/]+", text) and re.search(r"=?\d", text):
        return ""
    if not re.search(r"[A-Za-z가-힣]", text):
        return ""
    if text.endswith(":") or len(text) < 6:  # 라벨 fragment('수식:')·초단문 → 무의미
        return ""
    return text[:300]


def _strip_code_fences(body: str) -> str:
    """description 추출용으로 ```...``` 펜스 코드블록 제거.

    코드블록 안의 ASCII 다이어그램·코드가 description으로 추출되는 것을 막는다
    (P1: video-pipeline-comparison.md 의 53행 다이어그램이 description으로 샜음).

    펜스는 줄 시작의 ```로 열고(언어 태그 허용) 줄 시작의 ```로 닫는 **블록**만 매칭한다.
    단순 ` ```.*?``` `는 인라인/중첩 삼중백틱에서 내부가 잔류한다(Codex R3 지적).
    """
    return re.sub(r"(?ms)^```[^\n]*\n.*?\n```[ \t]*$", "", body)


@dataclass
class ExportStats:
    pages_exported: int = 0
    links_converted: int = 0
    broken_links: list = field(default_factory=list)        # 진짜 ghost: [(src_rel, target), ...]
    excluded_link_refs: list = field(default_factory=list)  # 제외 페이지를 가리키던 링크(의도된 절단·redact)
    excluded: list = field(default_factory=list)            # [rel_path, ...] (제외된 페이지 전체)
    excluded_private: list = field(default_factory=list)    # [rel_path, ...] scope:private로 제외(경로/도메인/slug 제외와 별도 표면화, v0.3.2 WS-6)
    skipped: list = field(default_factory=list)             # [(rel, reason), ...] 로드 실패·title 부재
    sensitive_hits: list = field(default_factory=list)      # [(rel, pattern), ...] 본문 평문 민감정보 후보
    by_dir: dict = field(default_factory=dict)              # {dir_name: count}


@dataclass
class _Page:
    """로드된 wiki 페이지의 중간 표현."""
    rel: str            # wiki_dir 기준 posix 상대경로. 예: concepts/rag.md
    dir: str            # rel 첫 파트. 예: concepts
    slug: str           # wikilink 해석용 slug
    fm: dict            # 원본 frontmatter
    body: str           # frontmatter 제거된 본문
    bundle_path: str    # 링크 타깃 = "/" + rel


class ShareGateError(RuntimeError):
    """A fail-closed Share-ready policy rejection safe to show without details."""


def load_config(path: Path | None) -> dict:
    """schema/okf_export.yaml 로드. path가 None/부재면 {} 반환 (하드코딩 기본값 사용)."""
    if path is None:
        return {}
    p = Path(path)
    if not p.is_file():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _compute_slug(rel: Path) -> str:
    """export_graph 방식 재사용: 깊이>2면 dir 제외한 subpath, 아니면 stem."""
    parts = rel.parts
    if len(parts) > 2:
        return "/".join(list(parts[1:-1]) + [rel.stem])
    return rel.stem


def _strip_markup(text: str) -> str:
    """wikilink·마크다운 마크업 제거 (description 추출용)."""
    # wikilink: 별칭 있으면 별칭, 없으면 타깃 텍스트
    text = _INLINE_WIKILINK_RE.sub(lambda m: m.group(2) or m.group(1), text)
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _MD_MARKUP_RE.sub("", text)
    return text.strip()


def _first_sentence(text: str, min_len: int = 14) -> str:
    """문단/섹션 텍스트에서 첫 문장 1개 추출.

    약어·이니셜(`Carlos E.`, `e.g.`)의 마침표에서 잘리지 않도록, 종결부호 직전이 단일
    대문자(이니셜)이거나 알려진 약어면 건너뛴다. 최소 길이 미달도 다음 종결을 찾는다(P1).
    """
    cleaned = _strip_markup(text)
    if not cleaned:
        return ""
    for m in re.finditer(r"[.。!?]+(?=\s|$)", cleaned):
        end = m.start()
        before = cleaned[:end]
        last_word = re.split(r"[\s(\[]", before)[-1] if before else ""
        if len(last_word) == 1 and last_word.isalpha():  # 이니셜 'E.'
            continue
        if last_word.lower().rstrip(".") in _ABBREV:       # 'e.g'·'etc'
            continue
        if last_word.rstrip(".").isdigit():                # 번호목록 마커 '2.'
            continue
        candidate = cleaned[: m.end()].strip()
        if len(candidate) >= min_len:
            return candidate
    return cleaned


def _extract_description(fm: dict, body: str) -> str:
    """description 규칙 기반 추출 (계약 §6, LLM 아님).

    ① fm.description → ② 본문 `## 핵심` 첫 문장 → ③ 첫 문단(헤딩 제외) 첫 문장.
    """
    desc = fm.get("description")
    if isinstance(desc, str) and desc.strip():
        return _clean_description(desc)

    lines = _strip_code_fences(body).split("\n")

    # ② `## 핵심` 섹션 첫 문장 (표·수평선 라인은 제외)
    for i, line in enumerate(lines):
        if re.match(r"^#{1,6}\s+핵심", line.strip()):  # '핵심'·'핵심 요약'·'핵심 공식' 등
            section: list[str] = []
            for nxt in lines[i + 1:]:
                if re.match(r"^#{1,6}\s", nxt):  # 다음 헤딩에서 중단
                    break
                if _is_skippable_desc_line(nxt):  # 표·수평선 스킵
                    continue
                section.append(nxt)
            sent = _first_sentence("\n".join(section).strip())
            if sent:
                return _clean_description(sent)
            break

    # ③ 첫 문단(헤딩·빈 줄·표·수평선 제외) 첫 문장
    paragraph: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if paragraph:  # 첫 문단 종료
                break
            continue
        if re.match(r"^#{1,6}\s", stripped) or _is_skippable_desc_line(stripped):
            # 헤딩·표·수평선: 문단 시작 전이면 스킵, 시작 후면 종료
            if paragraph:
                break
            continue
        paragraph.append(stripped)
    sent = _first_sentence(" ".join(paragraph))
    return _clean_description(sent) if sent else ""


def _assert_acyclic_yaml(value, active: set[int] | None = None) -> None:
    """Reject recursive YAML aliases before later serialization can recurse."""
    if not isinstance(value, (dict, list)):
        return
    if active is None:
        active = set()
    identity = id(value)
    if identity in active:
        raise ShareGateError("candidate frontmatter is invalid")
    active.add(identity)
    try:
        children = value.values() if isinstance(value, dict) else value
        for child in children:
            _assert_acyclic_yaml(child, active)
    except RecursionError as exc:
        raise ShareGateError("candidate frontmatter is invalid") from exc
    finally:
        active.remove(identity)


def _read_frontmatter(text: str, *, strict_share: bool = False) -> dict:
    """frontmatter를 PyYAML로 파싱 (타입·블록 리스트 정확).

    export_graph의 미니 파서는 들여쓰기 블록 리스트(`  - item`)를 처리 못 해
    sources/domain 소실 + 깨진 키(`x-llmbrain-- https: //...`)를 낳는다(P2 머신검증).
    또 모든 스칼라를 문자열로 읽어 access_count='0'·last_accessed='null'로 타입 손실.
    → export 읽기 경로는 yaml.safe_load를 쓰고, PyYAML이 거부하는 엣지 frontmatter만
    미니 파서로 fallback (페이지 누락 방지). export_graph.py는 수정하지 않는다.
    """
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    try:
        data = yaml.safe_load(m.group(1))
        if isinstance(data, dict):
            if strict_share:
                _assert_acyclic_yaml(data)
            return data
        if strict_share:
            raise ShareGateError("candidate frontmatter is invalid")
    except ShareGateError:
        raise
    except (yaml.YAMLError, RecursionError) as exc:
        if strict_share:
            raise ShareGateError("candidate frontmatter is invalid") from exc
    return parse_frontmatter(text)  # 미니 파서 fallback


def _assert_safe_share_candidate(wiki_dir: Path, candidate: Path) -> None:
    """Reject symlinks and paths resolving outside wiki before any candidate read."""
    try:
        if candidate.is_symlink():
            raise ShareGateError("wiki candidate symlink is forbidden")
        resolved = candidate.resolve(strict=True)
    except ShareGateError:
        raise
    except (OSError, RuntimeError) as exc:
        raise ShareGateError("wiki candidate path is invalid") from exc
    if resolved != wiki_dir and wiki_dir not in resolved.parents:
        raise ShareGateError("wiki candidate resolves outside wiki root")


def _validated_share_markdown_paths(wiki_dir: Path) -> list[Path]:
    """Validate the complete wiki tree before returning any readable candidate."""
    try:
        entries = sorted(wiki_dir.rglob("*"))
    except (OSError, RuntimeError) as exc:
        raise ShareGateError("wiki candidate path is invalid") from exc
    for entry in entries:
        _assert_safe_share_candidate(wiki_dir, entry)
    return [entry for entry in entries if entry.is_file() and entry.suffix == ".md"]


def _read_safe_share_candidate(wiki_dir: Path, candidate: Path) -> str:
    """Read a prevalidated regular file with O_NOFOLLOW where the platform supports it."""
    _assert_safe_share_candidate(wiki_dir, candidate)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        with os.fdopen(os.open(candidate, flags), "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ShareGateError("wiki candidate path is invalid")
            data = handle.read()
        return data.decode("utf-8")
    except ShareGateError:
        raise
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ShareGateError("candidate frontmatter is invalid") from exc


def _load_pages(
    wiki_dir: Path,
    stats: ExportStats,
    *,
    strict_share: bool = False,
) -> list[_Page]:
    """wiki/**/*.md 로드. 메타 파일·title 없는 파일 제외 (계약 §3).

    읽기/파싱 실패·title 부재는 stats.skipped에 (경로, 사유)로 기록한다(silent 금지).
    한 파일 실패로 전체 export를 중단하지 않되, 누락은 dry-run/log에서 보이게 한다.
    """
    pages: list[_Page] = []
    markdown_paths = (
        _validated_share_markdown_paths(wiki_dir)
        if strict_share
        else sorted(wiki_dir.rglob("*.md"))
    )
    for md in markdown_paths:
        if md.parent == wiki_dir and md.name in META_FILES:
            continue
        rel = md.relative_to(wiki_dir)
        try:
            text = (
                _read_safe_share_candidate(wiki_dir, md)
                if strict_share
                else md.read_text(encoding="utf-8")
            )
            fm = _read_frontmatter(text, strict_share=strict_share)
        except ShareGateError:
            raise
        except (UnicodeDecodeError, OSError, ValueError, RecursionError, yaml.YAMLError) as e:
            if strict_share:
                raise ShareGateError("candidate frontmatter is invalid") from e
            stats.skipped.append((rel.as_posix(), f"읽기/파싱 실패: {type(e).__name__}"))
            continue
        if not fm or "title" not in fm:
            stats.skipped.append((rel.as_posix(), "frontmatter title 부재"))
            continue
        body = FRONTMATTER_RE.sub("", text, count=1)
        pages.append(
            _Page(
                rel=rel.as_posix(),
                dir=rel.parts[0] if len(rel.parts) > 1 else "root",
                slug=_compute_slug(rel),
                fm=fm,
                body=body,
                bundle_path="/" + rel.as_posix(),
            )
        )
    return pages


def _is_excluded(
    page: _Page,
    exclude_paths: list[str],
    exclude_domains: list[str],
    exclude_slugs: list[str],
) -> bool:
    """페이지가 exclude 대상인지 판정 (경로 글롭 + domain 라벨 + slug).

    보안 경계(business 누출 방지)라 fail-safe로 over-exclude한다:
    - 대소문자 무시 — macOS APFS는 case-insensitive라 Business/·BUSINESS/도 같은 디렉토리.
    - `dir/**`·`dir/*` 글롭은 경로 어디에든 그 세그먼트가 있으면 제외(재귀).
      fnmatch의 `*`는 `/`를 못 넘고 `**`도 특별 의미가 없어, 중첩 business/가 새는 것을 막는다.
    """
    rel_lower = page.rel.lower()
    parts_lower = [p.lower() for p in Path(page.rel).parts]
    for pat in exclude_paths:
        pat_lower = pat.lower()
        if pat_lower.endswith("/**") or pat_lower.endswith("/*"):
            seg = pat_lower.split("/", 1)[0]
            if seg in parts_lower:  # 중첩 경로 어디에든 해당 세그먼트가 있으면 제외
                return True
        if fnmatch.fnmatch(rel_lower, pat_lower):
            return True
    if exclude_domains:
        domain = page.fm.get("domain", [])
        if isinstance(domain, str):
            domain = [domain] if domain else []
        if any(d in exclude_domains for d in domain):
            return True
    if exclude_slugs and page.slug in exclude_slugs:
        return True
    return False


def _is_scope_private(page: _Page) -> bool:
    """frontmatter `scope: private` 페이지인지 (v0.3.2 WS-6 P1 team-ready 훅).

    scope 미지정·`shared`는 공개(하위호환 — 기존 페이지 동작 불변). `private`만 제외한다.
    이 필터는 플래그가 아니라 **항상** 적용된다: public 커밋은 one-way door라, 플래그 게이트로
    두면 flag 없는 fresh clone/CI 실행이 private 페이지를 그대로 유출한다(빈 exclude_paths
    fail-safe와 같은 논리). 대소문자 무시(fail-safe over-exclude 방향). private 제외는
    business/** 제외와 같은 레일 — stats.excluded 에 반영되고 링크는 redact 처리된다.
    """
    scope = page.fm.get("scope")
    return isinstance(scope, str) and scope.strip().lower() == "private"


def _build_slug_map(pages: list[_Page]) -> dict[str, str]:
    """slug → 번들경로 맵. wikilink 해석용."""
    return {p.slug: p.bundle_path for p in pages}


def _resolve_link(target: str, slug_map: dict[str, str]) -> str | None:
    """wikilink target → 번들경로 (계약 §3).

    ① 정확 slug 매칭 → ② basename fallback("/"+target로 끝나는 유일 slug) → ③ None(깨짐).
    """
    if target in slug_map:
        return slug_map[target]
    matches = [bp for s, bp in slug_map.items() if s.endswith("/" + target)]
    if len(matches) == 1:
        return matches[0]
    return None


def _parse_wikilink_alias(raw: str) -> str | None:
    """wikilink 원문(`[[...]]`)에서 별칭(`|` 뒤)을 추출. 없으면 None.

    import한 WIKILINK_RE는 타깃(group1)만 캡처하고 별칭은 non-capturing이라,
    매칭된 원문을 직접 파싱한다 (export_graph 수정 없이 별칭 변환 지원).
    """
    inner = raw[2:-2]  # [[ ]] 제거
    if "|" not in inner:
        return None
    alias = inner.split("|", 1)[1]
    return alias.strip() or None


def _convert_wikilinks(
    body: str,
    src_rel: str,
    slug_map: dict[str, str],
    excluded_slug_map: dict[str, str],
    stats: ExportStats,
) -> str:
    """본문 wikilink를 OKF 마크다운 링크로 변환 (계약 §5).

    3-way 분류:
    - included 페이지 → [별칭/타깃](/<rel>) 링크.
    - **제외된 페이지를 가리키던 링크** → 별칭(자유 텍스트=누출 위험)을 버리고 slug(공개
      식별자)만 남긴다(redact). excluded_link_refs에 기록. 별칭에 담긴 민감 텍스트가
      public 번들 본문/description으로 새는 것을 차단(B3).
    - 진짜 ghost(어디에도 없음) → 텍스트화 + broken_links 기록.
    """
    def repl(m: re.Match) -> str:
        target = m.group(1).strip()
        alias = _parse_wikilink_alias(m.group(0))
        text = alias if alias else target
        bundle = _resolve_link(target, slug_map)
        if bundle is not None:
            stats.links_converted += 1
            return f"[{text}]({bundle})"
        if _resolve_link(target, excluded_slug_map) is not None:
            stats.excluded_link_refs.append((src_rel, target))
            return target  # 별칭 제거(redact), 페이지 식별자만 남김
        stats.broken_links.append((src_rel, target))
        return text  # 진짜 ghost: 텍스트화

    return WIKILINK_RE.sub(repl, body)


def _sanitize_fm_value(v):
    """frontmatter 값 정규화: '---' 제거 + date/datetime → ISO 문자열.

    date 변환 이유(P2 회귀): PyYAML 전환 후 `updated: 2026-06-08`이 datetime.date
    객체로 파싱돼 번들에 unquoted로 덤프된다. 머신 소비자가 yaml.safe_load 후
    json.dumps 하면 'date is not JSON serializable'로 깨진다. okf.md도 timestamp를
    string으로 가정하므로 ISO 문자열로 직렬화한다.
    """
    if isinstance(v, str):
        return re.sub(r"-{3,}", "—", v)
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()  # date/datetime 모두 처리(datetime이 date의 하위라 순서 무관)
    if isinstance(v, list):
        return [_sanitize_fm_value(x) for x in v]
    if isinstance(v, dict):
        return {k: _sanitize_fm_value(x) for k, x in v.items()}
    return v


def _coerce_source(s):
    """sources 항목을 문자열로 정규화.

    URL에 `: `(콜론+공백)가 있으면 PyYAML이 블록 리스트 항목을 dict로 오파싱한다
    (예: 'youtube.com/@X (Neural Networks: Zero to Hero)' → {'…(Neural Networks':'Zero to Hero)'}).
    dict를 'k: v'로 합쳐 원 URL에 근사 복원한다(P2 R3 minor).
    """
    if isinstance(s, dict):
        return "; ".join(f"{k}: {v}" for k, v in s.items())
    return s


def _filter_internal_sources(v):
    """x-llmbrain-sources 정규화: dict 오파싱 항목 문자열 복원 + 내부 raw/ 경로 제거.

    sources는 외부 URL과 내부 raw/ 파일경로가 섞여 있다. public 번들에 raw/ 경로가
    남으면 내부 디렉토리 구조가 유출되고 외부 독자에겐 무의미한 노이즈(P1·P3). 외부
    URL 등은 보존하고 raw/로 시작하는 항목만 제거한다.
    """
    if isinstance(v, list):
        out = []
        for s in v:
            s = _coerce_source(s)
            if isinstance(s, str) and s.lstrip().startswith("raw/"):
                continue
            out.append(s)
        return out
    v = _coerce_source(v)
    if isinstance(v, str) and v.lstrip().startswith("raw/"):
        return []
    return v


def _render_frontmatter(fm: dict, description: str, strip_internal: bool) -> str:
    """OKF 예약 필드 순서 고정 + x-llmbrain-* 보존 (계약 §4)."""
    out: dict = {}
    out["type"] = fm.get("type", "unknown")
    if "title" in fm:
        out["title"] = fm["title"]
    if description:
        out["description"] = description
    if "resource" in fm:
        out["resource"] = fm["resource"]
    if "tags" in fm and fm["tags"]:
        out["tags"] = fm["tags"]
    timestamp = fm.get("updated") or fm.get("created")
    if timestamp:
        out["timestamp"] = timestamp

    if not strip_internal:
        for k, v in fm.items():
            if k in PRESERVE_SKIP:
                continue
            if k == "sources":
                v = _filter_internal_sources(v)  # raw/ 내부경로 제거(구조 유출 방지)
            out[f"x-llmbrain-{k}"] = v

    # 안전 보장(fail-safe): OKF consumer는 frontmatter를 text.split("---")로 자르므로
    # 어떤 값에도 '---' 부분문자열이 남으면 frontmatter가 중간에 끊긴다. 문자열·문자열
    # 리스트 값의 '---'+ 를 em-dash로 치환해 consumer 호환을 보장한다.
    out = {k: _sanitize_fm_value(v) for k, v in out.items()}

    dumped = yaml.safe_dump(out, sort_keys=False, allow_unicode=True)
    return "---\n" + dumped + "---\n\n"


def export_bundle(
    wiki_dir: Path,
    out_dir: Path,
    *,
    strip_internal: bool = False,
    exclude_paths: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    exclude_slugs: list[str] | None = None,
    sensitive_patterns: list[str] | None = None,
    dry_run: bool = False,
    strict_share: bool = False,
) -> ExportStats:
    """wiki_dir를 OKF 번들로 out_dir에 export. dry_run=True면 파일 0개, ExportStats만.

    sensitive_patterns: included 페이지 본문/description에서 이 패턴(대소문자 무시)을
    스캔해 stats.sensitive_hits에 표면화한다. 페이지 단위 제외는 business *파일*만 막고,
    included 본문 산문의 평문 민감정보(실명·운영수치)는 못 막으므로(P3), 커밋 전 사람이
    검토하도록 dry-run 게이트에 노출하기 위함. 차단이 아니라 표면화(Rule 8 fail-loud).
    """
    wiki_dir = Path(wiki_dir).resolve()
    # GAP-2: symlink 거부는 resolve() **전** 원본 인자로 검사해야 한다. resolve()가
    # symlink를 먼저 해소하면 이후 is_symlink()는 항상 False가 되어 가드가 dead code가
    # 된다(E2E-19). out_dir이 symlink면 rmtree가 링크 대상을 삭제할 위험 → 즉시 거부.
    _out_arg = Path(out_dir)
    if _out_arg.is_symlink():
        raise SystemExit(f"[okf_export] out_dir가 심볼릭 링크라 거부(데이터 손실 방지): {_out_arg}")
    out_dir = _out_arg.resolve()
    # 안전 가드(Y4 회귀 수정): out_dir이 소스(wiki_dir)이거나 그 조상(레포 루트 등)이면
    # 절대 거부. `--out .`·`--out wiki` 오지정으로 rmtree가 소스/레포를 삭제하는 사고 방지.
    if out_dir == wiki_dir or out_dir in wiki_dir.parents:
        raise SystemExit(
            f"[okf_export] out_dir가 wiki_dir이거나 그 조상이라 거부(데이터 손실 방지): {out_dir}"
        )
    # 보안 fail-safe: 빈 리스트([])도 None과 동일하게 기본 제외를 강제한다. `is None`만
    # 보면 exclude_paths=[] 명시 호출이 business 제외를 통째로 우회한다(P3 critical).
    if not exclude_paths:
        exclude_paths = ["business/**", "canvas/**"]
    exclude_domains = exclude_domains or []
    exclude_slugs = exclude_slugs or []
    sensitive_patterns = sensitive_patterns or []

    stats = ExportStats()
    all_pages = _load_pages(wiki_dir, stats, strict_share=strict_share)

    included: list[_Page] = []
    excluded: list[_Page] = []
    for page in all_pages:
        path_excluded = _is_excluded(page, exclude_paths, exclude_domains, exclude_slugs)
        scope_private = _is_scope_private(page)
        if path_excluded or scope_private:
            stats.excluded.append(page.rel)
            excluded.append(page)
            # 경로/도메인/slug로 이미 제외되지 않았는데 scope로만 제외된 페이지 = 필터가
            # 추가로 막은 분량. dry-run/log에서 사람이 별도로 검토할 수 있게 분리 집계한다.
            if scope_private and not path_excluded:
                stats.excluded_private.append(page.rel)
        else:
            included.append(page)

    slug_map = _build_slug_map(included)
    # 제외된 페이지의 slug 맵 — 이걸 가리키던 링크를 redact 분류하기 위함(B3/Y1).
    excluded_slug_map = _build_slug_map(excluded)

    # 페이지별 변환 (본문 + frontmatter). 출력은 included만 대상.
    # 순서 주의: wikilink 변환을 먼저 하고, description은 **변환된 본문**에서 추출한다.
    # raw 본문에서 추출하면 제외 페이지 별칭의 민감 텍스트가 description으로 승격된다(B3).
    rendered: dict[str, tuple] = {}  # rel → (page, fm_block, new_body, description)
    for page in included:
        new_body = _convert_wikilinks(
            page.body, page.rel, slug_map, excluded_slug_map, stats
        )
        description = _extract_description(page.fm, new_body)
        fm_block = _render_frontmatter(page.fm, description, strip_internal)
        rendered[page.rel] = (page, fm_block, new_body, description)
        stats.pages_exported += 1
        stats.by_dir[page.dir] = stats.by_dir.get(page.dir, 0) + 1
        # 실제 게시 바이트(frontmatter + 본문)를 스캔한다. title/tags/resource를 빼면
        # Share-ready preflight가 민감 제목을 놓치므로 rendered frontmatter도 포함한다.
        if sensitive_patterns:
            haystack = (page.rel + "\n" + fm_block + new_body + "\n" + description).lower()
            for pat in sensitive_patterns:
                if pat and pat.lower() in haystack:
                    stats.sensitive_hits.append((page.rel, pat))

    if dry_run:
        return stats

    # ── 파일 작성 (out_dir에만) ──
    # stale 누출 방지 + 데이터 손실 방지(Y4): 우리가 만든 번들은 .okf-bundle 센티넬로
    # 식별한다. index.md/log.md는 llm-brain 어디에나 흔해(레포 루트도 둘 다 보유) 판별
    # 마커로 부적합 → rmtree 사고. 센티넬 있는 디렉토리만 정리, 그 외 비어있지 않은
    # 디렉토리는 덮어쓰지 않고 거부.
    if out_dir.exists() and any(out_dir.iterdir()):
        if (out_dir / ".okf-bundle").exists():
            # symlink 거부는 함수 진입부에서 resolve() 전에 처리(GAP-2). 여기 out_dir은
            # 이미 실경로라 안전.
            shutil.rmtree(out_dir)
        else:
            raise SystemExit(
                f"[okf_export] out_dir가 비어있지 않은데 OKF 번들 마커(.okf-bundle)가 "
                f"없어 덮어쓰기 거부: {out_dir}"
            )
    out_dir.mkdir(parents=True, exist_ok=True)
    # 센티넬: 다음 재export가 이 디렉토리를 안전하게 정리할 수 있게 표식.
    (out_dir / ".okf-bundle").write_text(
        "okf_export.py가 생성한 OKF 번들. 재export 시 통째로 재생성됨.\n", encoding="utf-8"
    )

    for rel, (page, fm_block, new_body, _desc) in rendered.items():
        dest = out_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(fm_block + new_body.lstrip("\n"), encoding="utf-8")

    _write_dir_indexes(out_dir, rendered)
    _write_root_index(out_dir, rendered)
    _write_log(out_dir, stats, strip_internal)

    return stats


def _write_dir_indexes(out_dir: Path, rendered: dict) -> None:
    """디렉토리별 index.md 생성 (계약 §7)."""
    by_dir: dict[str, list] = {}
    for rel, (page, _fm, _body, desc) in rendered.items():
        by_dir.setdefault(page.dir, []).append((page, desc))
    for dir_name, entries in by_dir.items():
        if dir_name == "root":
            continue  # 루트 직속 페이지는 디렉토리 index 없음
        lines = [f"# {dir_name}", ""]
        for page, desc in sorted(entries, key=lambda e: e[0].rel):
            title = page.fm.get("title", page.slug)
            suffix = f" — {desc}" if desc else ""
            lines.append(f"- [{title}]({page.bundle_path}){suffix}")
        (out_dir / dir_name / "index.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )


def _write_root_index(out_dir: Path, rendered: dict) -> None:
    """루트 index.md 생성: type별 섹션 + Directories 섹션 (계약 §7)."""
    by_type: dict[str, list] = {}
    dirs: set[str] = set()
    for rel, (page, _fm, _body, desc) in rendered.items():
        ptype = page.fm.get("type", "unknown")
        by_type.setdefault(ptype, []).append((page, desc))
        if page.dir != "root":
            dirs.add(page.dir)

    lines = ["# OKF Bundle — llm-brain", ""]
    for ptype in sorted(by_type):
        lines.append(f"## {ptype}")
        lines.append("")
        for page, desc in sorted(by_type[ptype], key=lambda e: e[0].rel):
            title = page.fm.get("title", page.slug)
            suffix = f" — {desc}" if desc else ""
            lines.append(f"- [{title}]({page.bundle_path}){suffix}")
        lines.append("")

    lines.append("## Directories")
    lines.append("")
    for dir_name in sorted(dirs):
        lines.append(f"- [{dir_name}](/{dir_name}/index.md)")
    lines.append("")

    (out_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")


def _write_log(out_dir: Path, stats: ExportStats, strip_internal: bool) -> None:
    """log.md 생성: export 이력 + 변환 경고 (계약 §7)."""
    today = datetime.date.today().isoformat()
    lines = [
        f"## {today} export",
        "",
        f"- pages_exported: {stats.pages_exported}",
        f"- links_converted: {stats.links_converted}",
        f"- broken_links (진짜 ghost): {len(stats.broken_links)}",
        f"- excluded_link_refs (제외 페이지 가리킴·redact): {len(stats.excluded_link_refs)}",
        f"- excluded_pages: {len(stats.excluded)}",
        f"- excluded_private (scope:private): {len(stats.excluded_private)}",
        f"- skipped (로드 실패·title 부재): {len(stats.skipped)}",
        f"- sensitive_hits (본문 민감정보 후보): {len(stats.sensitive_hits)}",
        f"- strip_internal: {strip_internal}",
        "",
    ]
    if stats.broken_links:
        lines.append("### 깨진 링크 — 진짜 ghost (wiki 작성 갭)")
        lines.append("")
        for src_rel, target in stats.broken_links:
            lines.append(f"- `{src_rel}` → `[[{target}]]` (대상 없음)")
        lines.append("")
    if stats.excluded_link_refs:
        lines.append("### 제외 페이지를 가리키던 링크 (별칭 redact·의도된 절단)")
        lines.append("")
        for src_rel, target in stats.excluded_link_refs:
            lines.append(f"- `{src_rel}` → `[[{target}]]` (제외됨)")
        lines.append("")
    if stats.excluded_private:
        lines.append("### scope:private 로 제외된 페이지 (team-ready 훅)")
        lines.append("")
        for rel in stats.excluded_private:
            lines.append(f"- `{rel}`")
        lines.append("")
    if stats.excluded:
        lines.append("### 제외된 페이지")
        lines.append("")
        for rel in stats.excluded:
            lines.append(f"- `{rel}`")
        lines.append("")
    if stats.skipped:
        lines.append("### 건너뛴 파일 (로드 실패·title 부재)")
        lines.append("")
        for rel, reason in stats.skipped:
            lines.append(f"- `{rel}` — {reason}")
        lines.append("")
    (out_dir / "log.md").write_text("\n".join(lines), encoding="utf-8")


def _resolve_exclude_paths(config: dict, cli_paths: list[str]) -> list[str]:
    """최종 exclude_paths = (config 또는 기본) + CLI (계약 §2)."""
    base = config.get("exclude_paths")
    if not base:
        base = ["business/**", "canvas/**"]
    return list(base) + list(cli_paths or [])


def _read_required_share_config(path: Path, label: str) -> dict:
    """Load one required share config strictly instead of using legacy defaults."""
    path = Path(path)
    if not path.is_file():
        raise ShareGateError(f"required config is absent ({label})")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ShareGateError(f"required config is invalid ({label})") from exc
    if not isinstance(data, dict):
        raise ShareGateError(f"required config is invalid ({label})")
    return data


def _require_list(config: dict, key: str, label: str) -> list:
    value = config.get(key)
    if not isinstance(value, list):
        raise ShareGateError(f"required config contract is invalid ({label}.{key})")
    return value


def _require_string_list(config: dict, key: str, label: str) -> list[str]:
    value = _require_list(config, key, label)
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ShareGateError(f"required config contract is invalid ({label}.{key})")
    return value


def _load_share_policy(
    config_path: Path,
    local_config_paths: list[Path],
    *,
    extra_exclude_paths: list[str] | None = None,
    extra_exclude_domains: list[str] | None = None,
    extra_exclude_slugs: list[str] | None = None,
) -> dict:
    """Load and validate both committed policy and user-local security layers."""
    canonical_path = REPO_ROOT / "schema" / "okf_export.yaml"
    supplied_path = Path(config_path)
    try:
        is_canonical = (
            not supplied_path.is_symlink()
            and supplied_path.resolve() == canonical_path.resolve()
        )
    except OSError as exc:
        raise ShareGateError("canonical share policy path is invalid") from exc
    if not is_canonical:
        raise ShareGateError("share requires the canonical committed policy")

    base = _read_required_share_config(canonical_path, "policy")
    for key in ("exclude_paths", "exclude_domains", "exclude_slugs", "sensitive_patterns"):
        _require_string_list(base, key, "policy")

    policy = base.get("share_policy")
    if not isinstance(policy, dict):
        raise ShareGateError("required config contract is invalid (share_policy)")
    approval_value = policy.get("approval_value")
    allowed_scopes = policy.get("allowed_scopes")
    allowed_classifications = policy.get("allowed_classifications")
    if not isinstance(approval_value, str) or not approval_value.strip():
        raise ShareGateError("required config contract is invalid (approval)")
    if approval_value != CANONICAL_SHARE_APPROVAL:
        raise ShareGateError("canonical approval contract is invalid")
    if not isinstance(allowed_scopes, list) or {
        str(value).strip().lower() for value in allowed_scopes
    } != KNOWN_SHARE_SCOPES:
        raise ShareGateError("required config contract is invalid (scope policy)")
    if not isinstance(allowed_classifications, list) or {
        str(value).strip().lower() for value in allowed_classifications
    } != KNOWN_SHARE_CLASSIFICATIONS:
        raise ShareGateError("required config contract is invalid (classification policy)")

    if not local_config_paths:
        raise ShareGateError("required config is absent (local security)")
    local_configs: list[dict] = []
    for path in sorted({Path(p) for p in local_config_paths}, key=lambda p: p.as_posix()):
        local = _read_required_share_config(path, "local security")
        unexpected = set(local) - {"exclude_slugs", "sensitive_patterns"}
        if unexpected:
            raise ShareGateError("local security config cannot redefine base policy")
        _require_string_list(local, "exclude_slugs", "local security")
        _require_string_list(local, "sensitive_patterns", "local security")
        local_configs.append(local)

    exclude_paths = list(base["exclude_paths"]) + list(extra_exclude_paths or [])
    # The structural defaults cannot be disabled by a weakened policy file.
    for required in ("business/**", "canvas/**"):
        if required not in exclude_paths:
            raise ShareGateError("required config contract is invalid (structural exclusions)")
    exclude_domains = list(base["exclude_domains"]) + list(extra_exclude_domains or [])
    exclude_slugs = list(base["exclude_slugs"]) + list(extra_exclude_slugs or [])
    sensitive_patterns = list(base["sensitive_patterns"])
    for local in local_configs:
        exclude_slugs.extend(local["exclude_slugs"])
        sensitive_patterns.extend(local["sensitive_patterns"])

    fingerprint_payload = {
        "policy": base,
        "local_security": local_configs,
        "cli_overrides": {
            "exclude_domains": list(extra_exclude_domains or []),
            "exclude_paths": list(extra_exclude_paths or []),
            "exclude_slugs": list(extra_exclude_slugs or []),
        },
    }
    encoded = json.dumps(
        fingerprint_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return {
        "approval_value": CANONICAL_SHARE_APPROVAL,
        "allowed_classifications": KNOWN_SHARE_CLASSIFICATIONS,
        "exclude_paths": exclude_paths,
        "exclude_domains": exclude_domains,
        "exclude_slugs": exclude_slugs,
        "sensitive_patterns": sensitive_patterns,
        "fingerprint": "sha256:" + hashlib.sha256(encoded).hexdigest(),
    }


def _wiki_fingerprint(wiki_dir: Path, *, strict_share: bool = False) -> str:
    """Hash input paths and bytes so a mid-export mutation cannot pass preflight."""
    digest = hashlib.sha256()
    try:
        pages = (
            _validated_share_markdown_paths(wiki_dir)
            if strict_share
            else sorted(Path(wiki_dir).rglob("*.md"))
        )
        for page in pages:
            digest.update(page.relative_to(wiki_dir).as_posix().encode("utf-8"))
            digest.update(b"\0")
            content = (
                _read_safe_share_candidate(wiki_dir, page).encode("utf-8")
                if strict_share
                else page.read_bytes()
            )
            digest.update(content)
            digest.update(b"\0")
    except ShareGateError:
        raise
    except (OSError, ValueError, RecursionError) as exc:
        raise ShareGateError("wiki input could not be validated") from exc
    return digest.hexdigest()


def _normalized_scope(page: _Page) -> str | None:
    value = page.fm.get("scope")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().lower()


def _normalized_classification(page: _Page) -> str | None:
    value = page.fm.get("type")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().lower()


def _increment(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _source_summary(pages: list[_Page]) -> dict[str, int]:
    pages_with_sources = 0
    references = 0
    for page in pages:
        sources = page.fm.get("sources")
        if isinstance(sources, list):
            count = len(sources)
        elif sources in (None, ""):
            count = 0
        else:
            count = 1
        if count:
            pages_with_sources += 1
            references += count
    return {"pages_with_sources": pages_with_sources, "references": references}


def _build_share_manifest(
    pages: list[_Page],
    stats: ExportStats,
    policy: dict,
) -> dict:
    included: list[_Page] = []
    excluded: list[_Page] = []
    scope_counts: dict[str, int] = {}
    included_classes: dict[str, int] = {}
    excluded_classes: dict[str, int] = {}

    for page in pages:
        structurally_excluded = _is_excluded(
            page,
            policy["exclude_paths"],
            policy["exclude_domains"],
            policy["exclude_slugs"],
        )
        scope = _normalized_scope(page)
        classification = _normalized_classification(page)

        if not structurally_excluded:
            if scope not in KNOWN_SHARE_SCOPES:
                raise ShareGateError("candidate scope is absent or unknown")
            if classification not in policy["allowed_classifications"]:
                raise ShareGateError("candidate classification is absent or unknown")

        scope_label = scope if scope in KNOWN_SHARE_SCOPES else (
            "absent" if scope is None else "unknown"
        )
        _increment(scope_counts, scope_label)

        is_excluded = structurally_excluded or scope == "private"
        target = excluded if is_excluded else included
        target.append(page)
        # Never put an arbitrary frontmatter value into the public manifest.
        class_label = (
            classification
            if classification in policy["allowed_classifications"]
            else "unknown"
        )
        _increment(excluded_classes if is_excluded else included_classes, class_label)

    if not included:
        raise ShareGateError("share policy rejected an empty public bundle")
    if len(included) != stats.pages_exported or len(excluded) != len(stats.excluded):
        raise ShareGateError("share policy inventory mismatch")

    return {
        "classification_counts": {
            "excluded": dict(sorted(excluded_classes.items())),
            "included": dict(sorted(included_classes.items())),
        },
        "config_fingerprint": policy["fingerprint"],
        "counts": {"excluded": len(excluded), "included": len(included)},
        "operation": "share-ready",
        "schema_version": "1",
        "scope_counts": dict(sorted(scope_counts.items())),
        "source_counts": {
            "excluded": _source_summary(excluded),
            "included": _source_summary(included),
        },
    }


def _validate_share_target(wiki_dir: Path, out_dir: Path) -> Path:
    """Validate the publication target without mutating it."""
    raw_out = Path(out_dir)
    if raw_out.is_symlink():
        raise ShareGateError("share output target is unsafe")
    resolved_wiki = Path(wiki_dir).resolve()
    repo_root = resolved_wiki.parent
    private_input_roots = (resolved_wiki, (repo_root / "raw").resolve())
    resolved_out = raw_out.resolve()
    if resolved_out == repo_root or any(
        resolved_out.is_relative_to(private_root)
        for private_root in private_input_roots
    ):
        raise ShareGateError("share output target is unsafe")
    if resolved_out.exists():
        if not resolved_out.is_dir():
            raise ShareGateError("share output target is unsafe")
        if any(resolved_out.iterdir()) and not (
            (resolved_out / ".okf-bundle").is_file()
            and (resolved_out / SHARE_SENTINEL).is_file()
        ):
            raise ShareGateError("share output target is not a managed share bundle")
    return resolved_out


def _write_share_log(out_dir: Path, stats: ExportStats) -> None:
    """Replace the legacy path-rich log with share-safe aggregate counts only."""
    lines = [
        "# Share-ready OKF export",
        "",
        f"- included: {stats.pages_exported}",
        f"- excluded: {len(stats.excluded)}",
        f"- links_converted: {stats.links_converted}",
        f"- excluded_link_refs: {len(stats.excluded_link_refs)}",
        "- sensitive_hits: 0",
        "",
    ]
    (out_dir / "log.md").write_text("\n".join(lines), encoding="utf-8")


def _share_publish_receipt(out_dir: Path) -> Path:
    return out_dir.parent / f".{out_dir.name}.publish.json"


def _share_publish_backup(out_dir: Path) -> Path:
    return out_dir.parent / f".{out_dir.name}.backup"


def _is_complete_share_bundle(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / ".okf-bundle").is_file()
        and (path / SHARE_SENTINEL).is_file()
    )


def _fsync_directory(path: Path) -> None:
    """Persist sibling rename/unlink metadata where directory fsync is supported."""
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        # Some filesystems/platforms reject directory fsync. The receipt still
        # provides logical recovery, but power-loss durability is platform-bound.
        pass


def _write_publish_receipt(receipt: Path, stage: Path, backup: Path) -> None:
    payload = {
        "backup": backup.name,
        "stage": stage.name,
        "version": 1,
    }
    temp = receipt.parent / f"{receipt.name}.tmp"
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, receipt)
        _fsync_directory(receipt.parent)
    finally:
        if temp.exists():
            temp.unlink()


def _receipt_member(out_dir: Path, name, expected: str) -> Path:
    if not isinstance(name, str) or name != expected or Path(name).name != name:
        raise ShareGateError("share publication recovery receipt is invalid")
    return out_dir.parent / name


def _recover_share_publish(out_dir: Path) -> None:
    """Recover or finalize an interrupted two-rename share publication."""
    out_dir = Path(out_dir).resolve()
    receipt = _share_publish_receipt(out_dir)
    if not receipt.exists():
        return
    try:
        data = json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShareGateError("share publication recovery receipt is invalid") from exc
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ShareGateError("share publication recovery receipt is invalid")
    backup = _receipt_member(out_dir, data.get("backup"), _share_publish_backup(out_dir).name)
    stage_name = data.get("stage")
    if (
        not isinstance(stage_name, str)
        or Path(stage_name).name != stage_name
        or not stage_name.startswith(f".{out_dir.name}.stage-")
    ):
        raise ShareGateError("share publication recovery receipt is invalid")
    stage = out_dir.parent / stage_name

    if _is_complete_share_bundle(out_dir):
        if backup.exists():
            if not _is_complete_share_bundle(backup):
                raise ShareGateError("share publication recovery backup is invalid")
            shutil.rmtree(backup)
        if stage.exists():
            if not _is_complete_share_bundle(stage):
                raise ShareGateError("share publication recovery stage is invalid")
            shutil.rmtree(stage)
    elif _is_complete_share_bundle(backup):
        if out_dir.exists():
            raise ShareGateError("share publication recovery target is invalid")
        os.replace(backup, out_dir)
        if stage.exists():
            if not _is_complete_share_bundle(stage):
                raise ShareGateError("share publication recovery stage is invalid")
            shutil.rmtree(stage)
    elif _is_complete_share_bundle(stage):
        if out_dir.exists():
            raise ShareGateError("share publication recovery target is invalid")
        os.replace(stage, out_dir)
    else:
        raise ShareGateError("share publication recovery is incomplete")

    receipt.unlink()
    _fsync_directory(out_dir.parent)


def _publish_staged_share(stage: Path, out_dir: Path, *, failure_injector=None) -> None:
    """Publish via a durable receipt plus two recoverable sibling renames.

    A directory replacement is not a single atomic operation on portable POSIX.
    Readers may observe a brief missing destination between the two renames, but
    after the first mutation either a complete bundle or a durable recovery
    receipt always remains.
    """
    stage = Path(stage).resolve()
    out_dir = Path(out_dir).resolve()
    if not _is_complete_share_bundle(stage):
        raise ShareGateError("staged share bundle is incomplete")
    _recover_share_publish(out_dir)
    backup = _share_publish_backup(out_dir)
    receipt = _share_publish_receipt(out_dir)
    if backup.exists() or receipt.exists():
        raise ShareGateError("share publication recovery state is not clean")

    def inject(point: str) -> None:
        if failure_injector is not None:
            failure_injector(point)

    _write_publish_receipt(receipt, stage, backup)
    inject("after_receipt")
    if out_dir.exists():
        os.replace(out_dir, backup)
        _fsync_directory(out_dir.parent)
    inject("after_backup_rename")
    os.replace(stage, out_dir)
    _fsync_directory(out_dir.parent)
    inject("after_publish_rename")
    if backup.exists():
        shutil.rmtree(backup)
        _fsync_directory(out_dir.parent)
    inject("after_backup_cleanup")
    receipt.unlink()
    _fsync_directory(out_dir.parent)


def export_share_bundle(
    wiki_dir: Path,
    out_dir: Path,
    *,
    config_path: Path,
    local_config_paths: list[Path],
    approval: str | None,
    extra_exclude_paths: list[str] | None = None,
    extra_exclude_domains: list[str] | None = None,
    extra_exclude_slugs: list[str] | None = None,
) -> tuple[ExportStats, dict]:
    """Validate, stage, and recoverably publish an explicitly approved share bundle."""
    wiki_arg = Path(wiki_dir)
    if wiki_arg.is_symlink():
        raise ShareGateError("wiki candidate symlink is forbidden")
    wiki_dir = wiki_arg.resolve()
    if not wiki_dir.is_dir():
        raise ShareGateError("wiki input is absent")
    out_dir = _validate_share_target(wiki_dir, out_dir)
    policy = _load_share_policy(
        config_path,
        local_config_paths,
        extra_exclude_paths=extra_exclude_paths,
        extra_exclude_domains=extra_exclude_domains,
        extra_exclude_slugs=extra_exclude_slugs,
    )
    if approval != policy["approval_value"]:
        raise ShareGateError("explicit human approval is required or invalid")

    input_fingerprint = _wiki_fingerprint(wiki_dir, strict_share=True)
    inventory_stats = ExportStats()
    pages = _load_pages(wiki_dir, inventory_stats, strict_share=True)
    stats = export_bundle(
        wiki_dir,
        out_dir,
        strip_internal=True,
        exclude_paths=policy["exclude_paths"],
        exclude_domains=policy["exclude_domains"],
        exclude_slugs=policy["exclude_slugs"],
        sensitive_patterns=policy["sensitive_patterns"],
        dry_run=True,
        strict_share=True,
    )
    if stats.skipped:
        raise ShareGateError("share policy rejected unreadable or incomplete pages")
    if stats.broken_links:
        raise ShareGateError("share policy rejected broken links")
    if stats.sensitive_hits:
        raise ShareGateError(
            f"sensitive content detected ({len(stats.sensitive_hits)} hits); no share output written"
        )
    manifest = _build_share_manifest(pages, stats, policy)

    # No temporary or destination write occurs until every gate above passes.
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    _recover_share_publish(out_dir)
    out_dir = _validate_share_target(wiki_dir, out_dir)
    stage = Path(tempfile.mkdtemp(prefix=f".{out_dir.name}.stage-", dir=out_dir.parent))
    try:
        staged_stats = export_bundle(
            wiki_dir,
            stage,
            strip_internal=True,
            exclude_paths=policy["exclude_paths"],
            exclude_domains=policy["exclude_domains"],
            exclude_slugs=policy["exclude_slugs"],
            sensitive_patterns=policy["sensitive_patterns"],
            strict_share=True,
        )
        if (
            staged_stats.sensitive_hits
            or _wiki_fingerprint(wiki_dir, strict_share=True) != input_fingerprint
        ):
            raise ShareGateError("share inputs changed during staged export")
        refreshed_policy = _load_share_policy(
            config_path,
            local_config_paths,
            extra_exclude_paths=extra_exclude_paths,
            extra_exclude_domains=extra_exclude_domains,
            extra_exclude_slugs=extra_exclude_slugs,
        )
        if refreshed_policy["fingerprint"] != policy["fingerprint"]:
            raise ShareGateError("share policy changed during staged export")
        if (
            staged_stats.pages_exported != stats.pages_exported
            or len(staged_stats.excluded) != len(stats.excluded)
            or staged_stats.broken_links
            or staged_stats.skipped
        ):
            raise ShareGateError("share inventory changed during staged export")

        _write_share_log(stage, staged_stats)
        (stage / SHARE_MANIFEST).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (stage / SHARE_SENTINEL).write_text(
            "Complete Share-ready OKF bundle; replace only through --share.\n",
            encoding="utf-8",
        )
        try:
            _publish_staged_share(stage, out_dir)
        except OSError as exc:
            raise ShareGateError(
                "share publication interrupted; recovery receipt retained"
            ) from exc
    finally:
        # Once a receipt exists, its referenced stage/backup are recovery state
        # and must survive process-level failures until the next valid share run.
        if stage.exists() and not _share_publish_receipt(out_dir).exists():
            shutil.rmtree(stage)

    return stats, manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="wiki/ → OKF v0.1 호환 번들 okf/ export (Phase 1)"
    )
    parser.add_argument(
        "--out",
        default=None,
        help="출력 번들 루트 (기본: private okf/, share okf-share/)",
    )
    parser.add_argument(
        "--strip-internal",
        action="store_true",
        help="OKF 예약 6필드만 남기고 x-llmbrain-* 전부 제거",
    )
    parser.add_argument(
        "--config",
        default="schema/okf_export.yaml",
        help="설정 파일 (있으면 로드, 부재 시 하드코딩 기본값)",
    )
    parser.add_argument(
        "--exclude-path", action="append", default=[], help="추가 제외 경로 글롭 (복수)"
    )
    parser.add_argument(
        "--exclude-domain", action="append", default=[], help="domain 라벨 기준 제외 (복수)"
    )
    parser.add_argument(
        "--exclude-slug", action="append", default=[], help="특정 slug 제외 (복수)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="파일 0개 작성, export 대상·통계만 출력 (보안 게이트용)",
    )
    parser.add_argument(
        "--share",
        action="store_true",
        help="별도 Share-ready 승인·manifest 게이트로 공개 번들 생성",
    )
    parser.add_argument(
        "--approve-share",
        metavar="VALUE",
        help="Share-ready 정책에 정의된 사람 승인 값을 명시",
    )
    args = parser.parse_args(argv)

    if args.approve_share is not None and not args.share:
        parser.error("--approve-share requires --share")
    if args.share and args.dry_run:
        parser.error("--share performs its own preflight and cannot be combined with --dry-run")

    wiki_dir = REPO_ROOT / "wiki"
    out_dir = Path(args.out or ("okf-share/" if args.share else "okf/"))
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = REPO_ROOT / config_path
    # gitignored 로컬 오버라이드(.local.yaml): 실명 등 민감 키워드를 커밋되는 yaml에 넣지
    # 않고 로컬에서만 sensitive_patterns·exclude_slugs를 보강한다(P3 privacy 게이트).
    # GAP-3: config별 `<config>.local.yaml` + 기본 `schema/okf_export.local.yaml`를 모두
    # 병합한다. custom --config만 쓰면 기본 민감설정이 silent 무시되던 우회를 막는다.
    local_paths = {
        config_path.with_suffix(".local.yaml"),
        REPO_ROOT / "schema" / "okf_export.local.yaml",
    }

    if args.share:
        try:
            stats, manifest = export_share_bundle(
                wiki_dir,
                out_dir,
                config_path=config_path,
                local_config_paths=[p for p in local_paths if p.is_file()],
                approval=args.approve_share,
                extra_exclude_paths=args.exclude_path,
                extra_exclude_domains=args.exclude_domain,
                extra_exclude_slugs=args.exclude_slug,
            )
        except ShareGateError as exc:
            print(f"[okf_export] SHARE BLOCKED: {exc}", file=sys.stderr)
            return 1
        print(f"[okf_export] SHARE-READY → {out_dir}")
        print(
            f"included={stats.pages_exported} excluded={len(stats.excluded)} "
            f"manifest={SHARE_MANIFEST} "
            f"config={manifest['config_fingerprint']}"
        )
        return 0

    config = load_config(config_path)
    local_present = any(p.is_file() for p in local_paths)
    local_sensitive: list = []
    local_exclude_slugs: list = []
    for lp in local_paths:
        lc = load_config(lp)
        local_sensitive += list(lc.get("sensitive_patterns", []))
        local_exclude_slugs += list(lc.get("exclude_slugs", []))

    exclude_paths = _resolve_exclude_paths(config, args.exclude_path)
    exclude_domains = list(config.get("exclude_domains", [])) + list(args.exclude_domain)
    exclude_slugs = (
        list(config.get("exclude_slugs", []))
        + local_exclude_slugs
        + list(args.exclude_slug)
    )
    sensitive_patterns = list(config.get("sensitive_patterns", [])) + local_sensitive

    # GAP-1 fail-loud: 로컬 민감설정 부재로 게이트가 침묵 비활성인 상태를 경고한다.
    # fresh clone/CI/협업자 환경엔 gitignored local.yaml이 없어 sensitive_patterns·
    # exclude_slugs가 모두 비고 게이트가 조용히 꺼진다 → 이전에 제외하기로 한 민감
    # 페이지가 다시 included될 수 있다(pages 증가, excluded 목록엔 안 잡힘). 차단 아닌 표면화.
    if not local_present:
        print(
            "🔴 경고: schema/okf_export.local.yaml 부재 — 민감 게이트가 비활성입니다"
            "(sensitive_patterns 본문 스캐너 + exclude_slugs 민감 페이지 제외 모두 꺼짐). "
            "fresh clone/CI에서는 이전에 제외한 민감 페이지가 다시 included될 수 있습니다. "
            "public 커밋 전 로컬 설정을 두고 --dry-run의 excluded 카운트를 직접 검토하세요.",
            file=sys.stderr,
        )

    if not wiki_dir.is_dir():
        print(f"[okf_export] ERROR: wiki dir not found: {wiki_dir}", file=sys.stderr)
        return 1

    stats = export_bundle(
        wiki_dir,
        out_dir,
        strip_internal=args.strip_internal,
        exclude_paths=exclude_paths,
        exclude_domains=exclude_domains,
        exclude_slugs=exclude_slugs,
        sensitive_patterns=sensitive_patterns,
        dry_run=args.dry_run,
    )

    mode = "DRY-RUN (파일 미작성)" if args.dry_run else f"→ {out_dir}"
    print(f"[okf_export] {mode}")
    print(
        f"pages={stats.pages_exported} links={stats.links_converted} "
        f"ghost={len(stats.broken_links)} excl_refs={len(stats.excluded_link_refs)} "
        f"excluded={len(stats.excluded)} private={len(stats.excluded_private)} "
        f"skipped={len(stats.skipped)}"
    )
    if stats.by_dir:
        by_dir_str = ", ".join(f"{d}={n}" for d, n in sorted(stats.by_dir.items()))
        print(f"  by_dir: {by_dir_str}")
    if stats.excluded:
        print(f"  excluded pages: {', '.join(stats.excluded)}")
    if stats.excluded_private:
        print(
            f"  🔒 scope:private 제외 ({len(stats.excluded_private)}건): "
            f"{', '.join(stats.excluded_private)}"
        )
    if stats.skipped:
        print(f"  skipped ({len(stats.skipped)}):")
        for rel, reason in stats.skipped[:20]:
            print(f"    {rel} — {reason}")
    if stats.excluded_link_refs:
        print(f"  제외 페이지 가리킨 링크 ({len(stats.excluded_link_refs)}, 별칭 redact됨):")
        for src_rel, target in stats.excluded_link_refs[:20]:
            print(f"    {src_rel} → [[{target}]]")
        if len(stats.excluded_link_refs) > 20:
            print(f"    ... ({len(stats.excluded_link_refs) - 20} more)")
    if stats.broken_links:
        print(f"  진짜 ghost 링크 ({len(stats.broken_links)}, wiki 작성 갭):")
        for src_rel, target in stats.broken_links[:20]:
            print(f"    {src_rel} → [[{target}]]")
        if len(stats.broken_links) > 20:
            print(f"    ... ({len(stats.broken_links) - 20} more)")
    if stats.sensitive_hits:
        print(f"  🔴 본문 민감정보 후보 ({len(stats.sensitive_hits)}건, 커밋 전 검토 필요):")
        for rel, pat in stats.sensitive_hits[:20]:
            print(f"    {rel} ← '{pat}'")
        if len(stats.sensitive_hits) > 20:
            print(f"    ... ({len(stats.sensitive_hits) - 20} more)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
