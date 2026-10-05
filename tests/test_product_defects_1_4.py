"""test_product_defects_1_4 — 2026-10-06 튜토리얼 e2e에서 나온 제품 결함 4건의 회귀 테스트.

1. 웹 기사(URL)는 답변 근거가 될 수 없는데 그 사실을 알려 주지 않고, 거부 때 "claims build"를 권해 같은 자리로 돌려보냈다.
2. 웹 기사에 메뉴·푸터가 그대로 들어와 기사 1건이 claim 266개(대부분 메뉴 문장)가 됐다.
3. 글자 레이어가 없는 스캔본 PDF 가 ingest 에서 조용히 넘어가고 compile 에서야 이유 없이 실패했다.
4. 실제 논문 PDF 의 위키 제목이 첫 줄의 저작권 문구가 됐다.

각 테스트는 "이게 깨지면 사용자에게 무슨 일이 일어나는가"를 적는다.
"""
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import compile as compile_mod  # noqa: E402
import ingest  # noqa: E402
from lib import claim_ledger  # noqa: E402

pymupdf = pytest.importorskip("pymupdf")


# ── 공용 도우미 ──────────────────────────────────────────────────────────────

NEWS_HTML = """<html><head><title>BBC News - site</title>
<meta property="og:title" content="SEO용 소셜 제목"></head><body>
<header><nav><ul><li><a href="/">Home</a></li><li><a href="/news">News</a></li><li><a href="/sport">Sport</a></li></ul></nav></header>
<main><article>
<h1>호주 보고서: 게임 플랫폼은 아동 안전을 개선해야 한다</h1>
<p>호주 온라인 안전 위원회는 이번 주 보고서를 내고 포트나이트, 로블록스, 마인크래프트, 스팀이
아동 보호 장치를 더 강화해야 한다고 밝혔다. 보고서는 연령 확인과 신고 절차의 허점을 지적했다.</p>
<button>Share</button>
<p>위원회는 이르면 다음 분기에 점검 결과를 공개하고, 개선 계획이 부족한 업체에는 과태료를 물리겠다고 말했다.
업계는 대체로 지적을 수용하지만 구체적인 일정에는 말을 아꼈다. 전문가들은 연령 확인 기술이 아직
충분히 정확하지 않아 현실적인 개선에 시간이 걸릴 것이라고 평가했다.</p>
<aside>관련 기사: 다른 소식</aside>
</article></main>
<footer>Copyright 2026 Terms of Use Privacy Contact Us</footer></body></html>"""


def _write_pdf(path: Path, pages, *, rotated_stamp=False, title_meta=None, header=None):
    """pages: [(제목 글자크기, 제목, 본문)]. header 는 첫 쪽 맨 위 작은 안내문."""
    doc = pymupdf.open()
    for i, (size, title, body) in enumerate(pages):
        page = doc.new_page()
        if i == 0 and header:
            page.insert_textbox(pymupdf.Rect(72, 40, 520, 110), header, fontsize=11)
        if i == 0 and rotated_stamp:
            page.insert_text((30, 400), "arXiv:1706.03762v7 [cs.CL] 2 Aug 2023", fontsize=20, rotate=90)
        page.insert_text((72, 150), title, fontsize=size)
        page.insert_textbox(pymupdf.Rect(72, 190, 520, 400), body, fontsize=10)
    if title_meta:
        doc.set_metadata({"title": title_meta})
    doc.save(str(path))


def _write_scanned_pdf(path: Path):
    """글자 레이어가 없는 PDF: 글자를 그림으로만 넣는다."""
    from PIL import Image, ImageDraw

    png = path.with_suffix(".png")
    im = Image.new("RGB", (600, 200), "white")
    ImageDraw.Draw(im).text((30, 80), "scanned receipt 4500", fill="black")
    im.save(png)
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=200)
    page.insert_image(page.rect, filename=str(png))
    doc.save(str(path))


