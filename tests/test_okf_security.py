"""test_okf_security.py — exclude 보안 경계 회귀 (적대검증 B1·B2·B3·Y1·Y4·Y2).

public 커밋(one-way door)에서 business 누출을 막는 불변식을 고정한다. 적대검증이
찾아낸 누출 경로(중첩 경로·대소문자·별칭 승격·stale 파일)를 각각 재현·차단 검증.
"""
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import okf_export  # noqa: E402


def _page(title, type_="concept", body="", extra_fm=""):
    fm = f"title: {title}\ntype: {type_}\nupdated: 2026-06-01\n{extra_fm}"
    return f"---\n{fm}---\n\n# {title}\n\n{body}\n"


def _write(wiki: Path, rel: str, content: str):
    p = wiki / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_nested_business_excluded(tmp_path):
    """B1: 중첩 경로(archive/business/, projects/x/business/)도 business/**로 제외돼야."""
    wiki = tmp_path / "wiki"
    _write(wiki, "business/anthropic.md", _page("Anthropic"))
    _write(wiki, "archive/business/old-deal.md", _page("Old Deal"))
    _write(wiki, "projects/p1/business/secret.md", _page("Secret"))
    _write(wiki, "concepts/clean.md", _page("Clean"))

    stats = okf_export.export_bundle(wiki, tmp_path / "okf")
    out = tmp_path / "okf"
    assert not (out / "business").exists()
    assert not (out / "archive" / "business").exists()
    assert not (out / "projects" / "p1" / "business").exists()
    # 어떤 출력 파일에도 business 경로가 없어야 (out 기준 상대경로로 판정 — tmp_path명 오탐 회피)
    assert not any(
        "business" in p.relative_to(out).as_posix().lower() for p in out.rglob("*.md")
    )
    assert (out / "concepts" / "clean.md").exists()


def test_case_variant_business_excluded(tmp_path):
    """B2: 대소문자만 다른 Business/·BUSINESS/도 제외돼야 (macOS APFS case-insensitive)."""
    wiki = tmp_path / "wiki"
    _write(wiki, "Business/anthropic.md", _page("Anthropic Upper"))
    _write(wiki, "concepts/clean.md", _page("Clean"))

    okf_export.export_bundle(wiki, tmp_path / "okf")
    out = tmp_path / "okf"
    assert not any(
        "business" in p.relative_to(out).as_posix().lower() for p in out.rglob("*.md")
    )
    # 루트 index.md 목차에도 누출 없어야
    idx = (out / "index.md").read_text(encoding="utf-8")
    assert "Anthropic Upper" not in idx


def test_alias_to_excluded_page_redacted(tmp_path):
    """B3: 제외 페이지를 가리키던 별칭의 민감 텍스트가 본문·description으로 새면 안 됨."""
    wiki = tmp_path / "wiki"
    _write(wiki, "business/anthropic.md", _page("Anthropic", type_="business"))
    _write(
        wiki,
        "concepts/deal.md",
        _page("Deal", body="자세한 건 [[anthropic|Anthropic과 100억 인수협상 진행중]] 참고."),
    )

    stats = okf_export.export_bundle(wiki, tmp_path / "okf")
    text = (tmp_path / "okf" / "concepts" / "deal.md").read_text(encoding="utf-8")

    # 민감 별칭 텍스트가 본문·frontmatter 어디에도 없어야
    assert "100억 인수협상" not in text
    # 링크는 ghost가 아니라 excluded_link_refs로 분류 (Y1)
    assert ("concepts/deal.md", "anthropic") in stats.excluded_link_refs
    assert ("concepts/deal.md", "anthropic") not in stats.broken_links


def test_ghost_vs_excluded_classification(tmp_path):
    """Y1: 진짜 ghost와 제외-타깃 링크가 분리 집계돼야 (보안 게이트 신뢰성)."""
    wiki = tmp_path / "wiki"
    _write(wiki, "business/openai.md", _page("OpenAI", type_="business"))
    _write(
        wiki,
        "concepts/a.md",
        _page("A", body="[[openai]] 그리고 [[정말없는페이지]]."),
    )

    stats = okf_export.export_bundle(wiki, tmp_path / "okf")
    assert ("concepts/a.md", "openai") in stats.excluded_link_refs
    assert ("concepts/a.md", "정말없는페이지") in stats.broken_links
    # 서로 겹치지 않아야
    assert ("concepts/a.md", "openai") not in stats.broken_links


