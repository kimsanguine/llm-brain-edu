---
title: Progressive Summarization (점진적 압축)
type: concept
tags: [progressive-summarization, distill, second-brain, llm-automation]
created: 2026-05-23
updated: 2026-05-23
sources:
  - https://fortelabs.com/blog/progressive-summarization-a-practical-technique-for-designing-discoverable-notes/
distill_level: 0
access_count: 0
---

# Progressive Summarization (점진적 압축)

## 개요

Tiago Forte가 2017년 블로그에서 제시한 노트 압축 기법. [[second-brain-code]] 의 CODE 프레임워크 중 **Distill** 단계의 핵심 실행 방법이다.

핵심 원리: 노트를 한 번에 완벽하게 요약하려 하지 않는다. 여러 번 열어볼 때마다 **레이어를 하나씩 추가**해 점진적으로 압축한다.

> "노트를 읽을 때마다 더 빠르게 핵심을 파악할 수 있어야 한다."

## 4단계 레이어

### Layer 0 — 원문 저장

소스 그대로 저장한다. 웹 클리핑, PDF 발췌, 하이라이트 등. 이 단계에서는 판단하지 않는다.

- 목적: 원본 보존, 재참조 가능성 확보
- LLM 매핑: `raw/` 계층, `distill_level: 0`

### Layer 1 — 볼드 강조

노트를 처음 읽으면서 중요해 보이는 문장·구절을 **볼드** 처리. 전체의 10-20% 수준.

- 기준: "다음에 이 노트를 열었을 때 먼저 읽고 싶은 부분"
- 실수: 너무 많이 볼드하면 Layer 0과 차이 없음

### Layer 2 — 하이라이트

볼드된 부분 중에서 다시 핵심만 하이라이트. 전체의 5% 내외.

- Obsidian에서는 `==하이라이트==` 문법 사용
- 이 단계까지 오면 30초 안에 노트의 핵심을 파악 가능

### Layer 3 — 요약 한 줄 (Executive Summary)

노트 상단에 자신의 말로 작성한 1-3문장 요약. 검색 결과에서 노트를 열기 전에 이 줄만 보고 열 가치가 있는지 판단한다.

- 원문 인용이 아닌 자신의 해석
- LLM 매핑: `distill_level: 3`

## LLM 자동화 매핑

[[llm-wiki-pattern]] 의 wiki 시스템에서 이 기법을 `distill_level` 필드로 자동화할 수 있다.

| distill_level | 상태 | 내용 |
|--------------|------|------|
| 0 | 원문 | raw/ 출처 그대로 구조화 |
| 1 | 1차 압축 | 핵심 섹션 추출, 부가 정보 제거 |
| 2 | 2차 압축 | 핵심 개념·수치·결론만 남김 |
| 3 | 최종 압축 | 한 문단 또는 한 줄 요약 |

### access_count 기반 우선순위

```
access_count >= 5  →  distill_level 1 자동 트리거 검토
access_count >= 15 →  distill_level 2 검토
access_count >= 30 →  distill_level 3 검토
```

자주 열리는 페이지는 더 압축된 상태로 제공하는 것이 효율적. 반대로 거의 열리지 않는 페이지를 미리 압축하는 것은 낭비다.

## 정보 손실 ≠ 압축

Progressive Summarization 에서 가장 많이 오해하는 지점:

**잘못된 이해**: 압축하면 원본이 사라진다.
**올바른 이해**: 원본은 항상 Layer 0에 보존된다. 압축본은 별도 레이어로 추가된다.

```
Layer 0: 원문 (변경 없음, 항상 접근 가능)
Layer 1: 원문 + 볼드 (원문에 마크업 추가)
Layer 2: 원문 + 볼드 + 하이라이트
Layer 3: 요약 + (원문은 하단에 그대로)
```

이 구조 덕분에 "압축을 너무 심하게 했나?"라는 걱정 없이 과감하게 요약할 수 있다.

## 언제 압축하는가

Forte의 권장: **노트를 다시 열게 되는 순간에 압축하라.** 미리 일괄 압축하지 않는다.

- 처음 저장할 때: Layer 0만
- 두 번째 열 때: Layer 1 (볼드)
- 세 번째 이상: Layer 2, Layer 3

"지금 이 노트가 프로젝트에 필요한가?"라는 맥락이 있을 때 압축 판단이 가장 정확하다.

## Obsidian 적용 패턴

```markdown
> **Executive Summary**: (Layer 3 요약)

## 핵심 내용
(Layer 1-2 볼드·하이라이트 섹션)

---
## 원문
(Layer 0 원본)
```

## 관련 개념

- [[second-brain-code]]
- [[llm-wiki-pattern]]
- [[obsidian]]
