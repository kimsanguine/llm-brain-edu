"""test_okf_export.py — okf_export.export_bundle 계약 검증 (TDD).

WHY: wiki/(내부 슈퍼셋)를 OKF v0.1 호환 번들 okf/로 투영하는 경계 변환이
공개 계약(SPEC.md 및 schema/okf.md)대로
동작하는지 확인한다. 검증 대상은 "변환 규칙의 의도"이지 구현 디테일이 아니다:
  - frontmatter OKF 매핑 (updated→timestamp, 내부필드→x-llmbrain-*, strip 모드)
  - wikilink → OKF 절대경로 마크다운 링크 (일반·별칭·깨진)
  - 경로 글롭 exclude (business/ 페이지 부재 + stats.excluded 기록)
  - description 규칙 기반 추출 3경로 (fm.description / ## 핵심 / 첫 문단)
  - 디렉토리 미러 + index/log 생성
  - 변환된 링크가 OKF consumer 정규식에 잡히는지

픽스처(tests/fixtures/okf_wiki/)는 실제 wiki/와 무관한 self-contained 트리라
requires_user_wiki 마커를 달지 않는다 (항상 실행). 출력은 tmp_path.

scripts/ import 방식은 tests/test_export_graph.py 패턴을 그대로 따른다
(sys.path.insert로 scripts/ 추가 후 모듈명 직접 import).
"""
import re
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import okf_export  # noqa: E402


FIXTURE_WIKI = Path(__file__).parent / "fixtures" / "okf_wiki"

# OKF 호환성의 단일 진실 (design.md 부록 / contract §5).
OKF_LINK_RE = re.compile(r"\]\((/[^)]+\.md)\)")

# 픽스처에서 business/ 제외 후 export 되는 페이지 (slug 기준).
EXPECTED_EXPORTED = {"rag", "vector-db", "llm", "researcher", "embeddings"}


def _read_okf_page(out_dir: Path, rel: str) -> tuple[dict, str]:
    """okf/<rel> 파일을 읽어 (frontmatter dict, body) 반환."""
    text = (out_dir / rel).read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{rel}: frontmatter 시작 마커 없음"
    _, fm_text, body = text.split("---", 2)
    fm = yaml.safe_load(fm_text) or {}
    return fm, body


@pytest.fixture
def exported(tmp_path):
    """기본 옵션(keep internal, 기본 exclude)으로 픽스처 export → out_dir 반환."""
    out_dir = tmp_path / "okf"
    stats = okf_export.export_bundle(FIXTURE_WIKI, out_dir)
    return out_dir, stats


# ---------------------------------------------------------------------------
# frontmatter 매핑
# ---------------------------------------------------------------------------

def test_updated_maps_to_timestamp(exported):
    """wiki.updated → OKF.timestamp 로 매핑된다."""
    out_dir, _ = exported
    fm, _ = _read_okf_page(out_dir, "concepts/rag.md")
    assert str(fm["timestamp"]) == "2026-06-20"
    # 원본 키 updated 는 timestamp 로 흡수되어 그대로 남지 않는다.
    assert "updated" not in fm


def test_timestamp_falls_back_to_created(exported):
    """updated 없으면 created 가 timestamp 가 된다 (tools/llm.md)."""
    out_dir, _ = exported
    fm, _ = _read_okf_page(out_dir, "tools/llm.md")
    assert str(fm["timestamp"]) == "2026-03-01"


def test_internal_fields_namespaced_when_kept(exported):
    """strip_internal=False(기본)면 내부필드는 x-llmbrain-* 로 보존된다.

    값 타입은 export_graph parse_frontmatter 가 문자열로 읽는 결정적 동작을
    따른다(스칼라는 str). 검증은 의미(보존 여부·값)에 두고 타입엔 관대하게 str 비교.
    """
    out_dir, _ = exported
    fm, _ = _read_okf_page(out_dir, "concepts/rag.md")
    assert str(fm["x-llmbrain-distill_level"]) == "1"
    assert str(fm["x-llmbrain-access_count"]) == "7"
    assert fm["x-llmbrain-domain"] == "ai"
    assert fm["x-llmbrain-resonance"] == "high"
    # created 도 예약 6필드가 아니므로 네임스페이스로 보존.
    assert str(fm["x-llmbrain-created"]) == "2026-01-01"


