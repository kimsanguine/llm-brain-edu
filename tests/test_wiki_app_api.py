import asyncio
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient

import wiki_app.api as api_module
from wiki_app.api import create_app


WIKI_ROOT = Path(__file__).parent.parent / "wiki"


@pytest.fixture(scope="module")
def client():
    app = create_app(wiki_root=WIKI_ROOT)
    return TestClient(app)


@pytest.mark.requires_user_wiki
def test_api_index_returns_metadata(client):
    r = client.get("/api/index")
    assert r.status_code == 200
    data = r.json()
    assert data["total_pages"] >= 40
    assert "categories" in data


@pytest.mark.requires_user_wiki
def test_api_search_returns_results(client):
    r = client.get("/api/search", params={"q": "habix"})
    assert r.status_code == 200
    data = r.json()
    assert data["query"] == "habix"
    assert data["total"] > 0
    slugs = [r["slug"] for r in data["results"]]
    assert "habix-profile" in slugs


def test_api_search_empty_query(client):
    r = client.get("/api/search", params={"q": ""})
    assert r.status_code == 200
    assert r.json()["total"] == 0


@pytest.mark.requires_user_wiki
def test_api_page_returns_html_and_metadata(client):
    r = client.get("/api/page/habix-profile")
    assert r.status_code == 200
    data = r.json()
    assert data["slug"] == "habix-profile"
    assert "<h1>" in data["html"]
    assert "frontmatter" in data
    assert "inbound" in data
    assert "outbound" in data


def test_api_page_unknown_slug_404(client):
    r = client.get("/api/page/nonexistent-xyz")
    assert r.status_code == 404


def test_api_ai_answer_contract(client):
    """AI endpoint의 응답 contract만 검증 (실제 LLM 응답은 환경별).

    Local (claude CLI 있음) → status=done + answer 비어있지 않음 (10-30s)
    CI    (claude CLI 없음) → status=unavailable (즉시)
    """
    r = client.post("/api/ai-answer", json={
        "question": "ping",
        "context_slugs": [],
    })
    assert r.status_code == 200
    data = r.json()
    assert data["status"] in ("done", "abstained", "unavailable", "timeout", "error")
    assert "answer" in data
    assert "sources" in data
    assert data["question"] == "ping"


# ---------------------------------------------------------------------------
# self-contained 엔드포인트 회귀 (tmp_path — 사용자 wiki 무의존)
# ---------------------------------------------------------------------------


def _build_project(tmp_path, *, with_index: bool, with_graph: bool):
    """tmp_path 안에 wiki_root + (옵션) index.md + (옵션) graph.json 구조.

    create_app/Index.build 가 wiki_root.parent/index.md 를 읽으므로 그 레이아웃 재현.
    반환: wiki_root Path.
    """
    project_root = tmp_path / "proj"
    wiki_root = project_root / "wiki"
    (wiki_root / "concepts").mkdir(parents=True)
    (wiki_root / "concepts" / "alpha.md").write_text(
        "---\ntitle: Alpha\ntags: [misc]\n---\n# Alpha\n\n본문.\n"
    )
    if with_index:
        (project_root / "index.md").write_text(
            "## concepts/ (1개)\n- [[alpha]] — 알파 페이지\n"
        )
    if with_graph:
        import json as _json
        (wiki_root / "graph.json").write_text(_json.dumps({
            "nodes": [{"id": "alpha", "kind": "page", "title": "Alpha",
                       "category": "concepts", "inbound": 0, "outbound": 0}],
            "links": [],
        }))
    return wiki_root


# --- 과제 1 회귀: index.md 부재가 create_app 부팅을 크래시시키지 않는다 ---
# WHY: Index.build 가 wiki_root.parent/index.md 를 무조건 읽어 부재 시
# FileNotFoundError 로 부팅이 죽었다. 부재 시 빈 인덱스로 graceful 부팅해야 한다.


def test_create_app_boots_without_index_md(tmp_path):
    wiki_root = _build_project(tmp_path, with_index=False, with_graph=False)

    # create_app 가 예외 없이 끝나야 한다 (부팅 크래시 금지).
    app = create_app(wiki_root=wiki_root)
    client = TestClient(app)

    r = client.get("/api/index")
    assert r.status_code == 200
    # index.md 가 없으면 slug 소스가 없어 0 페이지.
    assert r.json()["total_pages"] == 0


def test_search_endpoint_empty_index_returns_no_results(tmp_path):
    # index.md 부재 → 빈 인덱스 → 검색은 크래시 없이 빈 결과.
    wiki_root = _build_project(tmp_path, with_index=False, with_graph=False)
    client = TestClient(create_app(wiki_root=wiki_root))

    r = client.get("/api/search", params={"q": "alpha"})
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_page_display_and_search_preserve_raw_wiki_bytes_and_access_files(tmp_path):
    """Display/search are read paths; access tracking requires an explicit action."""
    wiki_root = _build_project(tmp_path, with_index=True, with_graph=False)
    project_root = wiki_root.parent
    raw_root = project_root / "raw"
    (raw_root / "notes").mkdir(parents=True)
    (raw_root / "notes" / "alpha.md").write_bytes(b"PRIVATE SOURCE\n")

    def snapshot():
        return {
            str(path.relative_to(project_root)): path.read_bytes()
            for root in (raw_root, wiki_root)
            for path in root.rglob("*")
            if path.is_file()
        }

    before = snapshot()
    client = TestClient(create_app(wiki_root=wiki_root))

    page_response = client.get("/api/page/alpha")
    search_response = client.get("/api/search", params={"q": "alpha"})

    assert page_response.status_code == 200
    assert page_response.json()["slug"] == "alpha"
    assert search_response.status_code == 200
    assert search_response.json()["total"] == 1
    assert snapshot() == before
    assert not (project_root / "wiki_stats.json").exists()
    assert not (project_root / ".access.lock").exists()


# --- 과제 2(a): /api/page/{slug}/graph 는 graph.json 부재 시 503 (현 분기 고정) ---
# WHY: api.py 는 graph.json 없으면 HTTPException(503) 를 던진다. 이 분기 동작을
# 회귀 테스트로 고정해, 의도치 않은 변경(예: 500 으로 떨어짐)을 잡는다.


def test_api_page_graph_returns_503_when_graph_json_missing(tmp_path):
    # graph.json 이 없는 wiki_root — graph 엔드포인트는 503 을 반환해야 한다.
    wiki_root = _build_project(tmp_path, with_index=True, with_graph=False)
    client = TestClient(create_app(wiki_root=wiki_root))

    r = client.get("/api/page/alpha/graph")
    assert r.status_code == 503


def test_api_page_graph_returns_neighborhood_when_graph_json_present(tmp_path):
    # 대비 경로: graph.json 이 있으면 503 이 아니라 center/neighbors/edges 를 준다.
    wiki_root = _build_project(tmp_path, with_index=True, with_graph=True)
    client = TestClient(create_app(wiki_root=wiki_root))

    r = client.get("/api/page/alpha/graph")
    assert r.status_code == 200
    data = r.json()
    assert data["center"]["slug"] == "alpha"
    assert "neighbors" in data
    assert "edges" in data