@pytest.fixture
def brain(tmp_path, monkeypatch):
    """ingest/compile 이 tmp 위에서 돌도록 경로를 격리한다."""
    (tmp_path / "raw" / "docs").mkdir(parents=True)
    (tmp_path / "raw" / "notes").mkdir(parents=True)
    for mod in (ingest,):
        monkeypatch.setattr(mod, "WIKI_ROOT", tmp_path)
        monkeypatch.setattr(mod, "RAW_DIR", tmp_path / "raw")
        monkeypatch.setattr(mod, "STATE_FILE", tmp_path / ".ingest_state.json")
    for name, value in {"ROOT": tmp_path, "WIKI_DIR": tmp_path / "wiki",
                        "INDEX_FILE": tmp_path / "index.md", "SEED_DIR": tmp_path / "seed"}.items():
        monkeypatch.setattr(compile_mod, name, value)
    monkeypatch.setattr(compile_mod, "CATEGORIES", ["concepts"])
    monkeypatch.setitem(sys.modules, "export_graph", types.SimpleNamespace(main=lambda: 0))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(compile_mod.llm_client, "load_llm_config",
                        lambda *a, **k: {"engine": "openai", "api_key_env": "OPENAI_API_KEY"})
    return tmp_path


def _compile(brain, monkeypatch, argv=("compile.py",)):
    monkeypatch.setattr(sys, "argv", list(argv))
    return compile_mod.main()


# ── 결함 1: 웹 기사는 답변 근거가 아니다, 그리고 그렇게 알려 준다 ─────────────────


def test_url_ingest_tells_the_user_the_article_cannot_be_cited(brain, monkeypatch, capsys):
    """웹 기사를 넣으면 "읽고 검색은 되지만 AI 답변 근거로는 못 쓴다"고 바로 알려 준다.

    깨지면: 사용자가 기사를 넣고 AI 답변을 눌렀다가 이유 없는 "관련 정보 없음"만 보고
    도구가 고장 난 줄 안다(2026-10-06 e2e 에서 그대로 재현).
    """
    import httpx

    monkeypatch.setattr(ingest.httpx, "get", lambda *a, **k: httpx.Response(
        200, text=NEWS_HTML, request=httpx.Request("GET", "https://news.example/a1")))
    ingest.scrape_url("https://news.example/a1")
    out = capsys.readouterr().out
    assert "AI 답변의 근거(인용)로는 쓰이지 않습니다" in out
    assert "ingest.py --note" in out


def test_abstention_next_action_depends_on_the_reason():
    """제외 사유가 전부 untrusted 면 "메모로 옮기라"고, 그 밖에는 원장 재생성을 안내한다.

    깨지면: 외부 수집물만 있는 거부에서 `claims.py build` 를 권해, 이미 실행한 사용자를
    같은 결과로 계속 돌려보낸다.
    """
    only_untrusted = claim_ledger.abstention_next_action({"untrusted": 266})
    assert "외부에서 수집한 글" in only_untrusted["message"]
    assert "ingest.py --note" in only_untrusted["command"]
    for other in ({"stale": 1, "untrusted": 2}, {"source_hash_mismatch": 3}, {}):
        assert claim_ledger.abstention_next_action(other) == {"command": claim_ledger.CLAIM_REBUILD_COMMAND}


