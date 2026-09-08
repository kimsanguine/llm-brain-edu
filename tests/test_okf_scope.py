"""test_okf_scope.py — v0.3.2 WS-6 P1: owner/scope frontmatter + okf scope 필터.

team-ready 훅: `scope: private` 페이지는 공개 OKF 번들에서 제외(business/**와 같은 레일),
`scope: shared`·미지정은 하위호환으로 포함, `--strip-internal` 은 소유자 노출을 막기 위해
owner/scope 내부 필드도 제거한다. 필터는 플래그가 아니라 **항상** 적용(one-way door 안전방향).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import okf_export  # noqa: E402


def _page(title, type_="concept", body="", extra_fm=""):
    fm = f"title: {title}\ntype: {type_}\nupdated: 2026-06-01\n{extra_fm}"
    return f"---\n{fm}---\n\n# {title}\n\n{body}\n"


def _write(wiki: Path, rel: str, content: str):
    p = wiki / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_private_page_excluded_from_bundle(tmp_path):
    """scope:private 페이지는 번들에서 제외되고 excluded/excluded_private 에 집계돼야."""
    wiki = tmp_path / "wiki"
    _write(wiki, "concepts/secret.md",
           _page("Secret", extra_fm="scope: private\nowner: kim\n"))
    _write(wiki, "concepts/clean.md", _page("Clean"))

    stats = okf_export.export_bundle(wiki, tmp_path / "okf")
    out = tmp_path / "okf"

    assert not (out / "concepts" / "secret.md").exists()
    assert (out / "concepts" / "clean.md").exists()
    # business 제외와 같은 레일: excluded 카운트에 반영
    assert "concepts/secret.md" in stats.excluded
    # scope 필터가 추가로 막은 분량으로 분리 집계
    assert "concepts/secret.md" in stats.excluded_private
    # 루트 index.md 목차에도 누출 없어야
    idx = (out / "index.md").read_text(encoding="utf-8")
    assert "Secret" not in idx


def test_shared_and_unspecified_pages_included(tmp_path):
    """scope:shared·미지정 페이지는 포함돼야 (하위호환 — 기존 동작 불변)."""
    wiki = tmp_path / "wiki"
    _write(wiki, "concepts/shared.md",
           _page("SharedPage", extra_fm="scope: shared\n"))
    _write(wiki, "concepts/legacy.md", _page("LegacyPage"))  # scope 미지정

    stats = okf_export.export_bundle(wiki, tmp_path / "okf")
    out = tmp_path / "okf"

    assert (out / "concepts" / "shared.md").exists()
    assert (out / "concepts" / "legacy.md").exists()
    assert "concepts/shared.md" not in stats.excluded
    assert "concepts/legacy.md" not in stats.excluded
    assert stats.excluded_private == []
    assert stats.pages_exported == 2


def test_scope_case_insensitive_and_whitespace(tmp_path):
    """fail-safe: 'PRIVATE'·' Private ' 같은 표기도 private 로 인정해 제외돼야."""
    wiki = tmp_path / "wiki"
    _write(wiki, "concepts/a.md", _page("A", extra_fm="scope: PRIVATE\n"))
    _write(wiki, "concepts/b.md", _page("B", extra_fm="scope: ' Private '\n"))
    _write(wiki, "concepts/clean.md", _page("Clean"))

    stats = okf_export.export_bundle(wiki, tmp_path / "okf")
    out = tmp_path / "okf"

    assert not (out / "concepts" / "a.md").exists()
    assert not (out / "concepts" / "b.md").exists()
    assert (out / "concepts" / "clean.md").exists()
    assert "concepts/a.md" in stats.excluded_private
    assert "concepts/b.md" in stats.excluded_private


def test_link_to_private_page_redacted(tmp_path):
    """private 페이지를 가리키던 링크는 business 제외와 동일하게 redact 처리돼야."""
    wiki = tmp_path / "wiki"
    _write(wiki, "concepts/secret.md",
           _page("Secret", extra_fm="scope: private\n"))
    _write(
        wiki,
        "concepts/deal.md",
        _page("Deal", body="자세한 건 [[secret|비밀 운영 수치 3.2억]] 참고."),
    )

    stats = okf_export.export_bundle(wiki, tmp_path / "okf")
    text = (tmp_path / "okf" / "concepts" / "deal.md").read_text(encoding="utf-8")

    # 민감 별칭 텍스트가 본문·frontmatter 어디에도 없어야 (redact)
    assert "비밀 운영 수치" not in text
    assert ("concepts/deal.md", "secret") in stats.excluded_link_refs
    assert ("concepts/deal.md", "secret") not in stats.broken_links


def test_strip_internal_removes_owner_scope_fields(tmp_path):
    """--strip-internal: 공유된(shared) 페이지에서 owner/scope 내부필드가 제거돼야.

    x-llmbrain-* 전면 제거의 부산물이지만, 소유자 노출 방지 불변식을 명시적으로 고정한다.
    """
    wiki = tmp_path / "wiki"
    _write(wiki, "concepts/shared.md",
           _page("SharedPage", extra_fm="scope: shared\nowner: alice\n"))

    okf_export.export_bundle(wiki, tmp_path / "okf", strip_internal=True)
    text = (tmp_path / "okf" / "concepts" / "shared.md").read_text(encoding="utf-8")

    assert "owner" not in text
    assert "alice" not in text
    assert "x-llmbrain-scope" not in text
    assert "x-llmbrain-owner" not in text


def test_keep_mode_preserves_owner_scope_as_internal(tmp_path):
    """기본(keep) 모드: owner/scope 는 x-llmbrain-* 네임스페이스로 보존돼야."""
    wiki = tmp_path / "wiki"
    _write(wiki, "concepts/shared.md",
           _page("SharedPage", extra_fm="scope: shared\nowner: alice\n"))

    okf_export.export_bundle(wiki, tmp_path / "okf", strip_internal=False)
    text = (tmp_path / "okf" / "concepts" / "shared.md").read_text(encoding="utf-8")

    assert "x-llmbrain-scope: shared" in text
    assert "x-llmbrain-owner: alice" in text


def test_private_filter_applies_even_with_strip_internal(tmp_path):
    """private 제외는 플래그와 무관하게 항상 적용 — strip_internal 여부와 독립."""
    wiki = tmp_path / "wiki"
    _write(wiki, "concepts/secret.md",
           _page("Secret", extra_fm="scope: private\n"))
    _write(wiki, "concepts/clean.md", _page("Clean"))

    stats = okf_export.export_bundle(
        wiki, tmp_path / "okf", strip_internal=True
    )
    out = tmp_path / "okf"
    assert not (out / "concepts" / "secret.md").exists()
    assert "concepts/secret.md" in stats.excluded_private
    assert (out / "concepts" / "clean.md").exists()


def test_private_page_surfaced_in_dry_run(tmp_path):
    """dry-run 에 private 카운트가 표면화돼야 (커밋 전 사람 검토용).

    main() 은 REPO_ROOT/wiki 고정이라 tmp 픽스처엔 export_bundle 로 직접 검증한다
    (main 이 stats.excluded_private 를 출력에 사용).
    """
    wiki = tmp_path / "wiki"
    _write(wiki, "concepts/secret.md",
           _page("Secret", extra_fm="scope: private\n"))
    _write(wiki, "concepts/clean.md", _page("Clean"))

    stats = okf_export.export_bundle(wiki, tmp_path / "okf", dry_run=True)
    # dry-run 은 파일 미작성
    assert not (tmp_path / "okf").exists()
    # private 카운트가 stats 로 표면화 (main 이 이 값을 출력)
    assert len(stats.excluded_private) == 1
    assert "concepts/secret.md" in stats.excluded_private
