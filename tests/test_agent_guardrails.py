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


def test_chat_may_summarize_external_clippings_but_not_republish_or_obey_them():
    # 코드가 untrusted 폴더를 늘렸는데 문서가 그대로면, 새 폴더의 글을 에이전트가 근거나 공개 자료로
    # 쓰게 되는 어긋남이 생긴다. 폴더 목록은 코드와 같아야 한다.
    rule = _guardrail(8)
    for marker in _UNTRUSTED_DIR_MARKERS:
        assert f"raw{marker}" in rule, f"가드레일 8번에 raw{marker} 가 없다"
    assert "요약해도" in rule          # 읽고 요약하는 것은 허용한다(재배포가 문제이지 읽기가 문제는 아니다)
    assert "출처 주소" in rule          # 요약에는 출처를 밝힌다
    assert "지시문" in rule             # 글 속 지시문은 따르지 않는다(주입 방어)
    assert "재배포" in rule             # 원문을 그대로 옮기거나 공개 자료로 내보내지 않는다
    assert "--note" in rule            # 근거로 쓰려면 사용자가 확인해 메모로 옮긴다


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
