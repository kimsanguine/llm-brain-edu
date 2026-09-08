"""test_llm_client — LLM 엔진 추상화(cli|api) 유닛 테스트.

계약: "claude CLI 없이 pytest 통과". 실제 anthropic API·claude CLI 를 부르지 않는다.
- cli 분기: asyncio.create_subprocess_exec 를 fake proc 으로 mock.
- api 분기: llm_client._import_anthropic 를 fake anthropic 모듈로 mock.
"""
import asyncio
import builtins
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pytest  # noqa: E402

from lib import llm_client  # noqa: E402
from lib.llm_client import (  # noqa: E402
    LLMError,
    call_llm,
    load_llm_config,
    stream_llm,
)


# ---------------------------------------------------------------------------
# fake subprocess (cli 엔진)
# ---------------------------------------------------------------------------


class _FakeReader:
    def __init__(self, lines=None, read_content: bytes = b""):
        self._lines = list(lines or [])
        self._read_content = read_content

    async def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        return b""

    async def read(self) -> bytes:
        return self._read_content


class FakeProc:
    """asyncio subprocess 흉내 — communicate/readline + kill/wait 추적."""

    def __init__(self, *, stdout: bytes = b"", stdout_lines=None,
                 returncode: int = 0, stderr_content: bytes = b"",
                 communicate_hang: bool = False):
        self.stdout = _FakeReader(lines=stdout_lines)
        self.stderr = _FakeReader(read_content=stderr_content)
        self._stdout_bytes = stdout
        self._rc = returncode
        self._communicate_hang = communicate_hang
        self.returncode = None
        self.killed = False
        self.waited = False

    async def communicate(self):
        if self._communicate_hang:
            await asyncio.Future()  # 영원히 hang → wait_for timeout 유발
        self.returncode = self._rc
        return (self._stdout_bytes, b"")

    def kill(self):
        self.killed = True

    async def wait(self):
        self.waited = True
        if self.returncode is None:
            self.returncode = self._rc
        return self.returncode


