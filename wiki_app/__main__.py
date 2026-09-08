"""uv run python -m wiki_app — 브라우저에서 볼 화면을 띄운다.

기본은 8000 번이다. 그 번호를 다른 프로그램(Jupyter·다른 실습 서버 등)이 이미
쓰고 있으면 빈 번호를 찾아 열고, 어느 주소로 들어가면 되는지 알려 준다.
"""
import os
import socket

import uvicorn

from wiki_app.api import create_app

DEFAULT_PORT = 8000
TRIES = 10


def _is_free(port: int) -> bool:
    """그 번호를 지금 쓸 수 있는지 실제로 잡아 본다."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def pick_port(start: int = DEFAULT_PORT, tries: int = TRIES) -> int | None:
    """start 부터 차례로 빈 번호를 찾는다. 다 막혔으면 None."""
    for port in range(start, start + tries):
        if _is_free(port):
            return port
    return None


def main():
    start = int(os.environ.get("BRAIN_PORT", DEFAULT_PORT))
    port = pick_port(start)

    if port is None:
        print(f"\n  {start}~{start + TRIES - 1} 번 자리가 모두 사용 중입니다.", flush=True)
        print("  다른 프로그램을 끄고 다시 실행하거나, 원하는 번호를 직접 정해 주세요:", flush=True)
        print("    BRAIN_PORT=9000 uv run python -m wiki_app\n", flush=True)
        raise SystemExit(1)

    if port != start:
        print(f"\n  {start} 번은 다른 프로그램이 쓰고 있어 {port} 번으로 엽니다.", flush=True)

    print(f"\n  브라우저에서 열어 보세요 →  http://localhost:{port}\n", flush=True)
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
