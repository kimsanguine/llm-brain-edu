"""A learner approves one connection step, never loses an existing profile."""
import os
from pathlib import Path
import subprocess
import sys
import shutil

import pytest
import yaml


def snippet():
    return {"mcp_servers": {"brain": {"command": "reader"},
                            "brain_manage": {"command": "manager", "args": ["--allow-writes"]}}}


def test_one_apply_adds_canonical_skill_and_preserves_profile(tmp_path):
    from wiki_app.hermes_bundle_setup import apply_bundle
    config = tmp_path / "config.yaml"
    original = b"model: dummy\nmemory: {provider: mem0}\nmcp_servers: {other: {command: keep}}\n"
    config.write_bytes(original)
    apply_bundle(config, snippet())
    updated = yaml.safe_load(config.read_bytes())
    assert updated["memory"] == {"provider": "mem0"}
    assert updated["model"] == "dummy"
    assert updated["mcp_servers"]["other"] == {"command": "keep"}
    assert set(updated["mcp_servers"]) == {"brain", "brain_manage", "other"}
    assert (tmp_path / "skills/llm-brain/SKILL.md").is_file()
    assert not (tmp_path / "skills/llm-brain-manage/SKILL.md").exists()
    assert (tmp_path / "config.yaml.brain-hermes.bak").read_bytes() == original
    before = config.read_bytes()
    apply_bundle(config, snippet())
    assert config.read_bytes() == before
    assert (tmp_path / "config.yaml.brain-hermes.bak").read_bytes() == original


def test_existing_matching_reader_is_kept_and_only_management_added(tmp_path):
    from wiki_app.hermes_bundle_setup import apply_bundle
    config = tmp_path / "config.yaml"
    config.write_text("mcp_servers: {brain: {command: reader}}\n")
    apply_bundle(config, snippet())
    assert yaml.safe_load(config.read_bytes())["mcp_servers"]["brain"] == {"command": "reader"}


@pytest.mark.parametrize("conflict", ["reader", "manager", "skill", "backup"])
def test_conflicts_stop_before_profile_or_skills_change(tmp_path, conflict):
    from wiki_app.hermes_bundle_setup import apply_bundle
    config = tmp_path / "config.yaml"
    data = {"model": "unchanged"}
    if conflict in ("reader", "manager"):
        key = "brain" if conflict == "reader" else "brain_manage"
        data["mcp_servers"] = {key: {"command": "different"}}
    config.write_text(yaml.safe_dump(data))
    if conflict == "skill":
        skill = tmp_path / "skills/llm-brain/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("my custom skill")
    if conflict == "backup":
        (tmp_path / "config.yaml.brain-hermes.bak").write_text("existing backup")
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises((ValueError, OSError)):
        apply_bundle(config, snippet())
    after = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before


def test_existing_custom_legacy_skill_is_preserved(tmp_path):
    from wiki_app.hermes_bundle_setup import apply_bundle
    config = tmp_path / "config.yaml"
    config.write_text("model: unchanged\n")
    legacy = tmp_path / "skills/llm-brain-manage/SKILL.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("my legacy skill")
    apply_bundle(config, snippet())
    assert legacy.read_text() == "my legacy skill"


def test_migration_flag_does_not_authorize_custom_skill_overwrite(tmp_path):
    from wiki_app.hermes_bundle_setup import apply_bundle
    config = tmp_path / "config.yaml"
    config.write_text("model: unchanged\n")
    target = tmp_path / "skills/llm-brain/SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("my custom skill")
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises(ValueError):
        apply_bundle(config, snippet(), migrate_public_skill=True)
    assert {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("approved", [False, True])
def test_known_public_reader_migration_requires_approval_and_keeps_reader(tmp_path, approved):
    from wiki_app.hermes_bundle_setup import apply_bundle
    original_skill = (Path(__file__).parent / "fixtures/hermes_public_reader_skill.md").read_bytes()
    target = tmp_path / "skills/llm-brain/SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(original_skill)
    reader = {"command": "old-reader", "args": ["-m", "wiki_app.brain_mcp", "--brain-root", str(tmp_path)], "cwd": "old-runtime"}
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"memory": {"provider": "mem0"}, "mcp_servers": {"brain": reader}}))
    original_config = config.read_bytes()
    desired = snippet()
    desired["mcp_servers"]["brain"]["args"] = reader["args"]
    if not approved:
        with pytest.raises(ValueError):
            apply_bundle(config, desired)
        assert config.read_bytes() == original_config
        assert target.read_bytes() == original_skill
        assert not target.with_name("SKILL.md.brain-public.bak").exists()
        return
    apply_bundle(config, desired, migrate_public_skill=True)
    canonical = Path(__file__).resolve().parents[1] / "integrations/hermes/llm-brain/SKILL.md"
    assert target.read_bytes() == canonical.read_bytes()
    assert target.with_name("SKILL.md.brain-public.bak").read_bytes() == original_skill
    data = yaml.safe_load(config.read_bytes())
    assert data["mcp_servers"]["brain"] == reader
    assert data["memory"] == {"provider": "mem0"}
    after = config.read_bytes()
    apply_bundle(config, desired, migrate_public_skill=True)
    assert config.read_bytes() == after
    assert target.with_name("SKILL.md.brain-public.bak").read_bytes() == original_skill


