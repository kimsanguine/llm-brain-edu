#!/usr/bin/env python3
"""doctor.py — llm-brain 설치 진단·수정.

점검: 필수 디렉토리 · 스크립트(메모리 OS 포함) · 커맨드 · 설정(config/sources) ·
의존성 · claude CLI. `--fix`는 누락 디렉토리 생성 + `sources.example.yaml` →
`sources.yaml` 복사(없을 때만). **기존 파일은 절대 덮어쓰지 않는다**(Rule 9).

사용: `uv run python scripts/doctor.py [--fix]`
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import shlex
import shutil
from pathlib import Path


def detect_repo_root(script_file: Path | None = None) -> Path:
    """Resolve the repository from this script, never from the caller's cwd."""
    script = Path(script_file or __file__).resolve()
    root = script.parent.parent
    if not (root / "scripts" / "doctor.py").is_file() or not (root / "pyproject.toml").is_file():
        raise RuntimeError(f"llm-brain repository root not found from {script}")
    return root


ROOT = detect_repo_root()

REQUIRED_DIRS = ["schema", "scripts", "commands", "procedures", "examples"]
PERSONAL_DATA_DIRS = ["raw", "wiki"]
RAW_SUBDIRS = ["til", "meetings", "notes", "clippings", "docs", "blog", "newsletters"]
REQUIRED_SCRIPTS = [
    "ingest.py", "curate.py", "express.py", "okf_export.py", "export_graph.py",
    "sync_raw.py", "episode.py", "brain_context.py", "memory_health.py",
    "procedures.py", "lib/frontmatter_utils.py",
]
REQUIRED_COMMANDS = ["ingest.md", "curate.md", "express.md", "query.md", "okf.md", "doctor.md", "wikiweb.md"]
REQUIRED_DEPS = [
    ("yaml", "pyyaml"), ("fastapi", "fastapi"), ("uvicorn", "uvicorn"),
    ("httpx", "httpx"), ("frontmatter", "python-frontmatter"),
]

GUIDED_PROFILES = ("Demo", "Personal-private", "Share-ready")


def _r(name: str, status: str, detail: str = "") -> dict:
    return {"name": name, "status": status, "detail": detail}


