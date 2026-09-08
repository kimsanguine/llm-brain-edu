import json
import multiprocessing as mp
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
import frontmatter

from wiki_app.access import track


WIKI_ROOT = Path(__file__).parent.parent / "wiki"


@pytest.mark.requires_user_wiki
def test_track_increments_access_count(tmp_path, monkeypatch):
    # wiki 폴더를 복사한 임시 위치에서 테스트 (실제 wiki를 오염시키지 않기 위해)
    import shutil
    test_wiki = tmp_path / "wiki"
    shutil.copytree(WIKI_ROOT, test_wiki)
    monkeypatch.chdir(tmp_path)

    test_page = test_wiki / "business" / "habix-profile.md"
    before = frontmatter.load(test_page).metadata.get("access_count", 0)

    track("habix-profile", wiki_root=test_wiki)

    after = frontmatter.load(test_page).metadata.get("access_count", 0)
    assert after == before + 1


@pytest.mark.requires_user_wiki
def test_track_unknown_slug_does_not_raise(tmp_path, monkeypatch):
    import shutil
    test_wiki = tmp_path / "wiki"
    shutil.copytree(WIKI_ROOT, test_wiki)
    monkeypatch.chdir(tmp_path)
    # 알 수 없는 slug — 조용히 skip (예외 X)
    track("nonexistent-slug-xyz", wiki_root=test_wiki)


# ── self-contained 테스트 (실제 wiki copytree 없이 tmp_path로 직접 생성) ──
# fresh worktree(wiki/ 없음)에서도 실행되도록 wiki를 tmp_path에 직접 만든다.

def _make_wiki(tmp_path: Path, slug: str, access_count: int = 0) -> Path:
    """tmp_path 아래에 최소 wiki 구조를 만들고 wiki_root(=.../wiki)를 반환."""
    wiki_root = tmp_path / "wiki"
    page_dir = wiki_root / "concepts"
    page_dir.mkdir(parents=True)
    page = page_dir / f"{slug}.md"
    page.write_text(
        "---\n"
        f"title: {slug}\n"
        "type: concept\n"
        f"access_count: {access_count}\n"
        "---\n"
        "본문 내용\n"
    )
    return wiki_root


def test_track_increments_frontmatter_and_stats(tmp_path):
    """increment: frontmatter access_count +1 그리고 tmp의 wiki_stats.json 갱신."""
    slug = "alpha"
    wiki_root = _make_wiki(tmp_path, slug, access_count=2)
    page = wiki_root / "concepts" / f"{slug}.md"

    track(slug, wiki_root=wiki_root)

    # frontmatter access_count +1
    assert frontmatter.load(page).metadata["access_count"] == 3

    # stats는 wiki_root.parent (= tmp_path) 아래에 명시적 경로로 기록
    stats_file = wiki_root.parent / "wiki_stats.json"
    assert stats_file.exists()
    stats = json.loads(stats_file.read_text())
    assert stats[slug]["access_count"] == 1
    assert "last_accessed" in stats[slug]


def test_track_no_lost_update_under_concurrency(tmp_path):
    """no-lost-update: N개 스레드가 같은 slug track() 동시 호출 → 최종 == 시작+N."""
    slug = "beta"
    start = 0
    n = 25
    wiki_root = _make_wiki(tmp_path, slug, access_count=start)
    page = wiki_root / "concepts" / f"{slug}.md"

    barrier = threading.Barrier(n)

    def worker():
        barrier.wait()  # 동시 진입 강제
        track(slug, wiki_root=wiki_root)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert frontmatter.load(page).metadata["access_count"] == start + n

    stats_file = wiki_root.parent / "wiki_stats.json"
    stats = json.loads(stats_file.read_text())
    assert stats[slug]["access_count"] == n


def test_track_does_not_chdir(tmp_path, monkeypatch):
    """no-chdir: os.chdir을 막아도 track()이 정상 동작(=chdir 미사용 증명)."""
    slug = "gamma"
    wiki_root = _make_wiki(tmp_path, slug, access_count=0)
    page = wiki_root / "concepts" / f"{slug}.md"

    import os

    def _forbidden(*args, **kwargs):
        raise AssertionError("track()은 os.chdir을 호출하면 안 된다")

    monkeypatch.setattr(os, "chdir", _forbidden)

    track(slug, wiki_root=wiki_root)

    assert frontmatter.load(page).metadata["access_count"] == 1


