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


def test_course_runtime_uses_the_openai_api_key_everywhere_the_student_looks():
    # 수업 기본 키는 OpenAI API 키(OPENAI_API_KEY)다(D30).
    # 설정 파일, setup 스크립트, 수강생 안내 중 하나라도 옛 키 이름을 쓰면
    # 수강생은 안내대로 키를 넣고도 RULE 경로에 머물고, 이유를 찾지 못한다.
    config = (ROOT / "schema" / "config.yaml").read_text(encoding="utf-8")
    setup = (ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    guide = (ROOT / "README_수강생용.md").read_text(encoding="utf-8")

    for text in (config, setup):
        assert "engine: openai" in text
        assert "api_key_env: OPENAI_API_KEY" in text
        assert "base_url: https://api.openai.com/v1" in text
    for text in (config, setup, guide):
        assert "OPENROUTER" not in text
    assert "OPENAI_API_KEY" in guide


def test_student_opens_codex_only_after_the_folder_exists():
    # Codex 에 폴더를 열라고 안내하기 전에 내려받기가 먼저 나와야 한다.
    # 순서가 뒤집히면 문서를 위에서부터 따라 하는 수강생이 첫 단계에서 막힌다.
    guide = (ROOT / "README_수강생용.md").read_text(encoding="utf-8")

    clone = guide.index("git clone https://github.com/kimsanguine/llm-brain-edu.git")
    codex_request = guide.index("AGENTS.md를 읽고 따라 주세요")
    assert clone < codex_request


def test_public_readme_does_not_clone_twice():
    # 설치 절에서 이미 받은 폴더를 빠른 시작에서 다시 clone 하면 "already exists" 로 실패한다.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert readme.count("git clone https://github.com/kimsanguine/llm-brain-edu.git") == 1
