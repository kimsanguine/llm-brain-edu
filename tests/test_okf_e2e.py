"""test_okf_e2e.py — OKF Export end-to-end 테스트 (멀티에이전트 설계, 2026-06-24).

단위 테스트(test_okf_*.py, 함수 단위)가 못 보는 **프로세스 경계·통합 시나리오**.
실제 CLI를 subprocess로 구동(argparse·경로해석·config+local 병합 전 경로) +
외부 OKF consumer로 산출물 소비. 공개 계약: SPEC.md 및 schema/okf.md

검증 철학: 명령 실행 → 실제 okf/ → 관측(exit code·파일·stdout·consumer).
수정자≠검증자: consumer 검증은 okf_export import 없이 독립 작성(스펙 §11 정규식).
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

_SCRIPTS = Path(__file__).parent.parent / "scripts"


# ── 미니레포 픽스처 (main()의 REPO_ROOT/wiki 하드코딩 우회) ──
def _minirepo(tmp_path: Path, pages: dict | None = None, local: dict | None = None) -> Path:
    """tmp_path에 실 okf_export.py를 복사한 미니레포 + wiki 생성."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "schema").mkdir()
    for s in ("okf_export.py", "export_graph.py"):
        shutil.copy(_SCRIPTS / s, repo / "scripts" / s)
    (repo / "schema" / "okf_export.yaml").write_text(
        "exclude_paths:\n  - 'business/**'\n  - 'canvas/**'\n"
        "exclude_domains: []\nexclude_slugs: []\nsensitive_patterns: []\n",
        encoding="utf-8",
    )
    if local is not None:
        (repo / "schema" / "okf_export.local.yaml").write_text(
            yaml.safe_dump(local, allow_unicode=True), encoding="utf-8"
        )
    pages = pages or {
        "concepts/rag.md": "---\ntitle: RAG\ntype: concept\nupdated: 2026-06-01\n---\n\n# RAG\n\nRAG는 검색 증강 생성이다. [[vector-db]] 참고.\n",
        "concepts/vector-db.md": "---\ntitle: Vector DB\ntype: concept\n---\n\n# Vector DB\n\n벡터 데이터베이스다.\n",
        "business/secret.md": "---\ntitle: Secret\ntype: business\n---\n\n# Secret\n\n민감 정보 평문.\n",
    }
    for rel, content in pages.items():
        p = repo / "wiki" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return repo


def _run(repo: Path, *args: str):
    """미니레포에서 okf_export CLI를 subprocess로 구동 → (rc, stdout, stderr)."""
    r = subprocess.run(
        [sys.executable, "scripts/okf_export.py", *args],
        cwd=repo, capture_output=True, text=True,
    )
    return r.returncode, r.stdout, r.stderr


# ── 스펙 §11 minimal consumer (독립 구현 — okf_export import 안 함) ──
def _load_bundle(root: Path):
    concepts, links = {}, []
    for path in root.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        meta = {}
        if text.startswith("---"):
            _, fm, body = text.split("---", 2)
            meta = yaml.safe_load(fm) or {}
        else:
            body = text
        concepts[str(path)] = meta
        for tgt in set(re.findall(r"\]\((/[^)]+\.md)\)", body)):
            links.append((str(path), tgt))
    return concepts, links


# ════════ Suite A — CLI 플래그 ════════
def test_e2e_default_export(tmp_path):
    repo = _minirepo(tmp_path)
    rc, out, _ = _run(repo)
    assert rc == 0, out
    okf = repo / "okf"
    assert (okf / ".okf-bundle").exists() and (okf / "index.md").exists()
    assert not (okf / "business").exists(), "business가 번들에 누출"
    assert "pages=" in out and "excluded pages:" in out


def test_e2e_dry_run_writes_nothing(tmp_path):
    repo = _minirepo(tmp_path)
    rc, out, _ = _run(repo, "--dry-run")
    assert rc == 0
    assert not (repo / "okf").exists(), "dry-run이 파일을 씀"
    assert "DRY-RUN" in out


