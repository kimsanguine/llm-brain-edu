#!/usr/bin/env python3
"""공개 AI 논문을 raw/docs에 받는다. 모델/API 키 없이 HTTP 다운로드만 한다."""
from pathlib import Path
import argparse
import sys

import pymupdf
import httpx

ROOT = Path(__file__).resolve().parents[1]
PAPER_URL = 'https://arxiv.org/pdf/1706.03762v7'
PAPER_PATH = ROOT / 'raw/docs/attention-is-all-you-need.pdf'


def _validate_pdf(content: bytes) -> None:
    if not content.startswith(b'%PDF-'):
        raise ValueError('PDF가 아닌 응답입니다. 잠시 뒤 다운로드를 다시 실행하세요.')
    try:
        with pymupdf.open(stream=content, filetype='pdf') as document:
            text = ''.join(page.get_text() for page in document)
            if document.page_count == 0 or 'Attention Is All You Need' not in text:
                raise ValueError('예정한 논문이 아닙니다. 기존 파일을 덮어쓰지 않습니다.')
    except pymupdf.FileDataError as exc:
        raise ValueError('손상된 PDF입니다. 파일을 확인한 뒤 다시 실행하세요.') from exc


def download_paper(target: Path = PAPER_PATH) -> Path:
    """검증된 논문만 저장하며, 기존 다른 문서는 절대 덮어쓰지 않는다."""
    target = Path(target)
    if target.exists():
        _validate_pdf(target.read_bytes())
        return target
    response = httpx.get(PAPER_URL, follow_redirects=True, timeout=60)
    response.raise_for_status()
    _validate_pdf(response.content)
    target.parent.mkdir(parents=True, exist_ok=True)
    # 동시에 실행해도 앞서 저장된 사용자 파일을 덮어쓰지 않습니다.
    with target.open('xb') as stream:
        stream.write(response.content)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description='Attention Is All You Need 공개 논문 다운로드')
    parser.add_argument('--output', type=Path, default=PAPER_PATH)
    args = parser.parse_args()
    try:
        path = download_paper(args.output)
    except (ValueError, OSError, httpx.HTTPError) as exc:
        print(f'다운로드 실패: {exc}', file=sys.stderr)
        return 1
    print(f'논문 준비 완료: {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path.name}')
    print(f'출처: {PAPER_URL}')
    print('다음: uv run python scripts/compile.py --rule')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