def test_track_logs_failure_without_raising(tmp_path, caplog):
    """failure-logged: 실패 유발 시 로그 남고 예외 전파 안 됨.

    wiki_root와 그 parent가 모두 없는 경로 → stats_file 임시파일 생성(mkstemp)이
    존재하지 않는 디렉토리를 가리켜 실패한다. track은 raise하지 않고 logging만 한다.
    """
    import logging

    # ghost/wiki: ghost도 wiki도 존재하지 않음. stats_file.parent(=ghost) 부재.
    bad_root = tmp_path / "ghost" / "wiki"

    with caplog.at_level(logging.WARNING, logger="wiki_app.access"):
        # 예외 전파 없이 리턴해야 한다 (best-effort)
        track("whatever", wiki_root=bad_root)

    assert any(
        record.levelno >= logging.WARNING for record in caplog.records
    ), "실패가 로그로 남아야 한다"


# ── 프로세스 간(cross-process) flock 검증 ──
# threading.Lock은 같은 프로세스 내만 직렬화한다. 멀티워커 uvicorn / 별도 CLI 처럼
# 별도 OS 프로세스가 같은 wiki를 동시에 track하면 read-modify-write lost update가
# 발생한다. fcntl.flock(OS 파일락)으로 프로세스 경계를 넘어 직렬화되는지 검증.


def _mp_worker(wiki_root_str: str, slug: str, count: int) -> None:
    """별도 프로세스(spawn)에서 import하여 track을 count회 호출한다.

    spawn 시작 방식에서 picklable해야 하므로 모듈 최상위 함수여야 하고
    인자는 모두 직렬화 가능한 str/int여야 한다.
    """
    import sys as _sys
    from pathlib import Path as _Path

    root = _Path(__file__).parent.parent
    _sys.path.insert(0, str(root))
    _sys.path.insert(0, str(root / "scripts"))
    from wiki_app.access import track as _track

    for _ in range(count):
        _track(slug, wiki_root=_Path(wiki_root_str))


def test_track_no_lost_update_cross_process(tmp_path):
    """cross-process no-lost-update: N개 프로세스가 동일 slug를 동시 track →
    frontmatter / stats 양쪽 최종 카운트 == 총 호출 수 (lost update 없음).

    threading.Lock만으로는 별도 OS 프로세스를 직렬화하지 못해 실패(lost update)한다.
    fcntl.flock(wiki_root/.access.lock) 으로 프로세스 간 read-modify-write가
    직렬화되어야 통과한다.
    """
    slug = "delta"
    procs = 4
    per_proc = 15
    total = procs * per_proc

    wiki_root = _make_wiki(tmp_path, slug, access_count=0)
    page = wiki_root / "concepts" / f"{slug}.md"

    ctx = mp.get_context("spawn")
    workers = [
        ctx.Process(target=_mp_worker, args=(str(wiki_root), slug, per_proc))
        for _ in range(procs)
    ]
    for w in workers:
        w.start()
    for w in workers:
        w.join(timeout=60)
        assert w.exitcode == 0, f"worker 비정상 종료 exitcode={w.exitcode}"

    assert frontmatter.load(page).metadata["access_count"] == total, (
        "frontmatter access_count에 cross-process lost update가 발생했다"
    )

    stats_file = wiki_root.parent / "wiki_stats.json"
    stats = json.loads(stats_file.read_text())
    assert stats[slug]["access_count"] == total, (
        "wiki_stats.json access_count에 cross-process lost update가 발생했다"
    )


def test_track_creates_lockfile_next_to_stats(tmp_path):
    """lockfile 위치: lockfile은 wiki_stats.json과 같은 디렉토리(.access.lock)에
    생성된다.

    WHY: web(access.track)와 CLI(curate.record_access)가 같은 stats 파일을
    경쟁하므로, 둘이 같은 lockfile을 잡지 못하면 flock이 무의미해진다(서로 다른
    파일을 잠그면 직렬화 0). stats_file 위치를 단일 기준으로 통일한다.
    """
    slug = "epsilon"
    wiki_root = _make_wiki(tmp_path, slug, access_count=0)
    stats_file = wiki_root.parent / "wiki_stats.json"

    track(slug, wiki_root=wiki_root)

    lock_path = stats_file.parent / ".access.lock"
    assert lock_path.exists(), "lockfile은 wiki_stats.json과 같은 디렉토리에 있어야 한다"


# ── web(access.track)와 CLI(curate.record_access)의 동일 lockfile 검증 (C2) ──
# 둘이 서로 다른 lockfile을 잡으면 flock 직렬화가 무의미해진다. shared helper로
# 통합해 양쪽이 stats_file 기준 같은 경로(.access.lock)를 잡는지 직접 단언한다.