def test_stale_bundle_cleaned_on_reexport(tmp_path):
    """Y4: 재export 시 이전 번들을 정리해 stale 누출 파일이 남지 않아야."""
    wiki = tmp_path / "wiki"
    _write(wiki, "concepts/keep.md", _page("Keep"))
    _write(wiki, "concepts/leak.md", _page("Leak"))
    out = tmp_path / "okf"

    okf_export.export_bundle(wiki, out)
    assert (out / "concepts" / "leak.md").exists()

    # leak 페이지를 제외하고 재export → stale 파일이 남으면 안 됨
    okf_export.export_bundle(wiki, out, exclude_slugs=["leak"])
    assert (out / "concepts" / "keep.md").exists()
    assert not (out / "concepts" / "leak.md").exists()


def test_reexport_refuses_non_bundle_dir(tmp_path):
    """Y4: OKF 번들이 아닌(중요 파일 있는) 비어있지 않은 디렉토리는 덮어쓰기 거부."""
    wiki = tmp_path / "wiki"
    _write(wiki, "concepts/a.md", _page("A"))
    out = tmp_path / "okf"
    out.mkdir()
    (out / "important.txt").write_text("사용자 파일", encoding="utf-8")

    import pytest
    with pytest.raises(SystemExit):
        okf_export.export_bundle(wiki, out)
    # 사용자 파일은 보존돼야
    assert (out / "important.txt").exists()


def test_refuses_dir_with_indexmd_but_no_sentinel(tmp_path):
    """Y4 회귀: index.md+log.md만으로 OKF 번들로 오인해 rmtree하면 안 됨.

    레포 루트도 index.md·log.md를 둘 다 가지므로, 이 판별이 느슨하면 레포가 삭제된다.
    .okf-bundle 센티넬이 없으면 거부하고 기존 파일을 보존해야 한다.
    """
    wiki = tmp_path / "wiki"
    _write(wiki, "concepts/a.md", _page("A"))
    out = tmp_path / "okf"
    out.mkdir()
    (out / "index.md").write_text("# 레포 핵심 인덱스", encoding="utf-8")
    (out / "log.md").write_text("# 레포 핵심 로그", encoding="utf-8")
    critical = out / "wiki_page.md"
    critical.write_text("절대 삭제되면 안 되는 내용", encoding="utf-8")

    import pytest
    with pytest.raises(SystemExit):
        okf_export.export_bundle(wiki, out)
    assert critical.exists(), "센티넬 없는 디렉토리의 파일이 삭제됨 — rmtree 사고"
    assert critical.read_text(encoding="utf-8") == "절대 삭제되면 안 되는 내용"


def test_refuses_out_dir_that_is_source_or_ancestor(tmp_path):
    """Y4: out_dir이 wiki_dir이거나 그 조상(레포 루트)이면 거부 — `--out .` 사고 방지."""
    wiki = tmp_path / "wiki"
    _write(wiki, "concepts/a.md", _page("A"))

    import pytest
    # out_dir == wiki_dir
    with pytest.raises(SystemExit):
        okf_export.export_bundle(wiki, wiki)
    # out_dir == wiki_dir의 조상(레포 루트 격)
    with pytest.raises(SystemExit):
        okf_export.export_bundle(wiki, tmp_path)
    # 소스 보존
    assert (wiki / "concepts" / "a.md").exists()


# ── v0.3 observing/rejected 봉인 (3점 방어 중 설정 측 — SPEC v0.3 §D) ────

_OKF_CONFIG_PATH = Path(__file__).parent.parent / "schema" / "okf_export.yaml"


