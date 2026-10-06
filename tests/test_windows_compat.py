"""윈도우에서 깨지던 두 가지가 다시 생기지 않도록 지킨다(2026-10-06 코드 점검, 맥에서 cp949 환경을 흉내 내 재현).

1. `fcntl` 은 유닉스 전용이라 윈도우에서 `import fcntl` 이 실패해 `curate.py` 와 웹 서버(`wiki_app`)가 시작되지 못한다.
2. 인코딩을 지정하지 않은 파일 읽기/쓰기는 한국어 윈도우의 기본 인코딩(cp949)으로 동작해, UTF-8 로 저장한
   한글 메모를 읽다가 `UnicodeDecodeError` 가 난다(`curate --audit` 에서 재현).
"""
import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _text_io_without_encoding():
    """텍스트 모드로 파일을 읽고 쓰는데 encoding 을 적지 않은 호출(파일, 줄)."""
    found = []
    for folder in ("scripts", "wiki_app"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = getattr(func, "attr", getattr(func, "id", ""))
                owner = getattr(getattr(func, "value", None), "id", "")
                if "encoding" in {k.arg for k in node.keywords}:
                    continue
                if name in ("read_text", "write_text"):
                    found.append((path.relative_to(ROOT).as_posix(), node.lineno))
                elif name == "open" and owner not in {"os", "pymupdf", "webbrowser", "Image", "zipfile", "tarfile"}:
                    mode = None
                    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                        mode = node.args[1].value
                    if isinstance(func, ast.Attribute) and node.args and isinstance(node.args[0], ast.Constant):
                        mode = node.args[0].value          # Path.open("a")
                    for k in node.keywords:
                        if k.arg == "mode" and isinstance(k.value, ast.Constant):
                            mode = k.value.value
                    if "b" not in str(mode or ""):
                        found.append((path.relative_to(ROOT).as_posix(), node.lineno))
    return found


def test_every_text_file_read_and_write_names_its_encoding():
    """깨지면: 한국어 윈도우(cp949)에서 UTF-8 한글 메모를 읽다가 오류가 나거나 글자가 깨진다."""
    assert _text_io_without_encoding() == []


@pytest.mark.parametrize("module_code", [
    "import curate; print(curate.fcntl)",
    "import sys; sys.path.insert(0, '.'); from wiki_app import access; print(access.fcntl)",
])
def test_modules_import_when_fcntl_is_missing(module_code):
    """깨지면: 윈도우에서 curate 와 웹 서버가 import 단계에서 ModuleNotFoundError 로 죽는다."""
    code = "import sys; sys.modules['fcntl'] = None; sys.path.insert(0, 'scripts'); " + module_code
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "None"


def test_access_counter_still_updates_without_fcntl(tmp_path):
    """fcntl 없이도(윈도우) 접근 횟수 갱신이 동작한다. 프로세스 사이 잠금만 건너뛴다."""
    code = (
        "import sys; sys.modules['fcntl'] = None; sys.path.insert(0, 'scripts'); import curate, pathlib; "
        f"p = pathlib.Path(r'{tmp_path}') / 'wiki_stats.json'; "
        "print(curate.update_stats_access('alpha', p), curate.update_stats_access('alpha', p))"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["1", "2"]