def test_skill_backup_conflict_stops_before_config_migration(tmp_path):
    from wiki_app.hermes_bundle_setup import apply_bundle
    target = tmp_path / "skills/llm-brain/SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_bytes((Path(__file__).parent / "fixtures/hermes_public_reader_skill.md").read_bytes())
    target.with_name("SKILL.md.brain-public.bak").write_text("existing backup")
    config = tmp_path / "config.yaml"
    config.write_text("model: unchanged\n")
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises(ValueError):
        apply_bundle(config, snippet(), migrate_public_skill=True)
    assert {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_migration_flag_without_apply_is_rejected():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-B", str(root / "integrations/hermes/connect.py"), "--with-management", "--migrate-public-skill"], capture_output=True)
    assert result.returncode != 0
    assert b"requires --with-management and --apply" in result.stderr


def test_bundle_entry_preview_does_not_modify_brain_or_profile(tmp_path):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "wiki").mkdir()
    for name in ("scripts", "schema", "wiki_app"):
        shutil.copytree(root / name, tmp_path / name, ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "index.md").write_text("# Empty public Brain")
    python = tmp_path / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    before = {str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")}
    result = subprocess.run([sys.executable, "-B", str(root / "integrations/hermes/connect.py"), "--with-management"],
        cwd=tmp_path, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode()
    servers = yaml.safe_load(result.stdout)["mcp_servers"]
    assert set(servers) == {"brain", "brain_manage"}
    assert "--allow-model-calls" not in servers["brain_manage"]["args"]
    assert {str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")} == before


def test_model_permission_is_not_accepted_without_management(tmp_path):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-B", str(root / "integrations/hermes/connect.py"), "--allow-model-calls"],
        cwd=tmp_path, capture_output=True)
    assert result.returncode != 0


def test_config_change_between_preflight_and_merge_is_rejected(tmp_path):
    from wiki_app.hermes_setup import merge_copy
    config = tmp_path / "config.yaml"
    config.write_text("model: recently-changed\n")
    with pytest.raises(ValueError):
        merge_copy(config, snippet(), expected_original=b"model: old\n")
    assert config.read_text() == "model: recently-changed\n"
    assert not (tmp_path / "config.yaml.brain-mcp.bak").exists()


def test_existing_legacy_runtime_reader_same_brain_is_preserved(tmp_path):
    from wiki_app.hermes_bundle_setup import apply_bundle
    legacy = {"command": sys.executable, "args": ["-m", "wiki_app.brain_mcp", "--brain-root", str(tmp_path)], "cwd": "old-runtime"}
    desired = snippet()
    desired["mcp_servers"]["brain"]["args"] = ["-m", "wiki_app.brain_mcp", "--brain-root", str(tmp_path)]
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"mcp_servers": {"brain": legacy}}))
    apply_bundle(config, desired)
    assert yaml.safe_load(config.read_text())["mcp_servers"]["brain"] == legacy


def test_help_explains_management_option_for_new_users():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-B", str(root / "integrations/hermes/connect.py"), "--help"], capture_output=True)
    assert result.returncode == 0
    assert b"--with-management" in result.stdout


def test_installed_bundle_runs_real_save_organize_read_and_audit(tmp_path):
    """Config registration alone must not be mistaken for working saved knowledge."""
    import asyncio
    import json
    import mcp
    from mcp.client.stdio import stdio_client
    from wiki_app.hermes_bundle_setup import bundle_preview, apply_bundle

    source = Path(__file__).resolve().parents[1]
    brain = tmp_path / "actual-brain"
    brain.mkdir()
    for name in ("scripts", "schema", "wiki_app"):
        shutil.copytree(source / name, brain / name, ignore=shutil.ignore_patterns("__pycache__"))
    (brain / "wiki").mkdir()
    (brain / "index.md").write_text("# Public Brain")
    python = brain / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    profile = tmp_path / "profile"
    profile.mkdir()
    config = profile / "config.yaml"
    config.write_text("model: dummy\nmemory: {provider: mem0}\n")
    apply_bundle(config, bundle_preview(brain, source))
    settings = yaml.safe_load(config.read_text())["mcp_servers"]

    async def call(name, actions):
        item = settings[name]
        params = mcp.StdioServerParameters(command=item["command"], args=item["args"], cwd=item["cwd"],
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        results = []
        async with stdio_client(params) as (read, write):
            async with mcp.ClientSession(read, write) as session:
                await session.initialize()
                for tool, arguments in actions:
                    result = await session.call_tool(tool, arguments)
                    assert not result.isError
                    results.append(json.loads(result.content[0].text))
        return results

    saved, organized, audit = asyncio.run(call("brain_manage", [
        ("brain_save_note", {"text": "# Moonlight\n달빛학원의 브리핑은 출처와 담당자를 표시합니다.", "note_id": "bundle-demo"}),
        ("brain_organize_note", {"note_id": "bundle-demo"}),
        ("brain_audit", {})]))
    assert organized["mode"] == "RULE"
    assert (brain / saved["source"]).is_file()
    assert (brain / audit["report"]).is_file()
    page, = asyncio.run(call("brain", [("brain_read", {"slug": organized["pages"][0]["slug"]})]))
    assert "달빛학원" in page["body_md"]
    assert page["sources"] == [saved["source"]]