def test_web_ui_shows_the_reason_message_not_only_the_command():
    """화면이 안내 문장(message)을 보여 준다(명령만 보이면 왜 그 명령인지 모른다)."""
    script = (ROOT / "wiki_app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "action.message" in script


# ── 결함 2: 기사 본문만 저장한다 ─────────────────────────────────────────────


def test_extract_article_keeps_the_body_and_drops_menus():
    """메뉴·푸터·공유 버튼·관련 기사를 걷어내고 본문만 남긴다.

    깨지면: 기사 1건이 메뉴 문장 수백 개가 돼 위키가 쓰레기로 차고, 근거 원장(claim)이
    266개로 부풀어 오른다.
    """
    title, body = ingest.extract_article(NEWS_HTML)
    assert "아동 보호 장치를 더 강화" in body
    for junk in ("Home", "Sport", "Copyright 2026", "Share", "관련 기사"):
        assert junk not in body, junk
    # 독자가 보는 기사 제목(h1)을 쓴다. og:title 은 SEO 용이라 다를 수 있다.
    assert title == "호주 보고서: 게임 플랫폼은 아동 안전을 개선해야 한다"


def test_extract_article_falls_back_to_the_whole_page_when_no_article_tag():
    """본문 후보(article/main)가 없거나 너무 짧으면 페이지 전체를 쓴다(내용을 잃지 않는다)."""
    html = "<html><body><h1>짧은 글</h1><p>태그 없는 단순한 페이지입니다.</p></body></html>"
    title, body = ingest.extract_article(html)
    assert title == "짧은 글"
    assert "태그 없는 단순한 페이지" in body


def test_extract_article_accepts_role_main_pages():
    """article/main 이 없고 role=main 만 있는 문서 사이트도 본문을 고른다."""
    long_text = "문장입니다. " * 80
    html = (f'<html><body><div class="menu"><a href="/">목차 링크</a></div>'
            f'<div role="main"><h1>설치 안내 ¶</h1><p>{long_text}</p></div></body></html>')
    title, body = ingest.extract_article(html)
    assert title == "설치 안내"            # 문단 링크 기호(¶)는 제목에서 뺀다
    assert "목차 링크" not in body and "문장입니다" in body


def test_scrape_url_saves_title_heading_and_only_the_article(brain, monkeypatch):
    """저장 파일에 제목(frontmatter, # 제목)이 있고 메뉴가 없다.

    깨지면: 위키 페이지 제목이 "웹 스크랩"이거나 본문 첫 줄(메뉴 이름)이 된다.
    """
    import httpx

    monkeypatch.setattr(ingest.httpx, "get", lambda *a, **k: httpx.Response(
        200, text=NEWS_HTML, request=httpx.Request("GET", "https://news.example/a1")))
    saved = ingest.scrape_url("https://news.example/a1")
    text = saved.read_text(encoding="utf-8")
    assert 'title: "호주 보고서: 게임 플랫폼은 아동 안전을 개선해야 한다"' in text
    assert "\n# 호주 보고서" in text
    assert "Sport" not in text and "Copyright" not in text


# ── 결함 3: 스캔본 PDF 는 조용히 넘어가지 않는다 ───────────────────────────────


def test_ingest_warns_when_a_pdf_has_no_text_layer(brain, tmp_path, monkeypatch, capsys):
    """글자 레이어가 없는 PDF 를 넣으면 그 자리에서 이유와 선택지를 알려 준다(원본은 보존).

    깨지면: 스캔본을 넣고도 아무 경고가 없어, compile 에서야 "내용을 읽지 못해"만 보고
    어떻게 해야 하는지 모른다.
    """
    scanned = tmp_path / "scan.pdf"
    _write_scanned_pdf(scanned)
    saved = ingest.ingest_file(scanned)
    out = capsys.readouterr().out
    assert saved.exists()                                   # 원본은 raw 에 보존
    assert "글자를 읽지 못했습니다" in out and "OCR" in out
    assert "--note" in out
    assert not list((brain / "raw" / "docs").glob("*.extracted.md"))   # 빈 추출본을 만들지 않는다


def test_ingest_does_not_warn_for_a_text_pdf(brain, tmp_path, capsys):
    """글자가 있는 PDF 에는 거짓 경고를 하지 않는다."""
    report = tmp_path / "report.pdf"
    _write_pdf(report, [(18, "Quarterly Report", "Churn fell three percent after the onboarding change.")])
    ingest.ingest_file(report)
    assert "글자를 읽지 못했습니다" not in capsys.readouterr().out


def test_compile_explains_unreadable_pdf_and_exits_nonzero(brain, tmp_path, monkeypatch, capsys):
    """compile 이 읽지 못한 PDF 를 이유와 함께 알리고, 다른 파일은 계속 처리한다.

    깨지면: "내용을 읽지 못해 넘겼습니다" 한 줄뿐이라 OCR 이 필요하다는 것도, 어떻게 풀지도 모른다.
    """
    _write_scanned_pdf(brain / "raw" / "docs" / "2026-10-06-scan.pdf")
    (brain / "raw" / "notes" / "2026-10-06-memo.md").write_text("# 메모\n정상 메모입니다.\n", encoding="utf-8")
    rc = _compile(brain, monkeypatch)
    out = capsys.readouterr().out
    assert rc == 1                                           # 부분 실패는 숨기지 않는다
    assert "scan.pdf: 글자를 읽지 못했습니다" in out
    assert "글자 인식(OCR)" in out and "--note" in out
    assert list((brain / "wiki" / "concepts").glob("*memo*.md"))    # 정상 메모는 만들어진다


# ── 결함 4: PDF 제목 ─────────────────────────────────────────────────────────


def test_pdf_title_ignores_copyright_header_and_rotated_stamp(tmp_path):
    """제목은 첫 쪽에서 가장 큰 가로 글자다. 작은 안내문과 세로 도장은 제목이 아니다.

    깨지면: 논문 PDF 가 `Provided proper attribution is provided,`(저작권 문구)나
    `arXiv:1706.03762v7 [cs.CL] ...`(arXiv 도장)이라는 이름의 위키 페이지가 된다.
    """
    paper = tmp_path / "paper.pdf"
    _write_pdf(paper, [(17, "Attention Is All You Need", "Abstract. We propose a new network.")],
               rotated_stamp=True,
               header="Provided proper attribution is provided, Google hereby grants permission to reproduce the tables.")
    assert ingest.pdf_title(paper) == "Attention Is All You Need"


def test_pdf_title_prefers_a_real_metadata_title(tmp_path):
    f = tmp_path / "a.pdf"
    _write_pdf(f, [(14, "본문 첫 줄", "내용")], title_meta="분기 보고서")
    assert ingest.pdf_title(f) == "분기 보고서"


def test_pdf_title_ignores_filename_like_metadata_and_scans(tmp_path):
    """메타데이터가 파일명 같은 쓰레기면 버리고, 글자가 없는 스캔본은 None 이다."""
    f = tmp_path / "a.pdf"
    _write_pdf(f, [(16, "Real Heading", "본문")], title_meta="Microsoft Word - draft.docx")
    assert ingest.pdf_title(f) == "Real Heading"
    scan = tmp_path / "s.pdf"
    _write_scanned_pdf(scan)
    assert ingest.pdf_title(scan) is None


def test_wiki_page_title_comes_from_the_pdf_title_for_direct_and_sidecar_pdfs(brain, tmp_path, monkeypatch):
    """`cp` 로 넣은 PDF 와 ingest --file 로 넣은 PDF(추출본) 모두 위키 제목이 PDF 제목이다.

    깨지면: 같은 논문이 넣는 방법에 따라 제목이 다르거나, 둘 다 저작권 문구가 된다.
    """
    header = "Provided proper attribution is provided, Google hereby grants permission to reproduce."
    direct = brain / "raw" / "docs" / "paper-direct.pdf"
    _write_pdf(direct, [(17, "Attention Is All You Need", "Abstract text of the paper goes here.")],
               rotated_stamp=True, header=header)
    other = tmp_path / "paper-ingested.pdf"
    _write_pdf(other, [(17, "Another Great Paper", "Abstract text of the other paper goes here.")],
               header=header)
    ingest.ingest_file(other)                       # 원본 + .extracted.md
    assert _compile(brain, monkeypatch) == 0
    titles = {p.name: p.read_text(encoding="utf-8") for p in (brain / "wiki" / "concepts").glob("*.md")}
    assert len(titles) == 2
    joined = "\n".join(titles.values())
    assert 'title: "Attention Is All You Need"' in joined
    assert 'title: "Another Great Paper"' in joined
    assert "Provided proper attribution" not in joined.split("---", 2)[1]
