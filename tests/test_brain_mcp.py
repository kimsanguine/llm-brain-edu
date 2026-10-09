import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess

import pytest
import yaml

from wiki_app.brain_mcp import BrainReader, validate_brain
from wiki_app.hermes_setup import merge_copy, preview


@pytest.fixture
def brain(tmp_path):
    root = tmp_path / "brain"
    (root / "wiki/concepts").mkdir(parents=True)
    (root / "raw").mkdir()
    (root / "raw/example.md").write_text("public dummy source", encoding="utf-8")
    (root / "index.md").write_text("## concepts/\n- [[example]] — public example\n", encoding="utf-8")
    (root / "wiki/concepts/example.md").write_text(
        "---\ntitle: Public example\nsources: [raw/example.md]\n---\nA public dummy knowledge page.", encoding="utf-8")
    return root


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def test_reader_is_read_only(brain):
    before = hashes(brain)
    reader = BrainReader(brain)
    assert reader.search("example")["results"][0]["source"] == "wiki/concepts/example.md"
    assert reader.read("example")["sources"] == ["raw/example.md"]
    assert hashes(brain) == before


def test_read_is_bounded_and_honest(brain):
    (brain / "wiki/concepts/example.md").write_text("x" * 25000, encoding="utf-8")
    result = BrainReader(brain).read("example")
    assert len(result["body_md"]) == 20000
    assert result["truncated"] is True
    assert result["original_length"] == 25000


def test_search_source_matches_actual_page_when_index_category_is_stale(brain):
    (brain / "wiki/tools").mkdir()
    (brain / "wiki/concepts/example.md").rename(brain / "wiki/tools/example.md")
    reader = BrainReader(brain)
    result = reader.search("example")["results"][0]
    assert result["source"] == reader.read("example")["source"] == "wiki/tools/example.md"
    assert result["category"] == "tools"


@pytest.mark.parametrize("slug", ["../../secret", "/secret", "..\\secret", "example/../example", "missing"])
def test_reject_bad_slugs(brain, slug):
    with pytest.raises(ValueError):
        BrainReader(brain).read(slug)


def test_index_traversal_and_symlink_never_expose_external_body(brain):
    secret = brain.parent / "secret.md"
    secret.write_text("PRIVATE_SENTINEL", encoding="utf-8")
    with (brain / "index.md").open("a") as file:
        file.write("- [[../../secret]] — PRIVATE_SENTINEL\n- [[linked]] — PRIVATE_SENTINEL\n")
    (brain / "wiki/concepts/linked.md").symlink_to(secret)
    reader = BrainReader(brain)
    assert "PRIVATE_SENTINEL" not in json.dumps(reader.search("PRIVATE_SENTINEL")["results"])
    with pytest.raises(ValueError):
        reader.read("linked")


@pytest.mark.parametrize("name", ["index.md", "wiki/graph.json"])
def test_reject_auxiliary_symlinks(brain, name):
    path = brain / name
    path.unlink(missing_ok=True)
    path.symlink_to(brain.parent / "outside")
    with pytest.raises(ValueError):
        validate_brain(brain)


