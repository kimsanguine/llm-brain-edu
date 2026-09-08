---
description: wiki 기반 블로그·강의·요약·리포트 초안 생성
---

llm-brain의 express 커맨드입니다. 아래 절차를 실행하세요.

## 인자 파싱

`$ARGUMENTS` 형식:
- `blog '<주제>'` → 블로그 포스트
- `lecture '<주제>' [--slides N]` → 강의 슬라이드 (기본 5장)
- `summary --week` → 주간 요약 (최근 7일)
- `summary --month` → 월간 요약 (최근 30일)
- `report '<주제>'` → 심층 리포트

## Step 1: express 스크립트 실행

```bash
cd "$(git rev-parse --show-toplevel)"  # llm-brain 레포 루트
uv run python scripts/express.py $ARGUMENTS
```

스크립트가 관련 wiki 페이지를 수집하고 `express/{type}/YYYY-MM-DD-{slug}.md` 초안 파일을 생성합니다.

## Step 2: 콘텐츠 합성

생성된 초안 파일을 읽습니다.
`<!-- CONTEXT_START -->` ~ `<!-- CONTEXT_END -->` 사이의 wiki 컨텍스트를 바탕으로 실제 콘텐츠를 작성해 초안 파일에 덮어씁니다.

타입별 작성 기준:

**blog**
- 독자: AI/기술 관심 한국어 독자
- 길이: 800-1200자 내외
- 구조: 도입 → 핵심 인사이트 2-3개 → 실천 제안 → 마무리

**lecture**
- 슬라이드 수: `--slides` 인자값 (기본 5)
- 각 슬라이드: `## 슬라이드 N: 제목` + 핵심 포인트 3개 이내
- 마지막 슬라이드: Q&A 또는 실습 과제

**summary**
- 섹션: 핵심 인사이트 / 반복 패턴 / 다음 액션
- wiki에 없는 기간이면 "해당 기간 wiki 업데이트 없음" 안내

**report**
- 섹션: 현황 / 주요 발견 / 시사점 / 권고사항
- 길이: 1500자 이상

## Step 3: 파일 경로 안내

작성 완료 후 저장된 파일 경로를 사용자에게 알립니다.
