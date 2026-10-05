"""AGENTS.md 가드레일 7~9가 코드와 어긋나지 않는지 검증한다.

에이전트가 실제로 따르는지는 문서 단언으로 알 수 없다(2026-10-05 에이전트 실행 비교로 따로 확인).
여기서는 문서가 코드의 사실을 따라가는지, 그리고 규칙이 지워지지 않는지만 지킨다.
"""

import re
from pathlib import Path

from scripts.lib.claim_ledger import _UNTRUSTED_DIR_MARKERS

ROOT = Path(__file__).resolve().parents[1]
AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")


def _guardrail(number: int) -> str:
    match = re.search(rf"^{number}\. (.+)$", AGENTS, flags=re.MULTILINE)
    assert match, f"AGENTS.md에 가드레일 {number}번이 없다"
    return match.group(1)


def test_chat_answers_exclude_the_same_untrusted_folders_as_the_web_answer():
    # 코드가 untrusted 폴더를 늘렸는데 문서가 그대로면, 웹 AI 답변은 거절하는 글을
    # 에이전트가 대화에서 요약해 주는 어긋남이 다시 생긴다.
    rule = _guardrail(8)
    for marker in _UNTRUSTED_DIR_MARKERS:
        assert f"raw{marker}" in rule, f"가드레일 8번에 raw{marker} 가 없다"
    assert "--note" in rule  # 거절만 하면 사용자가 막힌다: 대안 경로를 함께 안내한다


def test_deletion_scope_is_user_data_and_excludes_repository_code():
    # "저장소 전체에서 지워 줘"가 tests/ 같은 추적 파일을 고치지 않게 하는 규칙이다.
    rule = _guardrail(7)
    for user_data in ("raw/", "wiki/", "claims.jsonl", "episodes/"):
        assert user_data in rule
    for repo_code in ("scripts/", "tests/"):
        assert repo_code in rule


def test_installing_packages_waits_for_user_approval():
    rule = _guardrail(9)
    assert "uv sync --extra" in rule  # OCR 선택 설치가 실제 사례였다
    assert "승인" in rule
