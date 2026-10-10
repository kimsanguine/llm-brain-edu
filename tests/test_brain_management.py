import hashlib
import json
from pathlib import Path
import shutil

import pytest


@pytest.fixture
def managed_brain(tmp_path):
    root = tmp_path / "brain"
    root.mkdir()
    source = Path(__file__).resolve().parents[1]
    for name in ("scripts", "schema", "wiki_app"):
        shutil.copytree(source / name, root / name, ignore=shutil.ignore_patterns("__pycache__"))
    (root / "wiki/concepts").mkdir(parents=True)
    (root / "raw/notes").mkdir(parents=True)
    (root / "index.md").write_text("# Brain\n", encoding="utf-8")
    return root


def manager(root, **kwargs):
    from wiki_app.brain_management import BrainManager
    return BrainManager(root, **kwargs)


def test_disabled_writes_do_not_create_note_or_receipt(managed_brain):
    with pytest.raises(PermissionError):
        manager(managed_brain).save_note("public dummy note", "lesson-one")
    assert not list((managed_brain / "raw/notes").glob("*.md"))
    assert not (managed_brain / ".brain-management").exists()


def test_retry_returns_same_source_and_preserves_original(managed_brain):
    service = manager(managed_brain, allow_writes=True)
    first = service.save_note("# Moonlight\nPublic dummy lesson memo.", "lesson-one")
    again = service.save_note("# Moonlight\nPublic dummy lesson memo.", "lesson-one")
    assert first["source"] == again["source"]
    assert again["reused"] is True
    assert len(list((managed_brain / "raw/notes").glob("*.md"))) == 1
    assert "Public dummy lesson memo." in (managed_brain / first["source"]).read_text()
    with pytest.raises(ValueError):
        service.save_note("different content", "lesson-one")


def test_organize_only_requested_note_then_read_in_new_reader(managed_brain):
    from wiki_app.brain_mcp import BrainReader
    service = manager(managed_brain, allow_writes=True)
    saved = service.save_note("# Moonlight\n달빛학원의 브리핑은 근거와 제안을 구분합니다.", "lesson-one")
    unrelated = managed_brain / "raw/notes/unrelated.md"
    unrelated.write_text("Other pending private task", encoding="utf-8")
    result = service.organize_note("lesson-one")
    assert result["mode"] == "RULE"
    assert result["source"] == saved["source"]
    assert len(result["pages"]) == 1
    page = BrainReader(managed_brain).read(result["pages"][0]["slug"])
    assert page["sources"] == [saved["source"]]
    assert "달빛학원" in page["body_md"]
    assert "AI 요약" not in result.get("message", "")
    assert len(list((managed_brain / "wiki/concepts").glob("*.md"))) == 1
    assert "unrelated.md" not in (managed_brain / ".ingest_state.json").read_text()
    assert service.organize_note("lesson-one")["pages"] == result["pages"]


def test_source_tampering_and_model_call_without_optin_rejected(managed_brain):
    service = manager(managed_brain, allow_writes=True)
    saved = service.save_note("A public memo", "lesson-one")
    with pytest.raises(PermissionError):
        service.organize_note("lesson-one", mode="live")
    (managed_brain / saved["source"]).write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError):
        service.organize_note("lesson-one")


@pytest.mark.parametrize("note_id", ["../escape", "/tmp/escape", "a/b", "", "a\\b"])
def test_unsafe_ids_rejected(managed_brain, note_id):
    with pytest.raises(ValueError):
        manager(managed_brain, allow_writes=True).save_note("public memo", note_id)


def test_linked_data_path_cannot_write_outside_brain(managed_brain, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (managed_brain / "raw/notes").rmdir()
    (managed_brain / "raw/notes").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        manager(managed_brain, allow_writes=True).save_note("public memo", "lesson-one")
    assert not list(outside.iterdir())


def test_quality_report_does_not_modify_existing_knowledge(managed_brain):
    service = manager(managed_brain, allow_writes=True)
    service.save_note("# Public\nA public teaching example.", "lesson-one")
    page = service.organize_note("lesson-one")["pages"][0]["source"]
    before = hashlib.sha256((managed_brain / page).read_bytes()).hexdigest()
    result = service.audit()
    assert result["report"] == "wiki/curate_report.md"
    assert (managed_brain / result["report"]).is_file()
    assert hashlib.sha256((managed_brain / page).read_bytes()).hexdigest() == before


def test_separate_setup_preserves_reader_and_other_settings(managed_brain, tmp_path):
    from wiki_app.brain_management_setup import apply
    import yaml
    profile = tmp_path / "profile"
    profile.mkdir()
    config = profile / "config.yaml"
    original = {"model": "dummy", "memory": {"provider": "mem0"},
                "mcp_servers": {"brain": {"command": "old-reader"}}}
    config.write_text(yaml.safe_dump(original))
    snippet = {"mcp_servers": {"brain_manage": {"command": "new-manager"}}}
    apply(config, snippet)
    result = yaml.safe_load(config.read_text())
    assert result["model"] == "dummy"
    assert result["memory"] == {"provider": "mem0"}
    assert result["mcp_servers"]["brain"] == {"command": "old-reader"}
    assert result["mcp_servers"]["brain_manage"] == {"command": "new-manager"}
    assert (profile / "skills/llm-brain-manage/SKILL.md").is_file()
    assert not (profile / "skills/llm-brain").exists()
    before = config.read_bytes()
    apply(config, snippet)
    assert config.read_bytes() == before
    with pytest.raises(ValueError):
        apply(config, {"mcp_servers": {"brain_manage": {"command": "different"}}})


def test_real_management_mcp_saves_compiles_audits_and_reader_reloads(managed_brain):
    import asyncio
    import os
    import sys
    import mcp
    from mcp.client.stdio import stdio_client
    from wiki_app.brain_mcp import BrainReader

    async def run():
        params = mcp.StdioServerParameters(command=sys.executable,
            args=["-B", "-m", "wiki_app.brain_management", "--brain-root", str(managed_brain), "--allow-writes"],
            cwd=str(Path(__file__).resolve().parents[1]), env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        async with stdio_client(params) as (read, write):
            async with mcp.ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {t.name for t in tools.tools} == {"brain_save_note", "brain_organize_note", "brain_audit"}
                saved = await session.call_tool("brain_save_note", {"text": "# Moonlight\n달빛학원은 출처를 확인합니다.", "note_id": "protocol-note"})
                assert not saved.isError
                organized = await session.call_tool("brain_organize_note", {"note_id": "protocol-note"})
                assert not organized.isError
                audit = await session.call_tool("brain_audit", {})
                assert not audit.isError
                return json.loads(organized.content[0].text)

    result = asyncio.run(run())
    assert result["mode"] == "RULE"
    page = BrainReader(managed_brain).read(result["pages"][0]["slug"])
    assert "달빛학원" in page["body_md"]
