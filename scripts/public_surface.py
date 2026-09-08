#!/usr/bin/env python3
"""Reject directories that are intentionally local/private in public source."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


FORBIDDEN = frozenset({"docs", ".archive"})
EXCLUDED = frozenset({".git", ".worktrees", "worktrees", ".venv", "__pycache__"})


def _git_ignored(root: Path, path: Path) -> bool:
    """git 이 이 경로를 무시하는가.

    정책은 "must not be committed" 이지 "존재해서는 안 된다" 가 아니다.
    gitignore 된 로컬 작업 폴더는 공개 표면에 나갈 수 없으므로 위반이 아니다.
    git 이 없거나 저장소가 아니면 판단하지 않는다(=위반으로 본다).
    """
    try:
        r = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "-q", str(path)],
            capture_output=True, timeout=5,
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def violations(root: Path) -> set[str]:
    root = Path(root)
    found: set[str] = set()
    for candidate in root.rglob("*"):
        if not candidate.is_dir():
            continue
        relative = candidate.relative_to(root)
        if EXCLUDED.intersection(relative.parts):
            continue
        if FORBIDDEN.intersection(relative.parts):
            if _git_ignored(root, candidate):
                continue
            found.add(relative.as_posix())
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description="validate public repository paths")
    parser.add_argument("root", nargs="?", default=Path(__file__).parents[1], type=Path)
    args = parser.parse_args()
    found = sorted(violations(args.root))
    if found:
        raise SystemExit("forbidden public path(s): " + ", ".join(found))
    print("public surface: valid")


if __name__ == "__main__":
    main()