@pytest.fixture
def fake_exec(monkeypatch):
    """create_subprocess_exec 를 주입 FakeProc 으로 대체하고 호출 kwargs 를 캡처."""
    captured = {}

    def install(proc: FakeProc) -> FakeProc:
        async def _exec(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return proc

        monkeypatch.setattr(llm_client.asyncio, "create_subprocess_exec", _exec)
        return proc

    install.captured = captured
    return install


# ---------------------------------------------------------------------------
# fake anthropic (api 엔진)
# ---------------------------------------------------------------------------


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResp:
    def __init__(self, blocks):
        self.content = blocks


class _FakeDelta:
    def __init__(self, text):
        self.text = text


class _FakeEvent:
    def __init__(self, type_, text=None):
        self.type = type_
        self.delta = _FakeDelta(text) if text is not None else None


class _FakeMessages:
    def __init__(self, resp=None, events=None):
        self._resp = resp
        self._events = events
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return list(self._events or [])
        return self._resp


class _FakeClient:
    def __init__(self, messages):
        self.messages = messages


class FakeAnthropic:
    """anthropic 모듈 흉내 — Anthropic(api_key=..., timeout=...) 호출을 추적."""

    def __init__(self, messages):
        self._messages = messages
        self.last_api_key = None
        self.last_timeout = "__unset__"

    def Anthropic(self, api_key=None, timeout=None):  # noqa: N802 (SDK 이름 흉내)
        self.last_api_key = api_key
        self.last_timeout = timeout
        return _FakeClient(self._messages)


# ---------------------------------------------------------------------------
# call_llm — cli 분기
# ---------------------------------------------------------------------------


def test_call_llm_cli_returns_text(fake_exec):
    fake_exec(FakeProc(stdout=b"hello world\n"))
    out = asyncio.run(call_llm("q", config={"engine": "cli"}))
    assert out == "hello world"


def test_call_llm_cli_uses_new_session(fake_exec):
    fake_exec(FakeProc(stdout=b"x"))
    asyncio.run(call_llm("q", config={"engine": "cli"}))
    assert fake_exec.captured["kwargs"].get("start_new_session") is True
    assert fake_exec.captured["args"][:2] == ("claude", "-p")


def test_call_llm_engine_defaults_to_cli(fake_exec):
    # engine 미설정(config={}) → cli 기본
    fake_exec(FakeProc(stdout=b"ok"))
    assert asyncio.run(call_llm("q", config={})) == "ok"


def test_call_llm_cli_timeout_propagates_and_terminates(fake_exec, monkeypatch):
    proc = fake_exec(FakeProc(communicate_hang=True))

    async def boom(aw, timeout):
        if asyncio.iscoroutine(aw):
            aw.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(llm_client.asyncio, "wait_for", boom)
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(call_llm("q", config={"engine": "cli"}, timeout=5))
    # timeout 이어도 살아있는 child 는 정리돼야 한다
    assert proc.killed is True
    assert proc.waited is True


# ---------------------------------------------------------------------------
# call_llm — api 분기
# ---------------------------------------------------------------------------


def test_call_llm_api_returns_text(monkeypatch):
    msgs = _FakeMessages(resp=_FakeResp([_FakeTextBlock("A"), _FakeTextBlock("B")]))
    fake = FakeAnthropic(msgs)
    monkeypatch.setattr(llm_client, "_import_anthropic", lambda: fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    out = asyncio.run(call_llm("q", config={
        "engine": "api", "model": "claude-opus-4-8",
        "api_key_env": "ANTHROPIC_API_KEY", "max_tokens": 100,
    }))
    assert out == "AB"
    assert fake.last_api_key == "sk-test"
    assert msgs.calls[0]["model"] == "claude-opus-4-8"
    assert msgs.calls[0]["max_tokens"] == 100


def test_call_llm_api_missing_key_errors(monkeypatch):
    fake = FakeAnthropic(_FakeMessages(resp=_FakeResp([])))
    monkeypatch.setattr(llm_client, "_import_anthropic", lambda: fake)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMError):
        asyncio.run(call_llm("q", config={"engine": "api", "api_key_env": "ANTHROPIC_API_KEY"}))


def test_call_llm_api_custom_key_env(monkeypatch):
    msgs = _FakeMessages(resp=_FakeResp([_FakeTextBlock("hi")]))
    fake = FakeAnthropic(msgs)
    monkeypatch.setattr(llm_client, "_import_anthropic", lambda: fake)
    monkeypatch.setenv("MY_KEY", "sk-custom")
    out = asyncio.run(call_llm("q", config={"engine": "api", "api_key_env": "MY_KEY"}))
    assert out == "hi"
    assert fake.last_api_key == "sk-custom"


# ---------------------------------------------------------------------------
# api timeout 계약 — cli 와 대칭 (Codex 적대리뷰 high 회귀 방지)
# WHY: engine:api 경로가 timeout 을 우회하면 Anthropic hang 시 wiki_app 요청/worker 가
#      무기한 붙잡힌다. cli 와 동일하게 SDK timeout 주입 + asyncio.TimeoutError 전파해야 한다.
# ---------------------------------------------------------------------------


def test_call_llm_api_passes_timeout_to_sdk(monkeypatch):
    msgs = _FakeMessages(resp=_FakeResp([_FakeTextBlock("ok")]))
    fake = FakeAnthropic(msgs)
    monkeypatch.setattr(llm_client, "_import_anthropic", lambda: fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    asyncio.run(call_llm("q", config={"engine": "api"}, timeout=42))
    assert fake.last_timeout == 42  # SDK client 에 실제 network timeout 이 전달돼야 함


def test_call_llm_api_hang_raises_timeout(monkeypatch):
    """messages.create 가 응답하지 않으면 cli 와 동일하게 asyncio.TimeoutError."""
    import threading

    release = threading.Event()

    class _HangMessages:
        def create(self, **kwargs):
            release.wait(timeout=10)  # wait_for 가 먼저 풀어야 정상
            return _FakeResp([])

    fake = FakeAnthropic(_HangMessages())
    monkeypatch.setattr(llm_client, "_import_anthropic", lambda: fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    try:
        with pytest.raises(asyncio.TimeoutError):
            asyncio.run(call_llm("q", config={"engine": "api"}, timeout=0.05))
    finally:
        release.set()


def test_stream_llm_api_hang_raises_timeout(monkeypatch):
    """stream 이 첫 이벤트 전/중간에 멈추면 idle_timeout 에 asyncio.TimeoutError."""
    import threading

    release = threading.Event()

    class _HangStream:
        def __iter__(self):
            return self

        def __next__(self):
            release.wait(timeout=10)
            raise StopIteration

    class _HangMessages:
        def create(self, **kwargs):
            return _HangStream()

    fake = FakeAnthropic(_HangMessages())
    monkeypatch.setattr(llm_client, "_import_anthropic", lambda: fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    async def _drain():
        async for _ in stream_llm("q", config={"engine": "api"}, idle_timeout=0.05):
            pass

    try:
        with pytest.raises(asyncio.TimeoutError):
            asyncio.run(_drain())
    finally:
        release.set()


# ---------------------------------------------------------------------------
# anthropic 미설치 대비: cli 정상 · api 친절한 에러
# ---------------------------------------------------------------------------


def test_import_anthropic_missing_raises_llmerror(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "anthropic":
            raise ImportError("no anthropic")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(LLMError):
        llm_client._import_anthropic()


def test_cli_works_without_anthropic(fake_exec, monkeypatch):
    # anthropic import 를 강제 실패시켜도 cli 경로는 영향 없어야 한다
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "anthropic":
            raise ImportError()
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    fake_exec(FakeProc(stdout=b"cli ok"))
    assert asyncio.run(call_llm("q", config={"engine": "cli"})) == "cli ok"


# ---------------------------------------------------------------------------
# stream_llm — cli 청크
# ---------------------------------------------------------------------------


def test_stream_llm_cli_yields_chunks(fake_exec):
    fake_exec(FakeProc(stdout_lines=[b"a\n", b"b\n"]))

    async def collect():
        return [c async for c in stream_llm("q", config={"engine": "cli"})]

    assert asyncio.run(collect()) == ["a\n", "b\n"]


def test_stream_llm_cli_nonzero_returncode_raises_with_stderr(fake_exec):
    fake_exec(FakeProc(stdout_lines=[b"partial\n"], returncode=1,
                       stderr_content=b"rate limit exceeded"))

    async def collect():
        got = []
        agen = stream_llm("q", config={"engine": "cli"})
        with pytest.raises(LLMError) as ei:
            async for c in agen:
                got.append(c)
        return got, str(ei.value)

    got, msg = asyncio.run(collect())
    assert got == ["partial\n"]
    assert "rate limit exceeded" in msg


# ---------------------------------------------------------------------------
# stream_llm — api 청크
# ---------------------------------------------------------------------------


def test_stream_llm_api_yields_text_deltas(monkeypatch):
    events = [
        _FakeEvent("message_start"),
        _FakeEvent("content_block_delta", "he"),
        _FakeEvent("content_block_delta", "llo"),
        _FakeEvent("message_stop"),
    ]
    msgs = _FakeMessages(events=events)
    fake = FakeAnthropic(msgs)
    monkeypatch.setattr(llm_client, "_import_anthropic", lambda: fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")

    async def collect():
        return [c async for c in stream_llm("q", config={
            "engine": "api", "api_key_env": "ANTHROPIC_API_KEY"})]

    assert asyncio.run(collect()) == ["he", "llo"]
    assert msgs.calls[0]["stream"] is True


def test_stream_llm_api_missing_key_errors(monkeypatch):
    fake = FakeAnthropic(_FakeMessages(events=[]))
    monkeypatch.setattr(llm_client, "_import_anthropic", lambda: fake)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def collect():
        return [c async for c in stream_llm("q", config={"engine": "api"})]

    with pytest.raises(LLMError):
        asyncio.run(collect())


# ---------------------------------------------------------------------------
# config 로더 안전 처리 (부재/부분/오류)
# ---------------------------------------------------------------------------


def test_load_llm_config_absent_returns_defaults(tmp_path):
    cfg = load_llm_config(tmp_path / "nope.yaml")
    assert cfg["engine"] == "cli"
    assert cfg["model"] == llm_client.DEFAULT_MODEL
    assert cfg["api_key_env"] == llm_client.DEFAULT_API_KEY_ENV
    assert cfg["max_tokens"] == llm_client.DEFAULT_MAX_TOKENS


def test_load_llm_config_valid_override(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text("llm:\n  engine: api\n  model: claude-opus-4-8\n  max_tokens: 4096\n")
    cfg = load_llm_config(f)
    assert cfg["engine"] == "api"
    assert cfg["model"] == "claude-opus-4-8"
    assert cfg["max_tokens"] == 4096


def test_load_llm_config_partial_and_bad_keys_fall_back(tmp_path):
    f = tmp_path / "config.yaml"
    # engine 유효(api) 유지, max_tokens 음수·model 빈문자 → 기본값
    f.write_text("llm:\n  engine: api\n  max_tokens: -5\n  model: ''\n")
    cfg = load_llm_config(f)
    assert cfg["engine"] == "api"
    assert cfg["max_tokens"] == llm_client.DEFAULT_MAX_TOKENS
    assert cfg["model"] == llm_client.DEFAULT_MODEL


def test_load_llm_config_unknown_engine_falls_back(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text("llm:\n  engine: bogus\n")
    assert load_llm_config(f)["engine"] == "cli"


def test_load_llm_config_malformed_yaml_falls_back(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text("llm: [unterminated\n")
    assert load_llm_config(f)["engine"] == "cli"


def test_resolve_engine_dict(tmp_path):
    assert llm_client.resolve_engine({"engine": "api"}) == "api"
    assert llm_client.resolve_engine({}) == "cli"
