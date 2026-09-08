"""doctor.py — 설치 진단·수정 계약 테스트.

WHY: 설치가 제대로 됐는지 진단하고(누락 디렉토리·스크립트·커맨드·설정·의존성),
--fix 로 안전 복구(디렉토리 생성·sources 설정 복사, 기존 파일 미덮어씀)한다.
실 repo 는 FAIL 0 이어야 한다(있으면 그게 진짜 설치 문제).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import doctor  # noqa: E402


def _run_doctor(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_REPO_ROOT / "scripts" / "doctor.py"), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def test_doctor_flags_missing_on_empty(tmp_path):
    results = doctor.run_checks(tmp_path)
    assert any(r["status"] == "FAIL" for r in results)  # 빈 디렉토리 → 필수 누락 FAIL


def test_doctor_fix_creates_dirs(tmp_path):
    doctor.run_checks(tmp_path, fix=True)
    assert (tmp_path / "raw" / "notes").is_dir()
    assert (tmp_path / "procedures").is_dir()


def test_doctor_fix_copies_sources_example(tmp_path):
    (tmp_path / "schema").mkdir()
    (tmp_path / "schema" / "sources.example.yaml").write_text("sources: []\n", encoding="utf-8")
    doctor.run_checks(tmp_path, fix=True)
    assert (tmp_path / "schema" / "sources.yaml").is_file()  # example → sources 복사


def test_doctor_fix_does_not_overwrite_existing(tmp_path):
    (tmp_path / "schema").mkdir()
    (tmp_path / "schema" / "sources.example.yaml").write_text("sources: []\n", encoding="utf-8")
    existing = tmp_path / "schema" / "sources.yaml"
    existing.write_text("MINE\n", encoding="utf-8")
    doctor.run_checks(tmp_path, fix=True)
    assert existing.read_text(encoding="utf-8") == "MINE\n"  # 기존 파일 보존(Rule 9)


def test_doctor_treats_uninitialized_personal_data_dirs_as_warnings():
    statuses = {entry["name"]: entry["status"] for entry in doctor.run_checks(doctor.ROOT)}

    assert statuses["dir:raw"] == "WARN"
    assert statuses["dir:wiki"] == "WARN"


def test_doctor_real_repo_no_fail():
    # 실 repo 는 핵심 체크(디렉토리·스크립트·커맨드·의존성) 통과여야 한다.
    results = doctor.run_checks(doctor.ROOT)
    fails = [(r["name"], r["detail"]) for r in results if r["status"] == "FAIL"]
    assert not fails, f"실 repo FAIL: {fails}"


def test_guided_lists_exactly_three_profiles_from_any_working_directory(tmp_path):
    """Mutation caught: deriving root from cwd would point guided setup at unrelated data."""
    result = _run_doctor(tmp_path, "--guided")

    assert result.returncode == 0, result.stderr
    assert f"Repository root: {_REPO_ROOT.resolve()}" in result.stdout
    profile_lines = [
        line.removeprefix("  - ")
        for line in result.stdout.splitlines()
        if line.startswith("  - ")
    ]
    assert profile_lines == ["Demo", "Personal-private", "Share-ready"]


@pytest.mark.parametrize(
    ("profile", "required_text"),
    [
        ("demo", ("examples/seed-wiki/wiki", "installation verification", "no browser ui")),
        ("personal-private", ("schema/sources", "preview")),
        (
            "share-ready",
            (
                "schema/okf_export.yaml",
                "schema/okf_export.local.yaml",
                "explicit scope",
                "--share --approve-share I_ACKNOWLEDGE_SHARE_READY_EXPORT",
            ),
        ),
    ],
)
def test_guided_profile_returns_exactly_one_safe_next_action(
    tmp_path, profile, required_text
):
    result = _run_doctor(tmp_path, "--guided", "--profile", profile)

    assert result.returncode == 0, result.stderr
    assert result.stdout.count("Next action:") == 1
    next_action = result.stdout.split("Next action:", 1)[1]
    for text in required_text:
        assert text.lower() in next_action.lower()
    if profile == "personal-private":
        assert "--fix" not in next_action
        assert "sync_raw" not in next_action
        assert "ingest" not in next_action


def test_guided_profile_is_read_only_and_does_not_run_default_checks(tmp_path):
    """Mutation caught: routing guided through run_checks(fix=True) creates personal data."""
    personal_root = tmp_path / "unrelated-personal-content"
    (personal_root / "raw").mkdir(parents=True)
    (personal_root / "wiki").mkdir()
    secret = personal_root / "raw" / "private-note.md"
    secret.write_bytes(b"PRIVATE_MARKER\n")
    before = {
        str(path.relative_to(personal_root)): path.read_bytes()
        for path in personal_root.rglob("*")
        if path.is_file()
    }

    result = _run_doctor(personal_root, "--guided", "--profile", "personal-private")

    after = {
        str(path.relative_to(personal_root)): path.read_bytes()
        for path in personal_root.rglob("*")
        if path.is_file()
    }
    assert result.returncode == 0, result.stderr
    assert after == before
    assert "PRIVATE_MARKER" not in result.stdout
    assert "private-note.md" not in result.stdout


def test_personal_private_guided_action_uses_example_and_succeeds_in_fresh_clone(tmp_path):
    """Fresh clones have no gitignored sources.yaml, so the one action must exist."""
    root = tmp_path / "fresh-clone"
    schema = root / "schema"
    schema.mkdir(parents=True)
    example = schema / "sources.example.yaml"
    example.write_text("sources: []\n", encoding="utf-8")
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    output = doctor.render_guided(root, "personal-private")

    assert output.count("Next action:") == 1
    action = output.rsplit(": ", 1)[1]
    assert str(example) in action
    assert str(schema / "sources.yaml") not in action
    completed = subprocess.run(
        action, cwd=root, shell=True, text=True, capture_output=True, check=False
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "sources: []\n"
    after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert after == before


def test_personal_private_guided_action_prefers_existing_user_config(tmp_path):
    root = tmp_path / "configured-clone"
    schema = root / "schema"
    schema.mkdir(parents=True)
    (schema / "sources.example.yaml").write_text("sources: []\n", encoding="utf-8")
    sources = schema / "sources.yaml"
    sources.write_text("sources:\n  - path: ~/notes\n", encoding="utf-8")

    output = doctor.render_guided(root, "personal-private")

    assert output.count("Next action:") == 1
    assert str(sources) in output
    assert str(schema / "sources.example.yaml") not in output


def test_guided_and_fix_are_mutually_exclusive(tmp_path):
    result = _run_doctor(tmp_path, "--guided", "--fix")

    assert result.returncode == 2
    assert "not allowed with argument" in result.stderr
