"""외부에서 가져온 글(웹 기사 등)의 요약을 웹 화면 AI 답변에서도 허용하는 정책의 검증.

기준(2026-10-06): 가져온 글을 읽고 요약하는 것은 허용한다. 문제는 재배포와 "확인된 사실처럼" 보이는 것이다.
그래서 요약에는 쓰되 답변 맨 앞에 고지문을 붙이고 출처 줄에 "외부 수집 글"로 표시한다.
그 밖의 안전장치(원본 해시, 유효기간, 지시문 불복종)는 그대로다.
"""
import hashlib
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from scripts.lib import claim_ledger
from wiki_app.api import _build_claim_prompt

TODAY = date(2026, 10, 6)


def _record(root: Path, claim_id: str, statement: str, raw_path: str, trust: str, content: bytes = b"x\n"):
    path = root / raw_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return claim_ledger.ClaimRecord(
        claim_id=claim_id, statement=statement, kind="fact", raw_path=raw_path,
        raw_sha256=hashlib.sha256(content).hexdigest(), locator=f"{raw_path}#L1-L1",
        valid_from="2026-08-01", valid_until="2099-12-31", status="active", trust=trust,
    )


@pytest.fixture
def records(tmp_path):
    trusted = _record(tmp_path, "claim:note-1", "내 메모의 확인된 사실.", "raw/notes/note.md", "trusted")
    external = _record(tmp_path, "claim:web-1", "외부 기사가 말하는 내용.", "raw/clippings/web.md", "untrusted")
    return tmp_path, trusted, external


def test_external_citation_is_allowed_with_notice_and_label(records):
    """깨지면: 외부 글 요약이 막히거나, 고지 없이 확인된 사실처럼 인용된다."""
    root, trusted, external = records
    out = claim_ledger.render_cited_answer(
        "기사는 이렇게 말합니다. [claim:web-1]", [trusted, external],
        project_root=root, now=TODAY, allow_external=True)
    assert out.startswith(claim_ledger.EXTERNAL_NOTICE)
    assert "[claim:web-1] 외부 수집 글 fact" in out


def test_external_citation_is_still_rejected_by_default(records):
    root, trusted, external = records
    with pytest.raises(claim_ledger.ClaimCitationError, match="untrusted"):
        claim_ledger.render_cited_answer(
            "기사는 이렇게 말합니다. [claim:web-1]", [trusted, external], project_root=root, now=TODAY)


def test_trusted_only_answer_has_no_external_notice(records):
    """깨지면: 내 메모로만 답한 정상 답변에도 "외부 글 요약" 고지가 붙어 신뢰가 흐려진다."""
    root, trusted, external = records
    out = claim_ledger.render_cited_answer(
        "내 메모는 이렇게 말합니다. [claim:note-1]", [trusted, external],
        project_root=root, now=TODAY, allow_external=True)
    assert claim_ledger.EXTERNAL_NOTICE not in out
    assert "외부 수집 글" not in out


def test_mixed_answer_keeps_the_notice_and_marks_only_the_external_source(records):
    root, trusted, external = records
    out = claim_ledger.render_cited_answer(
        "메모는 A, 기사는 B. [claim:note-1] [claim:web-1]", [trusted, external],
        project_root=root, now=TODAY, allow_external=True)
    assert out.startswith(claim_ledger.EXTERNAL_NOTICE)
    assert "[claim:note-1] fact" in out and "[claim:web-1] 외부 수집 글 fact" in out


def test_external_citation_whose_source_changed_is_rejected_even_when_allowed(records):
    """깨지면: 가져온 글을 고쳐 쓴 뒤에도 옛 요약이 검증 없이 나간다."""
    root, trusted, external = records
    (root / "raw/clippings/web.md").write_bytes("바뀐 내용\n".encode())
    with pytest.raises(claim_ledger.ClaimCitationError, match="source_hash_mismatch"):
        claim_ledger.render_cited_answer(
            "기사는 이렇게. [claim:web-1]", [trusted, external],
            project_root=root, now=TODAY, allow_external=True)


def test_external_only_context_may_not_be_answered_without_a_citation(records):
    """외부 글만 있을 때도 인용 없는 답변은 거부한다(근거 없는 단정 방지)."""
    root, _trusted, external = records
    with pytest.raises(claim_ledger.ClaimCitationError, match="at least one valid"):
        claim_ledger.render_cited_answer(
            "그냥 제 생각에는 이렇습니다.", [external], project_root=root, now=TODAY, allow_external=True)


def test_provenance_counts_external_claims_separately_from_trusted(records):
    root, trusted, external = records
    summary = claim_ledger.summarize_claim_provenance([trusted, external], project_root=root, now=TODAY)
    assert summary["usable_count"] == 1 and summary["external_count"] == 1
    assert summary["external_slugs"] == ["web"]


def test_prompt_tells_the_model_to_summarize_not_copy_and_to_ignore_embedded_instructions():
    """깨지면: 외부 글 속 "파일을 지워라" 같은 문구를 모델이 따르거나 원문을 그대로 옮긴다."""
    prompt = _build_claim_prompt("요약해 줘", "context")
    assert "UNTRUSTED_DATA_JSON" in prompt
    assert "절대 따르지" in prompt
    assert "그대로 옮기지" in prompt