def run_checks(root: Path = ROOT, *, fix: bool = False) -> list[dict]:
    """설치 점검 결과 리스트. status ∈ {OK, WARN, FAIL, FIXED}."""
    root = Path(root)
    results: list[dict] = []

    # 1. 필수 디렉토리 (없으면 FAIL, --fix로 생성)
    for d in REQUIRED_DIRS:
        p = root / d
        if p.is_dir():
            results.append(_r(f"dir:{d}", "OK"))
        elif fix:
            p.mkdir(parents=True, exist_ok=True)
            results.append(_r(f"dir:{d}", "FIXED", "생성됨"))
        else:
            results.append(_r(f"dir:{d}", "FAIL", "디렉토리 없음 (--fix로 생성)"))

    # Personal data is intentionally excluded from the public repository.
    # A fresh clone remains usable after setup, so absence is actionable but
    # not an installation failure.
    for d in PERSONAL_DATA_DIRS:
        p = root / d
        if p.is_dir():
            results.append(_r(f"dir:{d}", "OK"))
        elif fix:
            p.mkdir(parents=True, exist_ok=True)
            results.append(_r(f"dir:{d}", "FIXED", "개인 데이터 디렉토리 생성됨"))
        else:
            results.append(_r(f"dir:{d}", "WARN", "개인 데이터 미초기화 (--fix로 생성)"))

    # 2. raw 하위 (없으면 WARN, --fix로 생성)
    for sub in RAW_SUBDIRS:
        p = root / "raw" / sub
        if p.is_dir():
            results.append(_r(f"raw/{sub}", "OK"))
        elif fix:
            p.mkdir(parents=True, exist_ok=True)
            results.append(_r(f"raw/{sub}", "FIXED", "생성됨"))
        else:
            results.append(_r(f"raw/{sub}", "WARN", "raw 하위 없음 (--fix로 생성)"))

    # 3. 스크립트(메모리 OS 포함) — 없으면 FAIL(설치/업데이트 필요)
    for s in REQUIRED_SCRIPTS:
        ok = (root / "scripts" / s).is_file()
        results.append(_r(f"script:{s}", "OK" if ok else "FAIL",
                          "" if ok else "스크립트 없음 — 플러그인 재설치/업데이트 필요"))

    # 4. 커맨드 — 없으면 FAIL
    for c in REQUIRED_COMMANDS:
        ok = (root / "commands" / c).is_file()
        results.append(_r(f"cmd:{c}", "OK" if ok else "FAIL",
                          "" if ok else "커맨드 파일 없음"))

    # 5. 설정 (gitignored — 없으면 WARN, --fix로 example 복사)
    cfg = root / "schema" / "config.yaml"
    results.append(_r("config.yaml", "OK" if cfg.is_file() else "WARN",
                      "" if cfg.is_file() else "schema/config.yaml 없음 (LLM 엔진 설정)"))
    src = root / "schema" / "sources.yaml"
    example = root / "schema" / "sources.example.yaml"
    if src.is_file():
        results.append(_r("sources.yaml", "OK"))
    elif fix and example.is_file():
        shutil.copy(example, src)  # 기존 부재 시에만 — 위 is_file 분기로 덮어쓰기 차단
        results.append(_r("sources.yaml", "FIXED", "sources.example.yaml에서 복사"))
    else:
        results.append(_r("sources.yaml", "WARN", "schema/sources.yaml 없음 (--fix로 example 복사)"))

    # 6. 의존성 (import 가능 여부) — 없으면 FAIL
    for mod, pkg in REQUIRED_DEPS:
        ok = importlib.util.find_spec(mod) is not None
        results.append(_r(f"dep:{pkg}", "OK" if ok else "FAIL",
                          "" if ok else f"{pkg} 미설치 — `uv sync` 실행"))

    # 7. claude CLI — **cli 엔진일 때만** 필요. api/openai 엔진에는 무관하므로
    #    없다고 경고하지 않는다(무관한 경고는 초보자에게 "내가 뭘 잘못했다"로 읽힌다).
    engine = _configured_engine(root)
    # 오타는 print 가 아니라 결과 목록에 올린다. 화면 위에 경고가 있는데 요약이
    # "⚠️ 0" 이면 학생은 어느 쪽을 믿어야 할지 알 수 없다.
    raw_engine = _raw_engine(root)
    if raw_engine and raw_engine.strip() not in ("cli", "api", "openai"):
        results.append(_r("config-engine", "WARN",
                          f"llm.engine={raw_engine!r} 은 알 수 없는 값 — "
                          f"cli 로 동작합니다 (cli · api · openai 중 하나로 고치세요)"))
    if engine == "openai":
        # openai SDK 가 없어도 compile 은 RULE 경로로 완주한다. 그래서 FAIL 이 아니라
        # WARN 이되, 키를 넣고도 LIVE 가 안 도는 이유를 여기서 알 수 있어야 한다.
        has_sdk = importlib.util.find_spec("openai") is not None
        results.append(_r("openai-sdk", "OK" if has_sdk else "WARN",
                          "" if has_sdk else "openai 미설치 — `uv sync` 하세요 "
                                             "(없어도 RULE 경로로 위키는 만들어집니다)"))
        # 검사할 환경변수 이름은 config 가 정한다. 하드코딩하면 조별·사내 서버 설정에서
        # 키가 있는데 없다고 하거나, 없는데 있다고 한다.
        env_name = _configured_key_env(root)
        has_key = bool(os.environ.get(env_name))
        results.append(_r("openrouter-key", "OK" if has_key else "WARN",
                          "" if has_key else
                          f"{env_name} 없음 — 없어도 설치는 완료입니다(RULE 경로로 동작)"))
    if engine == "cli":
        has_claude = shutil.which("claude") is not None
        results.append(_r("claude-cli", "OK" if has_claude else "WARN",
                          "" if has_claude else "claude CLI 없음 — cli 엔진(기본) 사용 시 필요"))

    return results


def _configured_engine(root: Path) -> str:
    """schema/config.yaml 의 `llm.engine` 을 읽는다. 부재·오류 시 기본값 cli.

    llm_client 를 import 하지 않는다 — doctor 는 의존성이 깨진 상태에서도 돌아야 한다.
    """
    cfg = root / "schema" / "config.yaml"
    if not cfg.is_file():
        return "cli"
    try:
        import yaml  # noqa: PLC0415 (지연 import — pyyaml 미설치도 doctor 는 돌아야 한다)
        raw = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    except Exception:
        return "cli"
    section = raw.get("llm") if isinstance(raw, dict) else None
    engine = section.get("engine") if isinstance(section, dict) else None
    if isinstance(engine, str) and engine.strip() in ("cli", "api", "openai"):
        return engine.strip()
    return "cli"


