---
description: wiki_app 웹 UI를 로컬에서 띄운다 (http://localhost:8000 — 검색·페이지뷰·wikilink·AI 답변)
---

llm-brain의 wiki-web UI(로컬 HTML 검색·페이지뷰)를 띄웁니다. CLI `query`의 시각화 버전입니다.

## 실행

```bash
cd "$(git rev-parse --show-toplevel)"  # llm-brain 레포 루트
uv run python -m wiki_app
```

(uv 미설치 시: `.venv/bin/python -m wiki_app`)

서버가 뜨면 브라우저에서 **http://localhost:8000** 을 엽니다. 종료는 `Ctrl+C`.

## 제공 기능

- **검색**: 제목·description·tags 점수 매칭, 결과 < 3개일 때 본문 grep(본문 검색) 자동 확장. 한국어/영문 모두.
- **페이지뷰**: 마크다운 렌더 + `[[wikilink]]`(페이지끼리 연결) 클릭 SPA(새로고침 없이 이동) 네비게이션.
- **AI 답변 토글**: `claude -p` 라이브 연결(미설치 시 graceful 비활성).
  citation 검증 전 토큰은 표시하지 않으며, 제한된 buffer에서 검증한 뒤 한 번에 보내는
  `verified-buffered` 방식임을 UI에 표시합니다. usable claim이 없으면 출처 페이지를
  표시하지 않고 제외 사유 count와 다음 행동 하나를 보여줍니다.

검색·페이지 보기·AI query는 읽기 경로이며 `raw/`·`wiki/`·`wiki_stats.json`·접근
lock을 변경하지 않습니다. 접근 통계가 필요하면 별도로
`uv run python scripts/curate.py --record-access PAGE_SLUG`를 실행합니다.

## 데이터가 없다면 (선택)

`wiki/`가 비어 있으면 검색 결과가 안 나옵니다. 데모 데이터로 먼저 체험:

```bash
cd "$(git rev-parse --show-toplevel)"
cp -r examples/seed-wiki/wiki ./wiki        # 데모 wiki 복사
cp examples/seed-wiki/index.md ./index.md   # 데모 목차
uv run python -m wiki_app                    # → http://localhost:8000
```