def test_e2e_dry_run_real_stats_parity(tmp_path):
    """dry-run 통계 == real 통계 (dry-run이 거짓 안심을 주지 않음)."""
    repo = _minirepo(tmp_path)
    _, dry, _ = _run(repo, "--dry-run")
    _, real, _ = _run(repo)
    grab = lambda s: next(l for l in s.splitlines() if l.startswith("pages="))
    assert grab(dry) == grab(real)


def test_e2e_strip_internal_removes_namespace(tmp_path):
    repo = _minirepo(tmp_path, pages={
        "concepts/a.md": "---\ntitle: A\ntype: concept\ndomain:\n  - ai\n"
                         "distill_level: 1\naccess_count: 3\n---\n\n# A\n\n본문이다.\n",
    })
    _run(repo, "--out", "full")
    _run(repo, "--out", "stripped", "--strip-internal")
    full = "\n".join(p.read_text() for p in (repo / "full").rglob("*.md"))
    strip = "\n".join(p.read_text() for p in (repo / "stripped").rglob("*.md"))
    assert "x-llmbrain-" in full and "x-llmbrain-" not in strip


# ════════ Suite C — 안전 가드 ════════
def test_e2e_reject_out_dot(tmp_path):
    repo = _minirepo(tmp_path)
    rc, out, err = _run(repo, "--out", ".")
    assert rc != 0 and "거부" in (out + err)


def test_e2e_reject_out_wiki_source(tmp_path):
    repo = _minirepo(tmp_path)
    before = len(list((repo / "wiki").rglob("*.md")))
    rc, _, _ = _run(repo, "--out", "wiki")
    assert rc != 0
    assert len(list((repo / "wiki").rglob("*.md"))) == before, "소스 wiki 훼손"


def test_e2e_reject_non_bundle_dir(tmp_path):
    repo = _minirepo(tmp_path)
    (repo / "notbundle").mkdir()
    keep = repo / "notbundle" / "keep.txt"
    keep.write_text("사용자 파일", encoding="utf-8")
    rc, _, _ = _run(repo, "--out", "notbundle")
    assert rc != 0 and keep.exists()


def test_e2e_reject_symlink_out(tmp_path):
    """GAP-2: symlink out_dir 거부 (dead guard 활성화 회귀)."""
    repo = _minirepo(tmp_path)
    real = repo / "realtarget"
    real.mkdir()
    (real / ".okf-bundle").write_text("x")
    link = repo / "linkout"
    os.symlink(real, link)
    rc, _, err = _run(repo, "--out", "linkout")
    assert rc != 0, "symlink out_dir이 거부되지 않음(GAP-2 회귀)"
    assert (real / ".okf-bundle").exists(), "symlink 대상이 rmtree됨"


# ════════ Suite B — Idempotency·Drift ════════
def test_e2e_idempotent_reexport(tmp_path):
    repo = _minirepo(tmp_path)
    _run(repo)
    snap = tmp_path / "snap"
    shutil.copytree(repo / "okf", snap)
    _run(repo)  # 2차 (센티넬 cleanup 경로)
    # 모든 파일 내용 동일
    for p in (repo / "okf").rglob("*"):
        if p.is_file():
            rel = p.relative_to(repo / "okf")
            assert (snap / rel).read_bytes() == p.read_bytes(), f"비결정적: {rel}"


def test_e2e_stale_page_removed_on_reexport(tmp_path):
    repo = _minirepo(tmp_path)
    extra = repo / "wiki" / "concepts" / "temp.md"
    extra.write_text("---\ntitle: Temp\ntype: concept\n---\n\n임시.\n", encoding="utf-8")
    _run(repo)
    assert (repo / "okf" / "concepts" / "temp.md").exists()
    extra.unlink()  # wiki에서 삭제
    _run(repo)
    assert not (repo / "okf" / "concepts" / "temp.md").exists(), "stale 페이지 잔류"


# ════════ Suite D — Consumer Interop ════════
def test_e2e_minimal_consumer_loads_no_dangling(tmp_path):
    repo = _minirepo(tmp_path)
    _run(repo)
    concepts, links = _load_bundle(repo / "okf")
    assert concepts, "consumer가 빈 번들 로드"
    present = {"/" + str(p.relative_to(repo / "okf")) for p in (repo / "okf").rglob("*.md")}
    dangling = [(s, t) for s, t in links if t not in present]
    assert not dangling, f"dangling 링크: {dangling}"


