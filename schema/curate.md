# Curate 규칙

curate는 wiki 전체를 감사(audit) + 압축(distill) + 수명 관리(lifecycle)하는 복합 오퍼레이션이다.
주 1회 자동 실행 또는 `curate --all` 온디맨드 실행.

## 플래그별 실행 범위

| 플래그 | 수행 단계 |
|---|---|
| `--all` | audit + distill + lifecycle 전체 |
| `--audit` | audit만 |
| `--distill` | distill만 |
| `--lifecycle` | lifecycle 후보 목록만 (실제 이동은 사용자 확인 후) |

---

## 1단계: AUDIT

wiki/ 전체를 스캔해 품질 문제를 탐지한다.

### 탐지 항목

**Orphan 페이지**: inbound `[[wikilink]]` 수가 0인 페이지
- 신규 생성 직후는 예외
- 30일 이상 orphan이면 보고

**Ghost 개념**: index.md ghost 섹션에 등록됐지만 90일 이상 페이지 미생성
- raw 데이터가 없어서인지, 아니면 누락인지 구분해 보고

**모순 감지**: 두 페이지에서 같은 개념에 대해 상충하는 서술
- 예: A 페이지 "X는 Y다", B 페이지 "X는 Z다"
- raw 파일 날짜가 더 최신인 쪽을 우선 표시

**Stale 링크**: `[[페이지명]]`이 존재하지 않는 페이지를 가리키는 경우

### 산출물
`wiki/curate_report.md` 갱신 — 문제 목록 + 권장 조치

---

## 2단계: DISTILL

도메인별로 wiki 페이지들을 읽고 고밀도 인사이트 페이지를 생성한다.

### 실행 대상
`wiki/insights/` — TIL·meetings에서 반복 등장한 패턴 압축

### 압축 기준
- 동일 개념이 3개 이상 wiki 페이지에서 언급 → insights/ 페이지로 압축
- 강의 관련 반복 패턴 → `insights/lecture-patterns.md` 갱신
- habix 비즈니스 관련 패턴 → `insights/habix-patterns.md` 갱신
- 개별 페이지 내부의 교차 종합(`## 인사이트 (종합)` 섹션)은 아래 `## Synthesis Rules` 적용 — 본 절 insights/ 압축 규칙의 확장(대체 아님)

### 압축 형식
```
# [패턴명]
## 핵심 원칙 (1-2줄)
## 관찰된 사례 (날짜 + 출처)
## 적용 방법
## 관련 개념
```

---

## 3단계: LIFECYCLE

오래됐거나 가치가 낮아진 페이지를 archive 후보로 선정한다.

### 후보 선정 기준 (결정론적)

| 조건 | 판정 |
|---|---|
| 마지막 업데이트 > `schema/sources.yaml`의 ttl_days AND inbound_links == 0 | archive 후보 |
| 마지막 업데이트 > ttl_days × 2 AND inbound_links <= 1 | delete 후보 |

도메인별 TTL은 `schema/sources.yaml`의 lifecycle 섹션 참조.

### 절차
1. 후보 목록을 `wiki/curate_report.md`에 작성
2. **사용자가 목록을 확인하고 승인**
3. 승인된 항목만 `wiki/archive/` 로 이동
4. 영구 삭제는 `--purge` 플래그 명시 시에만 실행

### 실행 금지
- 자동으로 파일 이동/삭제하지 않는다 (사용자 확인 필수)
- concepts/, tools/, people/, projects/ 도메인은 ttl_days: 0이므로 lifecycle 대상 제외

---

## 산출물 형식 (curate_report.md)

