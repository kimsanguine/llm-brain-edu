"""Prevent setup from replacing learner skills or changing settings without consent."""
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

import wiki_app.hermes_setup as setup


def test_skill_installs_into_selected_profile_and_repeat_keeps_bytes(tmp_path):
    home = tmp_path / "selected-profile"
    home.mkdir()
    source = tmp_path / "SKILL.md"
    source.write_text("---\nname: llm-brain\ndescription: Search knowledge\n---\nRead sources.", encoding="utf-8")
    target = setup.install_skill(home, source)
    before = target.stat().st_mtime_ns
    assert target == home / "skills/llm-brain/SKILL.md"
    assert target.read_bytes() == source.read_bytes()
    assert setup.install_skill(home, source).stat().st_mtime_ns == before


def test_existing_custom_skill_is_never_overwritten(tmp_path):
    home = tmp_path / "profile"
    target = home / "skills/llm-brain/SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("my own instructions", encoding="utf-8")
    source = tmp_path / "new.md"
    source.write_text("new instructions", encoding="utf-8")
    with pytest.raises(ValueError):
        setup.install_skill(home, source)
    assert target.read_text() == "my own instructions"


def test_linked_skill_directory_cannot_write_outside_profile(tmp_path):
    home = tmp_path / "profile"
    home.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (home / "skills").symlink_to(outside, target_is_directory=True)
    source = tmp_path / "new.md"
    source.write_text("instructions", encoding="utf-8")
    with pytest.raises(ValueError):
        setup.install_skill(home, source)
    assert not list(outside.iterdir())


def test_skill_install_requires_explicit_apply(tmp_path):
    result = subprocess.run([sys.executable, "-B", "-m", "wiki_app.hermes_setup", "--install-skill"],
                            capture_output=True, cwd=Path(__file__).resolve().parents[1])
    assert result.returncode != 0
    assert b"--apply" in result.stderr


def test_short_command_checks_current_brain_without_changing_it(tmp_path):
    pytest.importorskip("mcp")
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "wiki").mkdir()
    (tmp_path / "index.md").write_text("# Public empty index", encoding="utf-8")
    python = tmp_path / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    before = {str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")}
    result = subprocess.run([sys.executable, "-B", str(root / "scripts/connect_hermes.py")],
                            cwd=tmp_path, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode()
    assert "brain" in yaml.safe_load(result.stdout)["mcp_servers"]
    assert {str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")} == before


def test_skill_conflict_is_rejected_before_config_changes(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text("model: my-model\n", encoding="utf-8")
    skill = tmp_path / "skills/llm-brain/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("custom skill", encoding="utf-8")
    monkeypatch.setattr(setup, "preview", lambda *args: {"mcp_servers": {"brain": {"command": "python"}}})
    monkeypatch.setattr(sys, "argv", ["setup", "--apply", str(config), "--install-skill"])
    with pytest.raises(SystemExit):
        setup.main()
    assert config.read_text() == "model: my-model\n"
    assert not config.with_name("config.yaml.brain-mcp.bak").exists()


def test_apply_and_skill_repeat_never_replace_config_or_backup(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text("model: unchanged\nmemory: {provider: mem0}\n", encoding="utf-8")
    snippet = {"mcp_servers": {"brain": {"command": "python", "args": ["readonly"]}}}
    monkeypatch.setattr(setup, "preview", lambda *args: snippet)
    monkeypatch.setattr(sys, "argv", ["setup", "--apply", str(config), "--install-skill"])
    setup.main()
    after = config.read_bytes()
    backup = config.with_name("config.yaml.brain-mcp.bak").read_bytes()
    installed = (tmp_path / "skills/llm-brain/SKILL.md").read_bytes()
    setup.main()
    assert config.read_bytes() == after
    assert config.with_name("config.yaml.brain-mcp.bak").read_bytes() == backup
    assert (tmp_path / "skills/llm-brain/SKILL.md").read_bytes() == installed
    assert yaml.safe_load(after)["memory"] == {"provider": "mem0"}


def test_different_existing_brain_stops_before_installing_skill(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text("mcp_servers: {brain: {command: other}}\n", encoding="utf-8")
    original = config.read_bytes()
    monkeypatch.setattr(setup, "preview", lambda *args: {"mcp_servers": {"brain": {"command": "python"}}})
    monkeypatch.setattr(sys, "argv", ["setup", "--apply", str(config), "--install-skill"])
    with pytest.raises(SystemExit):
        setup.main()
    assert config.read_bytes() == original
    assert not (tmp_path / "skills").exists()
