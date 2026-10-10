---
description: wiki_app 웹 UI를 로컬에서 띄운다 (터미널의 실제 접속 주소 확인)
---

llm-brain의 wiki-web UI(로컬 HTML 검색·페이지뷰)를 띄웁니다. CLI `query`의 시각화 버전입니다.

## 실행

```bash
cd "$(git rev-parse --show-toplevel)"  # llm-brain 레포 루트
uv run python -m wiki_app
```

(uv 미설치 시: `.venv/bin/python -m wiki_app`)

서버가 뜨면 터미널의 `브라우저에서 열어 보세요` 주소를 엽니다. 기본은
`http://localhost:8000`이며, 사용 중이면 8001번 등 다음 빈 포트를 찾습니다.
`BRAIN_PORT`를 지정하면 해당 번호부터 10개 후보를 확인합니다. 종료는 `Ctrl+C`.

## 제공 기능

- **검색**: 제목·description·tags 점수 매칭, 결과 < 3개일 때 본문 grep(본문 검색) 자동 확장. 한국어/영문 모두.
- **페이지뷰**: 마크다운 렌더 + `[[wikilink]]`(페이지끼리 연결) 클릭 SPA(새로고침 없이 이동) 네비게이션.
- **AI 답변 토글**: `schema/config.yaml`의 `llm.engine`으로 실행합니다. 수업 기본은
  `openai`(OpenAI 호환 API), 선택 호환은 `cli`(`claude -p`)와 `api`(Anthropic API)입니다.
  필요한 키나 CLI가 없으면 AI 답변을 사용할 수 없지만 검색과 페이지 보기는 가능합니다.
  AI 답변 전 `uv run python scripts/claims.py build`로 근거 원장을 준비합니다.
  LIVE 답변은 선택한 AI 서비스로 질문과 관련 근거 내용을 전송하므로 처음 사용하거나
  엔진을 변경할 때 사용자에게 먼저 알립니다.
  citation 검증 전 토큰은 표시하지 않으며, 제한된 buffer에서 검증한 뒤 한 번에 보내는
  `verified-buffered` 방식임을 UI에 표시합니다. 사용할 trusted claim도 외부 capture도
  없으면 모델 호출 없이 답변을 보류하고, 제외 사유 count와 다음 행동 하나를 보여줍니다.
  외부 capture를 요약에 쓰면 "외부 글 요약" 고지문과 출처를 표시합니다.

검색·페이지 보기·AI query는 읽기 경로이며 `raw/`·`wiki/`·`wiki_stats.json`·접근
lock을 변경하지 않습니다. 접근 통계가 필요하면 별도로
`uv run python scripts/curate.py --record-access PAGE_SLUG`를 실행합니다.

## 데이터가 없다면 (선택)

`wiki/`가 비어 있으면 검색 결과가 안 나옵니다. raw 출처가 함께 있는 수업용 데모로 먼저 체험:

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python scripts/compile.py --seed
uv run python -m wiki_app  # 터미널의 실제 주소로 접속
```

`--seed`는 `examples/course-seed-wiki/`의 위키와 공개 원문을 설치합니다.
기존 위키 페이지나 같은 이름의 다른 raw 원문이 있으면 중단합니다. `--force`를
추가하지 말고 기존 위키를 보거나 README의 논문 실습을 진행하세요.
