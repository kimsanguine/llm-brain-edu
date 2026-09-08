"""test_pii — 개인정보가 섞였을 때 그 자리에서 알려 주는가.

이 도구를 쓰는 사람 중에는 병원 연구비 행정처럼 민감 자료를 다루는 직군이 있다.
README 와 교안이 "넣지 마세요"라고 이미 말하지만, 문서를 읽는 시점과 실수하는
시점이 다르다. 실수는 메모를 넣는 순간에 일어난다.

특히 LIVE 경로는 메모 본문을 그대로 외부 AI 서비스로 보낸다.
"""
import pytest

from lib.pii import find_pii, warn_if_pii


@pytest.mark.parametrize("text", [
    "연구원 주민번호 900101-1234567 확인",
    "주민등록번호 9001011234567 로 조회",  # 하이픈 없이 붙여 써도
    "카드 1234-5678-9012-3456 로 결제",
])
def test_catches_what_must_not_leave_the_laptop(text):
    """주민번호·카드번호가 있으면 찾아낸다.

    깨지면: 학생이 모르고 넣은 개인정보가 그대로 외부 AI 서비스로 전송되고,
    브레인 폴더를 공유하거나 GitHub 에 올릴 때 함께 나간다.
    """
    assert find_pii(text)


@pytest.mark.parametrize("text", [
    "과제 마감 3/14, 연구비는 분기별 정산",
    "지난주 CTR 2.1%, 소재 B 가 1.4배",
    "회의 결정: 재시도는 2회까지",
    "버전 2026-01-24 기준 집계",
    "전화 주세요 010-1234-5678",  # 전화번호는 일부러 안 본다(오탐이 잦다)
])
def test_stays_quiet_for_ordinary_notes(text):
    """평범한 업무 메모에는 아무 말도 하지 않는다.

    깨지면: 매번 경고가 떠서 학생이 경고를 무시하는 습관이 든다.
    그러면 진짜 위험한 순간에도 안 읽는다.
    """
    assert find_pii(text) == []


def test_the_warning_never_prints_the_value_itself(capsys):
    """경고는 찾은 값을 되풀이해 출력하지 않는다.

    깨지면: 개인정보를 알리려다 터미널·로그에 한 번 더 남긴다.
    """
    warn_if_pii("주민번호 900101-1234567", "메모")
    out = capsys.readouterr().out
    assert "주민등록번호" in out
    assert "900101" not in out


def test_does_not_block_saving():
    """경고만 하고 막지는 않는다 — 무엇을 넣을지는 사람이 정한다.

    깨지면: "주민번호는 앞 6자리가 생년월일"처럼 정당한 설명 메모나
    테스트용 더미 값까지 저장이 거부된다.
    """
    assert warn_if_pii("주민번호 900101-1234567", "메모") == ["주민등록번호"]