def test_e2e_content_nodes_have_type(tmp_path):
    repo = _minirepo(tmp_path)
    _run(repo)
    concepts, _ = _load_bundle(repo / "okf")
    # index.md·log.md(frontmatter 없음) 제외한 콘텐츠 노드는 type 필수
    content = {k: m for k, m in concepts.items() if m and "title" in m}
    assert content
    assert all("type" in m for m in content.values())


def test_e2e_frontmatter_json_serializable(tmp_path):
    """전 페이지 frontmatter가 strict json.dumps 가능 (date 회귀 가드)."""
    repo = _minirepo(tmp_path)
    _run(repo)
    concepts, _ = _load_bundle(repo / "okf")
    for path, meta in concepts.items():
        json.dumps(meta)  # date 객체면 TypeError


def test_e2e_root_to_page_navigation(tmp_path):
    """루트 index → 디렉토리 index → 페이지 3-hop 항행이 막힘없다."""
    repo = _minirepo(tmp_path)
    _run(repo)
    okf = repo / "okf"
    root = (okf / "index.md").read_text(encoding="utf-8")
    dir_links = re.findall(r"\]\((/[^)]+/index\.md)\)", root)
    assert dir_links, "루트 index에 디렉토리 링크 없음"
    for dl in dir_links:
        assert (okf / dl.lstrip("/")).exists(), f"디렉토리 index 부재: {dl}"


# ════════ Suite E — 보안 경계 ════════
def test_e2e_business_excluded_default_and_strip(tmp_path):
    repo = _minirepo(tmp_path)
    for mode in ([], ["--strip-internal"]):
        _run(repo, "--out", "b" + ("s" if mode else ""), *mode)
    for d in ("b", "bs"):
        out = repo / d
        assert not any("business" in p.relative_to(out).as_posix().lower()
                       for p in out.rglob("*.md")), f"{d}: business 누출"
        assert "민감 정보 평문" not in "\n".join(p.read_text() for p in out.rglob("*.md"))


def test_e2e_local_sensitive_surfaced(tmp_path):
    """local.yaml의 sensitive_patterns가 dry-run에 표면화."""
    repo = _minirepo(
        tmp_path,
        pages={"concepts/a.md": "---\ntitle: A\ntype: concept\n---\n\n홍길동의 FooApp 이탈률.\n"},
        local={"sensitive_patterns": ["홍길동", "FooApp"], "exclude_slugs": []},
    )
    rc, out, _ = _run(repo, "--dry-run")
    assert rc == 0
    assert "민감정보 후보" in out and "홍길동" in out


def test_e2e_gap1_warning_when_gate_inactive(tmp_path):
    """GAP-1: sensitive_patterns 미설정 + local.yaml 부재 시 stderr 경고."""
    repo = _minirepo(tmp_path)  # local 없음
    rc, _, err = _run(repo, "--dry-run")
    assert rc == 0
    assert "게이트가 비활성" in err, "GAP-1 경고 미발화(fresh-clone 침묵 비활성)"


def test_e2e_gap1_no_warning_when_local_present(tmp_path):
    """대조군: local.yaml 있으면 경고 미발화(false alarm 방지)."""
    repo = _minirepo(tmp_path, local={"sensitive_patterns": ["x"], "exclude_slugs": []})
    _, _, err = _run(repo, "--dry-run")
    assert "게이트가 비활성" not in err


# ════════ Suite F — Fresh-clone ════════
def test_e2e_wiki_absent_failsafe(tmp_path):
    """fresh clone(wiki 없음)에서 재export는 exit 1 + 기존 번들 무손상."""
    repo = _minirepo(tmp_path)
    _run(repo)  # 번들 생성
    before = len(list((repo / "okf").rglob("*")))
    shutil.rmtree(repo / "wiki")  # wiki 제거(fresh clone 모사)
    rc, _, err = _run(repo)
    assert rc == 1 and "wiki dir not found" in err
    assert len(list((repo / "okf").rglob("*"))) == before, "wiki 부재 시 번들 훼손"