def test_strip_internal_removes_namespaced_fields(tmp_path):
    """strip_internal=True 면 예약 필드만 남고 x-llmbrain-* 는 전부 제거된다."""
    out_dir = tmp_path / "okf"
    okf_export.export_bundle(FIXTURE_WIKI, out_dir, strip_internal=True)
    fm, _ = _read_okf_page(out_dir, "concepts/rag.md")
    assert not any(k.startswith("x-llmbrain-") for k in fm), fm
    # 예약 필드는 strip 모드에서도 유지.
    assert fm["type"] == "concept"
    assert fm["title"] == "RAG"
    assert "timestamp" in fm


def test_resource_field_preserved_when_present(exported):
    """fm.resource 가 있는 페이지만 OKF resource 필드를 갖는다."""
    out_dir, _ = exported
    fm_person, _ = _read_okf_page(out_dir, "people/researcher.md")
    assert fm_person["resource"] == "https://example.com/researcher"
    # resource 없는 페이지엔 키가 생기지 않는다.
    fm_rag, _ = _read_okf_page(out_dir, "concepts/rag.md")
    assert "resource" not in fm_rag


def test_type_is_required_field(exported):
    """모든 export 페이지는 OKF 필수 type 필드를 갖는다."""
    out_dir, _ = exported
    for slug, rel in [("rag", "concepts/rag.md"), ("llm", "tools/llm.md")]:
        fm, _ = _read_okf_page(out_dir, rel)
        assert "type" in fm and fm["type"]


# ---------------------------------------------------------------------------
# wikilink 변환
# ---------------------------------------------------------------------------

def test_plain_wikilink_converted_to_absolute_path(exported):
    """[[vector-db]] → [vector-db](/concepts/vector-db.md)."""
    out_dir, _ = exported
    _, body = _read_okf_page(out_dir, "concepts/rag.md")
    assert "[vector-db](/concepts/vector-db.md)" in body
    # 원래 wikilink 구문은 본문에서 사라진다.
    assert "[[vector-db]]" not in body


def test_aliased_wikilink_uses_alias_text(exported):
    """[[llm|대규모 언어 모델]] → [대규모 언어 모델](/tools/llm.md)."""
    out_dir, _ = exported
    _, body = _read_okf_page(out_dir, "concepts/rag.md")
    assert "[대규모 언어 모델](/tools/llm.md)" in body
    assert "[[llm" not in body


def test_broken_wikilink_left_as_text_and_recorded(exported):
    """깨진 [[nonexistent]] 는 텍스트만 남고 broken_links 에 기록된다."""
    out_dir, stats = exported
    _, body = _read_okf_page(out_dir, "concepts/rag.md")
    # 링크화되지 않고 텍스트만 남는다 (마크다운 링크 구문 없음).
    assert "nonexistent" in body
    assert "[nonexistent](" not in body
    assert "[[nonexistent]]" not in body
    # broken_links 에 (src_rel, target_slug) 형태로 기록.
    broken_targets = [t for (_src, t) in stats.broken_links]
    assert "nonexistent" in broken_targets


def test_converted_links_match_okf_consumer_regex(exported):
    """변환된 모든 링크는 OKF consumer 정규식 \\]\\((/[^)]+\\.md)\\) 에 잡혀야 한다."""
    out_dir, _ = exported
    _, body = _read_okf_page(out_dir, "concepts/rag.md")
    targets = OKF_LINK_RE.findall(body)
    # rag.md 본문엔 안 깨진 링크 2개(vector-db, llm).
    assert "/concepts/vector-db.md" in targets
    assert "/tools/llm.md" in targets
    # 모든 매치는 슬래시로 시작하는 번들 절대경로.
    assert all(t.startswith("/") and t.endswith(".md") for t in targets)


# ---------------------------------------------------------------------------
# exclude (business/)
# ---------------------------------------------------------------------------

def test_business_page_excluded_from_output(exported):
    """business/ 페이지는 출력 트리에 파일로 존재하지 않는다."""
    out_dir, _ = exported
    assert not (out_dir / "business").exists()
    assert not (out_dir / "business" / "secret.md").exists()


