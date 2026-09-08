"""test_okf_frontmatter_safety.py — 회귀: 실제 wiki 본문(표·수평선)이 OKF consumer를 깨뜨리지 않는지.

발견 경위: 픽스처 28개는 green이었으나 실 92페이지로 round-trip 시 OKF minimal
consumer(text.split("---")+yaml.safe_load)가 크래시. 원인: description 자동추출이
마크다운 표(`| --- | --- |`)를 집어 frontmatter 값에 '---'가 남았고, consumer의
부분문자열 split이 frontmatter를 중간에 끊음. 이 테스트가 그 경로를 고정한다.
"""
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import okf_export  # noqa: E402


# OKF minimal consumer (design.md 부록 그대로 — 호환성의 단일 진실)
def _load_bundle(root: Path):
    concepts, links = {}, []
    for path in root.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        meta = {}
        if text.startswith("---"):
            _, fm, body = text.split("---", 2)
            meta = yaml.safe_load(fm) or {}  # ← 버그 시 여기서 ScannerError
        else:
            body = text
        concepts[str(path)] = meta
        for target in set(re.findall(r"\]\((/[^)]+\.md)\)", body)):
            links.append((str(path), target))
    return concepts, links


# 표가 본문 맨 앞(프로즈 문단 없음) + `---` 수평선까지 포함한 악성 페이지
_TABLE_FIRST_PAGE = """---
title: Tools Comparison
type: concept
updated: 2026-06-01
---

# Tools Comparison

| 단계 | 대표 도구 | 본 wiki 페이지 |
| --- | --- | --- |
| Stage 1 | Evernote | [[evernote]] |
| Stage 2 | Notion | [[notion]] |

---

## 상세

본문 단락이다.
"""

# `## 핵심` 섹션이 표로 시작하는 페이지
_CORE_TABLE_PAGE = """---
title: Core Table
type: concept
updated: 2026-06-01
---

# Core Table

## 핵심

| a | b |
| --- | --- |
| 1 | 2 |

진짜 요약 문장이다.
"""


def _build_wiki(tmp_path: Path) -> Path:
    wiki = tmp_path / "wiki"
    (wiki / "concepts").mkdir(parents=True)
    (wiki / "concepts" / "tools-comparison.md").write_text(_TABLE_FIRST_PAGE, encoding="utf-8")
    (wiki / "concepts" / "core-table.md").write_text(_CORE_TABLE_PAGE, encoding="utf-8")
    return wiki


def test_table_body_produces_parseable_bundle(tmp_path):
    """표·수평선이 있는 페이지를 export해도 OKF consumer가 파싱에 성공해야 한다."""
    wiki = _build_wiki(tmp_path)
    out = tmp_path / "okf"
    okf_export.export_bundle(wiki, out)

    # 버그가 있으면 _load_bundle 안 yaml.safe_load가 ScannerError로 터진다.
    concepts, _links = _load_bundle(out)
    assert concepts, "번들이 비어선 안 됨"

    # 모든 페이지 파일에 '---'를 품은 frontmatter 값이 없어야 한다.
    for path, meta in concepts.items():
        for key, val in (meta or {}).items():
            if isinstance(val, str):
                assert "---" not in val, f"{path}:{key} 에 '---' 잔존: {val!r}"


def test_no_frontmatter_value_breaks_split(tmp_path):
    """emit된 각 페이지의 frontmatter 블록에 '---' 부분문자열이 없어야 한다.

    (OKF consumer text.split('---')가 frontmatter를 중간에 끊지 않음을 직접 보장)
    """
    wiki = _build_wiki(tmp_path)
    out = tmp_path / "okf"
    okf_export.export_bundle(wiki, out)

    for md in out.rglob("*.md"):
        text = md.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        # 첫 '---' 이후 frontmatter 종료 '---' 전까지 본문 split이 정확히 3조각이어야 함
        parts = text.split("---")
        # parts[0]="" / parts[1]=frontmatter / parts[2:]=본문(본문엔 --- 있어도 무방)
        fm_block = parts[1]
        # frontmatter 블록이 yaml로 단독 파싱돼야 한다
        assert yaml.safe_load(fm_block) is not None, f"{md} frontmatter 파싱 실패"


def test_table_first_page_description_is_clean(tmp_path):
    """프로즈 문단이 없고 표로 시작하는 페이지: description은 비거나 표 마크업이 없어야."""
    wiki = _build_wiki(tmp_path)
    out = tmp_path / "okf"
    okf_export.export_bundle(wiki, out)

    text = (out / "concepts" / "tools-comparison.md").read_text(encoding="utf-8")
    _, fm_block, _ = text.split("---", 2)
    meta = yaml.safe_load(fm_block)
    desc = meta.get("description", "")
    assert "|" not in desc, f"description에 표 파이프 잔존: {desc!r}"
    assert "---" not in desc

    # `## 핵심`이 표로 시작해도 그 뒤 진짜 문장을 description으로 잡아야 함
    core = (out / "concepts" / "core-table.md").read_text(encoding="utf-8")
    _, core_fm, _ = core.split("---", 2)
    core_desc = yaml.safe_load(core_fm).get("description", "")
    assert "진짜 요약 문장" in core_desc, f"핵심 섹션 문장 추출 실패: {core_desc!r}"
