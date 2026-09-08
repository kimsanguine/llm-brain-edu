"""frontmatter_utils — 공용 frontmatter 파서 계약 테스트 (Phase 0).

WHY (이 테스트가 인코딩하는 의도):
  curate.parse_frontmatter / serialize_frontmatter 의 검증된 계약을 신규 공용
  모듈 scripts/lib/frontmatter_utils.py 로 옮길 때, 빈 블록·invalid·non-dict·
  라운드트립 계약이 *동일하게* 유지되는지 기계가 보증한다. 특히 US-003 이 추가
  하는 memory_type 등 optional 필드가 write→read 라운드트립에서 손실되지 않아야
  한다 — 이 무손실이 이 모듈을 분리하는 이유다.

계약은 실제 curate.parse_frontmatter 를 .venv 로 실행해 박제했다(추측 아님).
모두 self-contained — 사용자 wiki/ 데이터에 의존하지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# scripts/ 를 import 경로에 추가 (기존 test_curate_frontmatter.py 컨벤션과 동일).
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from lib import frontmatter_utils as fmu  # noqa: E402


def test_read_fm_extracts_dict_and_body():
    fm, body = fmu.read_fm("---\ntitle: X\ntype: concept\n---\n본문\n")
    assert fm == {"title": "X", "type": "concept"}
    assert body == "\n본문\n"  # 닫는 --- 뒤 개행 포함 (실측 계약)


def test_read_fm_no_frontmatter_returns_empty_and_full_content():
    text = "그냥 본문, frontmatter 없음\n"
    assert fmu.read_fm(text) == ({}, text)


def test_read_fm_empty_block_is_valid_empty_dict():
    # 빈 블록(safe_load → None)은 정상 — ({}, body). (빈 줄 1개 필요)
    fm, body = fmu.read_fm("---\n\n---\n본문\n")
    assert fm == {}
    assert body == "\n본문\n"


def test_read_fm_invalid_yaml_raises_fail_loud():
    # 닫는 따옴표 뒤 텍스트 → YAML 거부 (curate 데이터손실 회귀 케이스와 동일).
    bad = '---\nsources:\n  - "Building a Second Brain" (Forte, 2022)\n---\n본문\n'
    with pytest.raises(fmu.FrontmatterParseError):
        fmu.read_fm(bad)


def test_read_fm_non_dict_raises_fail_loud():
    # list/scalar 등 dict 아닌 frontmatter 는 조용히 {} 반환 금지 — fail-loud.
    with pytest.raises(fmu.FrontmatterParseError):
        fmu.read_fm("---\n- a\n- b\n---\n본문\n")


def test_roundtrip_preserves_new_memory_fields():
    fm = {"title": "X", "memory_type": "semantic", "retention": "durable", "confidence": 0.9}
    body = "\n본문 한국어\n"
    fm2, body2 = fmu.read_fm(fmu.write_fm(fm, body))
    assert fm2 == fm  # 신규 memory_type 등 무손실 (이 모듈의 존재 이유)
    assert body2 == body


def test_write_fm_preserves_key_order():
    out = fmu.write_fm({"title": "X", "type": "concept", "memory_type": "semantic"}, "\nbody\n")
    assert out.index("title") < out.index("type") < out.index("memory_type")  # sort_keys=False


def test_write_fm_keeps_unicode_readable():
    out = fmu.write_fm({"title": "한국어 제목"}, "\nbody\n")
    assert "한국어 제목" in out  # allow_unicode=True (이스케이프 안 됨)
