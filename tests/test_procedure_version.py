"""procedures version(절차 버전) 계약 테스트 — 이미지 절차층 '스킬/패턴/버전'의 '버전'.

WHY: 절차 메모리는 워크플로우가 바뀌면 버전이 올라가야 재현·추적이 된다.
커밋된 예시는 version 을 선언하고, 로더는 미선언 시 안전 기본값을 준다.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import procedures  # noqa: E402


def test_procedure_version_returns_declared(tmp_path):
    (tmp_path / "p.md").write_text(
        "---\ntitle: P\nmemory_type: procedural\nversion: '2.1'\n---\nbody\n", encoding="utf-8"
    )
    assert procedures.procedure_version("p", procedures_dir=tmp_path) == "2.1"


def test_procedure_version_defaults_when_absent(tmp_path):
    (tmp_path / "p.md").write_text(
        "---\ntitle: P\nmemory_type: procedural\n---\nbody\n", encoding="utf-8"
    )
    assert procedures.procedure_version("p", procedures_dir=tmp_path) == "1.0"


def test_committed_examples_declare_version():
    # 이미지 절차층 '버전' — 커밋된 4 예시는 전부 version 을 선언해야 한다.
    slugs = procedures.list_procedures()
    assert slugs, "예시 절차가 있어야 함"
    for slug in slugs:
        fm, _ = procedures.read_procedure(slug)
        assert "version" in fm, f"{slug} missing version"
