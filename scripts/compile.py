#!/usr/bin/env python3
"""compile.py — raw/ 메모를 wiki/ 페이지로 컴파일한다 (llm-brain-edu).

상류 llm-brain 은 이 단계를 Claude Code 슬래시 커맨드(`commands/ingest.md` Step 2)가
수행한다. 수업용 배포판의 학생은 Claude Code 가 없으므로, 같은 일을 스크립트로 한다.
규칙은 새로 만들지 않고 `schema/ingest.md`(컴파일 규칙 정본)를 그대로 프롬프트로 쓴다.

경로는 둘이고, 어느 쪽으로 돌았는지 항상 화면에 찍는다:

  LIVE — OPENAI_API_KEY 가 있고 호출에 성공. LLM 이 요약·분류·연결까지 한다.
  RULE — 키가 없거나 호출이 실패. 원문을 그대로 옮긴 페이지를 만든다.
         위키는 생기고 화면에도 뜬다. 정리만 안 될 뿐이다.

즉 **키가 없어도 끝까지 완주한다.** 키는 "정리해 주는 사람"을 부르는 것이지,
브레인이 도는 조건이 아니다.

사용:
    python scripts/compile.py              # raw 미처리분을 컴파일
    python scripts/compile.py --dry-run    # 무엇을 할지만 보여준다
    python scripts/compile.py --recompile  # 처리 완료 자료도 다시 정리(키가 있으면 API 호출)
    python scripts/compile.py --seed       # 리커버리: 예제 위키를 넣어 화면을 먼저 본다
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import shutil
import sys

import yaml
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ingest  # noqa: E402  (미처리 목록·완료 표시를 재사용 — 같은 규칙을 두 번 쓰지 않는다)
from lib import llm_client, pii  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WIKI_DIR = ROOT / "wiki"
SCHEMA_DIR = ROOT / "schema"
SEED_DIR = ROOT / "examples" / "course-seed-wiki"
INDEX_FILE = ROOT / "index.md"

# index.md 가 쓰는 카테고리. RULE 경로는 판단하지 않으므로 concepts 로 모은다.
CATEGORIES = ["concepts", "tools", "people", "projects", "business"]
DEFAULT_CATEGORY = "concepts"


# ---------------------------------------------------------------------------
# 공통
# ---------------------------------------------------------------------------


def _title_of(text: str, fallback: str) -> str:
    """제목을 정한다: 마크다운 헤딩 → 본문 첫 줄 → 파일명.

    `ingest.py --note` 로 넣은 메모에는 헤딩이 없다. 그때 파일명(2026-09-07-1351-note)을
    제목으로 쓰면 학생이 위키를 열었을 때 무슨 내용인지 알 수 없다.
    """
    lines = [ln.strip() for ln in text.splitlines()]
    for line in lines:
        m = re.match(r"^#\s+(.+)$", line)
        if m:
            return m.group(1).strip()
    for line in lines:
        if line and not line.startswith(("---", ">", "|", "#")):
            return line[:40].rstrip()
    return fallback


def _yaml_str(s: str) -> str:
    """YAML 스칼라로 안전하게 감싼다.

    제목에 콜론이 들어오면("오늘 배운 것: 파이썬") frontmatter 가 통째로 깨지고,
    export_graph 가 그 페이지를 못 읽는다. 조용히 사라지는 대신 항상 인용한다.
    """
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _slugify(title: str) -> str:
    """제목을 파일명으로. 한글은 그대로 두고 공백·기호만 정리한다."""
    # 점도 바꾼다. claim ID(claim:{slug}-N)는 점을 허용하지 않아, 점이 남으면
    # claims.py build 가 그 페이지에서 멈추고 AI 답변을 쓸 수 없다.
    s = re.sub(r"[\s/\\:*?\"<>|.]+", "-", title.strip())
    s = re.sub(r"-{2,}", "-", s).strip("-").lower()
    return s[:60] or "untitled"


# ingest.py --file 은 PDF·DOCX·PPTX 원본 옆에 텍스트를 뽑은 `<원본 이름>.extracted.md`
# 사이드카를 함께 저장한다(상류에서는 Claude 가 이 사이드카를 읽는다). compile 은 둘을
# 각각 페이지로 만들면 안 된다 — 같은 내용이 두 번 검색되고, 추출본 쪽 slug 의 점 때문에
# claims.py build 가 실패한다. 사이드카가 있는 원본은 건너뛰고 사이드카로 한 페이지만 만든다.
SIDECAR_SUFFIX = ".extracted.md"


def _sidecar_of(raw_file: Path) -> Path:
    return raw_file.with_name(raw_file.stem + SIDECAR_SUFFIX)


def _has_sidecar(raw_file: Path) -> bool:
    """텍스트가 아닌 원본이고, 그 사이드카가 실제로 있으면 True."""
    return raw_file.suffix.lower() not in (".md", ".txt") and _sidecar_of(raw_file).is_file()


def _slug_stem(raw_file: Path) -> str:
    """페이지 이름의 바탕. 사이드카는 `.extracted` 를 떼어 원본 이름을 쓴다."""
    if raw_file.name.endswith(SIDECAR_SUFFIX):
        return raw_file.name[: -len(SIDECAR_SUFFIX)]
    return raw_file.stem


def _live_check(cfg: dict) -> tuple[bool, str]:
    """LIVE 로 돌 수 있는지와 화면에 찍을 이유를 돌려준다.

    cli 엔진은 `claude -p` 를 부르므로 키 환경변수가 필요 없다. 키만 보면 Claude 구독
    사용자는 engine 을 cli 로 바꿔도 영영 RULE 에 머물고, 가짜 키를 넣어야 LIVE 가 된다.
    """
    if cfg.get("engine") == "cli":
        if shutil.which("claude"):
            return True, "engine cli — claude CLI 감지됨"
        return False, "engine cli — claude CLI 없음, 원문을 그대로 옮깁니다"
    key_env = cfg.get("api_key_env", "OPENAI_API_KEY")
    if os.environ.get(key_env):
        return True, f"{key_env} 감지됨"
    return False, f"{key_env} 없음 — 원문을 그대로 옮깁니다"


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:].lstrip("\n")
    return text


# ---------------------------------------------------------------------------
# RULE 경로 — 키 없이도 페이지가 생긴다
# ---------------------------------------------------------------------------


def _raw_tags(text: str) -> list[str]:
    """원문 frontmatter 의 tags 를 살린다.

    RULE 경로는 LLM 이 없어 분류를 못 한다. 그래서 학생이 직접 적어 둔 태그가
    유일한 분류 신호다. 이걸 버리면 위키가 태그도 링크도 없는 평면 더미가 된다.
    """
    head = text.lstrip("\ufeff").lstrip()
    m = re.match(r"^---\s*\n(.*?)\n---", head, flags=re.S)
    if not m:
        return []
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return []
    raw = meta.get("tags") if isinstance(meta, dict) else None
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for x in raw:
        if isinstance(x, (str, int, float)):
            t = str(x).strip()
            if t and t not in out:
                out.append(t)
    return out


def _raw_scope(text: str) -> str | None:
    """원문 frontmatter 의 scope(private|shared)를 읽는다.

    okf export 는 wiki 페이지의 scope 만 본다. raw 에 `scope: private` 를 적어도
    compile 이 옮기지 않으면 그 메모가 공개 번들에 그대로 실린다.
    """
    head = text.lstrip("﻿").lstrip()
    m = re.match(r"^---\s*\n(.*?)\n---", head, flags=re.S)
    if not m:
        return None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    scope = meta.get("scope") if isinstance(meta, dict) else None
    if isinstance(scope, str) and scope.strip().lower() in ("private", "shared"):
        return scope.strip().lower()
    return None


def _with_scope(page: str, scope: str | None) -> str:
    """페이지 frontmatter 의 scope 를 raw 값으로 맞춘다(LIVE 모델이 빠뜨려도 지킨다)."""
    if not scope or not page.startswith("---"):
        return page
    end = page.find("\n---", 3)
    if end == -1:
        return page
    head = re.sub(r"(?m)^scope:.*\n?", "", page[:end + 1])
    return head + f"scope: {scope}\n" + page[end + 1:]


def _page_by_rule(raw_file: Path, text: str) -> tuple[Path, str]:
    """원문을 그대로 옮긴 위키 페이지를 만든다(요약·분류 없음)."""
    body = _strip_frontmatter(text).strip()
    title = _title_of(body, raw_file.stem)
    # slug 는 제목이 아니라 raw 파일명에서 만든다. CLAUDE.md 규약이 "한국어 개념도 영문
    # slug" 이고, 한글 파일명은 macOS 에서 NFD 로 저장돼 도구마다 다르게 보인다.
    # 화면에 뜨는 건 frontmatter 의 title 이므로 학생에게는 한국어 제목이 보인다.
    slug = _slugify(_slug_stem(raw_file))
    today = date.today().isoformat()
    rel_raw = raw_file.relative_to(ROOT).as_posix()
    tags = _raw_tags(text)
    tags_line = "tags: [" + ", ".join(_yaml_str(t) for t in tags) + "]\n"

    # 본문이 이미 같은 제목으로 시작하면 한 번만 남긴다(제목이 두 번 찍히는 걸 막는다).
    if body.startswith("# "):
        first, _, rest = body.partition("\n")
        if first[2:].strip() == title:
            body = rest.lstrip("\n")

    page = (
        "---\n"
        f"title: {_yaml_str(title)}\n"
        "type: note\n"
        f"{tags_line}"
        f"created: {today}\n"
        f"updated: {today}\n"
        "sources:\n"
        f"  - {rel_raw}\n"
        "distill_level: 0\n"
        "access_count: 0\n"
        "---\n\n"
        f"# {title}\n\n"
        "> 이 페이지는 **RULE 경로**로 만들어졌습니다. 원문을 그대로 옮겼고 요약·분류·\n"
        "> 연결은 하지 않았습니다. `OPENAI_API_KEY` 를 설정하거나(Claude Code 사용자는 `schema/config.yaml` 의\n"
        "> engine 을 `cli` 로) `compile.py --recompile`을 실행하면\n"
        "> 같은 메모가 어떻게 정리되는지 비교해 볼 수 있습니다.\n\n"
        f"{body}\n"
    )
    return WIKI_DIR / DEFAULT_CATEGORY / f"{slug}.md", page


# ---------------------------------------------------------------------------
# LIVE 경로 — schema/ingest.md 를 그대로 프롬프트로 쓴다
# ---------------------------------------------------------------------------


def _build_prompt(raw_file: Path, text: str) -> str:
    rules = (SCHEMA_DIR / "ingest.md").read_text(encoding="utf-8")
    domains = (SCHEMA_DIR / "domains.yaml").read_text(encoding="utf-8")
    index = INDEX_FILE.read_text(encoding="utf-8") if INDEX_FILE.exists() else "(아직 비어 있음)"
    rel_raw = raw_file.relative_to(ROOT).as_posix()
    cats = " | ".join(CATEGORIES)

    return f"""아래 규칙에 따라 raw 파일 하나를 위키 페이지 하나로 정리해라.

