"""test_ocr_option — 스캔본 PDF 글자 인식(OCR) 선택 옵션의 계약.

OCR 은 기본 설치에 없는 선택 기능이다(`uv sync --extra ocr` + Tesseract 프로그램).
핵심은 두 가지다: (1) 있으면 스캔본이 위키가 되고, (2) 없으면 기존처럼 이유와 선택지를 알리며
기본 동작을 절대 깨뜨리지 않는다.

각 테스트는 "이게 깨지면 사용자에게 무슨 일이 일어나는가"를 적는다.
"""
import shutil
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import compile as compile_mod  # noqa: E402
import ingest  # noqa: E402

pymupdf = pytest.importorskip("pymupdf")
PIL_Image = pytest.importorskip("PIL.Image")
from PIL import ImageDraw  # noqa: E402


def _scanned_pdf(path: Path, pages: int = 1):
    """글자 레이어가 없는 PDF: 쪽마다 글자를 그림으로만 넣는다."""
    doc = pymupdf.open()
    for i in range(pages):
        png = path.with_name(f"{path.stem}-{i}.png")
        im = PIL_Image.new("RGB", (600, 200), "white")
        ImageDraw.Draw(im).text((30, 80), f"scanned receipt page {i + 1}", fill="black")
        im.save(png)
        page = doc.new_page(width=600, height=200)
        page.insert_image(page.rect, filename=str(png))
    doc.save(str(path))


def _text_pdf(path: Path):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "Quarterly report with a real text layer.", fontsize=14)
    doc.save(str(path))


def _fake_tesseract(monkeypatch, text="Scanned receipt 4500 won", langs=("eng", "kor", "osd")):
    """pytesseract 와 tesseract 프로그램이 있는 것처럼 꾸민다(실제 인식은 하지 않는다)."""
    calls = []
    fake = types.SimpleNamespace(
        get_languages=lambda config="": list(langs),
        image_to_string=lambda image, lang="eng": calls.append(lang) or text,
    )
    monkeypatch.setitem(sys.modules, "pytesseract", fake)
    monkeypatch.setattr(ingest.shutil, "which", lambda name: "/usr/bin/tesseract")
    return calls


def _no_ocr(monkeypatch):
    monkeypatch.setitem(sys.modules, "pytesseract", None)      # import 시 ImportError


