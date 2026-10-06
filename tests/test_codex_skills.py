"""Codex 에서도 Claude Code 와 같은 이름의 llm-brain 명령을 쓸 수 있는지 지킨다.

2026-10-06: 저장소에는 Claude Code 슬래시 명령 7개(`commands/*.md`)만 있고 Codex 에는 등록된 명령이 없어
수강생이 Codex 로 하면 매번 자연어로 풀어 써야 했다. Codex 는 저장소의 `.agents/skills/<이름>/SKILL.md` 를
자동으로 스킬로 인식하므로(Codex 0.160.0 에서 실측), 명령마다 같은 이름의 스킬을 둔다.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
COMMANDS = sorted(p.stem for p in (ROOT / "commands").glob("*.md"))
SKILLS_DIR = ROOT / ".agents" / "skills"


def _frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, flags=re.S)
    assert match, f"{path} 에 머리말이 없다"
    meta = {}
    for line in match.group(1).splitlines():
        if re.match(r"^[A-Za-z_-]+:", line):
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta


def test_every_claude_command_has_a_codex_skill_and_nothing_extra():
    """깨지면: 새 슬래시 명령을 추가해도 Codex 수강생은 쓸 수 없는 채로 배포된다(이번 누락과 같은 일)."""
    skill_names = sorted(p.parent.name.removeprefix("llm-brain-") for p in SKILLS_DIR.glob("llm-brain-*/SKILL.md"))
    assert skill_names == COMMANDS


@pytest.mark.parametrize("command", COMMANDS)
def test_skill_is_a_valid_codex_skill_that_points_to_the_command_file(command):
    path = SKILLS_DIR / f"llm-brain-{command}" / "SKILL.md"
    meta = _frontmatter(path)
    assert meta["name"] == f"llm-brain-{command}"        # 폴더 이름과 같아야 `$이름` 으로 부를 수 있다
    assert len(meta["name"]) <= 64                         # Codex 가 이름 길이 64자를 넘으면 로드하지 않는다
    assert len(meta["description"]) >= 20                  # 설명이 있어야 자연어 요청에서 스킬이 골라진다
    body = path.read_text(encoding="utf-8")
    assert f"commands/{command}.md" in body                # 절차의 정본은 commands/ 한 곳이다
    assert "AGENTS.md" in body


def test_curate_skill_defaults_to_audit_and_okf_skill_requires_a_dry_run():
    """위험한 기본값을 막는 안전 문구가 사라지면 Codex 가 위키를 고치거나 공개 export 를 해 버릴 수 있다."""
    curate = (SKILLS_DIR / "llm-brain-curate" / "SKILL.md").read_text(encoding="utf-8")
    okf = (SKILLS_DIR / "llm-brain-okf" / "SKILL.md").read_text(encoding="utf-8")
    assert "--audit" in curate and "--distill" in curate
    assert "--dry-run" in okf and "승인" in okf