```markdown
# Curate Report — YYYY-MM-DD

## Audit 결과
### Orphan 페이지 (N개)
- wiki/path/page.md — 마지막 업데이트: YYYY-MM-DD
### Ghost 개념 (N개)
- 개념명 — 최초 언급: YYYY-MM-DD
### 모순 감지 (N개)
- A 페이지 vs B 페이지: 내용 요약

## Distill 결과
- 갱신된 insights 페이지: N개

## Lifecycle 후보
### Archive 후보 (사용자 확인 필요)
- wiki/insights/2026-01-15-note.md — 180일 경과, inbound 0
### Delete 후보 (사용자 확인 필요)
- wiki/insights/2025-11-01-note.md — 365일 경과, inbound 0
```

---

# v0.3 Quality-Driven Curation 규칙

> 아래 3개 절은 v0.3 신설 규칙이며, 현재 공개 설계 기준은 `SPEC.md`의 "v0.3 Quality-Driven Curation" 절이다.
> LLM 실행 경계(SPEC §A): 결정적 판정·스캔·큐 생성은 `scripts/`가 수행하고, LLM 컴파일러는 아래 규칙을 생성·강화·화해 작업의 판정 근거로 사용한다.

## Promotion Gates (G-1~G-4)

wiki 페이지의 신규 생성·강화·기각·유예를 품질 기준으로 판정한다 (WS-2, v0.3.0).
용어: CI 명령의 "Quality Gates"와 구분해 **Promotion Gates**로 통일한다.

### G-1 · 신규 생성

아래 7개 기준을 **전부** 충족할 때만 wiki 페이지를 신규 생성한다:

| 기준 | 임계값 |
|---|---|
| 반복 | ≥2회 (7일 내) |
| 본문 | ≥800자 |
| H2 섹션 | ≥3개 |
| 근거 (sources) | ≥2건 |
| frontmatter | 완비 |
| summary | 40~200자 |
| 기존 페이지 유사도 | <0.75 |

- 통과 시 frontmatter `gate_status: created` 기록.
- 유사도 ≥0.75 → 신규 생성 대신 기존 페이지 강화(G-2)로 라우팅.

### G-2 · 기존 강화

기존 페이지를 강화할 때: **사례 ≥1건 OR 새 각도 ≥200자**를 추가하고, 강화 후 본문 ≥800자를 유지한다.

- 통과 시 `gate_status: enriched` 갱신.
- 강화도 raw/ 출처 필수 — 근거 없는 살 붙이기 금지.

### G-3 · 기각 라우팅

G-1 미달이고 G-4 유예 대상도 아니면, 아래 5개 사유 중 하나로 분류해 `wiki/rejected/`로 라우팅한다:

| 사유 | 분류 기준 |
|---|---|
| `low_value` | 정보 가치 자체가 낮음 (형식 기준과 무관) |
| `insufficient_recurrence` | 반복 기준 미달 + 유예 가치 없음 (G-4 만료 포함) |
| `insufficient_content` | 본문·H2·근거 기준 미달 |
| `duplicate_existing` | 유사도 ≥0.75인데 강화(G-2) 가치도 없음 |
| `frontmatter_invalid` | frontmatter·summary 결손 |

- 기각 페이지에 `gate_status: rejected` + 사유를 기록한다.
- `wiki/rejected/`는 gitignored·okf 제외·index.md 미기록 — 사적 판단 로그 (SPEC §D 3점 방어).

### G-4 · Observing (7일 유예)

반복 1회이지만 잠재 가치가 있는 후보는 `wiki/observing/`에 7일 유예로 보관한다.

- frontmatter: `gate_status: observing` + `observation_expires: YYYY-MM-DD` (배치일 +7일).
- 유예 중 재등장(반복 ≥2회 충족) → G-1 재판정 후 승격.
- 재등장 없이 `observation_expires` 경과 → G-3 `insufficient_recurrence` 기각. 만료 관리는 gates가 자체 수행한다 (lifecycle TTL decay와 분리, SPEC §D).
- `wiki/observing/`도 rejected와 동일하게 gitignored·okf 제외·index.md 미기록.

### frontmatter 사용법 (Gates)

