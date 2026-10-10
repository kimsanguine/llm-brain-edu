"""Preview a separate opt-in management connection; apply only to an approved profile."""
import argparse
from pathlib import Path

import yaml

from wiki_app.hermes_setup import preview, merge_copy, skill_plan, install_skill


def management_preview(root: Path, *, allow_model_calls=False):
    server = Path(__file__).resolve().parents[1]
    connection = preview(root, server)["mcp_servers"]["brain"]
    connection["args"][connection["args"].index("wiki_app.brain_mcp")] = "wiki_app.brain_management"
    connection["args"].append("--allow-writes")
    if allow_model_calls:
        connection["args"].append("--allow-model-calls")
    connection["timeout"] = 240
    return {"mcp_servers": {"brain_manage": connection}}


def apply(config: Path, snippet: dict):
    source = Path(__file__).resolve().parents[1] / "integrations/hermes/llm-brain-manage/SKILL.md"
    skill_plan(config.parent, source, skill_name="llm-brain-manage")
    if any(path.is_symlink() for path in (config, *config.parents)) or config.stat().st_nlink != 1:
        raise ValueError("Use an existing regular profile config")
    existing = yaml.safe_load(config.read_bytes())
    if not isinstance(existing, dict) or not isinstance(existing.get("mcp_servers", {}), dict):
        raise ValueError("Config must contain a valid server mapping")
    current = existing.get("mcp_servers", {}).get("brain_manage")
    if current is not None and current != snippet["mcp_servers"]["brain_manage"]:
        raise ValueError("Existing management connection differs; refusing overwrite")
    if current is None:
        merge_copy(config, snippet, server_name="brain_manage", backup_suffix=".brain-manage.bak")
    install_skill(config.parent, source, skill_name="llm-brain-manage")


def main():
    parser = argparse.ArgumentParser(description="Brain 관리 연결, 기본은 변경 없는 미리보기")
    parser.add_argument("--brain-root", type=Path, default=Path.cwd())
    parser.add_argument("--apply", type=Path, help="Approval to add management to this profile only")
    parser.add_argument("--allow-model-calls", action="store_true", help="Approval to permit explicit LIVE calls; source may leave this computer")
    args = parser.parse_args()
    try:
        snippet = management_preview(args.brain_root, allow_model_calls=args.allow_model_calls)
        if args.apply:
            apply(args.apply.expanduser().absolute(), snippet)
            print("관리 연결과 llm-brain-manage 스킬을 준비했습니다. 기존 조회 연결은 유지합니다.")
        else:
            print(yaml.safe_dump(snippet, allow_unicode=True, sort_keys=False), end="")
    except (ValueError, OSError, yaml.YAMLError):
        parser.exit(1, "관리 연결 준비 실패. 일부 단계가 반영됐을 수 있습니다. 설정과 백업은 비공개로 확인하세요.\n")


if __name__ == "__main__":
    main()