@pytest.fixture
def brain(tmp_path, monkeypatch):
    (tmp_path / "raw" / "docs").mkdir(parents=True)
    (tmp_path / "raw" / "notes").mkdir(parents=True)
    monkeypatch.setattr(ingest, "WIKI_ROOT", tmp_path)
    monkeypatch.setattr(ingest, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(ingest, "STATE_FILE", tmp_path / ".ingest_state.json")
    for name, value in {"ROOT": tmp_path, "WIKI_DIR": tmp_path / "wiki",
                        "INDEX_FILE": tmp_path / "index.md", "SEED_DIR": tmp_path / "seed"}.items():
        monkeypatch.setattr(compile_mod, name, value)
    monkeypatch.setattr(compile_mod, "CATEGORIES", ["concepts"])
    monkeypatch.setitem(sys.modules, "export_graph", types.SimpleNamespace(main=lambda: 0))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(compile_mod.llm_client, "load_llm_config",
                        lambda *a, **k: {"engine": "openai", "api_key_env": "OPENAI_API_KEY"})
    return tmp_path


def _compile(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["compile.py", *argv])
    return compile_mod.main()


# ── 선택 설치가 없을 때: 기본 동작은 그대로, 안내만 정확히 ───────────────────────


def test_ocr_status_explains_what_is_missing(monkeypatch):
    """무엇이 빠졌는지(파이썬 패키지인지, Tesseract 프로그램인지) 정확히 알려 준다.

    깨지면: `uv sync --extra ocr` 만 하고 Tesseract 를 안 깐 사용자가 같은 안내를 반복해 본다.
    """
    _no_ocr(monkeypatch)
    ok, why = ingest.ocr_status()
    assert not ok and "--extra ocr" in why

    _fake_tesseract(monkeypatch)
    monkeypatch.setattr(ingest.shutil, "which", lambda name: None)
    ok, why = ingest.ocr_status()
    assert not ok and "Tesseract 프로그램" in why

    _fake_tesseract(monkeypatch)
    assert ingest.ocr_status() == (True, "")


def test_without_ocr_a_scanned_pdf_is_still_reported_with_install_choices(brain, tmp_path, monkeypatch, capsys):
    """OCR 이 없으면 스캔본은 이유와 설치 방법·다른 선택지를 안내하고 원본은 보존한다.

    깨지면: 선택 옵션이 있다는 사실을 몰라 OCR 이 필요한 사용자가 다른 도구를 찾아 헤맨다.
    """
    _no_ocr(monkeypatch)
    scan = tmp_path / "scan.pdf"
    _scanned_pdf(scan)
    saved = ingest.ingest_file(scan)
    out = capsys.readouterr().out
    assert saved.exists()
    assert "글자를 읽지 못했습니다" in out
    assert "uv sync --extra ocr" in out and "brew install tesseract" in out and "--note" in out
    assert not list((brain / "raw" / "docs").glob("*.extracted.md"))


def test_compile_lists_the_ocr_option_among_the_choices(brain, monkeypatch, capsys):
    """compile 의 읽기 실패 안내에 선택 설치와 다른 OCR 도구(PaddleOCR 등) 선택지가 있다."""
    _no_ocr(monkeypatch)
    _scanned_pdf(brain / "raw" / "docs" / "2026-10-06-scan.pdf")
    rc = _compile(monkeypatch)
    out = capsys.readouterr().out
    assert rc == 1
    assert "uv sync --extra ocr" in out and "PaddleOCR" in out and "--note" in out


def test_text_pdfs_never_touch_ocr(brain, tmp_path, monkeypatch):
    """글자가 있는 PDF 는 OCR 을 부르지 않는다(느리고 틀릴 수 있는 길을 타지 않는다).

    깨지면: 선택 설치를 한 사용자의 모든 PDF 가 느려지고 정확한 글자 대신 OCR 오탈자가 들어간다.
    """
    def boom(*a, **k):
        raise AssertionError("글자 레이어가 있는 PDF 에서 OCR 을 불렀다")

    monkeypatch.setitem(sys.modules, "pytesseract", types.SimpleNamespace(
        get_languages=boom, image_to_string=boom))
    monkeypatch.setattr(ingest.shutil, "which", lambda name: "/usr/bin/tesseract")
    report = tmp_path / "report.pdf"
    _text_pdf(report)
    assert "real text layer" in ingest.extract_text(report)


# ── 선택 설치가 있을 때: 스캔본이 위키가 된다 ─────────────────────────────────────


def test_with_ocr_a_scanned_pdf_becomes_a_wiki_page(brain, tmp_path, monkeypatch, capsys):
    """OCR 이 있으면 스캔본을 읽어 추출본을 만들고, 그것이 위키 페이지 1개가 된다.

    깨지면: 선택 옵션을 깔아도 스캔본이 여전히 위키에 못 들어간다.
    추출본 머리말에 `ocr: tesseract` 를 남겨, 나중에 읽는 사람이 OCR 결과임을 안다.
    """
    calls = _fake_tesseract(monkeypatch, text="Scanned receipt 4500 won")
    scan = tmp_path / "receipt.pdf"
    _scanned_pdf(scan)
    ingest.ingest_file(scan)
    out = capsys.readouterr().out
    assert "글자 인식(OCR)으로 읽었습니다" in out
    assert calls and set(calls) == {"kor+eng"}                 # 한국어 데이터가 있으면 한국어+영어
    sidecar = next((brain / "raw" / "docs").glob("*.extracted.md"))
    text = sidecar.read_text(encoding="utf-8")
    assert "ocr: tesseract" in text and "Scanned receipt 4500 won" in text

    assert _compile(monkeypatch, "--rule") == 0
    pages = list((brain / "wiki" / "concepts").glob("*.md"))
    assert len(pages) == 1                                      # 원본이 아니라 추출본 한 페이지


def test_ocr_falls_back_to_english_when_korean_data_is_missing(brain, tmp_path, monkeypatch):
    """한국어 데이터가 없으면 영어로만 읽고, 그래도 오류 없이 끝난다."""
    calls = _fake_tesseract(monkeypatch, langs=("eng", "osd"))
    scan = tmp_path / "s.pdf"
    _scanned_pdf(scan)
    assert "Scanned receipt" in ingest.extract_text(scan)
    assert set(calls) == {"eng"}


def test_ocr_reads_only_the_first_pages_and_says_so(brain, tmp_path, monkeypatch, capsys):
    """아주 긴 스캔본은 앞쪽만 읽고 그 사실을 알린다(몇 분씩 멈춘 듯 보이는 것을 막는다)."""
    calls = _fake_tesseract(monkeypatch)
    monkeypatch.setattr(ingest, "OCR_MAX_PAGES", 2)
    scan = tmp_path / "long.pdf"
    _scanned_pdf(scan, pages=4)
    ingest.extract_text(scan)
    assert len(calls) == 2
    assert "4쪽 중 앞 2쪽만" in capsys.readouterr().out


def test_ocr_that_finds_nothing_says_so_instead_of_the_install_hint(brain, tmp_path, monkeypatch, capsys):
    """OCR 이 있는데도 아무것도 못 읽었으면 "설치하라"고 하지 않고 사실대로 말한다."""
    _fake_tesseract(monkeypatch, text="   ")
    scan = tmp_path / "blank.pdf"
    _scanned_pdf(scan)
    ingest.ingest_file(scan)
    out = capsys.readouterr().out
    assert "OCR)까지 했지만 읽히지 않았습니다" in out
    assert "--extra ocr" not in out


# ── 실제 Tesseract(설치돼 있을 때만) ────────────────────────────────────────────

_REAL = shutil.which("tesseract") is not None
try:
    import pytesseract as _real_pytesseract  # noqa: F401
    _REAL = _REAL and "eng" in _real_pytesseract.get_languages(config="")
except Exception:
    _REAL = False


@pytest.mark.skipif(not _REAL, reason="Tesseract 와 pytesseract(`uv sync --extra ocr`)가 있을 때만")
def test_real_tesseract_reads_a_clean_english_scan(tmp_path, monkeypatch):
    """모의가 아니라 진짜 Tesseract 로 깨끗한 영어 스캔본을 읽는다."""
    monkeypatch.undo()                  # 앞 테스트의 모의 흔적이 남지 않게
    doc = pymupdf.open()
    from PIL import ImageFont
    font = ImageFont.load_default(size=40)
    im = PIL_Image.new("RGB", (900, 200), "white")
    ImageDraw.Draw(im).text((30, 70), "Scanned receipt 4500 won", font=font, fill="black")
    png = tmp_path / "r.png"
    im.save(png)
    page = doc.new_page(width=900, height=200)
    page.insert_image(page.rect, filename=str(png))
    pdf = tmp_path / "r.pdf"
    doc.save(str(pdf))
    assert "receipt" in ingest.extract_text(pdf).lower()


# ── 문서와 설정의 일치 ───────────────────────────────────────────────────────────


def test_ocr_is_an_optional_extra_documented_in_the_readmes():
    """OCR 은 선택 설치(extra)이고 README 가 같은 이름의 명령을 안내한다.

    깨지면: README 가 안내한 `uv sync --extra ocr` 가 없는 옵션이거나, 반대로 OCR 의존성이 기본
    설치에 끼어들어 모든 학생의 설치가 무거워진다(PaddleOCR 급이면 수백 MB).
    """
    import tomllib

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    extra = project["optional-dependencies"]["ocr"]
    assert any(d.startswith("pytesseract") for d in extra)
    assert not any("tesseract" in d.lower() or "paddle" in d.lower() for d in project["dependencies"])
    for readme in ("README.md", "README_수강생용.md"):
        assert "uv sync --extra ocr" in (ROOT / readme).read_text(encoding="utf-8"), readme
