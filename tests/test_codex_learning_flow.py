"""수업의 필수 에이전트 경로가 Codex인지 검증한다."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_codex_has_a_model_neutral_project_instruction():
    instructions = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "Codex" in instructions
    assert "raw/" in instructions
    assert "근거" in instructions


def test_student_quickstart_uses_codex_without_claude_slash_commands():
    guide = (ROOT / "README_수강생용.md").read_text(encoding="utf-8")

    assert "Codex" in guide
    assert "/llm-brain:" not in guide


def test_public_readme_marks_codex_as_standard_and_claude_as_compatibility():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Codex" in readme
    assert "선택 호환" in readme
    assert "engine: openai" in readme


def test_setup_script_keeps_the_course_runtime_on_openrouter():
    setup = (ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")

    assert "engine: openai" in setup
    assert "OPENROUTER_API_KEY" in setup
