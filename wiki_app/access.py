"""access_count 갱신 — frontmatter + wiki_stats.json 원자적 동시 갱신.

curate.record_access는 import 시점에 절대경로(curate.WIKI_ROOT)로 바인딩되어
test 격리가 불가능하고 cwd 변경(os.chdir)이라는 전역 side-effect를 요구하므로
재사용하지 않는다. 대신 wiki_root에서 파생한 명시적 경로로 직접 갱신한다.
frontmatter 파싱/직렬화만 curate에서 재사용한다.

동시성: read-modify-write 유실(lost update)을 두 경계에서 막는다.
  1. threading.Lock      — 같은 프로세스 내 thread 직렬화 (uvicorn threadpool).
  2. fcntl.flock(LOCK_EX) — 별도 OS 프로세스 직렬화 (멀티워커 uvicorn / 별도 CLI /
     두 앱 프로세스). lockfile = wiki_stats.json과 같은 디렉토리의 .access.lock.
두 store(frontmatter·wiki_stats.json)는 같은 lock 안에서 함께 읽고 갱신한다.

lockfile 경로는 stats 파일 기준(_curate.stats_lock_path)으로 통일한다. web과
CLI(curate.record_access)가 같은 wiki_stats.json을 경쟁하므로, 둘이 같은 lockfile을
잡지 못하면 flock 직렬화가 무의미해지기 때문이다. wiki_stats 갱신 로직은
_curate.write_stats_access(shared helper)로 통합해 한 곳에서만 관리한다.
"""
from __future__ import annotations

import fcntl
import logging
import os
import sys
import threading
from pathlib import Path

# scripts/ 를 sys.path에 추가 (기존 컨벤션)
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import curate as _curate  # noqa: E402

logger = logging.getLogger(__name__)

# threadpool 동시 호출의 read-modify-write 유실 방지용 프로세스 전역 lock.
_LOCK = threading.Lock()


def _stats_lock_path(stats_file: Path) -> Path:
    """stats_file 기준 lockfile 경로. CLI(curate)와 동일 경로로 수렴해야 한다.

    curate.stats_lock_path에 위임해 web/CLI가 같은 단일 경로를 잡도록 보장한다.
    """
    return _curate.stats_lock_path(stats_file)


def track(slug: str, wiki_root: Path | None = None) -> None:
    """페이지 조회 시 access_count를 1 증가시킨다 (best-effort).

    - frontmatter(.md)와 wiki_stats.json을 둘 다 같은 lock 안에서 갱신한다.
    - wiki_stats.json 경로는 wiki_root.parent / "wiki_stats.json" (명시적, cwd 무관).
    - lockfile은 stats_file 기준(_stats_lock_path) — CLI(curate.record_access)와
      동일 경로라야 둘이 같은 lock으로 직렬화된다.
    - 동시성: threading.Lock(프로세스 내) + fcntl.flock(프로세스 간)을 함께 건다.
    - 실패는 caller로 raise하지 않고 logger.warning으로 남긴다.

    wiki_root 기본값은 _REPO_ROOT / "wiki" (test에서는 tmp 경로 지정).
    """
    if wiki_root is None:
        wiki_root = _REPO_ROOT / "wiki"
    stats_file = wiki_root.parent / "wiki_stats.json"

    with _LOCK:
        try:
            with _cross_process_lock(stats_file):
                # 같은 lock 안에서 두 store를 함께 읽고 갱신해 lost update 방지.
                # stats 갱신은 curate의 shared core(write_stats_access)에 위임한다.
                _update_frontmatter_access(slug, wiki_root)
                _curate.write_stats_access(slug, stats_file)
        except Exception:
            logger.warning("access track 실패 (slug=%s)", slug, exc_info=True)


class _cross_process_lock:
    """stats_file과 같은 디렉토리의 .access.lock 에 fcntl.flock(LOCK_EX)을 거는 CM.

    별도 OS 프로세스(멀티워커 uvicorn / 별도 CLI)의 read-modify-write를 직렬화한다.
    flock은 advisory lock이라 같은 lockfile에 flock을 거는 프로세스끼리만 직렬화된다.
    web(여기)과 CLI(curate.update_stats_access)가 stats_file 기준 동일 경로를 쓰므로
    교차 직렬화가 성립한다. (Unix 전용; darwin 동작)

    lockfile은 빈 파일이므로 절대 truncate하지 않는다 — 데이터가 아니라 락 토큰이다.
    """

    def __init__(self, stats_file: Path) -> None:
        self._lock_path = _stats_lock_path(stats_file)
        self._fd: int | None = None

    def __enter__(self) -> "_cross_process_lock":
        # lockfile은 stats_file 디렉토리에 둔다. 그 디렉토리가 없으면 여기서 실패
        # → track이 로깅(best-effort)한다.
        self._fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None


def _update_frontmatter_access(slug: str, wiki_root: Path) -> None:
    """wiki_root 아래에서 slug에 해당하는 .md 파일을 찾아 access_count를 1 증가."""
    matches = list(wiki_root.rglob(f"{slug}.md"))
    if not matches:
        return
    page = matches[0]
    content = page.read_text(encoding="utf-8")
    fm, body = _curate.parse_frontmatter(content)
    fm["access_count"] = int(fm.get("access_count") or 0) + 1
    _curate._atomic_write_text(page, _curate.serialize_frontmatter(fm, body))
