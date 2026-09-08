import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from wiki_app.render import render_markdown


def test_basic_markdown_to_html():
    html = render_markdown("# 제목\n\n본문")
    assert "<h1>" in html
    assert "제목" in html
    assert "<p>본문</p>" in html


def test_wikilink_becomes_anchor_with_data_link():
    html = render_markdown("관련: [[habix-profile]]")
    assert '<a' in html
    assert 'data-link="habix-profile"' in html
    assert ">habix-profile</a>" in html


def test_wikilink_with_subpath():
    html = render_markdown("[[260515_llm_wiki/prd]]")
    assert 'data-link="260515_llm_wiki/prd"' in html


def test_multiple_wikilinks_in_same_paragraph():
    html = render_markdown("[[alpha]] 그리고 [[beta]]")
    assert 'data-link="alpha"' in html
    assert 'data-link="beta"' in html


def test_code_block_wikilinks_preserved_as_text():
    # 코드 블록 안의 [[slug]]는 변환하지 않음
    html = render_markdown("```\n[[in-code]]\n```")
    assert 'data-link=' not in html
    assert "[[in-code]]" in html
