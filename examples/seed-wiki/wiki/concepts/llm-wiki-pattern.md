---
title: LLM Wiki 패턴
type: concept
tags: [llm-wiki, karpathy, knowledge-management]
created: 2026-05-23
updated: 2026-05-23
sources:
  - https://twitter.com/karpathy (Karpathy LLM Wiki 원본 트윗)
distill_level: 0
access_count: 0
---

# LLM Wiki 패턴

## 개요

2024년 Andrej Karpathy가 트윗에서 제시한 개인 지식 관리 패러다임. 핵심 아이디어는 단순하다: **LLM을 컴파일러처럼 사용하라.** 원본 소스(raw/)는 컴파일 전 소스 코드이고, 정제된 위키(wiki/)는 그 산출물이다.

> "I want to build a wiki of everything I read/watch/listen to. The LLM is the compiler."
> — Karpathy, 2024

## 2계층 아키텍처

```
raw/          ← 읽기 전용 소스 (원문, 스크린샷, PDF, 트윗 텍스트)
wiki/         ← LLM이 컴파일한 정제 페이지
```

### raw/ 계층

- 인터넷에서 수집한 원문 그대로 보관
- 수정 금지 — 오직 추가만 가능
- 형식 제한 없음: `.md`, `.txt`, `.pdf`, 웹 스크랩 텍스트 모두 허용
- 인간이 직접 작성하지 않음. 외부 출처의 복사본

### wiki/ 계층

- LLM이 raw/ 를 읽어 생성한 구조화된 페이지
- 단일 개념/인물/도구/프로젝트 단위로 페이지 분할
- frontmatter로 메타데이터 관리 (type, tags, sources, distill_level 등)
- raw/ 출처가 명시되어야 생성 가능

## 핵심 가드레일

| 규칙 | 이유 |
|------|------|
| raw/ 출처 없이 wiki/ 작성 금지 | hallucination 방지, 사실 추적 가능성 확보 |
| raw/ 파일 수정 금지 | 원본 무결성 유지, 재컴파일 가능성 보장 |
| LLM 학습 데이터만으로 wiki/ 작성 금지 | 개인화된 지식이 아니라 일반 지식이 됨 |
| query 응답 중 wiki/ 편집 금지 | 읽기 세션에서 무결성 침해 방지 |

## 컴파일 프로세스

1. **ingest**: raw/ 에 소스 추가 → LLM이 wiki/ 페이지 생성·갱신
2. **curate**: 기존 wiki/ 페이지 압축(distill), 그래프 분석, 수명 주기 관리
3. **query**: wiki/ 기반 질의응답. wiki 에 없으면 "raw 데이터 필요" 응답
4. **express**: wiki/ 지식을 블로그·강의안·요약본으로 출력

## 한계 및 확장점

Karpathy 원안은 **capture(수집)** 과 **express(표현)** 단계를 구체화하지 않았다. 원안의 공백:

- 무엇을 ingest할지 우선순위 결정 기준 미제시
- wiki/ 페이지의 lifecycle(TTL, archive) 미정의
- 지식 → 표현물(글, 슬라이드) 전환 파이프라인 부재

이 공백은 [[second-brain-code]] 의 CODE 프레임워크나 [[distill-progressive]] 의 점진적 압축 기법으로 보완할 수 있다.

## LLM 컴파일러 비유

| 소프트웨어 빌드 | LLM Wiki |
|----------------|----------|
| 소스 코드 | raw/ (원본) |
| 컴파일러 | Claude/GPT |
| 바이너리/아티팩트 | wiki/ 페이지 |
| 빌드 스크립트 | schema/ 규칙 |
| CI 파이프라인 | ingest · curate 스크립트 |

소스가 바뀌면 재컴파일로 wiki/ 도 갱신된다. 사람은 소스만 수집하고, LLM이 구조화·정제를 담당한다.

## 관련 개념

- [[second-brain-code]]
- [[distill-progressive]]
- [[claude-code]]
