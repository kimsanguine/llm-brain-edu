"""frontmatter_utils — 신규+접촉 리더 공용 frontmatter 파서 (fail-loud).

curate.parse_frontmatter / serialize_frontmatter 의 검증된 계약을 단일 위치로
모은다. "단일 출처"는 **아니다** — export_graph.py 미니파서 등 미접촉 리더는 그대로
두고(Rule 3), 신규 코드(episode·brain_context·memory_health)와 US-003 이 건드리는
리더만 이 모듈을 쓴다. export_graph 미니파서는 블록리스트 데이터손실 이력이 있어
다음 접촉 시 이관 후보.
"""
from __future__ import annotations

import re

import yaml

_FM_PATTERN = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


class FrontmatterParseError(ValueError):
    """frontmatter 블록은 있으나 YAML invalid 또는 dict 아님.

    조용한 {} 반환을 금지한다 — 호출부의 덮어쓰기로 인한 사용자 필드 데이터
    손실을 막기 위한 fail-loud 신호.
    """


def read_fm(text: str) -> tuple[dict, str]:
    """(frontmatter_dict, body) 반환. frontmatter 없으면 ({}, text).

    블록은 존재하나 YAML 이 invalid 거나 dict 가 아니면 FrontmatterParseError 를
    raise 한다. 빈 블록(safe_load → None)은 정상으로 보고 ({}, body) 를 반환한다.
    """
    m = _FM_PATTERN.match(text)
    if not m:
        return {}, text
    try:
        loaded = yaml.safe_load(m.group(1))
    except yaml.YAMLError as exc:
        raise FrontmatterParseError(str(exc)) from exc
    if loaded is None:
        fm: dict = {}
    elif isinstance(loaded, dict):
        fm = loaded
    else:
        raise FrontmatterParseError(
            f"frontmatter는 dict여야 하나 {type(loaded).__name__}을 받음: {loaded!r}"
        )
    return fm, text[m.end():]


def write_fm(fm: dict, body: str) -> str:
    """(fm, body) → '---\\n{yaml}---{body}'. 키 순서 보존(sort_keys=False), 유니코드 가독."""
    dumped = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False)
    return f"---\n{dumped}---{body}"
