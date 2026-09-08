"""test_okf_audit_fixes.py — Ralph Round 1 audit(페르소나5+Codex) 수정 회귀 잠금.

각 테스트는 audit이 찾은 결함을 재현·차단한다. 출처 태그: P1/P2/P3/P5/Codex.
"""
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import okf_export  # noqa: E402


def _w(wiki: Path, rel: str, content: str):
    p = wiki / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _fm(text, rel):
    """export된 페이지의 frontmatter dict."""
    _, fm_block, _ = text.split("---", 2)
    return yaml.safe_load(fm_block)


def test_empty_exclude_paths_still_excludes_business(tmp_path):
    """[P3 critical] exclude_paths=[] 빈 리스트도 기본 business 제외를 강제해야."""
    wiki = tmp_path / "wiki"
    _w(wiki, "business/anthropic.md", "---\ntitle: A\ntype: business\n---\n\n민감.\n")
    _w(wiki, "concepts/a.md", "---\ntitle: B\ntype: concept\n---\n\n본문.\n")
    s = okf_export.export_bundle(wiki, tmp_path / "okf", exclude_paths=[])
    assert "business/anthropic.md" in s.excluded
    assert not (tmp_path / "okf" / "business").exists()


def test_block_list_frontmatter_preserved(tmp_path):
    """[P2 major] 들여쓰기 블록 YAML 리스트가 손상 없이 파싱돼야 (깨진 키 0)."""
    wiki = tmp_path / "wiki"
    _w(
        wiki,
        "concepts/a.md",
        "---\ntitle: A\ntype: concept\n"
        "sources:\n  - https://example.com/blog\n  - https://other.com\n"
        "domain:\n  - ai\n  - tools\n---\n\n본문.\n",
    )
    okf_export.export_bundle(wiki, tmp_path / "okf")
    text = (tmp_path / "okf" / "concepts" / "a.md").read_text(encoding="utf-8")
    # 깨진 키(x-llmbrain-- https) 없어야
    assert "x-llmbrain--" not in text
    meta = _fm(text, "concepts/a.md")
    # 블록 리스트 domain 보존(2개)
    assert meta.get("x-llmbrain-domain") == ["ai", "tools"]
    # 외부 URL sources 보존
    assert "https://example.com/blog" in (meta.get("x-llmbrain-sources") or [])


def test_raw_sources_stripped(tmp_path):
    """[P1/P3 major] x-llmbrain-sources의 내부 raw/ 경로 제거(구조 유출 방지)."""
    wiki = tmp_path / "wiki"
    _w(
        wiki,
        "concepts/a.md",
        "---\ntitle: A\ntype: concept\n"
        "sources:\n  - https://example.com\n  - raw/til/2026-05-14.md\n---\n\n본문.\n",
    )
    okf_export.export_bundle(wiki, tmp_path / "okf")
    meta = _fm((tmp_path / "okf" / "concepts" / "a.md").read_text(encoding="utf-8"), "x")
    srcs = meta.get("x-llmbrain-sources") or []
    assert "https://example.com" in srcs
    assert all("raw/" not in s for s in srcs), f"raw/ 경로 잔존: {srcs}"


def test_abbreviation_not_truncated_in_description(tmp_path):
    """[P1 major] 약어/이니셜('Carlos E.')에서 description이 잘리면 안 됨."""
    wiki = tmp_path / "wiki"
    _w(
        wiki,
        "tools/swe.md",
        "---\ntitle: SWE\ntype: tool\n---\n\n# SWE\n\n"
        "Princeton 팀(John Yang, Carlos E. Jimenez 등)이 만든 자율 에이전트 프레임워크다.\n",
    )
    okf_export.export_bundle(wiki, tmp_path / "okf")
    meta = _fm((tmp_path / "okf" / "tools" / "swe.md").read_text(encoding="utf-8"), "x")
    desc = meta.get("description", "")
    assert "Carlos E." in desc and "프레임워크" in desc, f"약어에서 잘림: {desc!r}"


