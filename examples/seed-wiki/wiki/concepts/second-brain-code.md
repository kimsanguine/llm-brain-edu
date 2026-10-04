---
title: Second Brain & CODE 프레임워크
type: concept
tags: [second-brain, code-framework, knowledge-management, productivity]
created: 2026-05-23
updated: 2026-05-23
sources:
  - https://fortelabs.com/blog/basboverview/ (Tiago Forte BASB Overview)
  - "Building a Second Brain (Tiago Forte, 2022)"
distill_level: 0
access_count: 0
---

# Second Brain & CODE 프레임워크

## 개요

Tiago Forte가 2017년 제시하고 2022년 동명의 책으로 완성한 개인 지식 관리 방법론. 핵심 전제는 하나다:

> "뇌는 아이디어를 *떠올리는* 곳이지, *저장하는* 곳이 아니다."

디지털 도구를 두 번째 뇌(Second Brain)로 삼아 정보를 외장화하고, 인지 부하를 줄여 창의적 사고에 집중한다. 실행 프레임워크는 **CODE** 4단계로 구성된다.

## CODE 4단계

### C — Capture (수집)

공명하는 것만 저장한다. 모든 것을 저장하면 아무것도 찾을 수 없다.

**기준**: 흥미롭다, 유용하다, 놀랍다, 영감을 준다 — 이 중 하나라도 해당하면 저장.

**수집 채널 예시**:
- 웹 클리퍼 (Readwise, Raindrop)
- 하이라이트 (전자책 마커)
- 음성 메모 (이동 중 아이디어)
- 스크린샷 (시각적 레퍼런스)

**피해야 할 것**: 나중에 유용할 것 같은 것을 무차별 저장하는 "수집 강박". 캡처는 사고의 대체가 아니다.

### O — Organize (정리)

프로젝트별로 분류한다. 주제별(topic-based)이 아니라 **용도별(actionability-based)** 분류.

**PARA 시스템** (Forte의 또 다른 방법론):
- **P**rojects: 현재 진행 중인 목표 (마감 있음)
- **A**reas: 지속 관리 영역 (건강, 재무, 개발 역량)
- **R**esources: 미래에 참고할 주제별 자료
- **A**rchive: 비활성화된 항목

주제 폴더에 넣는 것이 아니라 "이 정보가 어떤 프로젝트에 당장 쓸모 있는가?"를 먼저 묻는다.

### D — Distill (압축)

저장된 정보를 점진적으로 요약한다. 나중에 쓸 때 전체를 다시 읽지 않아도 되도록.

핵심 기법: [[distill-progressive]] (Progressive Summarization)

- 1단계: 원문 저장
- 2단계: 핵심 문장 **볼드** 처리
- 3단계: 그 중에서도 가장 중요한 구절 **하이라이트**
- 4단계: 자신의 말로 요약 한 줄 추가

"미래의 나"를 위해 남긴다는 관점이 중요하다. 현재 이해가 아니라 미래 검색 시 빠른 파악이 목적.

### E — Express (표현)

지식을 창작물로 전환한다. 단순 저장은 지식이 아니다. 표현을 통해 진짜 이해가 완성된다.

**표현의 형태**:
- 블로그 포스트
- 발표 슬라이드
- 코드 프로젝트
- 팀 내부 문서
- 소셜 미디어 스레드

중요한 관점: 항상 완성본을 만들 필요 없다. **중간 산출물(Intermediate Packets)** — 아이디어 초안, 개념 정리, 다이어그램 — 을 재사용 가능한 블록으로 관리하는 것이 핵심.

## LLM Wiki와의 결합

[[llm-wiki-pattern]] 과 Second Brain을 결합하면 각 단계를 자동화할 수 있다.

| CODE 단계 | 인간 역할 | LLM 역할 |
|-----------|----------|----------|
| Capture | URL/파일 수집 판단 | 자동 구조화 |
| Organize | PARA 폴더 판단 | 태그 자동 분류 |
| Distill | 공명 판단 | 요약·압축 실행 |
| Express | 주제 선택, 톤 결정 | 초안 생성 |

**결론**: LLM이 Distill을 대행함으로써 인간은 가장 고부가가치 단계인 **Express — 무엇을 만들 것인가** 에 집중할 수 있다.

## 비판적 시각

- CODE는 방법론이지 도구가 아니다. Notion·Obsidian·Roam 어디서든 작동하지만, 도구 선택에 과도한 에너지를 쓰는 "도구 덕질"은 경계해야 한다.
- "모든 것을 캡처하라"와 "공명하는 것만 캡처하라" 사이의 기준이 주관적이다. 처음에는 과잉 저장에서 시작해 점차 기준을 세우는 것이 현실적.
- 지식 관리 자체가 목적이 되는 순간 생산성을 갉아먹는다. Express 없는 Second Brain은 정보의 무덤.

## 관련 개념

- [[llm-wiki-pattern]]
- [[distill-progressive]]