# ---------------------------------------------------------------------------
# subprocess lifecycle regression tests
#
# Codex [high]: claude -p subprocess가 timeout/disconnect/stream error 시
# kill()+wait() 되지 않아 좀비/누적이 발생. 아래 테스트는 fake proc 으로
# create_subprocess_exec 를 대체해 "endpoint 가 timeout/오류 경로를 탔을 때
# proc.kill() 이 호출되고 proc.wait() 가 await 되는지"를 검증한다.
# ---------------------------------------------------------------------------


class _FakeStreamReader:
    """asyncio.StreamReader 흉내 — readline 이 영원히 hang(스트림 hang 재현)."""

    def __init__(self, hang: bool = False, lines: list[bytes] | None = None):
        self._hang = hang
        self._lines = list(lines or [])

    async def readline(self) -> bytes:
        if self._hang:
            # claude hang 재현 — 깨어나지 않는 future 를 대기
            await asyncio.Future()
        if self._lines:
            return self._lines.pop(0)
        return b""

    async def read(self) -> bytes:
        return b""


class FakeProc:
    """asyncio subprocess 흉내. kill()/wait() 호출을 플래그로 추적."""

    def __init__(self, *, communicate_hang: bool = False, stdout_hang: bool = False,
                 stdout_lines: list[bytes] | None = None, returncode_after_wait: int = 0,
                 communicate_output: bytes = "관련 정보 없음".encode()):
        self.stdout = _FakeStreamReader(hang=stdout_hang, lines=stdout_lines)
        self.stderr = _FakeStreamReader(lines=[])
        self._communicate_hang = communicate_hang
        self._returncode_after_wait = returncode_after_wait
        self._communicate_output = communicate_output
        self.returncode = None
        self.killed = False
        self.waited = False

    async def communicate(self):
        if self._communicate_hang:
            await asyncio.Future()  # 영원히 hang → wait_for timeout 유발
        self.returncode = 0
        return (self._communicate_output, b"")

    def kill(self):
        self.killed = True

    async def wait(self):
        self.waited = True
        # kill 후 returncode 확정 (실제 proc 의미)
        if self.returncode is None:
            self.returncode = self._returncode_after_wait
        return self.returncode


@pytest.fixture
def patched_subprocess(monkeypatch):
    """shutil.which("claude") 가 존재하게 하고, create_subprocess_exec 를
    호출자가 주입한 FakeProc 으로 대체하는 헬퍼.

    반환: install(proc) — 해당 proc 을 사용하도록 패치하고 그 proc 을 돌려줌.
    """

    def install(proc: FakeProc) -> FakeProc:
        monkeypatch.setattr(api_module.shutil, "which", lambda name: "/usr/bin/claude")

        async def fake_exec(*args, **kwargs):
            return proc

        monkeypatch.setattr(api_module.asyncio, "create_subprocess_exec", fake_exec)
        return proc

    return install