def test_diagram_and_version_description_empty(tmp_path):
    """[P1 major] ASCII 다이어그램·버전 문자열만인 본문은 description을 비운다(잘못된 것보다 없는 게 나음)."""
    wiki = tmp_path / "wiki"
    _w(wiki, "p/arch.md", "---\ntitle: Arch\ntype: project\n---\n\n# Arch\n\n[소스] ──sync──▶ [wiki]\n")
    _w(wiki, "tools/sdk.md", "---\ntitle: SDK\ntype: tool\n---\n\n# SDK\n\nopenai-agents=0.14.0.\n")
    okf_export.export_bundle(wiki, tmp_path / "okf")
    arch = _fm((tmp_path / "okf" / "p" / "arch.md").read_text(encoding="utf-8"), "x")
    sdk = _fm((tmp_path / "okf" / "tools" / "sdk.md").read_text(encoding="utf-8"), "x")
    assert not arch.get("description"), f"다이어그램이 description으로: {arch.get('description')!r}"
    assert not sdk.get("description"), f"버전만 description으로: {sdk.get('description')!r}"


def test_root_index_has_descriptions(tmp_path):
    """[P1 major] 루트 index.md 항목에 description이 붙어야(첫 관문 전모 파악)."""
    wiki = tmp_path / "wiki"
    _w(wiki, "concepts/a.md", "---\ntitle: Alpha\ntype: concept\ndescription: 알파 개념 요약\n---\n\n본문.\n")
    okf_export.export_bundle(wiki, tmp_path / "okf")
    root = (tmp_path / "okf" / "index.md").read_text(encoding="utf-8")
    assert "알파 개념 요약" in root, "루트 index에 description 없음"


def test_date_timestamp_is_json_serializable(tmp_path):
    """[P2 major·R2] PyYAML이 만든 date 객체가 ISO 문자열로 덤프돼 json.dumps 가능해야."""
    import json
    wiki = tmp_path / "wiki"
    _w(wiki, "concepts/a.md", "---\ntitle: A\ntype: concept\nupdated: 2026-06-08\n---\n\n본문.\n")
    okf_export.export_bundle(wiki, tmp_path / "okf")
    meta = _fm((tmp_path / "okf" / "concepts" / "a.md").read_text(encoding="utf-8"), "x")
    json.dumps(meta)  # date 객체면 여기서 TypeError
    assert meta["timestamp"] == "2026-06-08", f"timestamp가 ISO 문자열 아님: {meta['timestamp']!r}"


def test_numbered_list_description_not_truncated(tmp_path):
    """[P1 major·R2] 번호목록으로 시작하는 본문은 다음 번호('2.')에서 잘리지 말고 산문을 골라야."""
    wiki = tmp_path / "wiki"
    _w(
        wiki, "i/a.md",
        "---\ntitle: A\ntype: insight\n---\n\n# A\n\n1. 분석 단계 처리\n2. 변환 단계 처리\n\n진짜 요약 문장이다.\n",
    )
    okf_export.export_bundle(wiki, tmp_path / "okf")
    desc = _fm((tmp_path / "okf" / "i" / "a.md").read_text(encoding="utf-8"), "x").get("description", "")
    assert "진짜 요약 문장" in desc, f"번호목록에서 잘림/오추출: {desc!r}"
    assert not desc.strip().startswith("1.")


