"""마크다운 → HTML 렌더. [[wikilink]]는 클릭 가능한 SPA 앵커로 후처리."""
from __future__ import annotations

import re

from markdown_it import MarkdownIt


_md = MarkdownIt("commonmark", {"breaks": False, "html": False}).enable("table")

# [[slug]] 또는 [[folder/slug]] — 영문/한글/숫자/-_/ 허용
_WIKILINK_RE = re.compile(r"\[\[([A-Za-z0-9가-힣_\-/]+)\]\]")

# 이미 렌더된 HTML에서 <code>/<pre> 블록 사이의 텍스트만 치환
_CODE_BLOCK_RE = re.compile(r"(<pre[^>]*>.*?</pre>|<code[^>]*>.*?</code>)", re.DOTALL)


def _replace_wikilinks_outside_code(html: str) -> str:
    """코드 블록을 보존하며 [[slug]]을 앵커로 치환한다."""
    parts = []
    last_end = 0
    for m in _CODE_BLOCK_RE.finditer(html):
        # 코드 블록 앞 부분은 변환
        outside = html[last_end:m.start()]
        parts.append(_WIKILINK_RE.sub(
            lambda mm: f'<a data-link="{mm.group(1)}" href="#page={mm.group(1)}">{mm.group(1)}</a>',
            outside,
        ))
        parts.append(m.group(0))  # 코드 블록은 그대로
        last_end = m.end()
    # 남은 꼬리 부분
    tail = html[last_end:]
    parts.append(_WIKILINK_RE.sub(
        lambda mm: f'<a data-link="{mm.group(1)}" href="#page={mm.group(1)}">{mm.group(1)}</a>',
        tail,
    ))
    return "".join(parts)


def render_markdown(body_md: str) -> str:
    """body_md를 HTML 문자열로 변환한다."""
    html = _md.render(body_md)
    return _replace_wikilinks_outside_code(html)
