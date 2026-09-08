"""Public repository boundaries must stay enforceable in a fresh clone."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from public_surface import violations  # noqa: E402


def test_rejects_docs_and_archive_at_any_depth(tmp_path):
    (tmp_path / "nested" / "docs").mkdir(parents=True)
    (tmp_path / "history" / ".archive").mkdir(parents=True)

    assert violations(tmp_path) == {"history/.archive", "nested/docs"}


def test_ignores_local_worktrees(tmp_path):
    (tmp_path / ".worktrees" / "scratch" / "docs").mkdir(parents=True)

    assert violations(tmp_path) == set()


def test_current_public_tree_has_no_forbidden_directories():
    assert violations(ROOT) == set()