def test_code_fence_diagram_not_in_description(tmp_path):
    """[P1 major·R2] ```코드펜스``` 안 다이어그램이 description으로 새면 안 됨."""
    wiki = tmp_path / "wiki"
    body = "# A\n\n```\nYouTube URL ↓ yt-dlp ↓ Remotion\n```\n\n각 단계의 함정을 다룬다.\n"
    _w(wiki, "c/a.md", f"---\ntitle: A\ntype: concept\n---\n\n{body}")
    okf_export.export_bundle(wiki, tmp_path / "okf")
    desc = _fm((tmp_path / "okf" / "c" / "a.md").read_text(encoding="utf-8"), "x").get("description", "")
    assert "함정" in desc, f"코드펜스 뒤 산문 미추출: {desc!r}"
    assert "↓" not in desc and "yt-dlp" not in desc, f"다이어그램 누출: {desc!r}"


def test_formula_and_label_description_empty(tmp_path):
    """[P1·R2] 수식 라인·콜론 라벨('수식:')은 description을 비운다."""
    wiki = tmp_path / "wiki"
    _w(wiki, "l/a.md", "---\ntitle: A\ntype: lecture\n---\n\n# A\n\n수식: y = σ(w₀ + w₁x₁)\n")
    okf_export.export_bundle(wiki, tmp_path / "okf")
    desc = _fm((tmp_path / "okf" / "l" / "a.md").read_text(encoding="utf-8"), "x").get("description", "")
    assert not desc, f"수식/라벨이 description으로: {desc!r}"


def test_dict_source_coerced_to_string(tmp_path):
    """[P2 R3 minor] `: ` 때문에 dict로 오파싱된 sources 항목을 문자열로 복원."""
    wiki = tmp_path / "wiki"
    _w(
        wiki, "people/k.md",
        "---\ntitle: K\ntype: person\n"
        "sources:\n  - https://youtube.com/@X (Neural Networks: Zero to Hero)\n---\n\n본문.\n",
    )
    okf_export.export_bundle(wiki, tmp_path / "okf")
    meta = _fm((tmp_path / "okf" / "people" / "k.md").read_text(encoding="utf-8"), "x")
    srcs = meta.get("x-llmbrain-sources") or []
    assert all(isinstance(s, str) for s in srcs), f"dict 잔존: {srcs}"
    assert any("Neural Networks" in s for s in srcs)


def test_meta_file_curate_report_not_skipped_noise(tmp_path):
    """[P5 minor] curate_report.md는 META_FILES라 'title 부재' skip 노이즈로 안 잡혀야."""
    wiki = tmp_path / "wiki"
    _w(wiki, "curate_report.md", "# Curate Report\n\n본문(frontmatter 없음).\n")
    _w(wiki, "concepts/a.md", "---\ntitle: A\ntype: concept\n---\n\n본문.\n")
    s = okf_export.export_bundle(wiki, tmp_path / "okf", dry_run=True)
    assert not any("curate_report" in rel for rel, _ in s.skipped), f"메타 파일이 skip됨: {s.skipped}"


def test_strip_code_fences_line_anchored(tmp_path):
    """[Codex R3] 라인 앵커 펜스 제거 — well-formed 블록만 제거, 산문 보존."""
    body = "intro 산문 문장이다.\n\n```\ncode ↓ diagram\n```\n\ntail 문장.\n"
    out = okf_export._strip_code_fences(body)
    assert "diagram" not in out and "↓" not in out, f"펜스 내부 잔류: {out!r}"
    assert "intro 산문" in out and "tail 문장" in out, f"산문 손실: {out!r}"


def test_sensitive_patterns_surfaced(tmp_path):
    """[P3 major] included 본문 평문 민감정보가 dry-run 게이트에 표면화돼야."""
    wiki = tmp_path / "wiki"
    _w(wiki, "concepts/a.md", "---\ntitle: A\ntype: concept\n---\n\n홍길동의 개인 인프라와 FooApp 이탈률.\n")
    s = okf_export.export_bundle(
        wiki, tmp_path / "okf", sensitive_patterns=["홍길동", "FooApp"], dry_run=True
    )
    hits = {pat for _rel, pat in s.sensitive_hits}
    assert "홍길동" in hits and "FooApp" in hits, f"민감정보 미표면화: {s.sensitive_hits}"