def test_excluded_page_recorded_in_stats(exported):
    """제외된 페이지는 stats.excluded 에 rel 경로로 기록된다."""
    out_dir, stats = exported
    assert any("business/secret.md" in rel for rel in stats.excluded), stats.excluded


def test_exported_page_count_matches_non_excluded(exported):
    """export 페이지 수 = 픽스처 전체 - business 제외 = 5."""
    out_dir, stats = exported
    assert stats.pages_exported == len(EXPECTED_EXPORTED)


def test_excluded_page_links_not_in_broken(exported):
    """제외된 business 페이지의 wikilink([[rag]])는 broken_links 를 오염시키지 않는다."""
    out_dir, stats = exported
    srcs = [src for (src, _t) in stats.broken_links]
    assert not any("business" in s for s in srcs), stats.broken_links


# ---------------------------------------------------------------------------
# description 추출 (3경로)
# ---------------------------------------------------------------------------

def test_description_from_frontmatter(exported):
    """경로① fm.description 이 있으면 그대로 쓴다."""
    out_dir, _ = exported
    fm, _ = _read_okf_page(out_dir, "concepts/rag.md")
    assert fm["description"] == "검색 증강 생성으로 외부 지식을 LLM 응답에 결합한다."


def test_description_from_core_section(exported):
    """경로② fm.description 없으면 ## 핵심 섹션 첫 문장에서 추출."""
    out_dir, _ = exported
    fm, _ = _read_okf_page(out_dir, "concepts/vector-db.md")
    desc = fm["description"]
    assert "근사 최근접 이웃" in desc
    # 첫 문단(핵심 섹션 아님)이 description 으로 새지 않았는지 확인.
    assert "이 문장은 첫 문단" not in desc


def test_description_from_first_paragraph_fallback(exported):
    """경로③ description·## 핵심 둘 다 없으면 첫 문단 첫 문장."""
    out_dir, _ = exported
    fm, _ = _read_okf_page(out_dir, "tools/llm.md")
    desc = fm["description"]
    assert "사전학습한 신경망" in desc
    # 두 번째 문단은 포함되지 않는다.
    assert "두 번째 문단" not in desc


# ---------------------------------------------------------------------------
# 번들 구조 (디렉토리 미러 + index/log)
# ---------------------------------------------------------------------------

def test_directory_mirror(exported):
    """페이지는 wiki rel 구조 그대로 okf/<dir>/<file> 에 미러된다."""
    out_dir, _ = exported
    assert (out_dir / "concepts" / "rag.md").exists()
    assert (out_dir / "tools" / "llm.md").exists()
    assert (out_dir / "people" / "researcher.md").exists()


def test_per_directory_index_generated(exported):
    """각 디렉토리에 index.md 가 생성되고 페이지 링크를 담는다."""
    out_dir, _ = exported
    concepts_index = out_dir / "concepts" / "index.md"
    assert concepts_index.exists()
    text = concepts_index.read_text(encoding="utf-8")
    # 디렉토리 index 도 OKF 절대경로 링크를 쓴다.
    assert "/concepts/rag.md" in text


def test_root_index_generated(exported):
    """루트 okf/index.md 가 생성된다."""
    out_dir, _ = exported
    root_index = out_dir / "index.md"
    assert root_index.exists()
    text = root_index.read_text(encoding="utf-8")
    # 타입별 섹션 또는 페이지 링크가 들어간다.
    assert "/concepts/rag.md" in text


def test_log_generated_with_broken_links(exported):
    """okf/log.md 가 생성되고 깨진 링크 경고를 담는다."""
    out_dir, _ = exported
    log = out_dir / "log.md"
    assert log.exists()
    text = log.read_text(encoding="utf-8")
    assert "nonexistent" in text


# ---------------------------------------------------------------------------
# dry_run
# ---------------------------------------------------------------------------

def test_dry_run_writes_no_files(tmp_path):
    """dry_run=True 면 통계만 반환하고 파일을 0개 쓴다 (보안 게이트용)."""
    out_dir = tmp_path / "okf"
    stats = okf_export.export_bundle(FIXTURE_WIKI, out_dir, dry_run=True)
    # 통계는 정상 계산.
    assert stats.pages_exported == len(EXPECTED_EXPORTED)
    # 그러나 출력 트리는 만들어지지 않는다.
    assert not out_dir.exists() or not any(out_dir.rglob("*.md"))