def test_ai_answer_timeout_kills_and_waits_subprocess(
    trusted_client, patched_subprocess, monkeypatch
):
    """non-stream: communicate() 가 timeout 되면 endpoint 는 status=timeout 을
    반환하면서 child 를 kill() + wait() 해야 한다 (좀비 방지)."""
    proc = patched_subprocess(FakeProc(communicate_hang=True))

    # 90초 실제 대기 대신 wait_for 가 즉시 TimeoutError 를 던지게 함
    async def fast_wait_for(aw, timeout):
        # endpoint 의 communicate() 대기를 즉시 timeout 처리.
        # 넘겨받은 coroutine 은 닫아 RuntimeWarning 방지.
        if asyncio.iscoroutine(aw):
            aw.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(api_module.asyncio, "wait_for", fast_wait_for)

    r = trusted_client.post(
        "/api/ai-answer", json={"question": "ping", "context_slugs": ["alpha"]}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "timeout"

    # 핵심 단언: timeout 시 proc 정리
    assert proc.killed is True, "timeout 시 proc.kill() 이 호출되어야 함"
    assert proc.waited is True, "kill 후 proc.wait() 가 await 되어야 함"


def test_ai_answer_normal_does_not_leave_running_proc(trusted_client, patched_subprocess):
    """non-stream 정상 경로: 정상 종료한 proc 은 done 을 반환하고,
    이미 종료된 proc 에 대해 추가 kill 로 깨지지 않아야 한다."""
    proc = patched_subprocess(
        FakeProc(communicate_output=b"Alpha answer [claim:alpha-1].")
    )

    r = trusted_client.post(
        "/api/ai-answer", json={"question": "ping", "context_slugs": ["alpha"]}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "done"
    assert "[claim:alpha-1]" in data["answer"]
    # 정상 종료(returncode 설정됨) → 살아있지 않으므로 강제 kill 불필요
    assert proc.killed is False


def test_ai_answer_stream_hang_kills_and_waits_subprocess(
    trusted_client, patched_subprocess, monkeypatch
):
    """stream: readline() 이 영원히 hang 하면 idle/전체 timeout 후 proc 을
    kill() + wait() 하고 event: error 를 방출해야 한다."""
    proc = patched_subprocess(FakeProc(stdout_hang=True))

    real_wait_for = asyncio.wait_for

    async def fast_wait_for(aw, timeout):
        # stream readline 대기를 즉시 timeout 처리. 그 외 wait() 같은
        # 코루틴은 정상 대기시켜 정리 로직이 실제로 await 되게 함.
        if asyncio.iscoroutine(aw):
            # readline 코루틴만 timeout, 나머지는 실제 await
            name = getattr(getattr(aw, "cr_code", None), "co_name", "")
            if name == "readline":
                aw.close()
                raise asyncio.TimeoutError()
            return await real_wait_for(aw, timeout)
        return await real_wait_for(aw, timeout)

    monkeypatch.setattr(api_module.asyncio, "wait_for", fast_wait_for)

    with trusted_client.stream("POST", "/api/ai-answer/stream",
                               json={"question": "ping", "context_slugs": ["alpha"]}) as r:
        body = r.read().decode("utf-8")

    # 핵심 단언: stream hang 시 proc 정리
    assert proc.killed is True, "stream timeout 시 proc.kill() 이 호출되어야 함"
    assert proc.waited is True, "stream timeout 후 proc.wait() 가 await 되어야 함"
    assert "event: error" in body, "hang 시 event: error 를 방출해야 함"


# ---------------------------------------------------------------------------
# stderr concurrent-drain regression test
#
# 잔여 결함(low): stream 엔드포인트가 stdout 을 EOF 까지 다 읽은 *뒤에야*
# stderr 를 읽으면, claude 가 stderr 를 많이 뱉을 때 stderr 파이프 버퍼가
# 차서 claude 가 stderr write 에서 블록 → stdout 진행도 멈춤 → stdout EOF 가
# 영원히 안 오는 이론적 데드락. fix = create_subprocess_exec 직후 stderr 를
# 백그라운드 task 로 동시 drain.
#
# 아래 fake proc 은 그 데드락을 충실히 모델링한다:
#   stdout 의 마지막 EOF 는 stderr.read() 가 *시작(await)* 된 뒤에만 도착한다.
#   - 동시 drain(수정 후): stderr drain task 가 즉시 시작 → EOF 도착 → 완료.
#   - 순차 read(수정 전): stdout EOF 를 먼저 기다림 → 영원히 hang → 테스트 timeout.
# ---------------------------------------------------------------------------


class _DrainGatedStdoutReader:
    """stdout reader: chunk 들을 흘려보낸 뒤, stderr drain 이 시작될 때까지
    EOF(b"")를 막아둔다. stderr 동시 drain 이 일어나야만 EOF 에 도달."""

    def __init__(self, lines: list[bytes], stderr_started: asyncio.Event):
        self._lines = list(lines)
        self._stderr_started = stderr_started

    async def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        # 모든 chunk 소진 → EOF 전에 stderr drain 시작을 기다림(데드락 재현)
        await self._stderr_started.wait()
        return b""


class _GatedStderrReader:
    """stderr reader: read() 가 호출(=drain 시작)되면 event 를 set 하고
    누적 stderr 내용을 반환. stdout EOF 게이트를 여는 역할."""

    def __init__(self, content: bytes, stderr_started: asyncio.Event):
        self._content = content
        self._stderr_started = stderr_started

    async def read(self) -> bytes:
        # drain 이 시작됐음을 알림 → stdout EOF 게이트 해제
        self._stderr_started.set()
        return self._content


class StderrDrainFakeProc:
    """stdout chunk 여러 개 + stderr 내용 보유, returncode≠0 인 fake proc.
    stderr 가 동시 drain 될 때만 stdout 이 EOF 에 도달하도록 게이팅."""

    def __init__(self, *, stdout_lines: list[bytes], stderr_content: bytes,
                 returncode: int):
        self._stderr_started = asyncio.Event()
        self.stdout = _DrainGatedStdoutReader(stdout_lines, self._stderr_started)
        self.stderr = _GatedStderrReader(stderr_content, self._stderr_started)
        self._returncode = returncode
        self.returncode = None
        self.killed = False
        self.waited = False

    def kill(self):
        self.killed = True

    async def wait(self):
        self.waited = True
        if self.returncode is None:
            self.returncode = self._returncode
        return self.returncode


def test_ai_answer_stream_drains_stderr_concurrently(trusted_client, patched_subprocess):
    """stream: claude 가 stderr 를 많이 뱉어도 stderr 를 stdout 과 동시 drain 해
    데드락 없이 완료해야 하고, returncode≠0 이면 stderr 메시지가 event: error 로
    표면화돼야 한다.

    fake proc 은 stderr.read() 가 시작돼야만 stdout 이 EOF 에 도달하도록 게이팅 —
    순차(EOF 후 stderr) 구현이면 이 테스트는 영원히 hang 한다. 따라서 hang 없이
    완료한다는 것 자체가 '동시 drain' 의 증거다.
    """
    err_msg = "claude: rate limit exceeded\n" * 50  # 큰 stderr (버퍼 채움 모사)
    proc = patched_subprocess(StderrDrainFakeProc(
        stdout_lines=[b"chunk-1\n", b"chunk-2\n", b"chunk-3\n"],
        stderr_content=err_msg.encode("utf-8"),
        returncode=1,
    ))

    with trusted_client.stream("POST", "/api/ai-answer/stream",
                               json={"question": "ping", "context_slugs": ["alpha"]}) as r:
        body = r.read().decode("utf-8")

    # (a) stderr 가 drain 돼 hang 없이 완료
    # (b) non-zero returncode → stderr 메시지가 event: error 로 표면화
    assert "event: error" in body, "returncode≠0 시 event: error 방출해야 함"
    assert "rate limit exceeded" in body, "stderr 메시지가 error event 에 실려야 함"
    assert "event: done" not in body, "실패 케이스에선 done 이 아니라 error"
    # provenance 검증 전에 받은 stdout 은 사용자에게 먼저 흘리지 않는다.
    assert "event: chunk" not in body
    # proc 은 정상 종료(returncode 설정) → finally 의 _terminate_proc 은 no-op
    assert proc.waited is True


# ---------------------------------------------------------------------------
# C3 — stream 무제한 수명 방어 (absolute deadline + chunk/byte cap)
#
# Codex [high]: readline 에 idle timeout 만 걸려 있으면 claude 가 deadline 안에
# 한 줄씩 계속 흘려보낼 때 전체 스트림이 무기한 지속된다. fix = (1) 스트림 전체에
# absolute deadline, (2) max chunks/bytes cap. 초과 시 event: error + proc 종료.
# 추가로 child 를 새 process group(start_new_session=True)으로 띄우고 cleanup 시
# process group 전체를 종료해 descendant 누수를 막는다.
# ---------------------------------------------------------------------------


class _InfiniteStdoutReader:
    """readline 이 매번 즉시 한 줄을 돌려준다 — 절대 EOF(b"")에 도달하지 않음.

    각 readline 은 빠르게 반환되므로 idle timeout 은 발동하지 않는다. 오직
    absolute deadline / chunk cap 만이 이 무한 스트림을 끊을 수 있다.
    """

    def __init__(self, line: bytes = b"tick\n"):
        self._line = line
        self.count = 0

    async def readline(self) -> bytes:
        self.count += 1
        return self._line

    async def read(self) -> bytes:
        return b""


class InfiniteFakeProc:
    """무한히 stdout 라인을 흘려보내는 fake proc. pid 보유(process-group 경로용)."""

    def __init__(self, line: bytes = b"tick\n"):
        self.stdout = _InfiniteStdoutReader(line=line)
        self.stderr = _FakeStreamReader(lines=[])
        self.returncode = None
        self.pid = 424242
        self.killed = False
        self.waited = False

    def kill(self):
        self.killed = True

    async def wait(self):
        self.waited = True
        if self.returncode is None:
            self.returncode = -9
        return self.returncode


def test_ai_answer_stream_absolute_deadline_terminates(
    trusted_client, patched_subprocess, monkeypatch
):
    """stream: claude 가 deadline 안에 한 줄씩 계속 써도(idle timeout 미발동)
    전체 absolute deadline 을 넘기면 event: error + proc kill/wait 로 끊어야 한다."""
    proc = patched_subprocess(InfiniteFakeProc())

    # 실제 시계 대기 없이 deadline 초과를 강제: 시간이 deadline 보다 큰 폭으로
    # 흐르도록 monotonic 을 단조 증가 스텁으로 대체.
    fake_clock = {"t": 0.0}

    def fake_monotonic():
        fake_clock["t"] += 1000.0  # 한 번 호출될 때마다 1000초 경과 → 즉시 deadline 초과
        return fake_clock["t"]

    monkeypatch.setattr(api_module.time, "monotonic", fake_monotonic)

    with trusted_client.stream("POST", "/api/ai-answer/stream",
                               json={"question": "ping", "context_slugs": ["alpha"]}) as r:
        body = r.read().decode("utf-8")

    assert "event: error" in body, "deadline 초과 시 event: error 방출해야 함"
    assert proc.killed is True, "deadline 초과 시 proc.kill() 호출돼야 함"
    assert proc.waited is True, "deadline 초과 후 proc.wait() 가 await 돼야 함"
    # 무한 루프가 cap 으로 끊겼는지 — 유한 횟수만 읽었어야 한다(무기한 X)
    assert proc.stdout.count < 100000, "deadline 이 무한 스트림을 끊지 못함"


def test_ai_answer_stream_chunk_cap_terminates(
    trusted_client, patched_subprocess, monkeypatch
):
    """stream: deadline 전이라도 chunk/byte cap 을 넘으면 event: error + 종료.

    시계는 진행시키지 않고(deadline 미발동) cap 을 작게 낮춰 chunk 수 초과만으로
    스트림이 끊기는지 검증한다."""
    proc = patched_subprocess(InfiniteFakeProc())

    # 시계는 고정 → deadline 절대 발동 안 함. cap 만으로 끊겨야 한다.
    monkeypatch.setattr(api_module.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(api_module, "_AI_STREAM_MAX_CHUNKS", 5)

    with trusted_client.stream("POST", "/api/ai-answer/stream",
                               json={"question": "ping", "context_slugs": ["alpha"]}) as r:
        body = r.read().decode("utf-8")

    assert "event: error" in body, "chunk cap 초과 시 event: error 방출해야 함"
    assert proc.killed is True, "chunk cap 초과 시 proc.kill() 호출돼야 함"
    assert proc.waited is True
    # cap 근방에서 끊겼는지 — 무한정 안 읽었어야 한다
    assert proc.stdout.count <= 100, "chunk cap 이 무한 스트림을 끊지 못함"


def test_stream_subprocess_started_in_new_session(trusted_client, patched_subprocess):
    """stream: create_subprocess_exec 호출이 start_new_session=True 로 child 를
    새 process group/session 에 띄워야 descendant 까지 process-group kill 가능."""
    proc = patched_subprocess(FakeProc(stdout_lines=[b"hi\n"]))
    captured = {}

    real_exec = api_module.asyncio.create_subprocess_exec  # patched_subprocess 가 이미 대체

    async def capturing_exec(*args, **kwargs):
        captured["kwargs"] = kwargs
        return await real_exec(*args, **kwargs)

    api_module.asyncio.create_subprocess_exec = capturing_exec
    try:
        with trusted_client.stream("POST", "/api/ai-answer/stream",
                                   json={"question": "ping", "context_slugs": ["alpha"]}) as r:
            r.read()
    finally:
        api_module.asyncio.create_subprocess_exec = real_exec

    assert captured["kwargs"].get("start_new_session") is True, \
        "child 를 새 session(process group)으로 띄워야 함"


def test_terminate_proc_uses_process_group_kill(monkeypatch):
    """_terminate_proc 은 pid 가 있으면 os.killpg(os.getpgid(pid), SIGKILL) 로
    process group 전체를 종료해야 한다 (descendant 누수 방지)."""
    import os
    import signal

    calls = {"getpgid": None, "killpg": None}

    def fake_getpgid(pid):
        calls["getpgid"] = pid
        return pid  # pgid == pid (leader)

    def fake_killpg(pgid, sig):
        calls["killpg"] = (pgid, sig)

    monkeypatch.setattr(os, "getpgid", fake_getpgid)
    monkeypatch.setattr(os, "killpg", fake_killpg)

    proc = InfiniteFakeProc()  # pid=424242, returncode=None(살아있음)

    asyncio.run(api_module._terminate_proc(proc))

    assert calls["getpgid"] == 424242, "os.getpgid(pid) 가 호출돼야 함"
    assert calls["killpg"] == (424242, signal.SIGKILL), \
        "os.killpg(pgid, SIGKILL) 로 그룹 전체를 종료해야 함"
    assert proc.waited is True, "process-group kill 후에도 proc.wait() 가 await 돼야 함"


def test_terminate_proc_falls_back_to_kill_without_pgid(monkeypatch):
    """_terminate_proc 은 os.getpgid 가 실패(pid 없음 등)하면 graceful 하게
    proc.kill() 로 fallback 해야 한다 (테스트 fake proc / 플랫폼 호환)."""
    import os

    def boom_getpgid(pid):
        raise ProcessLookupError()

    monkeypatch.setattr(os, "getpgid", boom_getpgid)

    proc = FakeProc(communicate_hang=True)  # returncode=None, pid 없음

    asyncio.run(api_module._terminate_proc(proc))

    assert proc.killed is True, "process-group kill 실패 시 proc.kill() 로 fallback 해야 함"
    assert proc.waited is True


# ---------------------------------------------------------------------------
# C4 — AIAnswerRequest 입력 검증 (size / count / slug pattern)
#
# Codex [med]: question/context_slugs 길이·개수·패턴 무제한 → DoS 표면.
# fix = Pydantic Field 제약. 위반 시 FastAPI 가 자동 422.
# ---------------------------------------------------------------------------


def test_ai_answer_rejects_oversized_question(client):
    """question 이 max_length 를 넘으면 422 (Pydantic 검증)."""
    huge = "가" * 100_000
    r = client.post("/api/ai-answer", json={"question": huge, "context_slugs": []})
    assert r.status_code == 422


def test_ai_answer_rejects_too_many_context_slugs(client):
    """context_slugs 개수가 max_items 를 넘으면 422."""
    slugs = [f"slug-{i}" for i in range(100)]
    r = client.post("/api/ai-answer", json={"question": "ping", "context_slugs": slugs})
    assert r.status_code == 422


def test_ai_answer_rejects_path_traversal_slug(client):
    """traversal slug 는 거부(422). '..' segment·절대경로·백슬래시가 핵심 위험.

    중첩 slug('a/b')는 더 이상 여기 포함되지 않는다 — find_page_path containment
    모델이 wiki_root 내부 중첩 slug 를 정당하게 허용하므로(아래 nested 테스트 참고),
    '/' 자체가 아니라 segment 단위 위험 요소('..'·선행'/'·'\\')만 거부한다.
    """
    for bad in ["../etc/passwd", "a/../../b", "/abs", "a\\b", "..", "foo/../bar"]:
        r = client.post("/api/ai-answer",
                        json={"question": "ping", "context_slugs": [bad]})
        assert r.status_code == 422, f"악성 slug 거부 실패: {bad!r}"


def test_ai_answer_rejects_oversized_slug(client):
    """개별 slug 가 max_length 를 넘으면 422."""
    long_slug = "a" * 5000
    r = client.post("/api/ai-answer",
                    json={"question": "ping", "context_slugs": [long_slug]})
    assert r.status_code == 422


def test_ai_answer_accepts_valid_slug_pattern(client, patched_subprocess):
    """정상 slug(소문자-하이픈-숫자, 한글 포함)은 통과해야 한다 (회귀 방지).

    claude CLI 를 fake 로 대체해 검증 통과 후 정상 done 응답까지 확인.
    """
    patched_subprocess(FakeProc(communicate_hang=False))
    r = client.post("/api/ai-answer",
                    json={"question": "ping", "context_slugs": ["habix-profile", "개념-노트"]})
    assert r.status_code == 200
    assert r.json()["status"] == "abstained"


# ---------------------------------------------------------------------------
# C4 회귀 — 중첩 slug 가 AIAnswerRequest 에서 422 로 깨지는 문제
#
# Codex [high]: C4 가 slug 에 `pattern=r"^[\w가-힣-]+$"` 를 걸어 '/' 를 전면
# 금지했다. 그러나 pages.find_page_path 는 wiki_root 내부의 중첩 slug
# ("260515_llm_wiki/prd" 등)를 정당하게 허용하고, 프론트엔드는 검색 결과 slug 를
# 그대로 context_slugs 로 보낸다. 결과: 중첩 페이지가 검색에 뜨면 /api/page 는
# 열리지만 /api/ai-answer/stream 은 422 로 실패 → AI 답변이 사용자 눈에 깨진다.
#
# fix = '/' 전면 금지가 아니라 segment 단위 안전성(빈 segment·'..'·절대경로·
# 백슬래시 금지)으로 검증하고, find_page_path containment 를 최종 게이트로 사용.
# ---------------------------------------------------------------------------


def test_ai_answer_accepts_nested_slug(tmp_path, monkeypatch):
    """회귀: 중첩 slug('sub/nested')는 422 가 아니라 정상 처리돼야 한다.

    wiki_root 내부의 중첩 페이지를 만들어, 그 slug 를 context_slugs 로 보냈을 때
    (a) 422 가 안 나고 (b) 근거 ledger가 없으므로 status=abstained이며 (c) 그
    페이지가 context_slugs로 수집되되 출처로 오표시되지 않는지 확인한다.
    """
    # 중첩 페이지 fixture: wiki_root/concepts/sub/nested.md (slug = "sub/nested")
    project_root = tmp_path / "proj"
    wiki_root = project_root / "wiki"
    (wiki_root / "concepts" / "sub").mkdir(parents=True)
    (wiki_root / "concepts" / "sub" / "nested.md").write_text(
        "---\ntitle: Nested\ntags: [misc]\n---\n# Nested\n\n중첩 페이지 본문.\n"
    )
    (project_root / "index.md").write_text("## concepts/ (1개)\n")

    app = create_app(wiki_root=wiki_root)
    local_client = TestClient(app)

    # claude CLI fake (없으면 unavailable 로 빠지므로 검증 통과만 확인하려면 주입 필요)
    monkeypatch.setattr(api_module.shutil, "which", lambda name: "/usr/bin/claude")

    async def fake_exec(*args, **kwargs):
        return FakeProc(communicate_hang=False)

    monkeypatch.setattr(api_module.asyncio, "create_subprocess_exec", fake_exec)

    r = local_client.post("/api/ai-answer",
                          json={"question": "ping", "context_slugs": ["sub/nested"]})
    assert r.status_code == 200, "중첩 slug 가 422 로 거부되면 회귀 미해결"
    data = r.json()
    assert data["status"] == "abstained"
    assert "sub/nested" in data["context_slugs"], "중첩 페이지가 context 로 수집돼야 함"
    assert data["sources"] == [], "usable claim 없는 페이지를 출처로 표시하면 안 됨"


def test_ai_answer_excludes_traversal_slug_silently(tmp_path, monkeypatch):
    """containment 를 통과 못 하는(존재 안 하는) 중첩 slug 는 422 가 아니라
    조용히 제외돼야 한다.

    '..' 같은 노골적 traversal 은 Pydantic 단에서 422 로 거부되지만('..'·절대경로·
    백슬래시 — 위 traversal 테스트), 형식은 안전한데 wiki_root 안에 실재하지 않는
    중첩 slug 는 _collect_context 의 find_page_path containment 가 PageNotFound 로
    걸러 sources 에서 제외한다(요청 자체는 200).
    """
    project_root = tmp_path / "proj"
    wiki_root = project_root / "wiki"
    (wiki_root / "concepts").mkdir(parents=True)
    (project_root / "index.md").write_text("## concepts/ (0개)\n")

    app = create_app(wiki_root=wiki_root)
    local_client = TestClient(app)

    monkeypatch.setattr(api_module.shutil, "which", lambda name: "/usr/bin/claude")

    async def fake_exec(*args, **kwargs):
        return FakeProc(communicate_hang=False)

    monkeypatch.setattr(api_module.asyncio, "create_subprocess_exec", fake_exec)

    # 형식은 안전(빈 segment/'..'/절대경로 아님)하지만 실재하지 않는 중첩 slug
    r = local_client.post("/api/ai-answer",
                          json={"question": "ping", "context_slugs": ["sub/missing"]})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "abstained"
    # containment 미통과 → sources 에서 조용히 제외 (422 아님)
    assert data["sources"] == []


def test_ai_answer_uses_claim_ledger_context_and_renders_citations(tmp_path, monkeypatch):
    """query context는 current trusted claims만 보내고, 외부 capture는 untrusted로
    격리하며, 응답은 claim citation을 provenance footer로 렌더링해야 한다."""
    project_root = tmp_path / "proj"
    wiki_root = project_root / "wiki"
    (wiki_root / "concepts").mkdir(parents=True)
    (project_root / "raw" / "notes").mkdir(parents=True)
    (project_root / "raw" / "newsletters").mkdir(parents=True)
    (project_root / "index.md").write_text("## concepts/ (4개)\n", encoding="utf-8")

    (project_root / "raw" / "notes" / "alpha.md").write_text("Alpha current fact.\n", encoding="utf-8")
    (project_root / "raw" / "notes" / "gamma.md").write_text("Gamma stale fact.\n", encoding="utf-8")
    (project_root / "raw" / "notes" / "delta.md").write_text(
        "Old claim.\nCurrent replacement.\n", encoding="utf-8"
    )
    (project_root / "raw" / "newsletters" / "beta.md").write_text(
        "Beta external capture.\n", encoding="utf-8"
    )

    def persisted_claim(
        claim_id: str,
        statement: str,
        raw_path: str,
        *,
        status: str = "active",
        trust: str = "trusted",
    ) -> dict:
        return {
            "claim_id": claim_id,
            "statement": statement,
            "kind": "fact",
            "raw_path": raw_path,
            "raw_sha256": hashlib.sha256((project_root / raw_path).read_bytes()).hexdigest(),
            "locator": f"{raw_path}#L1-L1",
            "valid_from": "2026-08-01",
            "valid_until": "2099-12-31",
            "status": status,
            "trust": trust,
        }

    claims = [
        persisted_claim("claim:alpha-1", "Alpha current fact.", "raw/notes/alpha.md"),
        persisted_claim(
            "claim:beta-1",
            "Beta external capture.",
            "raw/newsletters/beta.md",
            trust="untrusted",
        ),
        persisted_claim(
            "claim:gamma-1",
            "Gamma stale fact.",
            "raw/notes/gamma.md",
            status="stale",
        ),
        persisted_claim(
            "claim:delta-1",
            "Old claim.",
            "raw/notes/delta.md",
            status="superseded",
        ),
        persisted_claim(
            "claim:delta-2",
            "Current replacement.",
            "raw/notes/delta.md",
        ),
    ]
    (project_root / "claims.jsonl").write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in claims),
        encoding="utf-8",
    )

    def page(title: str, body: str, sources: str, extra: str = "", updated: str = "2026-08-10") -> str:
        return (
            "---\n"
            f"title: {title}\n"
            "created: 2026-08-01\n"
            f"updated: {updated}\n"
            "sources:\n"
            f"  - {sources}\n"
            f"{extra}"
            "---\n\n"
            f"{body}\n"
        )

    (wiki_root / "concepts" / "alpha.md").write_text(
        page("Alpha", "Alpha current fact.", "raw/notes/alpha.md"), encoding="utf-8"
    )
    (wiki_root / "concepts" / "beta.md").write_text(
        page("Beta", "Beta external capture.", "raw/newsletters/beta.md"), encoding="utf-8"
    )
    (wiki_root / "concepts" / "gamma.md").write_text(
        page("Gamma", "Gamma stale fact.", "raw/notes/gamma.md", updated="2025-01-01"),
        encoding="utf-8",
    )
    (wiki_root / "concepts" / "delta.md").write_text(
        page(
            "Delta",
            "Old claim. Current replacement.",
            "raw/notes/delta.md",
            extra='superseded_claims: ["Old claim."]\n',
        ),
        encoding="utf-8",
    )

    local_client = TestClient(create_app(wiki_root=wiki_root))

    monkeypatch.setattr(api_module.llm_client, "load_llm_config", lambda: {"engine": "api"})
    captured = {}

    async def fake_call_llm(prompt, *, config, timeout):
        captured["prompt"] = prompt
        return "Alpha answer [claim:alpha-1]. Delta answer [claim:delta-2]."

    monkeypatch.setattr(api_module.llm_client, "call_llm", fake_call_llm)

    before_tree = {
        str(path.relative_to(project_root)): path.read_bytes()
        for directory in (project_root / "raw", project_root / "wiki")
        for path in directory.rglob("*")
        if path.is_file()
    }

    r = local_client.post(
        "/api/ai-answer",
        json={"question": "요약해줘", "context_slugs": ["alpha", "beta", "gamma", "delta"]},
    )

    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "done"
    assert "## trusted claim ledger" in captured["prompt"]
    assert "Alpha current fact." in captured["prompt"]
    assert "Current replacement." in captured["prompt"]
    assert "Gamma stale fact." not in captured["prompt"]
    assert "Old claim." not in captured["prompt"]
    assert "## 외부 캡처 원문 (검증 전)" in captured["prompt"]
    assert "Beta external capture." in captured["prompt"]
    assert "## 출처" in data["answer"]
    assert "raw/notes/alpha.md#L1-L1" in data["answer"]
    assert "raw/notes/delta.md#L1-L1" in data["answer"]
    after_tree = {
        str(path.relative_to(project_root)): path.read_bytes()
        for directory in (project_root / "raw", project_root / "wiki")
        for path in directory.rglob("*")
        if path.is_file()
    }
    assert after_tree == before_tree, "query API must preserve every raw/wiki byte"


def test_ai_answer_fails_closed_before_llm_on_malformed_persisted_ledger(tmp_path, monkeypatch):
    project_root = tmp_path / "proj"
    wiki_root = project_root / "wiki"
    (wiki_root / "concepts").mkdir(parents=True)
    (project_root / "raw" / "notes").mkdir(parents=True)
    (project_root / "index.md").write_text("## concepts/ (1개)\n", encoding="utf-8")
    (project_root / "raw" / "notes" / "alpha.md").write_text(
        "Alpha current fact.\n", encoding="utf-8"
    )
    (wiki_root / "concepts" / "alpha.md").write_text(
        "---\ntitle: Alpha\nsources: [raw/notes/alpha.md]\n---\n\nAlpha current fact.\n",
        encoding="utf-8",
    )
    valid = {
        "claim_id": "claim:alpha-1",
        "statement": "Alpha current fact.",
        "kind": "fact",
        "raw_path": "raw/notes/alpha.md",
        "raw_sha256": hashlib.sha256(b"Alpha current fact.\n").hexdigest(),
        "valid_from": "2026-08-01",
        "valid_until": "2099-12-31",
        "status": "active",
        "trust": "trusted",
    }
    (project_root / "claims.jsonl").write_text(
        json.dumps(valid) + "\n" + json.dumps({"claim_id": "claim:partial-1"}) + "\n",
        encoding="utf-8",
    )
    local_client = TestClient(create_app(wiki_root=wiki_root))
    monkeypatch.setattr(api_module.llm_client, "load_llm_config", lambda: {"engine": "api"})
    called = False

    async def fake_call_llm(prompt, *, config, timeout):
        nonlocal called
        called = True
        return "must not run"

    monkeypatch.setattr(api_module.llm_client, "call_llm", fake_call_llm)

    response = local_client.post(
        "/api/ai-answer",
        json={"question": "요약해줘", "context_slugs": ["alpha"]},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert "claim ledger invalid" in response.json()["message"].lower()
    assert called is False


@pytest.mark.parametrize(
    "current_sources",
    [
        ["raw/notes/trusted.md", "raw/newsletters/external.md"],
        ["raw/newsletters/external.md"],
    ],
    ids=["mixed-current-sources", "sole-source-mismatch"],
)
def test_query_rejects_legacy_trusted_claim_when_current_page_inventory_is_unsafe(
    tmp_path, monkeypatch, current_sources
):
    """Legacy first-source trust must not survive current wiki source validation."""
    project_root = tmp_path / "proj"
    wiki_root = project_root / "wiki"
    (wiki_root / "concepts").mkdir(parents=True)
    (project_root / "raw" / "notes").mkdir(parents=True)
    (project_root / "raw" / "newsletters").mkdir(parents=True)
    (project_root / "index.md").write_text("## concepts/ (1개)\n", encoding="utf-8")
    trusted_bytes = b"Trusted source statement.\n"
    (project_root / "raw" / "notes" / "trusted.md").write_bytes(trusted_bytes)
    (project_root / "raw" / "newsletters" / "external.md").write_text(
        "External capture statement.\n", encoding="utf-8"
    )
    source_yaml = "\n".join(f"  - {source}" for source in current_sources)
    (wiki_root / "concepts" / "mixed.md").write_text(
        "---\n"
        "title: Mixed\n"
        "sources:\n"
        f"{source_yaml}\n"
        "---\n\n"
        "External capture statement.\n",
        encoding="utf-8",
    )
    legacy_record = {
        "claim_id": "claim:mixed-1",
        "statement": "External capture statement.",
        "kind": "fact",
        "raw_path": "raw/notes/trusted.md",
        "raw_sha256": hashlib.sha256(trusted_bytes).hexdigest(),
        "locator": "raw/notes/trusted.md#L1-L1",
        "valid_from": "2026-08-01",
        "valid_until": "2099-12-31",
        "status": "active",
        "trust": "trusted",
    }
    (project_root / "claims.jsonl").write_text(
        json.dumps(legacy_record) + "\n", encoding="utf-8"
    )
    before = {
        path.relative_to(project_root).as_posix(): path.read_bytes()
        for root in (project_root / "raw", project_root / "wiki")
        for path in root.rglob("*")
        if path.is_file()
    }

    async def forged_legacy_answer(*args, **kwargs):
        return "External capture accepted [claim:mixed-1]."

    monkeypatch.setattr(api_module.llm_client, "load_llm_config", lambda: {"engine": "api"})
    monkeypatch.setattr(api_module.llm_client, "call_llm", forged_legacy_answer)
    response = TestClient(create_app(wiki_root=wiki_root)).post(
        "/api/ai-answer",
        json={"question": "외부 주장?", "context_slugs": ["mixed"]},
    )
    after = {
        path.relative_to(project_root).as_posix(): path.read_bytes()
        for root in (project_root / "raw", project_root / "wiki")
        for path in root.rglob("*")
        if path.is_file()
    }

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert "source inventory" in response.json()["message"].lower()
    assert "mixed" in response.json()["message"]
    assert "uv run python scripts/claims.py build" in response.json()["message"]
    assert response.json()["affected_slugs"] == ["mixed"]
    assert response.json()["affected_count"] == 1
    assert response.json()["answer"] == ""
    assert "claim:mixed-1" not in response.json()["message"]
    assert "raw/notes/trusted.md" not in response.json()["message"]
    assert "External capture statement" not in response.json()["message"]
    assert after == before


def _make_stream_claim_project(tmp_path):
    project_root = tmp_path / "proj"
    wiki_root = project_root / "wiki"
    (wiki_root / "concepts").mkdir(parents=True)
    (project_root / "raw" / "notes").mkdir(parents=True)
    (project_root / "raw" / "newsletters").mkdir(parents=True)
    (project_root / "index.md").write_text("## concepts/ (2개)\n", encoding="utf-8")

    raw_values = {
        "raw/notes/alpha.md": b"Alpha current fact.\n",
        "raw/newsletters/beta.md": b"Beta external capture.\n",
    }
    for rel, content in raw_values.items():
        path = project_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    for slug, raw_path, statement in [
        ("alpha", "raw/notes/alpha.md", "Alpha current fact."),
        ("beta", "raw/newsletters/beta.md", "Beta external capture."),
    ]:
        (wiki_root / "concepts" / f"{slug}.md").write_text(
            f"---\ntitle: {slug}\nsources: [{raw_path}]\n---\n\n{statement}\n",
            encoding="utf-8",
        )
    records = [
        {
            "claim_id": "claim:alpha-1",
            "statement": "Alpha current fact.",
            "kind": "fact",
            "raw_path": "raw/notes/alpha.md",
            "raw_sha256": hashlib.sha256(raw_values["raw/notes/alpha.md"]).hexdigest(),
            "locator": "raw/notes/alpha.md#L1-L1",
            "valid_from": "2026-08-01",
            "valid_until": "2099-12-31",
            "status": "active",
            "trust": "trusted",
        },
        {
            "claim_id": "claim:beta-1",
            "statement": "Beta external capture.",
            "kind": "fact",
            "raw_path": "raw/newsletters/beta.md",
            "raw_sha256": hashlib.sha256(raw_values["raw/newsletters/beta.md"]).hexdigest(),
            "locator": "raw/newsletters/beta.md#L1-L1",
            "valid_from": "2026-08-01",
            "valid_until": "2099-12-31",
            "status": "active",
            "trust": "untrusted",
        },
    ]
    (project_root / "claims.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    return project_root, wiki_root


@pytest.fixture
def trusted_client(tmp_path):
    _project_root, wiki_root = _make_stream_claim_project(tmp_path)
    return TestClient(create_app(wiki_root=wiki_root))


def test_ai_answer_stream_buffers_then_renders_valid_citations(tmp_path, monkeypatch):
    project_root, wiki_root = _make_stream_claim_project(tmp_path)
    local_client = TestClient(create_app(wiki_root=wiki_root))
    monkeypatch.setattr(api_module.llm_client, "load_llm_config", lambda: {"engine": "api"})

    async def fake_stream(*args, **kwargs):
        yield "Alpha answer [claim:"
        yield "alpha-1]."

    monkeypatch.setattr(api_module.llm_client, "stream_llm", fake_stream)

    with local_client.stream(
        "POST",
        "/api/ai-answer/stream",
        json={"question": "요약", "context_slugs": ["alpha"]},
    ) as response:
        body = response.read().decode("utf-8")

    assert body.count("event: chunk") == 1
    assert '"delivery_mode": "verified-buffered"' in body
    assert '"source_slugs": ["alpha"]' in body
    assert "[claim:alpha-1]" in body
    assert "## 출처" in body
    assert "raw/notes/alpha.md#L1-L1" in body
    assert "event: done" in body


def test_ai_answer_returns_abstained_with_safe_exclusion_summary(tmp_path, monkeypatch):
    _project_root, wiki_root = _make_stream_claim_project(tmp_path)
    local_client = TestClient(create_app(wiki_root=wiki_root))
    monkeypatch.setattr(api_module.llm_client, "load_llm_config", lambda: {"engine": "api"})

    async def fake_call(*args, **kwargs):
        return "관련 정보 없음"

    monkeypatch.setattr(api_module.llm_client, "call_llm", fake_call)
    response = local_client.post(
        "/api/ai-answer",
        json={"question": "외부 캡처 내용?", "context_slugs": ["beta"]},
    )

    data = response.json()
    assert data["status"] == "abstained"
    assert data["answer"] == "관련 정보 없음"
    assert data["sources"] == []
    assert data["exclusion_reason_counts"] == {"untrusted": 1}
    assert data["recommended_next_action"] == {
        "command": "uv run python scripts/claims.py build"
    }
    assert "Beta external capture" not in json.dumps(data, ensure_ascii=False)
    assert "raw/newsletters" not in json.dumps(data, ensure_ascii=False)


def test_ai_answer_zero_usable_claims_skips_llm_and_records_abstention(
    tmp_path, monkeypatch
):
    _project_root, wiki_root = _make_stream_claim_project(tmp_path)
    local_client = TestClient(create_app(wiki_root=wiki_root))
    monkeypatch.setattr(api_module.llm_client, "load_llm_config", lambda: {"engine": "api"})
    captured_episodes = []
    monkeypatch.setattr(
        api_module.episode,
        "append",
        lambda record, **kwargs: captured_episodes.append(record),
    )

    async def forbidden_llm_call(*args, **kwargs):
        pytest.fail("zero-usable provenance must skip call_llm")

    monkeypatch.setattr(api_module.llm_client, "call_llm", forbidden_llm_call)
    response = local_client.post(
        "/api/ai-answer",
        json={"question": "외부 캡처 내용?", "context_slugs": ["beta"]},
    )

    data = response.json()
    assert data["status"] == "abstained"
    assert data["answer"] == "관련 정보 없음"
    assert data["sources"] == []
    assert data["exclusion_reason_counts"] == {"untrusted": 1}
    assert data["recommended_next_action"] == {
        "command": "uv run python scripts/claims.py build"
    }
    assert len(captured_episodes) == 1
    assert captured_episodes[0]["outputs"] == {"answer_status": "abstained"}
    assert captured_episodes[0]["status"] == "abstained"


def test_ai_answer_stream_abstention_matches_nonstream_contract(tmp_path, monkeypatch):
    _project_root, wiki_root = _make_stream_claim_project(tmp_path)
    local_client = TestClient(create_app(wiki_root=wiki_root))
    monkeypatch.setattr(api_module.llm_client, "load_llm_config", lambda: {"engine": "api"})

    async def fake_stream(*args, **kwargs):
        yield "관련 정보 없음"

    monkeypatch.setattr(api_module.llm_client, "stream_llm", fake_stream)
    with local_client.stream(
        "POST",
        "/api/ai-answer/stream",
        json={"question": "외부 캡처 내용?", "context_slugs": ["beta"]},
    ) as response:
        body = response.read().decode("utf-8")

    assert '"delivery_mode": "verified-buffered"' in body
    assert '"source_slugs": []' in body
    assert '"exclusion_reason_counts": {"untrusted": 1}' in body
    assert '"recommended_next_action": {"command": "uv run python scripts/claims.py build"}' in body
    assert 'event: chunk\ndata: {"text": "관련 정보 없음"}' in body
    assert 'event: done\ndata: {"status": "abstained"}' in body
    assert "raw/newsletters" not in body


def test_ai_answer_stream_zero_usable_claims_skips_llm_stream(tmp_path, monkeypatch):
    _project_root, wiki_root = _make_stream_claim_project(tmp_path)
    local_client = TestClient(create_app(wiki_root=wiki_root))
    monkeypatch.setattr(api_module.llm_client, "load_llm_config", lambda: {"engine": "api"})

    def forbidden_llm_stream(*args, **kwargs):
        pytest.fail("zero-usable provenance must skip stream_llm")

    monkeypatch.setattr(api_module.llm_client, "stream_llm", forbidden_llm_stream)
    with local_client.stream(
        "POST",
        "/api/ai-answer/stream",
        json={"question": "외부 캡처 내용?", "context_slugs": ["beta"]},
    ) as response:
        body = response.read().decode("utf-8")

    events = [line for line in body.splitlines() if line.startswith("event:")]
    assert events == ["event: meta", "event: chunk", "event: done"]
    assert '"delivery_mode": "verified-buffered"' in body
    assert 'event: chunk\ndata: {"text": "관련 정보 없음"}' in body
    assert 'event: done\ndata: {"status": "abstained"}' in body


def test_ai_answer_stream_inventory_error_is_sanitized_and_actionable(tmp_path, monkeypatch):
    project_root, wiki_root = _make_stream_claim_project(tmp_path)
    (wiki_root / "concepts" / "alpha.md").write_text(
        "---\ntitle: alpha\nsources:\n"
        "  - raw/notes/alpha.md\n"
        "  - raw/newsletters/beta.md\n"
        "---\n\nAlpha current fact.\n",
        encoding="utf-8",
    )
    local_client = TestClient(create_app(wiki_root=wiki_root))
    monkeypatch.setattr(api_module.llm_client, "load_llm_config", lambda: {"engine": "api"})

    with local_client.stream(
        "POST",
        "/api/ai-answer/stream",
        json={"question": "요약", "context_slugs": ["alpha"]},
    ) as response:
        body = response.read().decode("utf-8")

    assert "event: error" in body
    assert "alpha" in body
    assert "uv run python scripts/claims.py build" in body
    assert '"affected_slugs": ["alpha"]' in body
    assert "raw/notes/alpha.md" not in body
    assert "Alpha current fact" not in body


def test_ai_ui_labels_verified_buffering_and_uses_only_source_slugs():
    script = (Path(__file__).parent.parent / "wiki_app" / "static" / "app.js").read_text(
        encoding="utf-8"
    )

    assert "verified-buffered" in script
    assert "검증 후 일괄 표시" in script
    assert "ev.data.source_slugs" in script
    assert "exclusion_reason_counts" in script
    assert "recommended_next_action" in script


def test_ai_answer_stream_emits_no_unvalidated_untrusted_citation(tmp_path, monkeypatch):
    _project_root, wiki_root = _make_stream_claim_project(tmp_path)
    local_client = TestClient(create_app(wiki_root=wiki_root))
    monkeypatch.setattr(api_module.llm_client, "load_llm_config", lambda: {"engine": "api"})

    async def fake_stream(*args, **kwargs):
        yield "Unsafe answer [claim:beta-1]."

    monkeypatch.setattr(api_module.llm_client, "stream_llm", fake_stream)

    with local_client.stream(
        "POST",
        "/api/ai-answer/stream",
        json={"question": "요약", "context_slugs": ["beta"]},
    ) as response:
        body = response.read().decode("utf-8")

    assert '"exclusion_reason_counts": {"untrusted": 1}' in body
    assert 'event: chunk\ndata: {"text": "관련 정보 없음"}' in body
    assert 'event: done\ndata: {"status": "abstained"}' in body
    assert "Unsafe answer" not in body


def test_ai_answer_rejects_success_without_a_trusted_citation(tmp_path, monkeypatch):
    """Non-stream success cannot return an uncited factual answer."""
    _project_root, wiki_root = _make_stream_claim_project(tmp_path)
    local_client = TestClient(create_app(wiki_root=wiki_root))
    monkeypatch.setattr(api_module.llm_client, "load_llm_config", lambda: {"engine": "api"})

    async def fake_call(*args, **kwargs):
        return "Alpha answer without provenance."

    monkeypatch.setattr(api_module.llm_client, "call_llm", fake_call)

    response = local_client.post(
        "/api/ai-answer",
        json={"question": "요약", "context_slugs": ["alpha"]},
    )

    assert response.json()["status"] == "error"
    assert "trusted citation" in response.json()["message"].lower()
    assert response.json()["answer"] == ""


def test_ai_answer_stream_emits_no_uncited_success_tokens(tmp_path, monkeypatch):
    """SSE must buffer and reject an uncited factual answer before any chunk event."""
    _project_root, wiki_root = _make_stream_claim_project(tmp_path)
    local_client = TestClient(create_app(wiki_root=wiki_root))
    monkeypatch.setattr(api_module.llm_client, "load_llm_config", lambda: {"engine": "api"})

    async def fake_stream(*args, **kwargs):
        yield "Alpha answer without provenance."

    monkeypatch.setattr(api_module.llm_client, "stream_llm", fake_stream)

    with local_client.stream(
        "POST",
        "/api/ai-answer/stream",
        json={"question": "요약", "context_slugs": ["alpha"]},
    ) as response:
        body = response.read().decode("utf-8")

    assert "event: error" in body
    assert "trusted citation" in body.lower()
    assert "event: chunk" not in body
    assert "Alpha answer" not in body
