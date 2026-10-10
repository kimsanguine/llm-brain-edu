"""One approved setup, two connections, unchanged read-only defaults."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

import yaml

from wiki_app.hermes_setup import preview, merge_copy, skill_plan, install_skill


def bundle_preview(root: Path, server_root: Path, *, allow_model_calls=False) -> dict:
    from wiki_app.brain_management_setup import management_preview
    reader = preview(root, server_root)
    manager = management_preview(root, allow_model_calls=allow_model_calls)
    return {"mcp_servers": {**reader["mcp_servers"], **manager["mcp_servers"]}}


def _same_brain_reader(current, desired) -> bool:
    """Keep a previously installed runtime only when it names the same Brain."""
    if current == desired:
        return True
    if not isinstance(current, dict):
        return False
    old, new = current.get("args"), desired.get("args")
    if not isinstance(old, list) or not isinstance(new, list):
        return False
    try:
        if old.count("--brain-root") != 1 or "wiki_app.brain_mcp" not in old:
            return False
        return Path(old[old.index("--brain-root") + 1]).resolve() == Path(new[new.index("--brain-root") + 1]).resolve()
    except (IndexError, ValueError, TypeError, OSError):
        return False


def apply_bundle(config: Path, snippet: dict) -> None:
    config = config.expanduser().absolute()
    # Check every destination before the first write. Never replace a custom skill.
    sources = Path(__file__).resolve().parents[1] / "integrations/hermes"
    for name in ("llm-brain", "llm-brain-manage"):
        skill_plan(config.parent, sources / name / "SKILL.md", skill_name=name)
    if any(p.is_symlink() for p in (config, *config.parents)) or config.stat().st_nlink != 1:
        raise ValueError("Use an existing regular unlinked profile config")
    original = config.read_bytes()
    data = yaml.safe_load(original)
    if not isinstance(data, dict) or not isinstance(data.get("mcp_servers", {}), dict):
        raise ValueError("Config must contain a valid server mapping")
    servers = data.get("mcp_servers", {})
    requested = snippet["mcp_servers"]
    missing = {}
    for name in ("brain", "brain_manage"):
        if name not in servers:
            missing[name] = requested[name]
        elif not (name == "brain" and _same_brain_reader(servers[name], requested[name])) and servers[name] != requested[name]:
            raise ValueError("Existing Brain connection differs; refusing overwrite")
    if missing:
        merge_copy(config, {"mcp_servers": missing}, server_name=next(iter(missing)),
                   backup_suffix=".brain-hermes.bak", expected_original=original)
    for name in ("llm-brain", "llm-brain-manage"):
        install_skill(config.parent, sources / name / "SKILL.md", skill_name=name)


def main() -> None:
    # The old command keeps its read-only behaviour unless management is selected.
    if "--with-management" not in sys.argv[1:] and not any(flag in sys.argv[1:] for flag in ("--help", "-h")):
        from wiki_app.hermes_setup import main as reader_main
        reader_main()
        return
    parser = argparse.ArgumentParser(description="Brain 조회와 관리 한 번에 준비, 기본은 변경 없는 미리보기")
    parser.add_argument("--with-management", action="store_true", help="Select save, organize and audit capabilities; does not itself write config")
    parser.add_argument("--brain-root", type=Path, default=Path.cwd())
    parser.add_argument("--server-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--apply", type=Path, help="Approve both connections and both skills for this existing profile config")
    parser.add_argument("--install-skill", action="store_true", help="Compatibility option; both skills are already included with management apply")
    parser.add_argument("--allow-model-calls", action="store_true", help="Permit explicit LIVE calls, including source/rules transmission and possible cost")
    args = parser.parse_args()
    if args.install_skill and not args.apply:
        parser.error("--install-skill requires --apply CONFIG_PATH approval")
    try:
        snippet = bundle_preview(args.brain_root, args.server_root, allow_model_calls=args.allow_model_calls)
        if args.apply:
            apply_bundle(args.apply, snippet)
            print("조회와 관리 연결, 두 스킬 준비 완료. 기존 연결은 보존하며 동일한 항목은 변경하지 않았습니다.")
            print("설정 변경 시 .brain-hermes.bak 백업이 생성됩니다. 같은 프로필에서 두 MCP를 점검하세요.")
        else:
            print(yaml.safe_dump(snippet, allow_unicode=True, sort_keys=False), end="")
    except (ValueError, OSError, subprocess.SubprocessError, yaml.YAMLError):
        parser.exit(1, "조회와 관리 준비 실패. 기존 연결이나 스킬을 덮어쓰지 않습니다. 일부 단계가 완료됐을 수 있으니 설정과 백업을 비공개로 확인하세요.\n")


if __name__ == "__main__":
    main()