def test_okf_config_excludes_gate_dirs_and_reweave_queue():
    """§D Phase 0 단서 패턴: export 결과뿐 아니라 config 값 자체를 단언한다."""
    cfg = yaml.safe_load(_OKF_CONFIG_PATH.read_text(encoding="utf-8"))
    exclude_paths = cfg["exclude_paths"]
    assert "observing/**" in exclude_paths
    assert "rejected/**" in exclude_paths
    # reweave 운영 큐(wiki/ 루트 산출물)도 공개 번들 봉인 — META_FILES 미등재 대비.
    assert "reweave_queue.md" in exclude_paths
    # v0.3.1 WS-5 모순 후보 큐도 동일 봉인(reweave_queue 선례).
    assert "contradiction_queue.md" in exclude_paths


def test_contradiction_queue_not_exported(tmp_path):
    """contradiction_queue.md 가 export 번들에 안 나와야 (WS-5 봉인 — exclude_paths 백스톱).

    title 을 부여해 'title 부재 skip' 을 우회시키면 exclude_paths 가 활성 게이트가 된다
    (reweave_queue 선례: 큐가 title 을 얻는 경우 대비 config 봉인)."""
    wiki = tmp_path / "wiki"
    _write(wiki, "contradiction_queue.md",
           _page("Contradiction Queue", body="- [ ] [[clean]] ↔ raw/x.md\n"))
    _write(wiki, "concepts/clean.md", _page("Clean"))

    cfg = yaml.safe_load(_OKF_CONFIG_PATH.read_text(encoding="utf-8"))
    stats = okf_export.export_bundle(wiki, tmp_path / "okf",
                                     exclude_paths=cfg["exclude_paths"])
    out = tmp_path / "okf"
    assert not (out / "contradiction_queue.md").exists()
    rels = [p.relative_to(out).as_posix().lower() for p in out.rglob("*.md")]
    assert not any("contradiction_queue" in r for r in rels)
    assert (out / "concepts" / "clean.md").exists()
    assert "contradiction_queue.md" in stats.excluded


def test_observing_rejected_not_exported(tmp_path):
    """observing/·rejected/ 픽스처 페이지가 export 목록·번들 어디에도 안 나와야."""
    wiki = tmp_path / "wiki"
    _write(wiki, "observing/pending-idea.md",
           _page("Pending Idea", extra_fm="gate_status: observing\n"))
    _write(wiki, "rejected/dropped-idea.md",
           _page("Dropped Idea", extra_fm="gate_status: rejected\n"))
    _write(wiki, "reweave_queue.md", "# Reweave Queue\n\n- [ ] `wiki/concepts/clean.md`\n")
    _write(wiki, "concepts/clean.md", _page("Clean"))

    cfg = yaml.safe_load(_OKF_CONFIG_PATH.read_text(encoding="utf-8"))
    stats = okf_export.export_bundle(wiki, tmp_path / "okf",
                                     exclude_paths=cfg["exclude_paths"])
    out = tmp_path / "okf"
    assert not (out / "observing").exists()
    assert not (out / "rejected").exists()
    assert not (out / "reweave_queue.md").exists()
    rels = [p.relative_to(out).as_posix().lower() for p in out.rglob("*.md")]
    assert not any("observing" in r or "rejected" in r or "reweave_queue" in r for r in rels)
    assert (out / "concepts" / "clean.md").exists()
    # export 목록(stats)에도 included 로 등장하면 안 된다 — excluded 로 집계돼야.
    assert "observing/pending-idea.md" in stats.excluded
    assert "rejected/dropped-idea.md" in stats.excluded
    # 루트 index.md 목차에도 누출 없어야
    idx = (out / "index.md").read_text(encoding="utf-8")
    assert "Pending Idea" not in idx and "Dropped Idea" not in idx


def test_dict_fm_value_with_triple_dash_sanitized(tmp_path):
    """Y2: dict 타입 내부필드 값의 '---'도 정리돼 consumer split이 안 깨져야."""
    wiki = tmp_path / "wiki"
    _write(
        wiki,
        "concepts/a.md",
        _page("A", extra_fm="meta:\n  note: 'a --- b'\n"),
    )
    okf_export.export_bundle(wiki, tmp_path / "okf")
    text = (tmp_path / "okf" / "concepts" / "a.md").read_text(encoding="utf-8")
    # frontmatter 블록이 '---' 부분문자열로 안 끊겨야
    _, fm_block, _ = text.split("---", 2)
    assert yaml.safe_load(fm_block) is not None