```yaml
gate_status: created        # created | enriched | observing | rejected
recurrence: 2               # 7일 윈도 내 관측된 반복 횟수
observation_expires: 2026-07-11  # gate_status: observing일 때만
```

- 3필드 전부 optional — 없어도 기존 페이지 유효 (v0.2 계약).
- 필드명은 `gate_status`다 — `status` 아님 (episodes JSONL `status`와 충돌 회피 개명, SPEC §C).

## Synthesis Rules

> 2단계 DISTILL의 "동일 개념이 3개 이상 wiki 페이지에서 언급 → insights/ 압축" 규칙의 **확장**이다 (대체 아님).
> insights/ 압축은 그대로 유지하고, 아래는 **개별 페이지 내부**의 교차 종합 규칙을 추가한다 (WS-1, v0.3.1).

### 생성 규칙 — `## 인사이트 (종합)` 섹션

대상 페이지(`wiki/reweave_queue.md`의 synthesis 대상)마다 본문에 `## 인사이트 (종합)` 섹션을 생성·갱신한다. 3요건 필수:

- (a) **2개+ raw 소스 교차 인용** — 서로 다른 raw/ 파일 2개 이상에서 근거를 끌어와 교차시킨다. 단일 소스 요약은 종합이 아니다.
- (b) **강한 각도 1~3개** — 소스들을 관통하는 판단·관점을 1~3개로 압축한다 (사실 나열 금지).
- (c) **반복 신호 카운트** — 같은 신호가 몇 개 소스에서 반복 관측됐는지 명시한다.

### frontmatter 사용법 (Synthesis)

```yaml
angles: ["각도 요약 1", "각도 요약 2"]  # 강한 각도 1~3개
signal_count: 4                        # 반복 신호 카운트
synthesis_updated: YYYY-MM-DD          # 마지막 종합 갱신일
```

### 불변식 (위반 시 저장 금지)

- **기존 본문·sources 삭제·단축 절대 금지** — append/갱신만 허용. 스크립트 shrink 가드가 본문·sources 감소 시 저장을 거부한다 (`WARN shrink`).
- **근거 없는 종합 금지** — 종합의 모든 진술은 raw/ 출처가 있어야 한다. 인용한 raw가 `sources`에 없으면 추가한다.

## Reconciliation Rules

> WS-5 (v0.3.1 구현됨). 결정적 모순 후보 탐지(→ `wiki/contradiction_queue.md`)는 스크립트(`reconcile` 코어, 후보 ≥1일 때만 큐 생성)가 수행하고,
> 화해 서술은 아래 규칙으로 LLM 컴파일러가 수행한다 — 1단계 AUDIT "모순 감지" 리포트를 실행 규칙으로 채우는 형태.

### 화해 서술 — `## 반론/갱신 (YYYY-MM-DD)` append

신규 근거가 기존 주장과 상충하면, 해당 페이지에 `## 반론/갱신 (YYYY-MM-DD)` 섹션을 append한다. 3요소 필수:

1. **기존 주장** — 무엇이 주장돼 있었나 (본문 원문 기준)
2. **반례 근거** — 어떤 raw/ 근거가 상충하나 (출처 경로 명시)
3. **현재 판단** — 지금 시점의 판단은 무엇인가

### frontmatter 사용법 (Reconciliation)

```yaml
superseded_claims: ["대체된 옛 주장 요약"]  # 옛 주장은 본문에 남기고 여기 표시
last_reconciled: YYYY-MM-DD
```

### 규칙

- **옛 주장 삭제 금지** — 본문의 기존 주장은 그대로 남기고, `superseded_claims`에 대체 표시만 한다.
- **오탐 방지** — 모순 없는 단순 보강 raw에는 반론 섹션을 생성하지 않는다 (반론 남발 금지).
- **추측·단정 금지** — "현재 판단"은 raw/ 출처가 뒷받침하는 범위까지만 서술한다. 어느 쪽이 옳은지 근거가 불충분하면 판단 보류를 명시한다.