def test_stdio_protocol_real_sdk(brain):
    mcp = pytest.importorskip("mcp")
    from mcp.client.stdio import stdio_client
    before = hashes(brain)

    async def run():
        params = mcp.StdioServerParameters(command=sys.executable,
            args=["-B", "-X", "utf8", "-m", "wiki_app.brain_mcp", "--brain-root", str(brain)],
            cwd=str(Path(__file__).resolve().parents[1]), env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        async with stdio_client(params) as (read, write):
            async with mcp.ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {t.name for t in tools.tools} == {"brain_search", "brain_read"}
                for tool in tools.tools:
                    assert tool.annotations.readOnlyHint is True
                    assert tool.annotations.destructiveHint is False
                    assert tool.annotations.idempotentHint is True
                    assert tool.annotations.openWorldHint is False
                result = await session.call_tool("brain_search", {"query": "example"})
                assert not result.isError
                assert "example" in result.content[0].text
                result = await session.call_tool("brain_read", {"slug": "example"})
                assert not result.isError
                assert "wiki/concepts/example.md" in result.content[0].text
                result = await session.call_tool("brain_read", {"slug": "../../secret"})
                assert result.isError
    asyncio.run(run())
    assert hashes(brain) == before


def test_preview_real_runtime_and_brain_python(brain):
    pytest.importorskip("mcp")
    python = brain / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    before = hashes(brain)
    snippet = preview(brain, Path(__file__).resolve().parents[1])
    assert snippet["mcp_servers"]["brain"]["args"][-1] == str(brain)
    assert hashes(brain) == before


def test_preview_fresh_runtime_creates_no_bytecode(brain, tmp_path):
    pytest.importorskip("mcp")
    root = Path(__file__).resolve().parents[1]
    runtime = tmp_path / "runtime"
    (runtime / "wiki_app").mkdir(parents=True)
    for name in ("__init__.py", "brain_mcp.py", "search.py", "pages.py"):
        (runtime / "wiki_app" / name).write_bytes((root / "wiki_app" / name).read_bytes())
    for directory in (brain, runtime):
        python = directory / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        python.parent.mkdir(parents=True)
        python.symlink_to(sys.executable)
    before = hashes(runtime)
    preview(brain, runtime)
    assert hashes(runtime) == before
    assert not list(runtime.rglob("__pycache__"))


def test_generated_runtime_handles_cp949_locale_with_utf8_korean(brain, tmp_path):
    pytest.importorskip("mcp")
    korean = brain.with_name("한글-브레인")
    brain.rename(korean)
    (korean / "index.md").write_text("## concepts/\n- [[example]] — 한글 지식 검색\n", encoding="utf-8")
    (korean / "wiki/concepts/example.md").write_text(
        "---\ntitle: 한글 지식\n---\n한글 본문 자료", encoding="utf-8")
    python = korean / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    root = Path(__file__).resolve().parents[1]
    snippet = preview(korean, root)["mcp_servers"]["brain"]
    # Simulate a non-UTF-8 Windows locale only for unspecified file encodings.
    # -X utf8 must bypass that locale; this is not a native Windows test.
    script = """import sys
from pathlib import Path
original = Path.read_text
def locale_read(self, encoding=None, errors=None):
    if encoding is None and not sys.flags.utf8_mode:
        encoding = 'cp949'
    return original(self, encoding=encoding, errors=errors)
Path.read_text = locale_read
from wiki_app.brain_mcp import BrainReader
reader = BrainReader(Path(sys.argv[1]))
assert reader.search('한글')['results'][0]['slug'] == 'example'
assert reader.read('example')['body_md'] == '한글 본문 자료'
print('korean_search_read_ok')
"""
    before = hashes(korean)
    env = {**os.environ, "PYTHONUTF8": "0"}
    baseline = subprocess.run([snippet["command"], "-B", "-c", script, str(korean)],
                              cwd=root, env=env, capture_output=True, timeout=15)
    # Current main explicitly reads UTF-8, so this locale no longer breaks readers.
    assert baseline.returncode == 0, baseline.stderr.decode(errors="replace")
    interpreter_args = snippet["args"][:snippet["args"].index("-m")]
    fixed = subprocess.run([snippet["command"], *interpreter_args, "-c", script, str(korean)],
                           cwd=root, env=env, capture_output=True, timeout=15)
    assert fixed.returncode == 0, "Generated MCP runtime must read UTF-8 Korean under CP949 locale"
    assert fixed.stdout.strip() == b"korean_search_read_ok"
    assert hashes(korean) == before


def test_merge_preserves_mem0_models_and_secrets(tmp_path):
    target = tmp_path / "copy.yaml"
    data = {"memory": {"provider": "mem0", "key": "dummy-secret"}, "model": "default-model",
            "fallback_models": ["fallback"], "mcp_servers": {"other": {"command": "other"}}}
    target.write_text(yaml.safe_dump(data), encoding="utf-8")
    original = target.read_bytes()
    backup = merge_copy(target, {"mcp_servers": {"brain": {"command": "python"}}})
    merged = yaml.safe_load(target.read_bytes())
    assert backup.read_bytes() == original
    assert {k: merged[k] for k in data if k != "mcp_servers"} == {k: data[k] for k in data if k != "mcp_servers"}
    assert merged["mcp_servers"]["other"] == data["mcp_servers"]["other"]
    with pytest.raises(ValueError):
        merge_copy(target, {"mcp_servers": {"brain": {}}})


@pytest.mark.parametrize("hazard", ["target", "parent", "backup", "hardlink"])
def test_merge_rejects_hazards(tmp_path, monkeypatch, hazard):
    real = tmp_path / "real"
    real.mkdir()
    target = real / "copy.yaml"
    target.write_text("model: default\n", encoding="utf-8")
    original = target.read_bytes()
    if hazard == "target":
        linked = tmp_path / "linked.yaml"
        linked.symlink_to(target)
        target = linked
    elif hazard == "parent":
        linked = tmp_path / "linked"
        linked.symlink_to(real, target_is_directory=True)
        target = linked / "copy.yaml"
    elif hazard == "backup":
        target.with_name(target.name + ".brain-mcp.bak").symlink_to(target)
    elif hazard == "hardlink":
        os.link(target, real / "another.yaml")
    with pytest.raises((ValueError, FileExistsError)):
        merge_copy(target, {"mcp_servers": {"brain": {}}})
    assert target.read_bytes() == original


def test_merge_rejects_concurrent_replacement(tmp_path, monkeypatch):
    import wiki_app.hermes_setup as setup
    target = tmp_path / "config.yaml"
    target.write_text("model: original\n", encoding="utf-8")
    original_mkstemp = setup.tempfile.mkstemp

    def replace_before_commit(*args, **kwargs):
        replacement = tmp_path / "replacement.yaml"
        replacement.write_text("model: concurrent\n", encoding="utf-8")
        os.replace(replacement, target)
        return original_mkstemp(*args, **kwargs)

    monkeypatch.setattr(setup.tempfile, "mkstemp", replace_before_commit)
    with pytest.raises(ValueError):
        merge_copy(target, {"mcp_servers": {"brain": {}}})
    assert yaml.safe_load(target.read_bytes())["model"] == "concurrent"


def test_tools_have_no_external_or_write_calls():
    import ast
    source = Path(__file__).resolve().parents[1] / "wiki_app/brain_mcp.py"
    tree = ast.parse(source.read_text())
    forbidden = {"write_text", "write_bytes", "unlink", "mkdir", "touch", "record_access",
                 "run", "Popen", "post", "get", "append_episode"}
    # server.run starts stdio; dict.get reads metadata. No other write/network/model call exists.
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "run":
                assert isinstance(node.func.value, ast.Name) and node.func.value.id == "server"
            elif node.func.attr != "get":
                assert node.func.attr not in forbidden
