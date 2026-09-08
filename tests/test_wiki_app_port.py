"""test_wiki_app_port — 화면을 어느 번호로 여는가.

학생 노트북에서 8000 번은 흔히 이미 쓰이고 있다(Jupyter·다른 실습 서버·Docker).
그때 서버가 그냥 죽으면 학생이 보는 것은 "왜 안 뜨지"뿐이다.
"""
import socket

from wiki_app.__main__ import pick_port


def _hold(port: int):
    """그 번호를 실제로 붙잡고 있는 소켓을 돌려준다."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port))
    s.listen(1)
    return s


def _free_port() -> int:
    """지금 비어 있는 번호 하나."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_uses_the_default_when_it_is_free():
    """비어 있으면 그 번호를 그대로 쓴다.

    깨지면: 아무 문제 없는 학생도 매번 다른 주소로 들어가야 해서,
    교재에 적힌 localhost:8000 이 틀린 안내가 된다.
    """
    port = _free_port()
    assert pick_port(port, 5) == port


def test_moves_to_the_next_port_when_the_default_is_taken():
    """이미 쓰이고 있으면 다음 번호로 옮긴다.

    깨지면: Jupyter 를 켜 둔 학생(수업에서 흔하다)은 화면을 아예 못 연다.
    """
    port = _free_port()
    held = _hold(port)
    try:
        assert pick_port(port, 5) == port + 1
    finally:
        held.close()


def test_returns_none_when_everything_is_taken():
    """다 막혔으면 조용히 실패하지 않고 None 을 돌려준다.

    깨지면: 열 자리가 모두 막힌 상황에서 무엇이 잘못됐는지 아무도 모른 채
    서버가 죽는다. 호출부가 이걸 받아 안내 문구를 띄운다.
    """
    port = _free_port()
    held = [_hold(port)]
    try:
        try:
            held.append(_hold(port + 1))
        except OSError:
            pass
        n = len(held)
        assert pick_port(port, n) is None
    finally:
        for s in held:
            s.close()
