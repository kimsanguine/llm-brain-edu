"""Validate a real Brain and preview, or safely merge, a Hermes config copy."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import stat

import yaml

from wiki_app.brain_mcp import validate_brain


def preview(brain_root: Path, server_root: Path) -> dict:
    brain = validate_brain(brain_root)
    server = server_root.expanduser().resolve(strict=True)
    brain_python = brain / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python = server / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not brain_python.is_file() or not python.is_file() or not (server / "wiki_app/brain_mcp.py").is_file():
        raise ValueError("Brain/runtime Python or MCP module missing; run uv sync in each folder")
    brain_check = subprocess.run([str(brain_python), "--version"], capture_output=True, timeout=15)
    if brain_check.returncode:
        raise ValueError("Brain Python is not executable")
    check = subprocess.run([str(python), "-B", "-X", "utf8", "-c", "import mcp; import wiki_app.brain_mcp"],
                           cwd=server, capture_output=True, timeout=15)
    if check.returncode:
        raise ValueError("MCP runtime not ready; run uv sync --extra mcp in server folder")
    return {"mcp_servers": {"brain": {"command": str(python),
            "args": ["-B", "-X", "utf8", "-m", "wiki_app.brain_mcp", "--brain-root", str(brain)],
            "cwd": str(server), "timeout": 30}}}


def merge_copy(target: Path, snippet: dict) -> Path:
    target = target.expanduser().absolute()
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise ValueError("Config target and parent directories must not be symlinks")
    initial = target.lstat()
    if not stat.S_ISREG(initial.st_mode) or initial.st_nlink != 1:
        raise ValueError("Use an existing regular config copy with no hard links")
    original = target.read_bytes()
    data = yaml.safe_load(original)
    if not isinstance(data, dict):
        raise ValueError("Config must be a YAML mapping")
    servers = data.get("mcp_servers", {})
    if not isinstance(servers, dict) or "brain" in servers:
        raise ValueError("Existing brain server or invalid mcp_servers; refusing overwrite")
    data["mcp_servers"] = {**servers, **snippet["mcp_servers"]}
    backup = target.with_name(target.name + ".brain-mcp.bak")
    # Exclusive creation prevents overwriting backups or following backup symlinks.
    backup_fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(backup_fd, "wb") as file:
        file.write(original)
    fd, temporary = tempfile.mkstemp(prefix=".brain-mcp-", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            yaml.safe_dump(data, file, allow_unicode=True, sort_keys=False)
        current = target.lstat()
        if (current.st_dev, current.st_ino, current.st_mtime_ns, current.st_size) != (initial.st_dev, initial.st_ino, initial.st_mtime_ns, initial.st_size) or target.is_symlink() or target.read_bytes() != original:
            raise ValueError("Config changed during merge; refusing overwrite")
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return backup


def skill_plan(home: Path, source: Path) -> tuple[Path, bytes]:
    """Inspect the chosen profile without creating folders or replacing user skills."""
    target = home.expanduser().absolute() / "skills/llm-brain/SKILL.md"
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise ValueError("Skill path must not contain symlinks")
    content = source.read_bytes()
    if target.exists() and (not target.is_file() or target.read_bytes() != content):
        raise ValueError("Existing llm-brain skill differs; refusing overwrite")
    return target, content


def install_skill(home: Path, source: Path) -> Path:
    target, content = skill_plan(home, source)
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    # Recheck after directory creation. Exclusive creation never overwrites a file.
    skill_plan(home, source)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(content)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Brain 연결 점검, 기본은 파일 변경 없음")
    parser.add_argument("--brain-root", type=Path, default=Path.cwd(), help="Default: the current Brain folder")
    parser.add_argument("--server-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--apply", type=Path, metavar="CONFIG_PATH", help="Explicit approval to merge this existing config; try a private copy first")
    parser.add_argument("--install-skill", action="store_true", help="Also install llm-brain in the selected config's profile; requires --apply")
    args = parser.parse_args()
    if args.install_skill and not args.apply:
        parser.error("--install-skill requires --apply CONFIG_PATH approval")
    try:
        snippet = preview(args.brain_root, args.server_root)
        if args.apply:
            target = args.apply.expanduser().absolute()
            source = Path(__file__).resolve().parents[1] / "integrations/hermes/llm-brain/SKILL.md"
            if args.install_skill:
                skill_plan(target.parent, source)  # Reject skill conflicts before touching config.
            if any(p.is_symlink() for p in (target, *target.parents)) or target.stat().st_nlink != 1:
                raise ValueError("Config must be a regular unlinked file")
            existing = yaml.safe_load(target.read_bytes())
            if not isinstance(existing, dict):
                raise ValueError("Config must be a mapping")
            servers = existing.get("mcp_servers", {})
            if not isinstance(servers, dict):
                raise ValueError("mcp_servers must be a mapping")
            if servers.get("brain") == snippet["mcp_servers"]["brain"]:
                print("동일한 Brain 연결이 이미 있습니다. 설정은 바꾸지 않았습니다.")
            else:
                merge_copy(target, snippet)
                print("Brain 연결 추가 완료. .brain-mcp.bak 백업을 보관하세요.")
            if args.install_skill:
                install_skill(target.parent, source)
                print("llm-brain 스킬 준비 완료. 새 대화에서 /llm-brain으로 요청하세요.")
        else:
            print(yaml.safe_dump(snippet, allow_unicode=True, sort_keys=False), end="")
    except (ValueError, OSError, subprocess.SubprocessError, yaml.YAMLError):
        parser.exit(1, "연결 또는 스킬 준비 실패. 기존 연결·스킬·백업은 덮어쓰지 않습니다. 일부 단계가 완료됐을 수 있으니 설정과 스킬을 확인한 뒤 다시 점검하세요.\n")


if __name__ == "__main__":
    main()
