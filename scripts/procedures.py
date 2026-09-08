#!/usr/bin/env python3
"""procedures.py — 재사용 절차 메모리 로더 (PRD US-004).

5층 메모리 OS 의 procedural 기질("어떻게 하는가"). procedures/ 의 .md 파일(각
memory_type: procedural)을 slug 단위로 나열·로드해 brain_context 의 후보 절차
주입에 쓰인다. frontmatter 파싱은 공용 fail-loud 파서(scripts/lib/frontmatter_utils)
를 재사용한다 — 별도 미니파서를 두지 않는다(Rule 3).

procedures/ 는 repo 루트(wiki/ 밖)이며 git-tracked + OKF-excluded(§D 보안 경계):
okf_export.py 는 wiki/ 만 스캔하므로 구조적으로 안 보이고, schema/okf_export.yaml
exclude_paths 에 procedures/** 가 명시돼 이중망을 이룬다.
"""
from __future__ import annotations

from pathlib import Path

from lib import frontmatter_utils

PROCEDURES_DIR = Path(__file__).parent.parent / "procedures"


def list_procedures(procedures_dir: Path = PROCEDURES_DIR) -> list[str]:
    """procedures_dir 의 .md 파일 slug(확장자 없는 파일명)를 정렬해 반환.

    부재 디렉토리는 빈 리스트(로드는 견고). 정렬로 호출 간 결정성을 보장한다.
    """
    procedures_dir = Path(procedures_dir)
    if not procedures_dir.exists():
        return []
    return sorted(p.stem for p in procedures_dir.glob("*.md"))


def read_procedure(slug: str, procedures_dir: Path = PROCEDURES_DIR) -> tuple[dict, str]:
    """slug.md 를 읽어 (frontmatter_dict, body) 반환(frontmatter_utils.read_fm).

    파일 부재 시 read_text 가 FileNotFoundError 를 raise 한다(fail-loud) — 조용한
    빈 반환은 호출측이 오타·stale slug 를 놓치게 하므로 금지.
    """
    procedures_dir = Path(procedures_dir)
    text = (procedures_dir / f"{slug}.md").read_text(encoding="utf-8")
    return frontmatter_utils.read_fm(text)


def procedure_version(slug: str, procedures_dir: Path = PROCEDURES_DIR) -> str:
    """절차의 version(frontmatter `version`). 미선언 시 '1.0' (이미지 절차층 '버전').

    워크플로우가 바뀌면 이 값을 올려 재현·추적한다. 항상 str 로 정규화한다.
    """
    fm, _ = read_procedure(slug, procedures_dir)
    return str(fm.get("version", "1.0"))
