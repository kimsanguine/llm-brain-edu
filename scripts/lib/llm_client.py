"""llm_client — LLM 엔진 추상화 (SPEC "LLM 엔진 통합" 절의 예약 인터페이스 구현).

`schema/config.yaml` 의 `llm.engine` 로 cli / api 를 분기한다.

- **cli** (기본): 기존 `claude -p` subprocess 로직을 재사용한다. API 키 불필요,
  Claude Code CLI 설치 필요. wiki_app 이 지금까지 써온 경로와 동일.
- **api**: `anthropic` SDK 로 직접 호출한다. `anthropic` 은 함수 내부에서 지연 import
  하므로 cli 모드에는 패키지가 없어도 무방하다 (부재 시 api 모드만 친절한 에러).

계약: "claude CLI 없이 pytest 통과". 테스트는 실제 anthropic API·claude CLI 를 부르지
않는다 — cli 모드는 subprocess 를, api 모드는 anthropic client 를 mock 한다.

config 안전 처리(기존 memory_score config 로더 패턴): config 부재=cli 기본,
부분/오류 키=항별 기본값 + stderr warn(조용한 실패 금지, Rule 8). api 인데 키 env
부재=명확한 LLMError.

subprocess 수명(process-group kill·idle timeout·동시 stderr drain)은 wiki_app/api.py
에서 이 모듈로 이관됐다. `_terminate_proc`/`_kill_process_group` 은 api.py 가 re-export
해 기존 테스트 훅(`api_module._terminate_proc`)을 유지한다.
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import yaml

# scripts/lib/llm_client.py → repo 루트 (memory_score.py 와 동일 지점)
SCHEMA_DIR = Path(__file__).parent.parent.parent / "schema"

# --- config 기본값 (schema/config.yaml `llm:` 섹션이 override) ---
DEFAULT_ENGINE = "cli"
DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_API_KEY_ENV = "ANTHROPIC_API_KEY"
DEFAULT_MAX_TOKENS = 8192

# --- openai 엔진 기본값 (OpenAI 호환 서버) ---
# base_url 한 줄만 바꾸면 OpenRouter·vLLM·Ollama·Azure OpenAI 어디든 붙는다.
DEFAULT_OPENAI_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENAI_API_KEY_ENV = "OPENROUTER_API_KEY"
DEFAULT_OPENAI_MODEL = "openai/gpt-5.6-luna"

# 비스트림 기본 timeout(초) — cli/api 공통 fallback. wiki_app 은 자기 상수
# (_AI_ANSWER_TIMEOUT)를 주입한다. api 도 동일 계약으로 이 deadline 을 적용한다.
DEFAULT_CLI_TIMEOUT = 90
# 스트림 이벤트 사이 idle timeout(초) — cli/api 공통. wiki_app 은
# _AI_STREAM_IDLE_TIMEOUT 을 주입한다. api stream 도 동일 계약으로 적용한다.
DEFAULT_CLI_STREAM_IDLE_TIMEOUT = 90


class LLMError(RuntimeError):
    """LLM 호출 관련 사용자용 명확한 에러 (조용한 실패 금지, Rule 8).

    api 엔진에 anthropic 미설치·키 env 부재, cli 비정상 종료 등을 표면화한다.
    """


# ---------------------------------------------------------------------------
# config 로더 — 부재/부분/오류 안전 폴백 (memory_score 로더 패턴)
# ---------------------------------------------------------------------------


def load_llm_config(config_file: Path | None = None) -> dict:
    """`llm` 섹션을 해석해 {engine, model, api_key_env, max_tokens} 를 돌려준다.

    config 부재/파싱오류/섹션부재 → 전부 기본값(engine=cli). 부분/타입오류 키는
    항별 기본값 + stderr warn 으로 안전 폴백한다(조용한 crash/flaky 금지).
    """
    cfg = {
        "engine": DEFAULT_ENGINE,
        "model": DEFAULT_MODEL,
        "api_key_env": DEFAULT_API_KEY_ENV,
        "max_tokens": DEFAULT_MAX_TOKENS,
    }
    if config_file is None:
        config_file = SCHEMA_DIR / "config.yaml"
    if not config_file.exists():
        return cfg
    try:
        raw = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"  [llm_client] config.yaml 파싱 실패 — 기본값 사용 ({exc})", file=sys.stderr)
        return cfg
    section = raw.get("llm") if isinstance(raw, dict) else None
    if not isinstance(section, dict):
        return cfg

    engine = section.get("engine")
    if isinstance(engine, str) and engine in ("cli", "api", "openai"):
        cfg["engine"] = engine
    elif engine is not None:
        print(f"  [llm_client] llm.engine={engine!r} 알 수 없음 — 기본값 {DEFAULT_ENGINE} 사용",
              file=sys.stderr)

    model = section.get("model")
    if isinstance(model, str) and model.strip():
        cfg["model"] = model
    elif model is not None:
        print(f"  [llm_client] llm.model={model!r} 무효 — 기본값 {DEFAULT_MODEL} 사용",
              file=sys.stderr)

    api_key_env = section.get("api_key_env")
    if isinstance(api_key_env, str) and api_key_env.strip():
        cfg["api_key_env"] = api_key_env
    elif api_key_env is not None:
        print(f"  [llm_client] llm.api_key_env={api_key_env!r} 무효 — 기본값 {DEFAULT_API_KEY_ENV} 사용",
              file=sys.stderr)

    max_tokens = section.get("max_tokens")
    if isinstance(max_tokens, bool):  # bool 은 int 하위형이지만 토큰 수로 무효
        print(f"  [llm_client] llm.max_tokens={max_tokens!r} 무효 — 기본값 {DEFAULT_MAX_TOKENS} 사용",
              file=sys.stderr)
    elif isinstance(max_tokens, int) and max_tokens > 0:
        cfg["max_tokens"] = max_tokens
    elif max_tokens is not None:
        print(f"  [llm_client] llm.max_tokens={max_tokens!r} 무효 — 기본값 {DEFAULT_MAX_TOKENS} 사용",
              file=sys.stderr)

    base_url = section.get("base_url")
    if isinstance(base_url, str) and base_url.strip():
        cfg["base_url"] = base_url.strip()
    elif base_url is not None:
        print(f"  [llm_client] llm.base_url={base_url!r} 무효 — 기본값 사용", file=sys.stderr)

    if cfg["engine"] == "openai":
        _apply_openai_defaults(cfg)

    return cfg


def _apply_openai_defaults(cfg: dict) -> None:
    """engine=openai 인데 anthropic 쪽 기본값이 남아 있으면 교정한다.

    model 을 적지 않은 학생이 Anthropic 모델명으로 OpenRouter 를 호출해 조용히 404 를
    받는 일이 없어야 한다. 교정했다는 사실은 stderr 로 알린다(조용한 실패 금지, Rule 8).
    """
    if cfg.get("model") == DEFAULT_MODEL:
        cfg["model"] = DEFAULT_OPENAI_MODEL
        print(f"  [llm_client] engine=openai 인데 llm.model 이 없어 {DEFAULT_OPENAI_MODEL} 를 씁니다",
              file=sys.stderr)
    if cfg.get("api_key_env") == DEFAULT_API_KEY_ENV:
        cfg["api_key_env"] = DEFAULT_OPENAI_API_KEY_ENV
        print(f"  [llm_client] engine=openai 인데 llm.api_key_env 가 없어 "
              f"{DEFAULT_OPENAI_API_KEY_ENV} 를 씁니다", file=sys.stderr)
    cfg.setdefault("base_url", DEFAULT_OPENAI_BASE_URL)


def _resolve_config(config: dict | None) -> dict:
    """호출부가 dict 를 넘기면 그대로, None 이면 schema/config.yaml 을 로드."""
    if isinstance(config, dict):
        return config
    return load_llm_config()


def resolve_engine(config: dict | None = None) -> str:
    """분기 엔진 문자열('cli'|'api')을 돌려준다(availability 게이트용)."""
    return _resolve_config(config).get("engine", DEFAULT_ENGINE)


# ---------------------------------------------------------------------------
# subprocess 수명 관리 (wiki_app/api.py 에서 이관 — api.py 가 re-export)
# ---------------------------------------------------------------------------


def _kill_process_group(proc) -> bool:
    """proc 의 process group 전체를 SIGKILL. 성공 시 True.

    pid 없음(fake proc)·getpgid/killpg 실패 시 False 를 돌려 호출자가
    proc.kill() 로 fallback 하게 한다.
    """
    pid = getattr(proc, "pid", None)
    if pid is None:
        return False
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
        return True
    except (ProcessLookupError, PermissionError, OSError, AttributeError):
        return False


async def _terminate_proc(proc) -> None:
    """proc(+descendant) 이 살아있으면 종료 후 wait — 좀비/누적/누수 방지.

    timeout·error·disconnect·정상 종료 어디서 호출돼도 안전(idempotent):
    이미 종료된 proc(returncode 설정됨)은 건드리지 않는다.

    child 를 start_new_session=True 로 띄웠으므로 child 는 자기 process group 의
    leader 다. os.killpg 로 group 전체를 SIGKILL 해 claude 가 spawn 한 descendant
    까지 정리한다. group kill 이 실패하면 graceful 하게 proc.kill() 로 fallback 한다.
    """
    if proc is None:
        return
    if proc.returncode is None:
        if not _kill_process_group(proc):
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        try:
            async with asyncio.timeout(10):
                await proc.wait()
        except (asyncio.TimeoutError, ProcessLookupError):
            pass


def _build_cli_prompt_argv(prompt: str) -> list[str]:
    return ["claude", "-p", prompt]


# ---------------------------------------------------------------------------
# anthropic (api 엔진) — 지연 import + 키 검증
# ---------------------------------------------------------------------------


def _import_anthropic():
    """anthropic 을 지연 import. 부재 시 친절한 LLMError(cli 는 anthropic 불요)."""
    try:
        import anthropic  # noqa: PLC0415  (지연 import 의도)
    except ImportError as exc:  # pragma: no cover — 설치 환경에선 도달 안 함
        raise LLMError(
            "api 엔진에 필요한 `anthropic` 패키지가 설치돼 있지 않습니다. "
            "`pip install anthropic` 하거나 config 의 engine 을 cli 로 두세요."
        ) from exc
    return anthropic


def _require_api_key(config: dict, *, engine: str = "api") -> str:
    """엔진용 API 키를 env 에서 읽는다. 부재 시 명확한 LLMError(조용한 실패 금지)."""
    default_env = DEFAULT_OPENAI_API_KEY_ENV if engine == "openai" else DEFAULT_API_KEY_ENV
    env_name = config.get("api_key_env") or default_env
    key = os.environ.get(env_name)
    if not key:
        raise LLMError(
            f"{engine} 엔진에 필요한 환경변수 {env_name} 가 설정돼 있지 않습니다. "
            f"키를 설정하거나 config 의 engine 을 cli 로 두세요."
        )
    return key


def _import_openai():
    """openai 를 지연 import. 부재 시 친절한 LLMError(cli/api 는 openai 불요)."""
    try:
        import openai  # noqa: PLC0415  (지연 import 의도)
    except ImportError as exc:  # pragma: no cover — 설치 환경에선 도달 안 함
        raise LLMError(
            "openai 엔진에 필요한 `openai` 패키지가 설치돼 있지 않습니다. "
            "`pip install openai` 하거나 config 의 engine 을 cli 로 두세요."
        ) from exc
    return openai


# ---------------------------------------------------------------------------
# 비스트림: call_llm
# ---------------------------------------------------------------------------


async def _call_cli(prompt: str, *, timeout: int) -> str:
    """`claude -p` subprocess 로 답변 텍스트를 얻는다 (기존 비스트림 로직)."""
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *_build_cli_prompt_argv(prompt),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    finally:
        await _terminate_proc(proc)
    return stdout.decode("utf-8", errors="replace").strip()


async def _call_api(prompt: str, *, config: dict, max_tokens: int | None, timeout: int) -> str:
    """anthropic SDK 로 답변 텍스트를 얻는다. sync client 를 thread 로 오프로드.

    timeout 은 cli 경로와 **동일 계약**으로 이중 적용한다(Codex 적대리뷰 high):
    - SDK client 의 `timeout=` 으로 실제 네트워크 호출을 취소 가능하게 해 worker thread
      가 hang 에 무기한 붙잡히지 않게 한다.
    - `asyncio.wait_for` 로 await 자체를 deadline 에 묶어, SDK 가 늦게 풀리더라도 호출부
      (wiki_app)가 cli 와 동일한 `asyncio.TimeoutError` 를 같은 시점에 받는다.
    """
    anthropic = _import_anthropic()
    key = _require_api_key(config)
    model = config.get("model", DEFAULT_MODEL)
    tokens = max_tokens if max_tokens is not None else config.get("max_tokens", DEFAULT_MAX_TOKENS)

    def _do() -> str:
        client = anthropic.Anthropic(api_key=key, timeout=timeout)
        resp = client.messages.create(
            model=model,
            max_tokens=tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = [
            getattr(block, "text", "")
            for block in resp.content
            if getattr(block, "type", None) == "text"
        ]
        return "".join(parts).strip()

    return await asyncio.wait_for(asyncio.to_thread(_do), timeout=timeout)


async def _call_openai(prompt: str, *, config: dict, max_tokens: int | None, timeout: int) -> str:
    """OpenAI 호환 서버(chat.completions)로 답변 텍스트를 얻는다.

    timeout 은 cli/api 와 **동일 계약**으로 이중 적용한다 — SDK `timeout=` 으로 네트워크
    호출을 취소 가능하게 하고, `asyncio.wait_for` 로 await 자체를 deadline 에 묶어
    호출부가 세 엔진에서 같은 시점에 같은 `asyncio.TimeoutError` 를 받게 한다.
    """
    openai = _import_openai()
    key = _require_api_key(config, engine="openai")
    model = config.get("model", DEFAULT_OPENAI_MODEL)
    base_url = config.get("base_url", DEFAULT_OPENAI_BASE_URL)
    tokens = max_tokens if max_tokens is not None else config.get("max_tokens", DEFAULT_MAX_TOKENS)

    def _do() -> str:
        client = openai.OpenAI(api_key=key, base_url=base_url, timeout=timeout)
        resp = client.chat.completions.create(
            model=model,
            max_tokens=tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        choices = getattr(resp, "choices", None) or []
        if not choices:
            raise LLMError(
                f"{model} 응답에 선택지가 없습니다 — 모델명이 맞는지, 키 한도가 남았는지 확인하세요."
            )
        text = (getattr(choices[0].message, "content", "") or "").strip()
        if not text:
            # 빈 문자열을 성공으로 돌려주면 호출부는 "답이 없는 답"을 정상으로 취급한다.
            # 한도 초과·필터링·잘린 응답이 조용한 빈 화면으로 끝나면 안 된다.
            reason = getattr(choices[0], "finish_reason", None)
            raise LLMError(
                f"{model} 이 빈 응답을 돌려줬습니다"
                + (f" (finish_reason={reason})" if reason else "")
                + " — 모델명·키 한도·입력 길이를 확인하세요."
            )
        return text

    return await asyncio.wait_for(asyncio.to_thread(_do), timeout=timeout)


async def call_llm(
    prompt: str,
    *,
    config: dict | None = None,
    max_tokens: int | None = None,
    timeout: int | None = None,
) -> str:
    """엔진(cli|api)으로 분기해 프롬프트에 대한 답변 텍스트를 돌려준다(양 모드 동일 형식).

    - cli: `claude -p` subprocess (timeout 로 hang 방어; 종료 시 process-group 정리).
    - api: anthropic SDK(messages.create). 키 env 부재/패키지 부재는 LLMError.

    예외: cli timeout 은 asyncio.TimeoutError 로 전파(호출부가 timeout 처리),
    그 외 오류는 원 예외/LLMError 로 전파(조용한 실패 금지).
    """
    cfg = _resolve_config(config)
    deadline = timeout if timeout is not None else DEFAULT_CLI_TIMEOUT
    engine = cfg.get("engine", DEFAULT_ENGINE)
    if engine == "openai":
        return await _call_openai(prompt, config=cfg, max_tokens=max_tokens, timeout=deadline)
    if engine == "api":
        return await _call_api(prompt, config=cfg, max_tokens=max_tokens, timeout=deadline)
    return await _call_cli(prompt, timeout=deadline)


# ---------------------------------------------------------------------------
# 스트림: stream_llm
# ---------------------------------------------------------------------------


async def _stream_api(prompt: str, *, config: dict, idle_timeout: int) -> AsyncIterator[str]:
    """anthropic SDK 스트리밍(messages.create stream=True) — 텍스트 델타만 yield.

    sync 이벤트 이터레이터를 thread 로 한 이벤트씩 당겨 async 로 브릿지한다.

    idle_timeout 은 cli 스트림과 **동일 계약**으로 `_open`·`_next` 양쪽 thread 호출을
    `asyncio.wait_for` 로 감싼다(Codex 적대리뷰 high): 첫 이벤트 전이든 이벤트 사이든
    Anthropic stream 이 멈추면 event 반환을 기다리지 않고 `asyncio.TimeoutError` 로 풀려,
    바깥 SSE 핸들러가 error 이벤트·episode 최종상태를 남길 수 있게 한다. SDK client 의
    `timeout=` 도 병행해 배후 네트워크 호출 자체를 취소 가능하게 한다.
    """
    anthropic = _import_anthropic()
    key = _require_api_key(config)
    model = config.get("model", DEFAULT_MODEL)
    tokens = config.get("max_tokens", DEFAULT_MAX_TOKENS)

    def _open():
        client = anthropic.Anthropic(api_key=key, timeout=idle_timeout)
        return iter(client.messages.create(
            model=model,
            max_tokens=tokens,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
        ))

    sentinel = object()

    def _next(it):
        try:
            return next(it)
        except StopIteration:
            return sentinel

    it = await asyncio.wait_for(asyncio.to_thread(_open), timeout=idle_timeout)
    while True:
        event = await asyncio.wait_for(asyncio.to_thread(_next, it), timeout=idle_timeout)
        if event is sentinel:
            break
        if getattr(event, "type", None) == "content_block_delta":
            delta = getattr(event, "delta", None)
            text = getattr(delta, "text", None)
            if text:
                yield text


async def _stream_openai(prompt: str, *, config: dict, idle_timeout: int) -> AsyncIterator[str]:
    """OpenAI 호환 서버 스트리밍 — 텍스트 델타만 yield.

    idle_timeout 계약은 cli/api 스트림과 같다: `_open`·`_next` 양쪽 thread 호출을
    `asyncio.wait_for` 로 감싸, 첫 이벤트 전이든 이벤트 사이든 멈추면
    `asyncio.TimeoutError` 로 풀려 바깥 SSE 핸들러가 error 이벤트를 남길 수 있다.
    """
    openai = _import_openai()
    key = _require_api_key(config, engine="openai")
    model = config.get("model", DEFAULT_OPENAI_MODEL)
    base_url = config.get("base_url", DEFAULT_OPENAI_BASE_URL)
    tokens = config.get("max_tokens", DEFAULT_MAX_TOKENS)

    def _open():
        client = openai.OpenAI(api_key=key, base_url=base_url, timeout=idle_timeout)
        return iter(client.chat.completions.create(
            model=model,
            max_tokens=tokens,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
        ))

    sentinel = object()

    def _next(it):
        try:
            return next(it)
        except StopIteration:
            return sentinel

    it = await asyncio.wait_for(asyncio.to_thread(_open), timeout=idle_timeout)
    yielded = False
    while True:
        event = await asyncio.wait_for(asyncio.to_thread(_next, it), timeout=idle_timeout)
        if event is sentinel:
            break
        choices = getattr(event, "choices", None) or []
        if not choices:
            continue
        delta = getattr(choices[0], "delta", None)
        text = getattr(delta, "content", None)
        if text:
            yielded = True
            yield text
    if not yielded:
        # 텍스트 청크가 하나도 없이 끝났다. 호출부에는 "정상 완료"로 보이지만
        # 화면에는 빈 답이 남는다. 한도 초과·필터링·잘린 응답을 구분할 수 있어야 한다.
        raise LLMError(
            f"{model} 스트림이 아무 내용 없이 끝났습니다 — "
            "모델명·키 한도·입력 길이를 확인하세요."
        )


async def stream_llm(
    prompt: str,
    *,
    config: dict | None = None,
    idle_timeout: int | None = None,
) -> AsyncIterator[str]:
    """엔진(cli|api)으로 분기해 답변을 텍스트 청크로 스트리밍한다.

    호출부(wiki_app/api.py)가 SSE 계약(event: chunk/done/error·deadline·cap)을
    바깥에서 감싼다. 이 제너레이터는 청크 소스 + subprocess 수명만 책임진다.

    cli 분기는 subprocess 수명을 이 제너레이터의 finally 에 **직접** 담는다 —
    호출부가 조기 종료(deadline/cap) 후 `aclose()` 하면 이 finally 가 즉시 실행돼
    child 를 process-group 종료한다(중첩 async-for 위임은 aclose 시 내부 finally 가
    지연돼 좀비를 남길 수 있어 인라인한다).

    cli 세부:
    - stderr 를 stdout 과 *동시* drain 해 stderr 파이프 버퍼 데드락 방지.
    - readline 에 idle timeout(줄 사이 hang 방어) — TimeoutError 는 호출부로 전파.
    - EOF 후 returncode≠0 이면 stderr 메시지를 담은 LLMError 를 raise(표면화).
    """
    cfg = _resolve_config(config)
    idle = idle_timeout if idle_timeout is not None else DEFAULT_CLI_STREAM_IDLE_TIMEOUT
    engine = cfg.get("engine", DEFAULT_ENGINE)
    if engine == "openai":
        async for chunk in _stream_openai(prompt, config=cfg, idle_timeout=idle):
            yield chunk
        return
    if engine == "api":
        async for chunk in _stream_api(prompt, config=cfg, idle_timeout=idle):
            yield chunk
        return

    proc = None
    stderr_task = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *_build_cli_prompt_argv(prompt),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        assert proc.stderr is not None
        stderr_task = asyncio.create_task(proc.stderr.read())
        assert proc.stdout is not None
        while True:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=idle)
            if not line:
                break
            yield line.decode("utf-8", errors="replace")
        # stdout EOF — 종료 대기 후 동시 drain 한 stderr 회수
        await proc.wait()
        stderr_bytes = await stderr_task
        if proc.returncode not in (0, None):
            msg = stderr_bytes.decode("utf-8", errors="replace").strip() \
                or f"claude exited with code {proc.returncode}"
            raise LLMError(msg)
    finally:
        await _terminate_proc(proc)
        if stderr_task is not None and not stderr_task.done():
            stderr_task.cancel()
            try:
                await stderr_task
            except (asyncio.CancelledError, Exception):
                pass
