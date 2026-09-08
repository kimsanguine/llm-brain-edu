"""test_compile — raw 메모를 위키로 컴파일하는 경로의 계약.

교안 P3-10-1 §6 이 수강생에게 약속한 것을 지키는지 검증한다.
  "메모 3건 넣어보기 → 위키 첫 페이지 3개가 생긴 것을 눈으로 확인"
  "필수 실습은 전부 키가 없어도 끝까지 돌아갑니다"

각 테스트는 "이게 깨지면 수강생에게 무슨 일이 일어나는가"를 주석으로 남긴다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pytest  # noqa: E402

import compile as compile_mod  # noqa: E402


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """저장소가 아니라 tmp_path 위에서 돌게 한다."""
    for name, value in {
        "ROOT": tmp_path,
        "WIKI_DIR": tmp_path / "wiki",
        "INDEX_FILE": tmp_path / "index.md",
        "SEED_DIR": tmp_path / "seed",
    }.items():
        monkeypatch.setattr(compile_mod, name, value)
    (tmp_path / "raw" / "notes").mkdir(parents=True)
    return tmp_path


def _raw(sandbox: Path, name: str, body: str) -> Path:
    """ingest.py --note 가 만드는 것과 같은 모양의 raw 파일."""
    f = sandbox / "raw" / "notes" / name
    f.write_text(f"---\ntitle: 수동 노트\ncreated: 2026-09-07-1351\n---\n\n{body}", encoding="utf-8")
    return f


# ---------------------------------------------------------------------------
# RULE 경로 — 키 없이도 완주한다
# ---------------------------------------------------------------------------


def test_rule_path_makes_a_page_without_any_key(sandbox):
    """키가 없어도 위키 페이지가 생긴다.

    깨지면: 개강 전 혼자 설치하는 학생이 "키가 없어서 아무것도 안 된다"에 막힌다.
    교안이 "키 없이도 끝까지 돌아갑니다"라고 이미 약속했으므로 신뢰가 깨진다.
    """
    f = _raw(sandbox, "2026-09-07-1351-note.md", "오늘 배운 것: 리스트 컴프리헨션")
    path, page = compile_mod._page_by_rule(f, f.read_text(encoding="utf-8"))
    assert path.suffix == ".md"
    assert "오늘 배운 것: 리스트 컴프리헨션" in page
    assert "RULE" in page  # 어느 경로로 만들어졌는지 페이지 자신이 밝힌다


def test_title_with_colon_keeps_frontmatter_parseable(sandbox):
    """제목에 콜론이 있어도 frontmatter 가 깨지지 않는다.

    깨지면: "오늘 배운 것: 파이썬" 같은 지극히 평범한 메모가 YAML 을 깨뜨려
    export_graph 가 그 페이지를 못 읽고, 학생 위키에서 조용히 사라진다.
    """
    import yaml

    f = _raw(sandbox, "n.md", "오늘 배운 것: 파이썬 리스트 컴프리헨션")
    _, page = compile_mod._page_by_rule(f, f.read_text(encoding="utf-8"))
    fm = yaml.safe_load(page.split("---")[1])
    assert fm["title"] == "오늘 배운 것: 파이썬 리스트 컴프리헨션"


def test_slug_is_ascii_even_for_korean_title(sandbox):
    """제목이 한글이어도 파일명은 ASCII 다.

    깨지면: CLAUDE.md 명명 규약("한국어 개념도 영문 slug")을 어기고, macOS 가
    한글 파일명을 NFD 로 저장해 도구마다 다르게 보이는 문제까지 끌어온다.
    """
    f = _raw(sandbox, "2026-09-07-1351-note.md", "관심 링크: RAG 평가 방법")
    path, _ = compile_mod._page_by_rule(f, f.read_text(encoding="utf-8"))
    assert path.stem.isascii(), f"slug 에 비ASCII: {path.stem}"


def test_note_without_heading_still_gets_a_readable_title(sandbox):
    """헤딩 없는 메모도 알아볼 수 있는 제목을 갖는다.

    깨지면: ingest --note 로 넣은 메모가 전부 "2026-09-07-1351-note" 라는 제목이 되어,
    학생이 위키를 열어도 어느 페이지가 무슨 내용인지 구분할 수 없다.
    """
    f = _raw(sandbox, "2026-09-07-1351-note.md", "이번 주 할 일: 주간 보고서 자동화")
    _, page = compile_mod._page_by_rule(f, f.read_text(encoding="utf-8"))
    assert "이번 주 할 일" in page.split("---")[1]  # frontmatter title 에 들어간다


# ---------------------------------------------------------------------------
# LIVE 경로 파싱 — 형식이 어긋나면 조용히 넘어가지 않는다
# ---------------------------------------------------------------------------


def test_live_output_parsed_into_path_and_body():
    out = 'PATH: wiki/concepts/rag-eval.md\n---\ntitle: "RAG 평가"\n---\n\n# RAG 평가\n본문'
    parsed = compile_mod._parse_live_output(out)
    assert parsed is not None
    path, body = parsed
    assert path.as_posix().endswith("wiki/concepts/rag-eval.md")
    assert body.startswith("---")


@pytest.mark.parametrize("bad", [
    "PATH: ../../etc/passwd.md\n---\ntitle: x\n---\n",   # 경로 탈출
    "PATH: /tmp/evil.md\n---\ntitle: x\n---\n",          # wiki/ 밖
    "그냥 설명만 하고 형식을 안 지킨 응답",                    # PATH 없음
    "PATH: wiki/concepts/a.md\n본문만 있고 frontmatter 없음",  # frontmatter 없음
])
def test_malformed_live_output_is_rejected(bad):
    """모델이 형식을 어기면 받아들이지 않는다(→ RULE 폴백).

    깨지면: 모델이 부른 경로에 파일을 쓰게 되어 저장소 밖에 파일이 생기거나,
    frontmatter 없는 페이지가 위키에 섞여 그래프가 깨진다.
    """
    assert compile_mod._parse_live_output(bad) is None


# ---------------------------------------------------------------------------
# --seed 리커버리 — 학생 자료를 덮어쓰지 않는다
# ---------------------------------------------------------------------------


def test_seed_refuses_to_overwrite_existing_wiki(sandbox, capsys):
    """이미 위키가 있으면 --seed 가 덮어쓰지 않는다.

    깨지면: 몇 주치 자기 메모를 쌓아 둔 학생이 리커버리 명령 한 번에 전부 잃는다.
    되돌릴 수 없는 손실이므로 --force 를 요구한다.
    """
    (sandbox / "wiki" / "concepts").mkdir(parents=True)
    mine = sandbox / "wiki" / "concepts" / "내-메모.md"
    mine.write_text("소중한 내용", encoding="utf-8")

    assert compile_mod.do_seed(force=False) == 1
    assert mine.read_text(encoding="utf-8") == "소중한 내용"
    assert "--force" in capsys.readouterr().out


def test_seed_copies_when_wiki_is_empty(sandbox):
    """빈 위키에는 예제를 넣어 준다 — 설치가 막힌 학생의 리커버리 경로."""
    seed_wiki = sandbox / "seed" / "wiki" / "concepts"
    seed_wiki.mkdir(parents=True)
    (seed_wiki / "example.md").write_text("---\ntitle: 예제\n---\n\n# 예제", encoding="utf-8")
    (sandbox / "seed" / "index.md").write_text("# Index", encoding="utf-8")

    assert compile_mod.do_seed(force=False) == 0
    assert (sandbox / "wiki" / "concepts" / "example.md").is_file()
    assert (sandbox / "index.md").is_file()


# ---------------------------------------------------------------------------
# index.md
# ---------------------------------------------------------------------------


def test_index_lists_pages_with_korean_description(sandbox):
    """목차에 한국어 설명이 붙는다.

    깨지면: slug 가 ASCII 라서 목차가 "[[2026-09-07-1351-note]]" 나열이 되고,
    학생이 자기 위키에서 무엇을 찾을 수 있는지 알 수 없다.
    """
    d = sandbox / "wiki" / "concepts"
    d.mkdir(parents=True)
    (d / "2026-09-07-note.md").write_text(
        '---\ntitle: "오늘 배운 것"\n---\n\n# 오늘 배운 것\n\n리스트 컴프리헨션을 배웠다\n',
        encoding="utf-8",
    )
    total = compile_mod.rebuild_index()
    assert total == 1
    index = (sandbox / "index.md").read_text(encoding="utf-8")
    assert "[[2026-09-07-note]]" in index
    assert "리스트 컴프리헨션" in index


# ---------------------------------------------------------------------------
# 적대 리뷰(Codex)에서 나온 결함들 — 회귀 방지
# ---------------------------------------------------------------------------


def test_live_path_must_be_wiki_category_file(sandbox):
    """모델이 준 경로는 wiki/<카테고리>/<파일>.md 정확히 세 조각이어야 한다.

    깨지면: wiki/concepts/sub/a.md 같은 경로가 저장되지만 rebuild_index 는 카테고리
    최상위만 훑으므로 목차에도 화면에도 안 나온다. 학생은 "만들었다"는 말만 듣고
    페이지를 찾지 못한다.
    """
    ok = 'PATH: wiki/concepts/a.md\n---\ntitle: "가"\n---\n\n# 가'
    assert compile_mod._parse_live_output(ok) is not None
    for bad_path in ["wiki/concepts/sub/a.md", "wiki/other/a.md", "wiki/a.md",
                     "wiki/concepts/.hidden.md", "wiki/concepts/a.txt"]:
        out = f'PATH: {bad_path}\n---\ntitle: "가"\n---\n\n# 가'
        assert compile_mod._parse_live_output(out) is None, f"통과하면 안 됨: {bad_path}"


def test_existing_page_from_other_source_is_not_overwritten(sandbox):
    """다른 raw 에서 나온 같은 이름의 페이지를 덮어쓰지 않는다.

    깨지면: 모델이 우연히 기존 슬러그를 반환하면 학생이 몇 주간 쌓은 페이지가
    통째로 교체된다. 되돌릴 방법이 없다.
    """
    page = sandbox / "wiki" / "concepts" / "rag.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text("---\nsources:\n  - raw/notes/예전메모.md\n---\n\n소중한 기존 내용",
                    encoding="utf-8")
    newraw = _raw(sandbox, "2026-09-08-1000-note.md", "새 메모")

    target = compile_mod._safe_target(page, newraw)
    assert target != page
    assert target.name == "rag-2.md"
    assert "소중한 기존 내용" in page.read_text(encoding="utf-8")


def test_same_source_page_is_updated_in_place(sandbox):
    """같은 raw 에서 나온 페이지는 갱신한다(재컴파일은 새 파일을 만들지 않는다).

    깨지면: 같은 메모를 두 번 컴파일할 때마다 rag-2, rag-3 이 쌓인다.
    """
    raw = _raw(sandbox, "2026-09-08-1000-note.md", "메모")
    rel = raw.relative_to(sandbox).as_posix()
    page = sandbox / "wiki" / "concepts" / "rag.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(f"---\nsources:\n  - {rel}\n---\n\n이전 내용", encoding="utf-8")

    assert compile_mod._safe_target(page, raw) == page


def test_safe_target_reads_sources_field_not_whole_body(sandbox):
    """출처 확인은 frontmatter 의 sources 만 본다.

    깨지면: 페이지 본문에 인용문으로 남의 raw 경로가 들어 있으면 "같은 출처"로
    오판해 덮어쓴다. 덮어쓰기를 막으려고 만든 함수가 덮어쓰기 경로를 남기는 셈이다.
    (재적대 리뷰에서 나온 정확한 재현 케이스)
    """
    newraw = _raw(sandbox, "2026-09-08-1000-note.md", "새 메모")
    rel_new = newraw.relative_to(sandbox).as_posix()
    page = sandbox / "wiki" / "concepts" / "rag.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    # sources 는 다른 파일인데 본문에 새 raw 경로가 인용돼 있다
    page.write_text(
        f"---\nsources:\n  - raw/notes/예전메모.md\n---\n\n"
        f"참고: {rel_new} 에서 이어짐\n\n소중한 기존 내용",
        encoding="utf-8")

    target = compile_mod._safe_target(page, newraw)
    assert target != page, "본문 인용에 속아 덮어쓰려 했다"
    assert "소중한 기존 내용" in page.read_text(encoding="utf-8")


@pytest.mark.parametrize("shape,label", [
    ("---\nsources:\n  - {rel}\n---\n\n본문", "정상"),
    ("---\r\nsources:\r\n  - {rel}\r\n---\r\n\r\n본문", "CRLF"),
    ("﻿---\nsources:\n  - {rel}\n---\n\n본문", "BOM(메모장 저장)"),
    ("\n---\nsources:\n  - {rel}\n---\n\n본문", "앞 빈 줄"),
    ("---\ntags:\n  - python\nsources:\n  - {rel}\n---\n\n본문", "tags 블록 먼저"),
    ('---\nsources:\n  - "{rel}"\n---\n\n본문', "따옴표 경로"),
])
def test_same_source_detected_across_file_shapes(sandbox, shape, label):
    """같은 출처는 파일 모양이 달라도 갱신으로 인식한다.

    깨지면: 학생이 위키 페이지를 메모장으로 한 번 열어 저장하면(BOM 추가) 그 뒤로
    재컴파일마다 rag-2, rag-3 이 쌓여 같은 내용이 위키에 여러 벌 생긴다.
    """
    raw = _raw(sandbox, "2026-09-08-1000-note.md", "메모")
    rel = raw.relative_to(sandbox).as_posix()
    page = sandbox / "wiki" / "concepts" / "rag.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(shape.format(rel=rel), encoding="utf-8")

    assert compile_mod._safe_target(page, raw) == page, f"{label} 에서 같은 출처를 놓쳤다"


def test_inline_sources_list_is_recognized(sandbox):
    """`sources: [경로]` 인라인 형식도 같은 출처로 인식한다.

    깨지면: 모델이 인라인으로 낸 페이지는 재컴파일마다 -2, -3 이 쌓인다.
    (2차 재적대 지적 — 줄 단위 정규식은 블록 목록만 읽었다)
    """
    raw = _raw(sandbox, "2026-09-08-1000-note.md", "메모")
    rel = raw.relative_to(sandbox).as_posix()
    page = sandbox / "wiki" / "concepts" / "rag.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(f'---\ntitle: "가"\nsources: [{rel}]\n---\n\n본문', encoding="utf-8")
    assert compile_mod._safe_target(page, raw) == page


def test_tags_block_is_not_mistaken_for_sources(sandbox):
    """tags 의 블록 목록을 sources 로 주워 담지 않는다.

    깨지면: tags 에 우연히 raw 경로 문자열이 있으면 남의 페이지를 덮어쓴다.
    (2차 재적대 지적 — 줄 단위 정규식은 필드를 구분하지 못했다)
    """
    raw = _raw(sandbox, "2026-09-08-1000-note.md", "메모")
    rel = raw.relative_to(sandbox).as_posix()
    page = sandbox / "wiki" / "concepts" / "rag.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        f'---\ntitle: "가"\ntags:\n  - {rel}\nsources:\n  - raw/notes/다른것.md\n---\n\n소중한 내용',
        encoding="utf-8")
    assert compile_mod._safe_target(page, raw) != page, "tags 를 sources 로 오인했다"
    assert "소중한 내용" in page.read_text(encoding="utf-8")


@pytest.mark.parametrize("bad_state", [
    {"processed": "raw/notes/a.md"},              # 문자열
    {"processed": [{"path": "raw/a.md"}]},        # dict 원소
    {"processed": [None, "raw/notes/a.md"]},      # None 섞임
    {"processed": ["raw\\notes\\a.md"]},          # Windows 구분자
])
def test_corrupt_ingest_state_does_not_crash(sandbox, monkeypatch, bad_state):
    """상태 파일이 손상돼도 컴파일이 죽지 않는다.

    깨지면: 학생이 .ingest_state.json 을 한 번 열어 고치면 그 뒤로 compile 이
    TypeError 로 중단된다. 되돌리는 법을 모른다.
    (2차 재적대 지적)
    """
    import ingest as ingest_mod

    raw = _raw(sandbox, "2026-09-08-1000-note.md", "메모 본문")
    monkeypatch.setattr(sys, "argv", ["compile.py"])          # argparse 가 pytest 인자를 보지 않게
    monkeypatch.setattr(ingest_mod, "load_state", lambda: dict(bad_state))
    saved = {}
    monkeypatch.setattr(ingest_mod, "save_state", lambda st: saved.update(st))
    monkeypatch.setattr(ingest_mod, "find_unprocessed", lambda priority_only=False: [raw])
    monkeypatch.setattr(compile_mod, "CATEGORIES", ["concepts"])

    assert compile_mod.main() == 0                             # 죽지 않는다
    assert all(isinstance(x, str) for x in saved["processed"])  # 상태가 문자열 목록으로 남는다
    assert "\\" not in "".join(saved["processed"])              # 경로 구분자는 / 로 통일