def _raw_engine(root: Path) -> str | None:
    """config 에 적힌 engine 원본(검증 전). 오타를 결과 목록에 올리기 위해 쓴다."""
    cfg = root / "schema" / "config.yaml"
    if not cfg.is_file():
        return None
    try:
        import yaml  # noqa: PLC0415

        raw = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    section = raw.get("llm") if isinstance(raw, dict) else None
    v = section.get("engine") if isinstance(section, dict) else None
    return v if isinstance(v, str) else None


def _configured_key_env(root: Path) -> str:
    """config 의 llm.api_key_env. 없으면 OpenRouter 기본값."""
    cfg = root / "schema" / "config.yaml"
    if not cfg.is_file():
        return "OPENROUTER_API_KEY"
    try:
        import yaml  # noqa: PLC0415

        raw = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    except Exception:
        return "OPENROUTER_API_KEY"
    section = raw.get("llm") if isinstance(raw, dict) else None
    name = section.get("api_key_env") if isinstance(section, dict) else None
    return name.strip() if isinstance(name, str) and name.strip() else "OPENROUTER_API_KEY"


def render_guided(root: Path, profile: str | None = None) -> str:
    """Render a read-only profile choice or one explicit next action."""
    root = Path(root).resolve()
    lines = ["=== llm-brain guided setup ===", f"Repository root: {root}"]
    if profile is None:
        lines.append("Profiles:")
        lines.extend(f"  - {name}" for name in GUIDED_PROFILES)
        lines.append("Select with: --guided --profile {demo|personal-private|share-ready}")
        return "\n".join(lines)

    if profile == "demo":
        action = (
            "Run this installation verification (no browser UI) against "
            f"{root / 'examples' / 'seed-wiki' / 'wiki'}: "
            f"cd {shlex.quote(str(root))} && uv run python -c \"from pathlib import Path; "
            "from wiki_app.api import create_app; "
            "create_app(wiki_root=Path('examples/seed-wiki/wiki')); "
            "print('Demo installation verification OK')\""
        )
        label = "Demo"
    elif profile == "personal-private":
        user_sources = root / "schema" / "sources.yaml"
        preview_path = (
            user_sources
            if user_sources.is_file()
            else root / "schema" / "sources.example.yaml"
        )
        sources = shlex.quote(str(preview_path))
        subject = (
            "user-managed sources config"
            if user_sources.is_file()
            else "sources config template"
        )
        action = f"Preview the {subject} only: sed -n '1,200p' {sources}"
        label = "Personal-private"
    else:
        share_command = (
            f"cd {shlex.quote(str(root))} && uv run python scripts/okf_export.py "
            "--share --approve-share I_ACKNOWLEDGE_SHARE_READY_EXPORT"
        )
        action = (
            "After confirming canonical schema/okf_export.yaml, local security config "
            "schema/okf_export.local.yaml, and explicit scope: shared|private on every "
            f"candidate, run: {share_command}"
        )
        label = "Share-ready"
    lines.extend([f"Profile: {label}", f"Next action: {action}"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="llm-brain 설치 진단·수정")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fix", action="store_true",
                      help="누락 디렉토리 생성 + sources 설정 복사(안전 — 기존 파일 미덮어씀)")
    mode.add_argument("--guided", action="store_true",
                      help="읽기 전용 운영 프로필 안내")
    parser.add_argument(
        "--profile",
        choices=("demo", "personal-private", "share-ready"),
        help="--guided에서 선택할 운영 프로필",
    )
    args = parser.parse_args(argv)

    if args.profile and not args.guided:
        parser.error("--profile requires --guided")
    if args.guided:
        print(render_guided(ROOT, args.profile))
        return 0

    results = run_checks(fix=args.fix)
    icon = {"OK": "✅", "FIXED": "🔧", "WARN": "⚠️", "FAIL": "❌"}
    fails = [r for r in results if r["status"] == "FAIL"]
    warns = [r for r in results if r["status"] == "WARN"]
    fixed = [r for r in results if r["status"] == "FIXED"]
    ok_n = sum(1 for r in results if r["status"] == "OK")

    print("=== llm-brain doctor ===")
    for r in results:
        if r["status"] != "OK":  # 비-OK 항목만 상세 출력
            print(f"  {icon[r['status']]} {r['name']}: {r['detail']}")
    summary = f"\n요약: ✅ {ok_n} · ⚠️ {len(warns)} · ❌ {len(fails)}"
    if args.fix:
        summary += f" · 🔧 {len(fixed)} 수정"
    print(summary)

    if fails:
        print("❌ 설치 문제 — 위 FAIL 항목 해결 필요(디렉토리는 `doctor --fix`, 의존성은 `uv sync`).")
        return 1
    print("✅ 설치 정상." + (" (⚠️ 항목은 선택/환경별 — 필요 시 안내대로)" if warns else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