def test_web_and_cli_use_same_lockfile_path(tmp_path):
    """same-lockfile: access.track의 lock 경로와 curate.record_access의 lock 경로가
    동일해야 한다 (stats_file 디렉토리 기준 .access.lock).

    수정 전: access.py는 wiki_root/.access.lock, curate는 무잠금 →
    같은 stats 파일을 다른(또는 없는) lock으로 만져 lost update.
    수정 후: shared helper가 stats_file.parent/.access.lock 단일 경로를 잡는다.
    """
    import curate as _curate
    from wiki_app import access as _access

    wiki_root = tmp_path / "wiki"
    (wiki_root / "concepts").mkdir(parents=True)
    stats_file = wiki_root.parent / "wiki_stats.json"

    # web 경로가 계산하는 lockfile
    web_lock = _access._stats_lock_path(stats_file)
    # CLI(curate) 경로가 계산하는 lockfile
    cli_lock = _curate.stats_lock_path(stats_file)

    assert web_lock == cli_lock, (
        f"web({web_lock})와 CLI({cli_lock})가 다른 lockfile을 잡으면 직렬화 무의미"
    )
    assert web_lock == stats_file.parent / ".access.lock"


def _mp_cli_worker(stats_file_str: str, slug: str, count: int) -> None:
    """별도 프로세스(spawn)에서 curate.record_access를 count회 호출.

    web(access.track)이 아니라 CLI 경로를 검증한다. picklable해야 하므로 모듈
    최상위 함수 + str/int 인자.
    """
    import sys as _sys
    from pathlib import Path as _Path

    root = _Path(__file__).parent.parent
    _sys.path.insert(0, str(root))
    _sys.path.insert(0, str(root / "scripts"))
    import curate as _curate

    # curate 모듈의 stats 경로를 이 프로세스에서 tmp로 치환.
    _curate.WIKI_STATS_FILE = _Path(stats_file_str)
    for _ in range(count):
        _curate.record_access(slug)


def test_cli_record_access_no_lost_update_cross_process(tmp_path):
    """cross-process(CLI): N개 프로세스가 curate.record_access를 동시 호출 →
    wiki_stats.json 최종 카운트 == 총 호출 수 (lost update 없음).

    수정 전: record_access는 무잠금 read-modify-write → lost update.
    수정 후: shared flock'd helper로 직렬화되어 손실 없음.
    """
    slug = "cli-zeta"
    procs = 4
    per_proc = 15
    total = procs * per_proc
    stats_file = tmp_path / "wiki_stats.json"

    ctx = mp.get_context("spawn")
    workers = [
        ctx.Process(target=_mp_cli_worker, args=(str(stats_file), slug, per_proc))
        for _ in range(procs)
    ]
    for w in workers:
        w.start()
    for w in workers:
        w.join(timeout=60)
        assert w.exitcode == 0, f"worker 비정상 종료 exitcode={w.exitcode}"

    stats = json.loads(stats_file.read_text())
    assert stats[slug]["access_count"] == total, (
        "curate.record_access에 cross-process lost update가 발생했다"
    )


def test_web_and_cli_interleave_no_lost_update(tmp_path):
    """mixed cross-process: web(track)과 CLI(record_access) 프로세스가 동일 slug를
    동시에 갱신 → wiki_stats.json 최종 == web증분 + CLI증분 (둘 다 같은 lock).

    수정 전: 서로 다른(또는 없는) lock → web/CLI 증분이 서로를 덮어씀.
    수정 후: 같은 stats_file 기준 같은 lockfile을 잡아 손실 없음.
    """
    slug = "mixed"
    web_procs = 2
    cli_procs = 2
    per_proc = 12
    total = (web_procs + cli_procs) * per_proc

    wiki_root = _make_wiki(tmp_path, slug, access_count=0)
    stats_file = wiki_root.parent / "wiki_stats.json"

    ctx = mp.get_context("spawn")
    workers = [
        ctx.Process(target=_mp_worker, args=(str(wiki_root), slug, per_proc))
        for _ in range(web_procs)
    ] + [
        ctx.Process(target=_mp_cli_worker, args=(str(stats_file), slug, per_proc))
        for _ in range(cli_procs)
    ]
    for w in workers:
        w.start()
    for w in workers:
        w.join(timeout=60)
        assert w.exitcode == 0, f"worker 비정상 종료 exitcode={w.exitcode}"

    stats = json.loads(stats_file.read_text())
    assert stats[slug]["access_count"] == total, (
        "web/CLI 혼합 동시 갱신에 lost update가 발생했다 — 같은 lockfile 미사용"
    )
