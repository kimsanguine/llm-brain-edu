"""test_llm_client_openai — openai 엔진(OpenAI 호환 서버) 유닛 테스트.

llm-brain-edu 델타 §5. 실제 OpenRouter 를 부르지 않는다 —
`llm_client._import_openai` 를 fake 모듈로 mock 한다.

각 테스트는 "이게 깨지면 수강생에게 무슨 일이 일어나는가"를 주석으로 남긴다.
수강생 79.8%가 파이썬 입문자이고, 개강 전 혼자 설치하다 막히면 그대로 이탈한다.
"""
import asyncio
import builtins
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pytest  # noqa: E402

from lib import llm_client  # noqa: E402
from lib.llm_client import (  # noqa: E402
    DEFAULT_OPENAI_API_KEY_ENV,
    DEFAULT_OPENAI_BASE_URL,
    DEFAULT_OPENAI_MODEL,
    LLMError,
    call_llm,
    load_llm_config,
    stream_llm,
)


# ---------------------------------------------------------------------------
# fake openai SDK
# ---------------------------------------------------------------------------


def _resp(text: str):
    """chat.completions.create 의 비스트림 응답 흉내."""
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def _delta(text: str):
    """스트림 청크 흉내."""
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])


class FakeOpenAI:
    """openai 모듈 흉내 — OpenAI(api_key=, base_url=, timeout=) 호출을 기록한다."""

    def __init__(self, create):
        self._create = create
        self.last_api_key = None
        self.last_base_url = "__unset__"
        self.last_timeout = "__unset__"
        self.last_kwargs = {}

    def OpenAI(self, api_key=None, base_url=None, timeout=None):  # noqa: N802 (SDK 이름)
        self.last_api_key = api_key
        self.last_base_url = base_url
        self.last_timeout = timeout
        outer = self

        def _create(**kwargs):
            outer.last_kwargs = kwargs
            return outer._create(**kwargs)

        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=_create))
        )


@pytest.fixture
def fake_openai(monkeypatch):
    """fake openai 모듈을 심고, 키를 세팅한다."""

    def _install(create):
        fake = FakeOpenAI(create)
        monkeypatch.setattr(llm_client, "_import_openai", lambda: fake)
        monkeypatch.setenv(DEFAULT_OPENAI_API_KEY_ENV, "sk-or-test")
        return fake

    return _install


OPENAI_CFG = {"engine": "openai"}


# ---------------------------------------------------------------------------
# 계약 1·2 — 지연 import, 조용한 실패 금지
# ---------------------------------------------------------------------------


def test_missing_openai_package_tells_student_the_fix(monkeypatch):
    """openai 미설치 → 무슨 명령을 치라는지까지 한국어로 나와야 한다.

    깨지면: 학생이 raw ImportError 스택트레이스를 보고 무엇을 해야 할지 모른 채 멈춘다.
    """
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "openai":
            raise ImportError("no openai")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(LLMError) as exc:
        llm_client._import_openai()
    msg = str(exc.value)
    assert "pip install openai" in msg
    assert "cli" in msg  # 대안 엔진까지 알려준다


def test_missing_key_names_the_exact_env_var(fake_openai, monkeypatch):
    """키 부재 → 어느 환경변수인지 이름을 찍어야 한다.

    깨지면: 교안이 `OPENROUTER_API_KEY` 를 쓰라고 했는데 에러가 이름을 안 알려주면
    학생은 자기가 만든 변수명이 틀렸는지조차 확인할 수 없다.
    """
    fake_openai(lambda **kw: _resp("x"))
    monkeypatch.delenv(DEFAULT_OPENAI_API_KEY_ENV, raising=False)
    with pytest.raises(LLMError) as exc:
        asyncio.run(call_llm("q", config=OPENAI_CFG))
    assert DEFAULT_OPENAI_API_KEY_ENV in str(exc.value)


def test_empty_choices_is_surfaced_not_returned_as_blank(fake_openai):
    """빈 응답을 빈 문자열로 삼키지 않는다.

    깨지면: 키 한도를 초과했거나 모델명이 틀렸을 때 위키에 빈 문서가 조용히 쌓인다.
    """
    fake_openai(lambda **kw: SimpleNamespace(choices=[]))
    with pytest.raises(LLMError) as exc:
        asyncio.run(call_llm("q", config=OPENAI_CFG))
    assert "한도" in str(exc.value)