# 컴파일 규칙
{rules}

# 도메인 분류 기준
{domains}

# 현재 위키 목차
{index}

# 정리할 raw 파일: {rel_raw}
{text}

# 출력 형식 (이 형식만 출력하고 다른 말은 쓰지 마라)
첫 줄에 파일 경로를 쓰고, 그다음 줄부터 페이지 전문을 쓴다.

PATH: wiki/<카테고리>/<slug>.md
---
title: "<한국어 제목 — 콜론이 들어가도 되도록 반드시 큰따옴표로 감쌀 것>"
type: <concept|tool|note|meeting>
tags: [<태그들>]
created: {date.today().isoformat()}
updated: {date.today().isoformat()}
sources:
  - {rel_raw}
distill_level: 0
access_count: 0
---

# <제목>

## 개요
<2~4문장 요약>

## 내용
<핵심을 정리. 원문에 없는 사실을 지어내지 마라.>

카테고리는 {cats} 중 하나다. slug 는 **영문 소문자와 하이픈만** 쓴다(한글 금지, 30자 이내).
기존 위키에 관련 페이지가 있으면 본문에서 [[슬러그]] 로 연결해라.
"""


def _parse_live_output(out: str) -> tuple[Path, str] | None:
    """모델 출력에서 (경로, 본문)을 뽑는다. 형식이 어긋나면 None(→ RULE 폴백)."""
    m = re.search(r"^PATH:\s*(\S+\.md)\s*$", out, flags=re.MULTILINE)
    if not m:
        return None
    rel = m.group(1).lstrip("/").replace("\\", "/")
    # wiki/<허용 카테고리>/<파일>.md 정확히 세 조각만 받는다.
    # 접두사만 보면 wiki/concepts/sub/a.md 가 저장되는데, rebuild_index 는 카테고리
    # 최상위만 훑으므로 그 페이지는 목차에도 화면에도 나타나지 않는다(조용한 유실).
    parts = rel.split("/")
    if len(parts) != 3 or parts[0] != "wiki" or parts[1] not in CATEGORIES:
        return None
    if ".." in parts or not parts[2].endswith(".md") or parts[2].startswith("."):
        return None
    body = out[m.end():].lstrip("\n")
    if not body.startswith("---"):
        return None
    return ROOT / rel, body.rstrip() + "\n"


async def _page_by_llm(raw_file: Path, text: str) -> tuple[Path, str] | None:
    # 본문이 그대로 외부 AI 서비스로 나간다. 나가기 전에 한 번 알린다.
    pii.warn_if_pii(text, raw_file.name)
    out = await llm_client.call_llm(_build_prompt(raw_file, text))
    return _parse_live_output(out)


# ---------------------------------------------------------------------------
# index.md 재생성
# ---------------------------------------------------------------------------


def _first_summary(page_text: str) -> str:
    """개요 첫 문장을 목차 설명으로 쓴다."""
    body = _strip_frontmatter(page_text)
    for line in body.splitlines():
        s = line.strip()
        if s and not s.startswith(("#", ">", "-", "|")):
            return s[:80]
    return ""


def rebuild_index() -> int:
    """wiki/ 를 스캔해 index.md 를 다시 쓴다. 총 페이지 수를 돌려준다."""
    sections, total = [], 0
    for cat in CATEGORIES:
        pages = sorted((WIKI_DIR / cat).glob("*.md")) if (WIKI_DIR / cat).is_dir() else []
        total += len(pages)
        lines = [f"## {cat}/ ({len(pages)}개)"]
        for p in pages:
            lines.append(f"- [[{p.stem}]] — {_first_summary(p.read_text(encoding='utf-8'))}")
        sections.append("\n".join(lines))

    INDEX_FILE.write_text(
        "\n# LLM Wiki — Index\n\n"
        "> 이 파일은 compile 시 자동 갱신된다. 직접 편집하지 않는다.\n\n"
        f"**마지막 갱신**: {date.today().isoformat()}\n"
        f"**총 페이지**: {total}개\n\n---\n\n" + "\n\n".join(sections) + "\n",
        encoding="utf-8",
    )
    return total


# ---------------------------------------------------------------------------
# --seed 리커버리
# ---------------------------------------------------------------------------


def do_seed(force: bool) -> int:
    """예제 위키를 넣어 화면부터 본다. 학생 페이지는 절대 덮어쓰지 않는다."""
    existing = [p for p in WIKI_DIR.rglob("*.md")] if WIKI_DIR.is_dir() else []
    if existing and not force:
        print(f"  위키에 이미 {len(existing)}개 페이지가 있어 덮어쓰지 않았습니다.")
        print("  정말 예제로 되돌리려면: python scripts/compile.py --seed --force")
        return 1
    if not (SEED_DIR / "index.md").is_file() or not (SEED_DIR / "wiki").is_dir():
        print(f"  예제 위키가 없습니다: {SEED_DIR.relative_to(ROOT)}")
        print("  저장소를 다시 내려받거나(git pull), 이 화면을 복사해 질문 채널에 올려 주세요.")
        return 1
    # 수업 seed는 공개 원문도 함께 제공합니다. claims.py가 실제 raw 출처를
    # 확인할 수 있게 설치하되, 같은 이름의 사용자 원문은 절대 덮어쓰지 않습니다.
    inputs = []
    for seed_page in (SEED_DIR / 'wiki').rglob('*.md'):
        for source in _page_sources(seed_page):
            relative = Path(source)
            if relative.is_absolute() or '..' in relative.parts or not source.startswith('raw/'):
                continue
            template, target = SEED_DIR / relative, ROOT / relative
            if not template.is_file() or (target.exists() and target.read_bytes() != template.read_bytes()):
                print('  예제 원문이 없거나 같은 이름의 다른 사용자 원문이 있어 변경하지 않았습니다.')
                return 1
            inputs.append((template, target))
    for template, target in inputs:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy(template, target)
    shutil.copy(SEED_DIR / "index.md", INDEX_FILE)
    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SEED_DIR / "wiki", WIKI_DIR, dirs_exist_ok=True)
    if inputs:
        state = ingest.load_state()
        previous = state.get('processed', [])
        done = {p for p in previous if isinstance(p, str)} if isinstance(previous, list) else set()
        previous_records = state.get('compiled', {})
        records = previous_records if isinstance(previous_records, dict) else {}
        for _, target in inputs:
            relative = target.relative_to(ROOT).as_posix()
            done.add(relative)
            records[relative] = {'sha256': ingest.file_digest(target)}
        state.update(processed=sorted(done), compiled=records)
        ingest.save_state(state)
    n = len(list(WIKI_DIR.rglob("*.md")))
    print(f"  예제 위키 {n}개 페이지를 넣었습니다.")
    print("  이제 `uv run python -m wiki_app` 을 실행하고 터미널에 찍힌 주소(보통 http://localhost:8000)를 여세요.")
    print("  (내 메모로 만든 위키를 보려면 나중에 --seed 없이 다시 실행하세요.)")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def dt_stamp() -> str:
    from datetime import datetime
    return datetime.now().strftime("%H%M%S%f")[:10]


def _page_sources(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    # 본문 전체를 부분문자열로 뒤지면 인용문에 속고, 줄 단위 정규식으로 읽으면
    # tags 의 블록 목록까지 sources 로 주워 담는다. frontmatter 를 YAML 로 파싱해
    # **sources 필드만** 본다. 인라인(`sources: [a, b]`)도 블록도 같이 처리된다.
    # BOM(윈도우 메모장)·앞 공백도 걷어낸다 — 안 그러면 학생이 페이지를 한 번 열어
    # 저장한 뒤부터 재컴파일마다 rag-2, rag-3 이 쌓인다.
    head = text.lstrip("\ufeff").lstrip()
    fm = re.match(r"^---\s*\n(.*?)\n---", head, flags=re.S)
    sources = []
    if fm:
        try:
            meta = yaml.safe_load(fm.group(1)) or {}
            raw_src = meta.get("sources") if isinstance(meta, dict) else None
            if isinstance(raw_src, str):
                sources = [raw_src]
            elif isinstance(raw_src, list):
                sources = [str(x) for x in raw_src if isinstance(x, (str, int, float))]
        except yaml.YAMLError:
            sources = []                        # 깨진 frontmatter → 덮지 않는 쪽으로
    return [x.strip() for x in sources]


def _previous_target(raw_file: Path) -> Path | None:
    """RULE→LIVE 전환 때도 같은 출처의 단일 페이지를 갱신해 이전 본문을 남기지 않는다."""
    rel = raw_file.relative_to(ROOT).as_posix()
    for category in CATEGORIES:
        for page in sorted((WIKI_DIR / category).glob("*.md")):
            if _page_sources(page) == [rel]:
                return page
    return None


def _safe_target(out_path: Path, raw_file: Path) -> Path:
    """기존 페이지를 덮어쓰지 않는다.

    같은 raw 에서 나온 페이지면 갱신이 맞지만(재컴파일), 다른 출처면 학생이 몇 주간
    쌓아 온 것이다. LIVE 는 모델이 경로를 정하므로 우연히 남의 페이지를 가리킬 수 있다.
    출처가 다르면 빈 번호를 찾아 새 파일로 만든다 — 사라지는 것보다 두 개가 낫다.
    """
    if not out_path.exists():
        return out_path
    rel_raw = raw_file.relative_to(ROOT).as_posix()
    sources = _page_sources(out_path)
    if rel_raw in [x.strip() for x in sources]:
        return out_path                         # 같은 출처 → 갱신
    stem, n = out_path.stem[:80], 2      # 이름 폭주와 ENAMETOOLONG 방지
    while out_path.exists() and n < 100:
        out_path = out_path.with_name(f"{stem}-{n}.md")
        n += 1
    if out_path.exists():                # 100개까지 찼으면 시각으로 유일성 확보
        out_path = out_path.with_name(f"{stem}-{dt_stamp()}.md")
    print(f"     같은 이름의 페이지가 이미 있어 {out_path.name} 로 저장합니다")
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description="raw/ 메모를 wiki/ 페이지로 컴파일한다")
    ap.add_argument("--dry-run", action="store_true", help="무엇을 할지만 보여준다")
    ap.add_argument("--seed", action="store_true", help="예제 위키를 넣는다(리커버리)")
    ap.add_argument("--recompile", action="store_true", help="처리 완료된 raw도 다시 컴파일한다(키가 있으면 API 호출)")
    ap.add_argument("--force", action="store_true", help="--seed 시 기존 위키를 덮어쓴다")
    ap.add_argument("--rule", action="store_true", help="키가 있어도 무료 RULE만 사용한다(모델 호출 없음)")
    args = ap.parse_args()

    if args.seed:
        return do_seed(args.force)

    files = (sorted(f for f in ingest.RAW_DIR.rglob("*")
                    if f.is_file() and f.suffix.lower() in ingest.SUPPORTED_EXTENSIONS)
             if args.recompile else ingest.find_unprocessed())
    twins = [f for f in files if _has_sidecar(f)]      # 사이드카로 정리되는 원본
    files = [f for f in files if not _has_sidecar(f)]
    if not files and not twins:
        print("[compile] 새로 정리할 메모가 없습니다.")
        print("  메모를 먼저 넣어 보세요: uv run python scripts/ingest.py --note \"오늘 배운 것\"")
        return 0

    can_live, why = _live_check(llm_client.load_llm_config())
    live = can_live and not args.rule
    print(f"[compile] 메모 {len(files)}건 → 위키 컴파일")
    print(f"  경로: {'LIVE' if live else 'RULE'} "
          f"({'--rule 지정 — 모델 호출 없음' if args.rule else why})")

    if args.dry_run:
        for f in files:
            print(f"   · {f.relative_to(ROOT)}")
        return 0

    written = 0
    live_failed = 0              # 키가 있는데 LIVE 가 안 된 건수(요약 줄에서 숨기지 않는다)
    compiled_records: dict = {}
    ok_files: list = []          # 실제로 페이지가 만들어진 raw 만 완료 처리한다
    for orig in twins:
        # 사이드카로 정리했으므로 원본은 페이지를 만들지 않고 완료로만 기록한다.
        # 예전 판에서 원본으로 따로 만든 중복 페이지가 있으면 함께 정리한다.
        dup = _previous_target(orig)
        if dup is not None:
            dup.unlink()
            print(f"   - {dup.relative_to(ROOT)}: 추출본 페이지와 중복이라 지웠습니다")
        compiled_records[orig.relative_to(ROOT).as_posix()] = {"sha256": ingest.file_digest(orig)}
    for f in files:
        digest = ingest.file_digest(f)
        try:
            text = ingest.extract_text(f)
        except Exception as exc:
            print(f"   ✗ {f.name}: 읽기 실패({type(exc).__name__}). 원본을 확인한 뒤 다시 실행하세요.")
            continue
        if not text:
            print(f"   ✗ {f.name}: 내용을 읽지 못해 건너뜁니다")
            continue

        result, how = None, "RULE"
        if live:
            try:
                result = asyncio.run(_page_by_llm(f, text))
                how = "LIVE" if result else "RULE"
                if result is None:
                    live_failed += 1
                    print(f"   ! {f.name}: 응답 형식이 어긋나 RULE 로 넘어갑니다")
            except Exception as exc:  # 한도 초과·네트워크 등 — 삼키지 않고 이유를 보여준다
                live_failed += 1
                print(f"   ! {f.name}: 호출 실패({type(exc).__name__}) — RULE 로 넘어갑니다")
                print(f"     {exc}")
        if result is None:
            result = _page_by_rule(f, text)

        out_path, page = result
        page = _with_scope(page, _raw_scope(text))
        prev, stale = _previous_target(f), None
        if prev is not None and "." in prev.stem:
            # 점이 든 옛 이름(예: …paper.extracted)은 claims 가 읽지 못한다. 새 이름으로 옮긴다.
            prev, stale = None, prev
        out_path = prev or _safe_target(out_path, f)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(page, encoding="utf-8")
        if stale is not None and stale != out_path:
            stale.unlink()
            print(f"     옛 이름 {stale.relative_to(ROOT)} 는 지웠습니다(같은 출처, 새 이름으로 옮김)")
        written += 1
        ok_files.append(f)
        compiled_records[f.relative_to(ROOT).as_posix()] = {"sha256": digest}
        print(f"   ✓ {out_path.relative_to(ROOT)}  [{how}]")

    total = rebuild_index()
    print(f"  index.md 갱신 · 총 {total}개 페이지")

    import export_graph  # noqa: PLC0415 (그래프 생성은 페이지가 다 써진 뒤에만 의미가 있다)
    export_graph.main()

    # ingest.mark_done() 은 raw/ **전체**를 완료로 기록한다. 추출에 실패해 페이지가
    # 안 생긴 파일까지 완료가 되면 다시 시도할 방법이 없어진다(약속: 메모 3건 → 페이지 3건).
    # 그래서 성공한 것만 상태에 더한다.
    state = ingest.load_state()
    prev = state.get("processed")
    # 손상되거나 손으로 고친 상태 파일에는 문자열·dict·None 이 섞여 들어온다.
    # 문자열이면 set() 이 문자 집합이 되고, dict 면 unhashable 로 컴파일이 죽는다.
    # 그리고 Windows 에서 저장된 `raw\notes\a.md` 는 같은 파일인데 다른 문자열이다.
    done = set()
    if isinstance(prev, list):
        done = {p.replace("\\", "/") for p in prev if isinstance(p, str)}
    done.update(f.relative_to(ROOT).as_posix() for f in ok_files + twins)
    state["processed"] = sorted(done)
    previous_records = state.get("compiled")
    state["compiled"] = {**(previous_records if isinstance(previous_records, dict) else {}), **compiled_records}
    ingest.save_state(state)

    failed = len(files) - len(ok_files)
    print(f"[compile] 완료 — {written}개 페이지를 만들었습니다.")
    if failed:
        print(f"  {failed}건은 내용을 읽지 못해 넘겼습니다. 고친 뒤 다시 실행하면 그때 처리됩니다.")
    if live_failed:
        print(f"  ⚠️ LIVE 실패 {live_failed}건, RULE로 대체했습니다(AI 정리 없이 원문을 옮김).")
        print("     키·잔액·네트워크를 확인한 뒤 `uv run python scripts/compile.py --recompile` 로 다시 정리하세요.")
    print("  화면으로 보기: uv run python -m wiki_app  →  터미널에 찍힌 주소(보통 http://localhost:8000)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