# ---------------------------------------------------------------------------
# 계약 6 — 모델·키 이름 교정 (조용한 404 방지)
# ---------------------------------------------------------------------------


def test_engine_openai_without_model_uses_openrouter_model(tmp_path, capsys):
    """engine 만 openai 로 적고 model 을 빠뜨려도 Anthropic 모델명이 남지 않는다.

    깨지면: `claude-opus-4-8` 을 OpenRouter 로 보내 404 가 나고, 학생은 자기 키가
    잘못된 줄 안다. 교정 사실은 stderr 로 알려 조용한 치환도 막는다.
    """
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("llm:\n  engine: openai\n", encoding="utf-8")
    cfg = load_llm_config(cfg_file)
    assert cfg["model"] == DEFAULT_OPENAI_MODEL
    assert cfg["api_key_env"] == DEFAULT_OPENAI_API_KEY_ENV
    assert cfg["base_url"] == DEFAULT_OPENAI_BASE_URL
    assert "engine=openai" in capsys.readouterr().err


def test_explicit_model_and_base_url_win(tmp_path):
    """학생/강사가 명시한 값은 교정이 덮어쓰지 않는다.

    깨지면: 사내 LLM 서버(base_url 교체)로 돌리려는 설정이 OpenRouter 로 되돌아간다.
    """
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "llm:\n"
        "  engine: openai\n"
        "  model: qwen/qwen3-max\n"
        "  base_url: http://localhost:8000/v1\n",
        encoding="utf-8",
    )
    cfg = load_llm_config(cfg_file)
    assert cfg["model"] == "qwen/qwen3-max"
    assert cfg["base_url"] == "http://localhost:8000/v1"


def test_openai_engine_is_accepted_not_downgraded_to_cli(tmp_path, capsys):
    """`engine: openai` 가 '알 수 없음'으로 취급돼 cli 로 떨어지면 안 된다.

    깨지면: config 는 openai 인데 실제로는 `claude -p` 를 부르고, 학생 PC 에 Claude CLI
    가 없으니 원인 모를 실패가 난다.
    """
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("llm:\n  engine: openai\n", encoding="utf-8")
    assert load_llm_config(cfg_file)["engine"] == "openai"
    assert "알 수 없음" not in capsys.readouterr().err


# ---------------------------------------------------------------------------
# 비스트림 동작 + 계약 3 (timeout 이중 적용)
# ---------------------------------------------------------------------------


def test_returns_text_and_sends_base_url_and_key(fake_openai):
    """base_url 이 실제로 SDK 에 전달돼야 한다.

    깨지면: OpenRouter 키를 들고 OpenAI 본사로 요청이 가서 401 이 난다.
    """
    fake = fake_openai(lambda **kw: _resp("  안녕하세요  "))
    out = asyncio.run(call_llm("q", config=OPENAI_CFG))
    assert out == "안녕하세요"
    assert fake.last_base_url == DEFAULT_OPENAI_BASE_URL
    assert fake.last_api_key == "sk-or-test"
    assert fake.last_kwargs["model"] == DEFAULT_OPENAI_MODEL


def test_timeout_reaches_the_sdk(fake_openai):
    """SDK 에도 timeout 을 넘겨 네트워크 호출 자체를 취소 가능하게 한다.

    깨지면: 워커 스레드가 hang 에 무기한 붙잡혀, 호출부가 풀려도 스레드가 남는다.
    """
    fake = fake_openai(lambda **kw: _resp("x"))
    asyncio.run(call_llm("q", config=OPENAI_CFG, timeout=7))
    assert fake.last_timeout == 7


def test_hang_raises_asyncio_timeout_like_cli(fake_openai):
    """멈추면 cli/api 와 같은 asyncio.TimeoutError 로 풀린다.

    깨지면: 위키 화면이 영원히 도는 상태로 남고 학생은 무엇이 멈췄는지 모른다.
    """
    import time

    def _hang(**kw):
        time.sleep(5)
        return _resp("late")

    fake_openai(_hang)
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(call_llm("q", config=OPENAI_CFG, timeout=1))


def test_max_tokens_argument_overrides_config(fake_openai):
    """호출부가 넘긴 max_tokens 가 config 값을 이긴다(cli/api 와 동일 계약)."""
    fake = fake_openai(lambda **kw: _resp("x"))
    asyncio.run(call_llm("q", config={"engine": "openai", "max_tokens": 100}, max_tokens=42))
    assert fake.last_kwargs["max_tokens"] == 42


# ---------------------------------------------------------------------------
# 계약 4 — 스트리밍 동일 계약
# ---------------------------------------------------------------------------


def test_stream_yields_only_text_deltas(fake_openai):
    """델타 텍스트만 흘리고, 내용 없는 이벤트는 건너뛴다.

    깨지면: 답변 중간에 `None` 이나 빈 청크가 화면에 찍힌다.
    """
    events = [_delta("안"), SimpleNamespace(choices=[]), _delta("녕")]
    fake_openai(lambda **kw: iter(events))

    async def _collect():
        return [c async for c in stream_llm("q", config=OPENAI_CFG)]

    assert asyncio.run(_collect()) == ["안", "녕"]


def test_stream_hang_raises_timeout(fake_openai):
    """이벤트 사이가 멈추면 idle_timeout 으로 풀린다.

    깨지면: SSE 핸들러가 error 이벤트를 남기지 못해 화면이 무한 로딩에 갇힌다.
    """
    import time

    def _hanging_iter():
        yield _delta("첫")
        time.sleep(5)
        yield _delta("늦")

    fake_openai(lambda **kw: _hanging_iter())

    async def _collect():
        return [c async for c in stream_llm("q", config=OPENAI_CFG, idle_timeout=1)]

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(_collect())


# ---------------------------------------------------------------------------
# 계약 5 — 회귀 금지
# ---------------------------------------------------------------------------


def test_cli_engine_works_without_openai_package(monkeypatch):
    """openai 가 없어도 cli 경로는 영향받지 않는다(지연 import 확인).

    깨지면: openai 를 안 쓰는 사용자가 설치 안 한 패키지 때문에 못 돌린다.
    """
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "openai":
            raise ImportError("no openai")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    class _Proc:
        returncode = 0

        async def communicate(self):
            return b"ok", b""

        async def wait(self):
            return 0

    async def _exec(*a, **k):
        return _Proc()

    monkeypatch.setattr(llm_client.asyncio, "create_subprocess_exec", _exec)
    assert asyncio.run(call_llm("q", config={"engine": "cli"})) == "ok"


def test_stream_with_no_text_chunks_raises(fake_openai):
    """청크가 하나도 없이 끝나면 조용히 성공으로 넘기지 않는다.

    깨지면: 한도 초과·필터링·잘린 응답이 "빈 답변"으로 보이고, 학생은 무엇이
    잘못됐는지 알 수 없다. 화면에는 아무것도 안 뜨는데 오류도 없다.
    (적대 리뷰 지적 — 비스트림만 고쳤고 스트림은 남아 있었다)
    """
    fake_openai(lambda **kw: iter([]))          # 이벤트 0개

    async def _collect():
        return [c async for c in stream_llm("q", config=OPENAI_CFG)]

    with pytest.raises(LLMError) as exc:
        asyncio.run(_collect())
    assert "아무 내용 없이" in str(exc.value)


def test_empty_content_is_not_returned_as_success(fake_openai):
    """content 가 빈 문자열이면 성공이 아니다.

    깨지면: compile 은 형식 파싱 실패로 우연히 RULE 로 떨어지지만, AI 답변 경로는
    빈 답을 정상 완료로 취급한다.
    """
    msg = SimpleNamespace(content="")
    fake_openai(lambda **kw: SimpleNamespace(
        choices=[SimpleNamespace(message=msg, finish_reason="length")]))
    with pytest.raises(LLMError) as exc:
        asyncio.run(call_llm("q", config=OPENAI_CFG))
    assert "빈 응답" in str(exc.value)
